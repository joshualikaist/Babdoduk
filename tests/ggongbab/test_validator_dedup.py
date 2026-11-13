# -*- coding: utf-8 -*-
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from ggongbab.dedup import find_match, merge_into, same_building, same_url, score_pair
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
    # Structured Outputs requires every field to be present (None allowed, no defaults). What is
    # sent is the SDK's strict conversion: the v4 fields' null defaults are dropped there.
    from openai.lib._pydantic import to_strict_json_schema
    schema = to_strict_json_schema(EventExtraction)
    assert set(schema["required"]) == set(schema["properties"].keys())
    assert set(schema["$defs"]["Evidence"]["required"]) == {"event_time", "location", "food", "registration",
                                                             "giveaway", "from_poster", "audience"}
    # v6 (2026-10-18): the per-day sessions and the audience are nested objects with every field required.
    assert set(schema["$defs"]["SessionExtraction"]["required"]) == set(schema["$defs"]["SessionExtraction"]["properties"])
    assert set(schema["$defs"]["AudienceExtraction"]["required"]) == {"text", "basis"}
    assert '"default"' not in json.dumps(schema)


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


RANGE_TEXT = "2026 뇌인지과학과 학과설명회\n일시: 2026년 11월 11일(수) 16:30~17:30\n장소: W13 컨퍼런스룸\n참석자에게 식사를 제공합니다."


def _range_extraction(start, end):
    return make_extraction(event_start=start, event_end=end, building="W13", room=None, time_text="16:30~17:30",
                           evidence=Evidence(event_time="2026년 11월 11일(수) 16:30~17:30", location="W13 컨퍼런스룸",
                                             food="참석자에게 식사를 제공합니다", registration=None))


def test_validator_flags_a_start_that_is_the_range_end():
    """Audit 2026-11-13: an AI start of 17:30 for "16:30~17:30" passed because 17:30 is in the text."""
    facts = analyze(RANGE_TEXT, REFERENCE)
    wrong = validate(_range_extraction("2026-11-11T17:30:00+09:00", None), facts, RANGE_TEXT, reference=REFERENCE)
    assert wrong.needs_review and any("시작/종료 혼동" in r for r in wrong.review_reasons)
    right = validate(_range_extraction("2026-11-11T16:30:00+09:00", "2026-11-11T17:30:00+09:00"), facts, RANGE_TEXT,
                     reference=REFERENCE)
    assert not right.needs_review, right.review_reasons
    assert right.event_end.strftime("%H:%M") == "17:30"


def test_validator_keeps_an_end_before_the_start_for_review():
    """Audit 2026-11-13: an end before the start was dropped silently; it is now a review reason."""
    facts = analyze(RANGE_TEXT, REFERENCE)
    cand = validate(_range_extraction("2026-11-11T16:30:00+09:00", "2026-11-11T15:30:00+09:00"), facts, RANGE_TEXT,
                    reference=REFERENCE)
    assert cand.needs_review and any("종료가 시작보다 이름" in r for r in cand.review_reasons)
    assert cand.event_end is not None and cand.event_end.strftime("%H:%M") == "15:30"


def test_validator_reads_a_bare_range_end_in_the_afternoon():
    text = "11월 20일(목) 오후 6시 30분 ~ 8시 N1 102호 간담회. 저녁 도시락을 제공합니다."
    facts = analyze(text, REFERENCE)
    assert facts.times == ["18:30", "20:00"]
    morning = make_extraction(event_start="2026-11-20T08:00:00+09:00", event_end=None,
                              evidence=Evidence(event_time="11월 20일(목) 오후 6시 30분 ~ 8시", location="N1",
                                                food="저녁 도시락을 제공합니다", registration=None))
    cand = validate(morning, facts, text, reference=REFERENCE)
    assert cand.needs_review and any("시간 충돌" in r for r in cand.review_reasons)


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


