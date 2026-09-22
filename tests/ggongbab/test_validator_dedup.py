# -*- coding: utf-8 -*-
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from ggongbab.dedup import find_match, merge_into, score_pair
from ggongbab.models import EventCandidate, EventExtraction, Evidence
from ggongbab.parsers.rule_parser import analyze
from ggongbab.parsers.validator import fallback_reasons, parse_iso, validate

from .conftest import NEGATIVE_TEXT, POSITIVE_TEXT, REFERENCE, make_extraction


# --- AI schema ----------------------------------------------------------------
def test_ai_schema_parses_and_rejects_bad_enum():
    ext = make_extraction()
    dumped = json.loads(ext.model_dump_json())
    assert dumped["food_provided"] == "true" and dumped["evidence"]["food"]
    again = EventExtraction.model_validate(dumped)
    assert again.event_start == "2026-09-25T12:00:00+09:00"
    with pytest.raises(ValidationError):
        make_extraction(food_type="pizza")
    with pytest.raises(ValidationError):
        make_extraction(food_provided="maybe")


def test_ai_schema_is_strict_friendly():
    # Structured Outputs requires every field to be present (None allowed, no defaults).
    schema = EventExtraction.model_json_schema()
    assert set(schema["required"]) == set(schema["properties"].keys())
    assert set(schema["$defs"]["Evidence"]["required"]) == {"event_time", "location", "food", "registration"}


# --- validator: regression fixtures -----------------------------------------
def test_validator_positive_fixture():
    facts = analyze(POSITIVE_TEXT, REFERENCE)
    cand = validate(make_extraction(), facts, POSITIVE_TEXT, source_type="dooray", reference=REFERENCE)
    assert cand.is_event
    assert cand.event_start.date().isoformat() == "2026-09-25"
    assert cand.event_start.strftime("%H:%M") == "12:00"
    assert cand.event_start.utcoffset().total_seconds() == 9 * 3600
    assert cand.building == "N1"
    assert cand.food_provided == "true"
    assert cand.food_type == "lunchbox"
    assert not cand.needs_review, cand.review_reasons


def test_validator_lunch_time_counterexample():
    facts = analyze(NEGATIVE_TEXT, REFERENCE)
    # AI wrongly claims food with a time-of-day quote
    ai = make_extraction(food_provided="true", food_type="meal",
                         evidence=Evidence(event_time="9월 25일 12시", location="N1", food="12시 점심시간에", registration=None))
    cand = validate(ai, facts, NEGATIVE_TEXT, reference=REFERENCE)
    assert cand.food_provided != "true"
    assert cand.needs_review
    assert any("근거" in r for r in cand.review_reasons)
    assert "food_ambiguous" in fallback_reasons(ai, facts, NEGATIVE_TEXT, 0.75)


def test_validator_rejects_date_conflict():
    text = "9월 26일 오후 3시 N1에서 설명회. 참석자에게 간식 제공."
    facts = analyze(text, REFERENCE)
    ai = make_extraction(event_start="2026-09-25T12:00:00+09:00", food_type="snack",
                         evidence=Evidence(event_time="9월 26일 오후 3시", location="N1", food="간식 제공", registration=None))
    cand = validate(ai, facts, text, reference=REFERENCE)
    assert cand.event_start is None
    assert cand.needs_review
    assert any("날짜 충돌" in r for r in cand.review_reasons)
    assert "date_conflict" in fallback_reasons(ai, facts, text, 0.75)


def test_validator_drops_hallucinated_url_and_flags_rule_conflict():
    facts = analyze(POSITIVE_TEXT, REFERENCE)
    ai = make_extraction(registration_url="https://forms.gle/not-in-text", food_provided="unknown", food_type="unknown",
                         evidence=Evidence(event_time="9월 25일 12시", location="N1", food=None, registration=None))
    cand = validate(ai, facts, POSITIVE_TEXT, reference=REFERENCE)
    assert cand.registration_url is None
    assert any("URL" in r for r in cand.review_reasons)
    assert any("규칙은 식사 제공 감지" in r for r in cand.review_reasons)
    assert "rule_conflict" in fallback_reasons(ai, facts, POSITIVE_TEXT, 0.75)


def test_validator_not_event_passthrough():
    facts = analyze("이번 주 학식 메뉴 안내", REFERENCE)
    cand = validate(make_extraction(is_event=False, title=None), facts, "이번 주 학식 메뉴 안내")
    assert cand.is_event is False


def test_fallback_not_triggered_for_clean_result():
    facts = analyze(POSITIVE_TEXT, REFERENCE)
    assert fallback_reasons(make_extraction(), facts, POSITIVE_TEXT, 0.75) == []
    assert "low_confidence" in fallback_reasons(make_extraction(confidence=0.5), facts, POSITIVE_TEXT, 0.75)


def test_parse_iso_defaults_to_kst():
    dt = parse_iso("2026-09-25T12:00")
    assert dt.utcoffset().total_seconds() == 9 * 3600
    assert parse_iso("2026-09-25T03:00:00Z").hour == 12


# --- dedup --------------------------------------------------------------------
def _cand(title, start="2026-09-25T12:00:00+09:00", **kw) -> EventCandidate:
    c = EventCandidate(title=title, event_start=parse_iso(start), confidence=0.9, **kw)
    return c


def test_dedup_matches_same_event_across_sources():
    existing = {"id": "e1", "title": "[안내] 삼성전자 Tech Lunch Talk", "event_start": "2026-09-25T12:00:00+09:00",
                "organizer": "경력개발센터", "building": "N1", "status": "published", "confidence": 0.8,
                "food_provided": "true", "food_type": "lunchbox", "needs_review": False, "review_reason": None}
    cand = _cand("삼성전자 Tech Lunch Talk 참가 신청", organizer="KAIST 경력개발센터", building="N1")
    assert score_pair(cand, existing) >= 0.72
    match = find_match(cand, [existing], 0.72)
    assert match and match.event["id"] == "e1"


def test_dedup_rejects_same_title_different_day():
    existing = {"id": "e1", "title": "삼성전자 Tech Lunch Talk", "event_start": "2026-09-25T12:00:00+09:00",
                "organizer": None, "building": "N1"}
    cand = _cand("삼성전자 Tech Lunch Talk", start="2026-10-02T12:00:00+09:00", building="N1")
    assert find_match(cand, [existing], 0.72) is None


def test_merge_fills_missing_and_flags_conflicts():
    existing = {"id": "e1", "title": "Tech Lunch Talk", "event_start": "2026-09-25T12:00:00+09:00", "building": "N1",
                "room": None, "food_provided": "unknown", "food_type": "unknown", "registration_url": None,
                "confidence": 0.7, "needs_review": False, "review_reason": None, "status": "published", "summary": ""}
    cand = _cand("Tech Lunch Talk", room="101호", food_provided="true", food_type="lunchbox",
                 registration_url="https://forms.gle/a")
    updated, reasons = merge_into(existing, cand)
    assert updated["room"] == "101호" and updated["food_provided"] == "true" and updated["registration_url"] == "https://forms.gle/a"
    assert reasons == [] and not updated["needs_review"] and updated["status"] == "published"

    conflicting = _cand("Tech Lunch Talk", building="E5", food_provided="false")
    updated2, reasons2 = merge_into(updated, conflicting)
    assert updated2["building"] == "N1"  # never overwritten
    assert updated2["needs_review"] and updated2["status"] == "review"
    assert any("building" in r for r in reasons2) and any("food_provided" in r for r in reasons2)
