# -*- coding: utf-8 -*-
"""AI failure classification, bounded retry, and log privacy.

The live preview finished with 5 extraction failures out of 39 candidates. A
count alone could not say whether those were transient or permanent, and the raw
SDK message could not be printed because it may quote the request - and the
request carries mail text. Hence categories, and a retry that only re-sends what
actually failed.
"""
from __future__ import annotations

import ast
from pathlib import Path

import types

import pytest

from ggongbab.db.repository import MemoryRepository
from ggongbab.parsers import ai_errors
from ggongbab.parsers.ai_parser import AIResult
from ggongbab.preview import MAX_ERROR_RETRIES, generate_preview
from ggongbab.web.exit_codes import UiContractError

from .conftest import make_extraction
from .test_pipeline_export import FUTURE_TEXT, _item, future_extraction

ROOT = Path(__file__).resolve().parents[2]


# --- classification -----------------------------------------------------------
class FakeSdkError(Exception):
    def __init__(self, name, status=None):
        super().__init__("request body: 9월 25일 점심 도시락 제공 ... secret-ish text")
        self.__class__.__name__ = name
        if status is not None:
            self.status_code = status


@pytest.mark.parametrize("name,expected", [
    ("APITimeoutError", ai_errors.TIMEOUT),
    ("RateLimitError", ai_errors.RATE_LIMIT),
    ("APIConnectionError", ai_errors.CONNECTION),
    ("InternalServerError", ai_errors.SERVER_ERROR),
    ("BadRequestError", ai_errors.BAD_REQUEST),
    ("AuthenticationError", ai_errors.AUTH),
    ("PermissionDeniedError", ai_errors.AUTH),
    ("SomethingElseError", ai_errors.UNKNOWN),
])
def test_exception_classes_map_to_categories(name, expected):
    assert ai_errors.classify_exception(FakeSdkError(name)) == expected


@pytest.mark.parametrize("status,expected", [
    (408, ai_errors.TIMEOUT), (429, ai_errors.RATE_LIMIT), (401, ai_errors.AUTH),
    (503, ai_errors.SERVER_ERROR), (422, ai_errors.BAD_REQUEST),
])
def test_status_codes_map_to_categories(status, expected):
    assert ai_errors.classify_exception(FakeSdkError("HttpError", status)) == expected


@pytest.mark.parametrize("message,expected", [
    ("APITimeoutError: took too long", ai_errors.TIMEOUT),
    ("no parsed output", ai_errors.NO_PARSED_OUTPUT),
    ("refusal: I cannot help", ai_errors.REFUSAL),
    ("ValidationError: bad schema", ai_errors.SCHEMA),
    ("", ai_errors.UNKNOWN),
])
def test_message_classification(message, expected):
    assert ai_errors.classify_message(message) == expected


def test_classification_never_reads_the_message_body():
    """A message quoting mail text must not steer the category."""
    leaky = "SomeError: 9월 25일 12시 N1 점심 도시락 제공 timeout rate limit"
    assert ai_errors.classify_message(leaky) == ai_errors.UNKNOWN


def test_retryable_set_excludes_permanent_failures():
    for category in (ai_errors.TIMEOUT, ai_errors.RATE_LIMIT, ai_errors.CONNECTION,
                     ai_errors.SERVER_ERROR, ai_errors.NO_PARSED_OUTPUT):
        assert ai_errors.is_retryable(category)
    for category in (ai_errors.REFUSAL, ai_errors.BAD_REQUEST, ai_errors.AUTH, ai_errors.SCHEMA):
        assert not ai_errors.is_retryable(category)


def test_summary_prints_counts_only():
    lines = ai_errors.summary_lines({"timeout": 2, "rate_limit": 1, "no_parsed_output": 2})
    assert lines[0] == "AI error summary:"
    joined = "\n".join(lines)
    assert "timeout: 2" in joined and "rate_limit: 1" in joined
    for leak in ("9월", "도시락", "@", "http", "id"):
        assert leak not in joined
    assert ai_errors.summary_lines({}) == []


