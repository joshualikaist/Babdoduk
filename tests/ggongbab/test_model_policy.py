# -*- coding: utf-8 -*-
"""Model policy: Luna only, fallback off, fail fast, and what a run costs.

The system extracts literal fields and a deterministic validator decides truth
afterwards, so an ambiguous source belongs in needs_review rather than in a
second opinion from a model that costs about ten times as much per token. These
tests pin that policy down where it is easy to undo by accident: a default, a
workflow line, an env file.
"""
from __future__ import annotations

import ast
import inspect

import re
import textwrap
from pathlib import Path

import pytest

from ggongbab import pricing
from ggongbab.config import Settings
from ggongbab.parsers import ai_errors
from ggongbab.parsers.ai_parser import AIResult, OpenAIExtractor
from ggongbab.pipeline import Pipeline, RunStats

from .test_pipeline_export import _item, future_extraction

ROOT = Path(__file__).resolve().parents[2]


def raw_items(count):
    return [_item(ext_id=f"policy-{n}") for n in range(count)]


# ---------------------------------------------------------------------------
# 1-2, 5-6: the default is Luna alone, in every place that can set it
# ---------------------------------------------------------------------------
def test_primary_model_defaults_to_luna(monkeypatch):
    monkeypatch.delenv("GGONGBAB_AI_MODEL", raising=False)
    assert Settings().ai_model == "gpt-5.6-luna"


def test_fallback_model_defaults_to_empty(monkeypatch):
    monkeypatch.delenv("GGONGBAB_AI_FALLBACK_MODEL", raising=False)
    assert Settings().ai_fallback_model == ""


@pytest.mark.parametrize("raw", ["", "   ", "\t"])
def test_blank_fallback_is_treated_as_unset(monkeypatch, raw):
    """A variable set to whitespace must not switch the fallback on."""
    monkeypatch.setenv("GGONGBAB_AI_FALLBACK_MODEL", raw)
    assert Settings().ai_fallback_model == ""


def test_env_example_ships_an_empty_fallback():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert re.search(r"^GGONGBAB_AI_MODEL=gpt-5\.6-luna$", text, re.M)
    assert re.search(r"^GGONGBAB_AI_FALLBACK_MODEL=$", text, re.M)


def test_workflow_does_not_inject_terra():
    """The cron must not re-enable the expensive model behind the operator."""
    text = (ROOT / ".github" / "workflows" / "ggongbab-refresh.yml").read_text(encoding="utf-8")
    line = next(l for l in text.splitlines() if "GGONGBAB_AI_FALLBACK_MODEL:" in l)
    assert "terra" not in line.lower(), line
    assert line.strip() == "GGONGBAB_AI_FALLBACK_MODEL: ${{ vars.GGONGBAB_AI_FALLBACK_MODEL }}"


# ---------------------------------------------------------------------------
# 7: reasoning effort
# ---------------------------------------------------------------------------
def test_extractor_requests_no_reasoning_effort():
    """Chain-of-thought is billed as output tokens and buys nothing here."""
    source = textwrap.dedent(inspect.getsource(OpenAIExtractor.extract))
    call = next(node for node in ast.walk(ast.parse(source))
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute) and node.func.attr == "parse")
    reasoning = next(kw for kw in call.keywords if kw.arg == "reasoning")
    assert ast.literal_eval(reasoning.value) == {"effort": "none"}


def test_reasoning_effort_none_is_a_value_the_sdk_accepts():
    """Guard against a syntax the installed SDK would reject at runtime."""
    from openai.types.shared.reasoning_effort import ReasoningEffort
    import typing

    assert "none" in typing.get_args(typing.get_args(ReasoningEffort)[0])


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------
class RecordingExtractor:
    """Answers from a script and remembers which models were asked."""

    def __init__(self, script):
        self.script = list(script)
        self.models = []

    def extract(self, text, images, model):
        self.models.append(model)
        result = self.script.pop(0) if self.script else None
        if callable(result):
            return result(model)
        return result


def _pipeline(settings, extractor, repo=None):
    from ggongbab.db.repository import MemoryRepository

    return Pipeline(settings, repo or MemoryRepository(), extractor, [])


