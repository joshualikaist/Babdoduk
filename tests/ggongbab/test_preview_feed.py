import json
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

import dooray_web_agent as agent
from ggongbab import preview
from ggongbab.db import repository
from ggongbab.exporter import build_payload
from ggongbab.models import RawItem
from ggongbab.web.exit_codes import UiContractError
from ggongbab.web.mail_reader import MailHeader
from ggongbab.web.ui_contract import UiContract
from .conftest import FakeExtractor, REFERENCE
from .test_pipeline_export import FUTURE_TEXT, future_extraction
from .test_export_contract import row


def forbidden(*args, **kwargs):
    pytest.fail("preview crossed a forbidden boundary")


@pytest.fixture
def isolated(monkeypatch, tmp_path, settings):
    monkeypatch.setattr(preview, "PREVIEW_FILE", tmp_path / ".local" / "ggongbab-preview.json")
    monkeypatch.setattr(repository.SupabaseRepository, "__init__", forbidden)
    monkeypatch.setattr(agent.TaskWriter, "__init__", forbidden)
    monkeypatch.setattr(agent.TaskWriter, "create_task", forbidden)
    settings.openai_api_key = "fake-test-key"
    return preview.PREVIEW_FILE


def item():
    return RawItem(source_type="dooray", external_id="private-mail-id", subject="기업 설명회",
                   raw_text=FUTURE_TEXT + "\nprivate@example.org", source_created_at=REFERENCE,
                   metadata={"preview_mode": True, "read_state": "read"})


def test_real_pipeline_memory_export_and_private_metadata(isolated, settings, monkeypatch):
    extractor = FakeExtractor(future_extraction)
    seen = []
    original = preview.Pipeline.process_item
    def process(self, raw):
        assert type(self.repo) is repository.MemoryRepository
        seen.append(raw.source_type)
        return original(self, raw)
    monkeypatch.setattr(preview.Pipeline, "process_item", process)
    payload = preview.generate_preview([item()], {"loadedRows": 1, "subject": "SECRET"}, settings,
                                      extractor_factory=lambda _: extractor, log=lambda *_: None)
    assert seen == ["dooray"] and extractor.calls
    assert "private@example.org" not in extractor.calls[0][1]
    assert payload["count"] == 1 and payload["events"][0]["food"]["provided"] == "true"
    assert all(type(v) is int for v in payload["_preview"].values())
    assert set(payload["_preview"]) == set(preview.COUNTERS)
    text = isolated.read_text(encoding="utf-8")
    assert "private-mail-id" not in text and "private@example.org" not in text and "SECRET" not in text
    assert json.loads(text) == payload
    assert list(isolated.parent.parent.rglob("*.json")) == [isolated]


def test_preview_path_is_fixed_and_not_public():
    assert preview.PREVIEW_FILE.parts[-2:] == (".local", "ggongbab-preview.json")
    assert ".local/" in (Path(agent.ROOT) / ".gitignore").read_text()


def test_safety_limit_precedes_all_ai_calls(isolated, settings):
    with pytest.raises(UiContractError, match="51 candidates exceed"):
        preview.generate_preview([item()] * 51, {}, settings, extractor_factory=forbidden)
    assert not isolated.exists()


def test_force_is_explicit_and_reuses_pipeline(isolated, settings):
    extractor = FakeExtractor(future_extraction)
    payload = preview.generate_preview([item()] * 2, {}, settings, max_ai_candidates=1, force=True,
                                      extractor_factory=lambda _: extractor, log=lambda *_: None)
    assert payload["count"] == 1 and len(extractor.calls) == 1  # production dedup/cache


@pytest.mark.parametrize("food,review,expected", [("true", False, 1), ("false", False, 0),
                                                   ("unknown", False, 0), ("true", True, 0)])
def test_public_food_policy_keeps_db_records(settings, food, review, expected):
    source = row(food_provided=food, needs_review=review)
    payload = build_payload([source], settings, food_only=True)
    assert payload["count"] == expected
    assert source["food_provided"] == food