def test_ai_result_exposes_a_safe_category():
    assert AIResult(extraction=None, model="m", error="APITimeoutError: x").category == ai_errors.TIMEOUT
    assert AIResult(extraction=None, model="m", error="x", error_category="rate_limit").category == "rate_limit"
    assert AIResult(extraction=make_extraction(), model="m").category == ""


# --- log privacy ---------------------------------------------------------------
def test_pipeline_warning_carries_no_identifier():
    source = (ROOT / "scripts" / "ggongbab" / "pipeline.py").read_text(encoding="utf-8")
    start = source.index("def run(")
    body = source[start:source.index("def process_item(")]
    assert "item processing failed" in body
    for leak in ("item.external_id", "item.subject", "external_id[:", "item.raw_text"):
        assert leak not in body, leak


def test_no_module_logs_an_external_id():
    """No print anywhere may interpolate a mail identifier or its text."""
    for path in sorted((ROOT / "scripts" / "ggongbab").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "print"):
                continue
            rendered = ast.dump(node)
            for leak in ("external_id", "raw_text", "sender_email", "'subject'", "attr='subject'"):
                assert leak not in rendered, f"{path.name}: print interpolates {leak}"


# --- bounded retry -------------------------------------------------------------
class ScriptedExtractor:
    """Fails a given number of times per item, then succeeds."""

    def __init__(self, failures_by_call=(), fail_forever=False):
        self.script = list(failures_by_call)
        self.fail_forever = fail_forever
        self.calls = 0

    def extract(self, text, images, model):
        self.calls += 1
        if self.fail_forever:
            return AIResult(extraction=None, model=model, error="APITimeoutError: x",
                            error_category="timeout")
        if self.script and self.script[0] > 0:
            self.script[0] -= 1
            return AIResult(extraction=None, model=model, error="APITimeoutError: x",
                            error_category="timeout")
        return AIResult(extraction=future_extraction(text), model=model)


def _settings_with_key(settings):
    settings.openai_api_key = "sk-test"
    return settings


def _counts():
    from ggongbab.preview import COUNTERS

    return dict.fromkeys(COUNTERS, 0)


def _preview(settings, items, extractor, retries=1, tmp_path=None, monkeypatch=None):
    if tmp_path is not None and monkeypatch is not None:
        monkeypatch.setattr("ggongbab.preview.PREVIEW_FILE", tmp_path / "preview.json")
    return generate_preview(items, _counts(), _settings_with_key(settings), error_retries=retries,
                            backoff_seconds=0,
                            extractor_factory=lambda _key: extractor, log=lambda *_a: None)


def test_transient_failure_recovers_on_retry(settings, tmp_path, monkeypatch):
    extractor = ScriptedExtractor(failures_by_call=[1])
    payload = _preview(settings, [_item()], extractor, retries=1, tmp_path=tmp_path, monkeypatch=monkeypatch)
    meta = payload["_preview"]
    assert meta["aiErrorAttempts"] == 1
    assert meta["aiRecovered"] == 1
    assert meta["aiErrors"] == 0
    assert meta["likelyEvents"] == 1


def test_persistent_failure_leaves_a_final_error(settings, tmp_path, monkeypatch):
    from ggongbab.web.exit_codes import PipelineFailed

    extractor = ScriptedExtractor(fail_forever=True)
    monkeypatch.setattr("ggongbab.preview.PREVIEW_FILE", tmp_path / "preview.json")
    with pytest.raises(PipelineFailed):
        generate_preview([_item()], _counts(), _settings_with_key(settings), error_retries=1,
                         backoff_seconds=0,
                         extractor_factory=lambda _key: extractor, log=lambda *_a: None)
    # One first pass plus one retry pass, never an unbounded loop.
    assert extractor.calls == 2