def _ok(model, *, confidence=0.95, needs_review=False, tokens=(1000, 200)):
    extraction = future_extraction("")
    extraction.confidence = confidence
    extraction.needs_review = needs_review
    from ggongbab.parsers.ai_parser import AIUsage

    return AIResult(extraction=extraction, model=model,
                    usage=AIUsage(input_tokens=tokens[0], output_tokens=tokens[1]))


def _fail(model, category, tokens=(0, 0)):
    from ggongbab.parsers.ai_parser import AIUsage

    return AIResult(extraction=None, model=model, error=f"{category}: x",
                    error_category=category,
                    usage=AIUsage(input_tokens=tokens[0], output_tokens=tokens[1]))


# ---------------------------------------------------------------------------
# 3-4: fallback only when explicitly configured
# ---------------------------------------------------------------------------
def test_ambiguous_result_makes_no_second_call_when_fallback_is_unset(settings):
    """Ambiguous is an answer, not an error: it becomes needs_review, not a retry."""
    settings.ai_fallback_model = ""
    extractor = RecordingExtractor([lambda m: _ok(m, confidence=0.2, needs_review=True)])
    pipeline = _pipeline(settings, extractor)
    outcome = pipeline.process_item(_item())

    assert extractor.models == ["gpt-5.6-luna"]
    assert pipeline.stats.ai_fallback == 0
    assert pipeline.stats.fallback_attempted == 0
    assert outcome.candidate is not None and outcome.candidate.needs_review


def test_explicit_fallback_still_works(settings):
    settings.ai_fallback_model = "gpt-5.6-terra"
    extractor = RecordingExtractor([
        lambda m: _ok(m, confidence=0.2, needs_review=True),
        lambda m: _ok(m, confidence=0.99),
    ])
    pipeline = _pipeline(settings, extractor)
    pipeline.process_item(_item())

    assert extractor.models == ["gpt-5.6-luna", "gpt-5.6-terra"]
    assert pipeline.stats.ai_fallback == 1


def test_fallback_equal_to_primary_is_not_called_twice(settings):
    settings.ai_fallback_model = settings.ai_model
    extractor = RecordingExtractor([lambda m: _ok(m, confidence=0.2, needs_review=True)])
    pipeline = _pipeline(settings, extractor)
    pipeline.process_item(_item())

    assert extractor.models == ["gpt-5.6-luna"]


# ---------------------------------------------------------------------------
# 8-11: fail fast on account-level failures, retry only transient ones
# ---------------------------------------------------------------------------
def test_quota_and_auth_are_fatal_and_never_retryable():
    for category in (ai_errors.QUOTA, ai_errors.AUTH):
        assert ai_errors.is_fatal(category)
        assert not ai_errors.is_retryable(category)


@pytest.mark.parametrize("category", [ai_errors.TIMEOUT, ai_errors.RATE_LIMIT,
                                      ai_errors.CONNECTION, ai_errors.SERVER_ERROR,
                                      ai_errors.NO_PARSED_OUTPUT])
def test_transient_categories_are_retryable_and_not_fatal(category):
    assert ai_errors.is_retryable(category)
    assert not ai_errors.is_fatal(category)


@pytest.mark.parametrize("category", [ai_errors.BAD_REQUEST, ai_errors.REFUSAL, ai_errors.SCHEMA])
def test_permanent_item_failures_are_not_retried_and_not_fatal(category):
    """These fail one item for good; they must not stop the whole run either."""
    assert not ai_errors.is_retryable(category)
    assert not ai_errors.is_fatal(category)


@pytest.mark.parametrize("category", [ai_errors.QUOTA, ai_errors.AUTH])
def test_a_fatal_failure_stops_the_remaining_candidates(settings, category):
    """39 candidates and a spent quota must cost one call, not 39."""
    settings.ai_fallback_model = ""
    extractor = RecordingExtractor([lambda m: _fail(m, category)])
    pipeline = _pipeline(settings, extractor)
    items = raw_items(5)

    outcomes = [pipeline.process_item(item) for item in items]

    assert len(extractor.models) == 1
    assert pipeline.stats.ai_attempted == 1
    assert pipeline.stats.ai_errors == 1
    assert pipeline.stats.ai_skipped_quota == 4
    assert pipeline.stats.fatal_category == category
    assert all(o.halted for o in outcomes[1:])
    assert pipeline.stats.stop_lines() == [
        "AI processing stopped early:", f"  reason: {category}",
        "  processed: 1", "  remaining: 4"]