def test_merge_treats_one_building_or_link_written_two_ways_as_the_same():
    """2026-11-02: 업비트 특강 (KI빌딩 vs KI빌딩(E4)) and NAVER D2SF 토크 (a link with and without
    ?pk=g) were held from the site as merge conflicts although both mails said the same thing."""
    existing = {"title": "업비트 디지털 자산 특강", "event_start": "2026-09-25T14:00:00+09:00", "building": "KI빌딩",
                "registration_url": "https://luma.com/viqcul3g?pk=g", "food_provided": "true", "food_type": "snack",
                "confidence": 1.0, "needs_review": False, "review_reason": None, "status": "published", "summary": ""}
    cand = _cand("업비트 디지털 자산 특강", start="2026-09-25T14:00:00+09:00", building="KI빌딩(E4)",
                 registration_url="https://luma.com/viqcul3g", food_provided="true", food_type="snack")
    updated, reasons = merge_into(existing, cand)
    assert reasons == [] and not updated["needs_review"] and updated["status"] == "published"
    assert updated["building"] == "KI빌딩(E4)" and updated["registration_url"] == "https://luma.com/viqcul3g?pk=g"


@pytest.mark.parametrize("a, b, same", [
    ("KI빌딩", "KI빌딩(E4)", True), ("E11", "창의학습관(E11)", True), ("창의학습관 (E11)", "창의학습관(E11)", True),
    ("E1", "E11", False), ("E4", "E6-1", False), ("KI빌딩(E4)", "N1", False), ("학생회관", "응용공학동", False),
    ("KI빌딩", "", False),
])
def test_same_building(a, b, same):
    assert same_building(a, b) is same and same_building(b, a) is same


@pytest.mark.parametrize("a, b, same", [
    ("https://luma.com/viqcul3g?pk=g", "https://luma.com/viqcul3g", True),
    ("https://forms.gle/abc/", "https://Forms.gle/abc", True),
    ("https://www.example.com/x?utm_source=insta&id=3", "https://example.com/x?id=3", True),
    ("https://board.kaist.ac.kr/view?id=3", "https://board.kaist.ac.kr/view?id=4", False),
    ("https://forms.gle/abc", "https://forms.gle/abd", False),
    ("https://forms.gle/abc", "http://evil.example/abc", False),
    ("javascript:alert(1)", "https://forms.gle/abc", False),
])
def test_same_url(a, b, same):
    assert same_url(a, b) is same and same_url(b, a) is same


# --- dedup: same-day sessions (audit 2026-11-13) -------------------------------
# The real title shapes of the 2026 department info sessions (inputs/ggongbab/manual.json and a
# Dooray mail shape). On one day they used to merge: the same-title floor ignored the start time,
# building and organizer, and normalization dropped "[전산학부]" and turned "AI" into "i".
INFO_SESSION_TITLES = [
    "2026 기계공학과 학과설명회", "2026 산업및시스템공학과 학과설명회", "2026 뇌인지과학과 학과설명회",
    "2026 기술경영학부 학과설명회", "2026 전기및전자공학부 학과설명회", "2026 바이오및뇌공학과 학과설명회",
    "2026 산업디자인학과 학과설명회", "2026 AX학과 학과설명회", "2026 신소재공학과 학과설명회",
    "2026 AI컴퓨팅학과 학과설명회", "2026 생명화학공학과 학과설명회", "2026 항공우주공학과 학과설명회",
    "2026 수리과학과 학과설명회", "2026 건설및환경공학과 학과설명회", "2026 원자력및양자공학과 학과설명회",
    "2026 AI미래학과 학과설명회", "2026 물리학과 학과설명회", "2026 화학과 학과설명회",
    "2026 AI시스템학과 학과설명회", "2026 생명과학과 학과설명회", "융합인재학부 학과설명회",
    "[전산학부] 학과 설명회",
]
DEPARTMENTS = [t.split()[-2] if t.startswith("2026") else t.split()[0].strip("[]") for t in INFO_SESSION_TITLES]
BRACKET_TITLES = [f"[{d}] 학과 설명회" for d in DEPARTMENTS]          # the Dooray mail shape for every department
BUILDINGS = ["N7", "E2", "E4", "E5", "E6", "E7", "N1", "N3", "N4", "N5", "W1", "W2", "W3", "W4", "W5", "W6",
             "W7", "W8", "W9", "W10", "E15", "E3"]


def _session(i, title, building=True):
    start = f"2026-11-23T{9 + i // 2:02d}:{30 * (i % 2):02d}:00+09:00"     # 09:00, 09:30, ... 19:30
    return _cand(title, start=start, building=BUILDINGS[i] if building else None,
                 food_provided="true", food_type="meal")