def test_successful_items_are_not_resent(settings, tmp_path, monkeypatch):
    """Only the failed item may re-enter the pipeline."""
    good, bad = _item(ext_id="ok-1"), _item(ext_id="bad-1", text=FUTURE_TEXT + " 재시도")

    class PerItem:
        def __init__(self):
            self.seen = []

        def extract(self, text, images, model):
            self.seen.append(text)
            if "재시도" in text and self.seen.count(text) == 1:
                return AIResult(extraction=None, model=model, error="APITimeoutError: x",
                                error_category="timeout")
            return AIResult(extraction=future_extraction(text), model=model)

    extractor = PerItem()
    payload = _preview(settings, [good, bad], extractor, retries=1, tmp_path=tmp_path, monkeypatch=monkeypatch)
    assert payload["_preview"]["aiRecovered"] == 1 and payload["_preview"]["aiErrors"] == 0
    assert sum(1 for t in extractor.seen if "재시도" not in t) == 1, "the good item was re-sent"


def test_uncertain_results_are_not_retried(settings, tmp_path, monkeypatch):
    """needs_review and not-an-event are answers, not failures."""
    class Uncertain:
        def __init__(self, extraction):
            self.extraction = extraction
            self.calls = 0

        def extract(self, text, images, model):
            self.calls += 1
            return AIResult(extraction=self.extraction, model=model)

    review = make_extraction(needs_review=True, review_reason="ambiguous")
    not_event = make_extraction(is_event=False, title=None)
    for extraction in (review, not_event):
        extractor = Uncertain(extraction)
        payload = _preview(settings, [_item()], extractor, retries=2,
                           tmp_path=tmp_path, monkeypatch=monkeypatch)
        assert payload["_preview"]["aiErrors"] == 0
        assert payload["_preview"]["aiErrorAttempts"] == 0
        assert extractor.calls <= 2, "an uncertain answer must not trigger a retry pass"


def test_zero_retries_is_honoured(settings, tmp_path, monkeypatch):
    from ggongbab.web.exit_codes import PipelineFailed

    extractor = ScriptedExtractor(failures_by_call=[1])
    monkeypatch.setattr("ggongbab.preview.PREVIEW_FILE", tmp_path / "preview.json")
    with pytest.raises(PipelineFailed):
        generate_preview([_item()], _counts(), _settings_with_key(settings), error_retries=0,
                         extractor_factory=lambda _key: extractor, log=lambda *_a: None)
    assert extractor.calls == 1


@pytest.mark.parametrize("retries", [-1, 3, 10])
def test_retry_count_out_of_range_fails_closed(settings, retries):
    extractor = ScriptedExtractor()
    with pytest.raises(UiContractError, match="ai-error-retries"):
        generate_preview([_item()], _counts(), _settings_with_key(settings), error_retries=retries,
                         extractor_factory=lambda _key: extractor, log=lambda *_a: None)
    assert extractor.calls == 0, "the limit must be checked before any AI call"


def test_max_retries_constant_is_small():
    assert MAX_ERROR_RETRIES == 2


def test_retry_does_not_duplicate_the_event(settings, tmp_path, monkeypatch):
    extractor = ScriptedExtractor(failures_by_call=[1])
    monkeypatch.setattr("ggongbab.preview.PREVIEW_FILE", tmp_path / "preview.json")
    repos = []
    real_repo = MemoryRepository

    def tracking_repo():
        repo = real_repo()
        repos.append(repo)
        return repo

    monkeypatch.setattr("ggongbab.preview.MemoryRepository", tracking_repo)
    generate_preview([_item()], _counts(), _settings_with_key(settings), error_retries=1,
                     backoff_seconds=0,
                     extractor_factory=lambda _key: extractor, log=lambda *_a: None)
    assert len(repos[0].events) == 1, "the retry must not create a second event"