def test_a_transient_failure_does_not_stop_the_run(settings):
    settings.ai_fallback_model = ""
    extractor = RecordingExtractor([lambda m: _fail(m, ai_errors.TIMEOUT)] * 3)
    pipeline = _pipeline(settings, extractor)
    for item in raw_items(3):
        pipeline.process_item(item)

    assert len(extractor.models) == 3
    assert pipeline.stats.fatal_category == ""
    assert pipeline.stats.ai_skipped_quota == 0


# ---------------------------------------------------------------------------
# 12: the retry path actually runs (the import collision made it raise)
# ---------------------------------------------------------------------------
def test_retry_path_can_actually_sleep():
    """`from datetime import time` once shadowed the module, so sleep() raised."""
    from ggongbab import preview

    assert preview.time_module is not __import__("datetime").time
    assert callable(preview.time_module.sleep)
    preview.time_module.sleep(0)


def test_preview_uses_the_datetime_alias_for_midnight():
    from ggongbab import preview

    source = inspect.getsource(preview.collect_candidates)
    assert "dt_time.min" in source
    assert "time.min" not in source.replace("dt_time.min", "")


# ---------------------------------------------------------------------------
# 13-16: per-model usage aggregation and cost
# ---------------------------------------------------------------------------
def test_usage_is_aggregated_per_model(settings):
    settings.ai_fallback_model = "gpt-5.6-terra"
    extractor = RecordingExtractor([
        lambda m: _ok(m, confidence=0.2, needs_review=True, tokens=(1000, 200)),
        lambda m: _ok(m, confidence=0.99, tokens=(1100, 300)),
    ])
    pipeline = _pipeline(settings, extractor)
    pipeline.process_item(_item())

    assert pipeline.stats.model_usage == {
        "gpt-5.6-luna": {"calls": 1, "input_tokens": 1000, "output_tokens": 200},
        "gpt-5.6-terra": {"calls": 1, "input_tokens": 1100, "output_tokens": 300},
    }


def test_a_retried_call_is_counted_in_usage(settings):
    """A retry is billed, so it belongs in the total even though it failed."""
    settings.ai_fallback_model = ""
    extractor = RecordingExtractor([
        lambda m: _fail(m, ai_errors.TIMEOUT, tokens=(900, 0)),
        lambda m: _ok(m, tokens=(900, 150)),
    ])
    pipeline = _pipeline(settings, extractor)
    item = _item()
    pipeline.process_item(item)
    pipeline.process_item(item)

    usage = pipeline.stats.model_usage["gpt-5.6-luna"]
    assert usage["calls"] == 2
    assert usage["input_tokens"] == 1800
    assert usage["output_tokens"] == 150


def test_cost_for_luna_matches_the_published_rate():
    # 1,000,000 in + 1,000,000 out = $0.20 + $1.20
    assert pricing.estimate_cost_usd("gpt-5.6-luna", 1_000_000, 1_000_000) == pytest.approx(1.40)
    # A realistic run: ~118k in, ~29k out
    assert pricing.estimate_cost_usd("gpt-5.6-luna", 118_234, 28_741) == pytest.approx(
        118_234 * 0.20 / 1e6 + 28_741 * 1.20 / 1e6)


def test_cost_for_terra_matches_the_published_rate():
    assert pricing.estimate_cost_usd("gpt-5.6-terra", 1_000_000, 1_000_000) == pytest.approx(14.00)


def test_terra_is_ten_times_luna_per_token():
    """The reason the fallback is off by default; if this changes, revisit it."""
    luna = pricing.MODEL_PRICING_USD_PER_MTOK["gpt-5.6-luna"]
    terra = pricing.MODEL_PRICING_USD_PER_MTOK["gpt-5.6-terra"]
    assert terra["input"] == pytest.approx(luna["input"] * 10)
    assert terra["output"] == pytest.approx(luna["output"] * 10)


