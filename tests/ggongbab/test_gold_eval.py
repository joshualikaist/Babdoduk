# -*- coding: utf-8 -*-
"""The gold seed set keeps the deterministic stages honest; the AI stage never runs by accident."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import eval_ggongbab as ev  # noqa: E402
from ggongbab.models import EventExtraction, Evidence  # noqa: E402
from ggongbab.parsers.ai_parser import AIResult, AIUsage  # noqa: E402


def test_seed_samples_are_synthetic_and_sanitized():
    samples = ev.load_samples()
    assert len(samples) >= 30 and len({s["id"] for s in samples}) == len(samples)
    for s in samples:
        blob = json.dumps(s, ensure_ascii=False)
        assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", blob), s["id"]
        assert not re.search(r"https?://", blob), s["id"]
        assert not re.search(r"\d{6,}", re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", "", blob)), s["id"]


def test_the_seed_covers_the_owner_categories():
    kinds = {s["kind"] for s in ev.load_samples()}
    assert {"positive", "supply", "registration", "hard_negative", "eligibility", "ambiguous", "miss"} <= kinds


def test_deterministic_stages_meet_the_targets():
    report = ev.evaluate_rules(ev.load_samples())
    assert report["prefilter"]["recall"] == 1.0, report["mismatches"]
    assert report["rule_food"]["recall"] == 1.0, report["mismatches"]
    assert report["rule_food"]["false_positives"] == 0, report["mismatches"]
    assert all(value == 1.0 for value in report["fields"].values()), (report["fields"], report["mismatches"])


def test_the_ai_stage_needs_an_explicit_budget(capsys):
    with pytest.raises(SystemExit):
        ev.main(["--ai", "luna"])
    assert "nothing was sent" in capsys.readouterr().err


class FakeExtractor:
    def __init__(self):
        self.texts = []

    def extract(self, text, images, model):
        self.texts.append(text)
        return AIResult(extraction=EventExtraction(
            is_event=True, title="t", summary=None, event_start=None, event_end=None, date_text=None,
            time_text=None, location_name=None, building=None, room=None, food_provided="unknown",
            food_type="unknown", food_description=None, organizer=None, eligibility=None,
            registration_required="unknown", registration_deadline=None, registration_url=None, confidence=0.5,
            evidence=Evidence(event_time=None, location=None, food=None, registration=None),
            needs_review=True, review_reason="fake"), model=model, usage=AIUsage(10, 5))


def test_the_ai_stage_uses_the_production_prompt_input_and_respects_the_budget():
    fake = FakeExtractor()
    report = ev.evaluate_ai(ev.load_samples(), "fake-model", 3, extractor=fake)
    assert report["calls"] == 3 and len(fake.texts) == 3
    assert all(t.startswith("SOURCE: dooray\nMAIL_DATE: ") for t in fake.texts)
    assert report["tokens"] == {"input": 30, "output": 15}
    assert report["false_publications"] == 0