def test_preview_metadata_stays_count_only(settings, tmp_path, monkeypatch):
    import json as _json

    extractor = ScriptedExtractor(failures_by_call=[1])
    payload = _preview(settings, [_item()], extractor, retries=1, tmp_path=tmp_path, monkeypatch=monkeypatch)
    blob = _json.dumps(payload["_preview"], ensure_ascii=False)
    assert all(isinstance(v, int) for v in payload["_preview"].values())
    for leak in ("@", "http", "dooray", "post-1", "기업"):
        assert leak not in blob, leak


def test_quota_exhaustion_is_separated_from_throttling():
    """Both arrive as RateLimitError, but only throttling is worth retrying.

    The live run hit `rate_limit_exceeded` on all 39 candidates; an empty balance
    would have looked identical without this split.
    """
    throttled = FakeSdkError("RateLimitError", 429)
    throttled.code = "rate_limit_exceeded"
    assert ai_errors.classify_exception(throttled) == ai_errors.RATE_LIMIT
    assert ai_errors.is_retryable(ai_errors.RATE_LIMIT)

    empty = FakeSdkError("RateLimitError", 429)
    empty.code = "insufficient_quota"
    assert ai_errors.classify_exception(empty) == ai_errors.QUOTA
    assert not ai_errors.is_retryable(ai_errors.QUOTA)


def test_retry_waits_before_re_firing():
    """Re-firing instantly is what turned 39 throttled calls into 78."""
    import inspect

    from ggongbab import preview

    source = inspect.getsource(preview.generate_preview)
    assert "time_module.sleep(pause)" in source
    assert preview.RETRY_BACKOFF_SECONDS >= 60


class FakeThrottle(Exception):
    """A 429 carrying the rate-limit headers the live API actually returned."""

    def __init__(self, retry_after):
        super().__init__("request body: ... mail text ...")
        self.__class__.__name__ = "RateLimitError"
        self.status_code = 429
        self.code = "rate_limit_exceeded"
        self.response = types.SimpleNamespace(headers={"retry-after": str(retry_after)})


def test_a_spent_daily_allowance_is_not_treated_as_throttling():
    """The live blocker: 0/50 requests left, reset 23h38m away, same 429 code.

    Waiting out a per-minute window is worth a retry; waiting out a day is not.
    """
    assert ai_errors.classify_exception(FakeThrottle(1728)) == ai_errors.QUOTA
    assert not ai_errors.is_retryable(ai_errors.QUOTA)


def test_a_short_window_is_still_ordinary_throttling():
    assert ai_errors.classify_exception(FakeThrottle(12)) == ai_errors.RATE_LIMIT
    assert ai_errors.is_retryable(ai_errors.RATE_LIMIT)


@pytest.mark.parametrize("headers", [None, {}, {"retry-after": "not-a-number"}])
def test_a_429_without_a_usable_window_stays_retryable(headers):
    exc = FakeThrottle(1)
    exc.response = types.SimpleNamespace(headers=headers) if headers is not None else None
    assert ai_errors.classify_exception(exc) == ai_errors.RATE_LIMIT


def test_non_retryable_failures_are_never_resent(settings, tmp_path, monkeypatch):
    """A spent quota must not double the call count the way throttling did."""
    from ggongbab.web.exit_codes import PipelineFailed

    class AlwaysQuota:
        def __init__(self):
            self.calls = 0

        def extract(self, text, images, model):
            self.calls += 1
            return AIResult(extraction=None, model=model, error="RateLimitError: x",
                            error_category=ai_errors.QUOTA)

    extractor = AlwaysQuota()
    monkeypatch.setattr("ggongbab.preview.PREVIEW_FILE", tmp_path / "preview.json")
    with pytest.raises(PipelineFailed):
        generate_preview([_item(), _item(ext_id="b-2")], _counts(), _settings_with_key(settings),
                         error_retries=2, backoff_seconds=0,
                         extractor_factory=lambda _key: extractor, log=lambda *_a: None)
    # A spent quota fails the account, not the item: the first rejection stops
    # the run, so the second item is never sent and no retry pass happens.
    assert extractor.calls == 1