def test_an_unpriced_model_contributes_zero_and_is_named():
    assert pricing.estimate_cost_usd("gpt-future", 1_000_000, 1_000_000) == 0.0
    lines = pricing.usage_lines({"gpt-future": {"calls": 1, "input_tokens": 10, "output_tokens": 2}})
    assert any("not in price table" in line for line in lines)
    assert any("gpt-future" in line for line in lines)


def test_total_cost_sums_every_model():
    usage = {"gpt-5.6-luna": {"calls": 2, "input_tokens": 1_000_000, "output_tokens": 0},
             "gpt-5.6-terra": {"calls": 1, "input_tokens": 1_000_000, "output_tokens": 0}}
    assert pricing.total_cost_usd(usage) == pytest.approx(0.20 + 2.00)


def test_usage_summary_is_labelled_an_estimate():
    lines = pricing.usage_lines({"gpt-5.6-luna": {"calls": 1, "input_tokens": 10, "output_tokens": 2}})
    text = "\n".join(lines)
    assert "estimated cost" in text
    assert "Total estimated API cost" in text
    assert pricing.PRICING_AS_OF in text


# ---------------------------------------------------------------------------
# 17: cost and error reporting must stay content-free
# ---------------------------------------------------------------------------
def test_usage_summary_contains_only_numbers_and_model_names():
    usage = {"gpt-5.6-luna": {"calls": 3, "input_tokens": 1234, "output_tokens": 56}}
    for line in pricing.usage_lines(usage):
        assert "@" not in line
        assert not re.search(r"[가-힣]", line), line


def test_pricing_module_never_touches_mail_content():
    """Cost comes from token counts alone; nothing here may read an item."""
    source = (ROOT / "scripts" / "ggongbab" / "pricing.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    banned = {"subject", "body", "raw_text", "external_id", "mail_id", "title"}
    names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    names |= {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert not (names & banned)


def test_stop_lines_report_counts_only():
    stats = RunStats()
    stats.fatal_category = ai_errors.QUOTA
    stats.ai_attempted = 1
    stats.ai_skipped_quota = 38
    lines = stats.stop_lines()
    assert lines == ["AI processing stopped early:", "  reason: quota_exhausted",
                     "  processed: 1", "  remaining: 38"]
    for line in lines:
        assert not re.search(r"[가-힣@]", line)


# ---------------------------------------------------------------------------
# 18: fallback effectiveness, for the day someone asks whether Terra earns its price
# ---------------------------------------------------------------------------
def _fallback_run(settings, primary, fallback):
    settings.ai_fallback_model = "gpt-5.6-terra"
    extractor = RecordingExtractor([primary, fallback])
    pipeline = _pipeline(settings, extractor)
    pipeline.process_item(_item())
    return pipeline.stats


def test_fallback_improved_is_counted(settings):
    stats = _fallback_run(
        settings,
        lambda m: _ok(m, confidence=0.2, needs_review=True),
        lambda m: _ok(m, confidence=0.99, needs_review=False))
    assert stats.fallback_attempted == 1
    assert stats.fallback_improved == 1
    assert stats.fallback_same == 0
    assert stats.fallback_worse == 0


def test_fallback_that_denies_the_event_is_counted_as_worse(settings):
    def not_an_event(model):
        result = _ok(model)
        result.extraction.is_event = False
        return result

    stats = _fallback_run(settings,
                          lambda m: _ok(m, confidence=0.2, needs_review=True), not_an_event)
    assert stats.fallback_attempted == 1
    assert stats.fallback_worse == 1
    assert stats.fallback_improved == 0


def test_effectiveness_counters_stay_zero_without_a_fallback(settings):
    settings.ai_fallback_model = ""
    extractor = RecordingExtractor([lambda m: _ok(m, confidence=0.2, needs_review=True)])
    pipeline = _pipeline(settings, extractor)
    pipeline.process_item(_item())
    stats = pipeline.stats
    assert (stats.fallback_attempted, stats.fallback_improved,
            stats.fallback_same, stats.fallback_worse) == (0, 0, 0, 0)