@pytest.mark.parametrize("titles", [INFO_SESSION_TITLES, BRACKET_TITLES], ids=["manual", "bracket"])
def test_department_info_sessions_on_one_day_stay_separate(settings, titles):
    assert len(titles) == len(set(DEPARTMENTS)) == 22
    from ggongbab.db.repository import MemoryRepository
    from ggongbab.pipeline import Pipeline
    repo = MemoryRepository()
    pipe = Pipeline(settings, repo, None, [])
    for i, title in enumerate(titles):
        pipe.store_candidate(_session(i, title), f"raw-{i}")
    assert len(repo.events) == 22
    assert sorted(row["title"] for row in repo.events.values()) == sorted(titles)


@pytest.mark.parametrize("titles", [INFO_SESSION_TITLES, BRACKET_TITLES], ids=["manual", "bracket"])
@pytest.mark.parametrize("building", [True, False])
def test_no_two_department_info_sessions_score_as_one(building, titles):
    sessions = [_session(i, t, building) for i, t in enumerate(titles)]
    for i, a in enumerate(sessions):
        for b in sessions[i + 1:]:
            row = b.to_db_row()
            assert score_pair(a, row) < 0.72, (a.title, b.title, score_pair(a, row))
            # Even at the very same minute without a building, the department names keep them apart.
            same_time = _cand(a.title, start=row["event_start"])
            assert score_pair(same_time, {**row, "building": None}) < 0.72, (a.title, b.title)


def test_same_title_same_day_but_hours_apart_is_two_events():
    row = {"id": "e1", "title": "기계공학과 간담회 (학부생)", "event_start": "2026-11-20T12:00:00+09:00"}
    assert find_match(_cand("기계공학과 간담회 (대학원생)", start="2026-11-20T18:00:00+09:00"), [row], 0.72) is None
    same = {"id": "e1", "title": "AI 세미나", "event_start": "2026-11-20T12:00:00+09:00"}
    assert find_match(_cand("AI 세미나", start="2026-11-20T15:00:00+09:00"), [same], 0.72) is None


@pytest.mark.parametrize("existing, incoming", [
    # one session, two mails: brackets, 안내/설명회 and spacing differ
    ({"title": "[전산학부] 학과 설명회", "event_start": "2026-11-23T18:00:00+09:00", "building": "E3"},
     {"title": "전산학부 학과설명회 안내", "start": "2026-11-23T18:00:00+09:00", "building": "E3"}),
    # the same title, one source gives only the date
    ({"title": "2026 수리과학과 학과설명회", "event_start": "2026-11-23T00:00:00+09:00", "building": None},
     {"title": "2026 수리과학과 학과설명회", "start": "2026-11-23T17:00:00+09:00", "building": "E6-1"}),
    # the same title and minute, the building written two ways
    ({"title": "2026 생명과학과 학과설명회", "event_start": "2026-11-18T18:30:00+09:00", "building": "창의학습관(E11)"},
     {"title": "2026 생명과학과 학과설명회", "start": "2026-11-18T18:30:00+09:00", "building": "E11"}),
    # the same title and minute, the KST and UTC spellings of one instant
    ({"title": "삼성전자 Tech Lunch Talk", "event_start": "2026-09-25T03:00:00+00:00", "building": "N1"},
     {"title": "[안내] 삼성전자 Tech Lunch Talk", "start": "2026-09-25T12:00:00+09:00", "building": "N1"}),
])
def test_true_duplicates_still_merge(existing, incoming):
    row = {"id": "e1", **existing}
    cand = _cand(incoming["title"], start=incoming["start"], building=incoming["building"])
    match = find_match(cand, [row], 0.72)
    assert match is not None and match.event["id"] == "e1", score_pair(cand, row)


def test_normalize_title_keeps_brackets_and_ai():
    from ggongbab.dedup import normalize_title
    assert normalize_title("[전산학부] 학과 설명회") == "전산학부 학과"
    assert normalize_title("기계공학과 간담회 (대학원생)") == "기계공학과 간담회 대학원생"
    assert normalize_title("2026 AI미래학과 학과설명회") == "2026 ai미래학과 학과"
    assert normalize_title("The Future of AI and Data") == "future ai data"
    assert normalize_title("Fwd: RE: 점심 특강 안내") == "점심 특강"