def test_preview_mode_never_constructs_writers_or_writes_public_feed(isolated, settings, monkeypatch):
    production = Path(agent.ROOT) / "data/ggongbab/latest.json"
    before = production.read_bytes()
    contract = UiContract(verified=True, list_api="https://example.org/mails", read_state_key="read")
    monkeypatch.setattr(agent, "load_contract", lambda _: contract)
    monkeypatch.setattr(agent, "load_settings", lambda: settings)
    monkeypatch.setattr(agent, "select_mail_page", lambda *a: None)
    monkeypatch.setattr(preview, "list_mails", lambda *a, **kw: [])
    @contextmanager
    def session(*a, **kw):
        yield SimpleNamespace(contract=contract, context=None, assert_authenticated=lambda: None)
    monkeypatch.setattr(agent, "open_session", session)
    args = agent.build_parser().parse_args(["--preview-feed", "--read-state", "read"])
    assert agent.cmd_preview_feed(args) == 0
    assert production.read_bytes() == before
    assert isolated.exists()


def test_read_filter_runs_before_body_fetch(monkeypatch):
    headers = [MailHeader(mail_id="1", subject="설명회", received=date(2026,9,19), unread=True)]
    monkeypatch.setattr(preview, "list_mails", lambda *a, **kw: headers)
    monkeypatch.setattr(preview, "open_body", forbidden)
    session = SimpleNamespace(contract=UiContract(read_state_key="read"))
    items, counts = preview.collect_candidates(session, date(2026,9,1), date(2026,9,19), limit=10)
    assert items == [] and counts["readEligible"] == 0
    headers[0].unread = None
    with pytest.raises(UiContractError):
        preview.collect_candidates(session, date(2026,9,1), date(2026,9,19), limit=10)


def test_candidate_body_and_preview_fallback_counts(monkeypatch):
    headers = [MailHeader(mail_id=str(i), subject="기업 설명회", preview=FUTURE_TEXT,
                          received=date(2026,9,19), unread=False) for i in range(2)]
    monkeypatch.setattr(preview, "list_mails", lambda *a, **kw: headers)
    def body(session, header, **kw):
        if header.mail_id == "0": header.body, header.body_opened = FUTURE_TEXT, True
    monkeypatch.setattr(preview, "open_body", body)
    items, counts = preview.collect_candidates(SimpleNamespace(contract=UiContract(read_state_key="read")),
                                               date(2026,9,1), date(2026,9,19), limit=10)
    assert len(items) == 2 and counts["bodyAttempted"] == 2 and counts["bodyFetched"] == 1
    assert all(i.raw_text == FUTURE_TEXT and not i.sender_email and not i.source_url for i in items)


def test_scheduler_command_has_safety_flags_without_running_it():
    command = (Path(agent.ROOT) / "scripts/run_ggongbab_agent.cmd").read_text()
    run = next(line for line in command.splitlines() if line.startswith("python "))
    assert "--read-state read" in run and "--cdp" in run


def test_preview_mode_is_mutually_exclusive():
    with pytest.raises(SystemExit):
        agent.build_parser().parse_args(["--run", "--preview-feed"])


def test_export_privacy_is_checked_before_writing(isolated, settings):
    def extraction(text):
        result = future_extraction(text)
        result.summary = "Contact private@example.org"
        return result
    from ggongbab.web.exit_codes import PipelineFailed
    with pytest.raises(PipelineFailed, match="validation failed"):
        preview.generate_preview([item()], {}, settings,
                                 extractor_factory=lambda _: FakeExtractor(extraction), log=lambda *_: None)
    assert not isolated.exists()


def test_preview_export_matches_existing_frontend_schema(isolated, settings):
    from validate_content import validate_ggongbab
    payload = preview.generate_preview([item()], {}, settings,
                                      extractor_factory=lambda _: FakeExtractor(future_extraction), log=lambda *_: None)
    assert validate_ggongbab(isolated) == []
    assert {"title", "startAt", "location", "food", "registration", "sources"} <= payload["events"][0].keys()
