# -*- coding: utf-8 -*-
"""Sessions and audience (2026-10-18): read back from the stored AI parse, validated, exported and kept
honest. The case that started it: the poster of 자연과학과 함께하는 토크 콘서트 (Mon-Thu 12:00-12:50 in one
hall, Fri 16:00-19:30 in another) was read correctly, but the event had one start and one end, so the page
showed only the first day. Fakes only: no model, database or network."""
from __future__ import annotations

import copy
import sys
from datetime import timedelta, timezone
from pathlib import Path

import pytest

from ggongbab import parse_extras
from ggongbab.config import KST, PROMPT_VERSION
from ggongbab.db.repository import MemoryRepository, SupabaseRepository
from ggongbab.exporter import build_archive, build_payload
from ggongbab.models import AudienceExtraction, Evidence, EventExtraction, SessionExtraction
from ggongbab.pipeline import Pipeline
from ggongbab.public_feed import PUBLIC_FIELDS, prepare_public_feed

from .conftest import TEST_NOW, FakeExtractor, make_extraction
from .test_export_contract import row
from .test_pipeline_export import FUTURE, ListCollector, _item

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from validate_content import validate_ggongbab_archive_payload, validate_ggongbab_payload  # noqa: E402

DAY0 = (TEST_NOW + timedelta(days=4)).astimezone(KST).replace(hour=12, minute=0, second=0, microsecond=0)


def at(day, hour, minute=0):
    return (DAY0 + timedelta(days=day)).replace(hour=hour, minute=minute).isoformat(timespec="seconds")


def concert_sessions():
    days = [{"start": at(d, 12), "end": at(d, 12, 50), "location_name": "자연과학관 공통강의실", "building": "E6-1",
             "room": "1501", "food_description": "샌드위치 선착순 130명"} for d in range(4)]
    days.append({"start": at(4, 16), "end": at(4, 19, 30), "location_name": "KI빌딩 퓨전홀", "building": "E4",
                 "room": "C101", "food_description": "쉐이크쉑 버거 선착순 250명"})
    return days


def utc(text):
    return parse_extras.aware(text).astimezone(timezone.utc).isoformat()


def concert_row(**over):
    extras = over.pop("_extras", {"sessions": concert_sessions(),
                                  "audience": {"text": "자연과학대학 학사과정 학생", "basis": "stated"}})
    return row(title="자연과학과 함께하는 토크 콘서트", event_start=utc(at(0, 12)), event_end=utc(at(4, 19, 30)),
               date_text="November 2 – 5 (Mon. – Thu.) / November 6 (Fri.)", time_text="12:00–12:50 / 16:00–19:30",
               _extras=extras, **over)


# --- sessions -------------------------------------------------------------------------------------
def test_the_talk_concert_becomes_five_days_with_their_own_times_and_places():
    sessions = parse_extras.public_sessions({"sessions": concert_sessions()}, utc(at(0, 12)), utc(at(4, 19, 30)))
    assert len(sessions) == 5
    assert [s["startAt"][:10] for s in sessions] == [at(d, 12)[:10] for d in range(5)]
    assert all(s["startAt"].endswith("+09:00") for s in sessions)
    monday, friday = sessions[0], sessions[4]
    assert (monday["startAt"][11:16], monday["endAt"][11:16]) == ("12:00", "12:50")
    assert monday["location"] == {"name": "자연과학관 공통강의실", "building": "E6-1", "room": "1501"}
    assert monday["foodDescription"] == "샌드위치 선착순 130명"
    assert (friday["startAt"][11:16], friday["endAt"][11:16]) == ("16:00", "19:30")
    assert friday["location"]["room"] == "C101" and "쉐이크쉑" in friday["foodDescription"]


def test_a_session_without_its_own_place_or_food_carries_neither():
    plain = [{"start": at(0, 12), "end": at(0, 13)}, {"start": at(1, 12), "end": None}]
    got = parse_extras.public_sessions({"sessions": plain}, utc(at(0, 12)), utc(at(1, 12)))
    assert got == [{"startAt": at(0, 12), "endAt": at(0, 13)}, {"startAt": at(1, 12), "endAt": None}]


def broken(mutator):
    sessions = concert_sessions()
    mutator(sessions)
    return {"sessions": sessions}


@pytest.mark.parametrize("name,extras", [
    ("one session is just the event", {"sessions": concert_sessions()[:1]}),
    ("fifteen is too many", {"sessions": [{"start": at(d, 12), "end": at(d, 13)} for d in range(15)]}),
    ("out of order", broken(lambda s: s.reverse())),
    ("the same start twice", broken(lambda s: s.__setitem__(1, dict(s[0])))),
    ("the first session is not the event's start", broken(lambda s: s.pop(0))),
    ("ends before it starts", broken(lambda s: s[1].update(end=at(1, 11)))),
    ("longer than a day", broken(lambda s: s[1].update(end=at(3, 12)))),
    ("a naive time", broken(lambda s: s[1].update(start="2026-11-03T12:00:00"))),
    ("no start", broken(lambda s: s[2].pop("start"))),
    ("not an object", broken(lambda s: s.__setitem__(2, "Fri 16:00"))),
    ("an unparseable end", broken(lambda s: s[2].update(end="soon"))),
    ("a session after the event's end", broken(lambda s: s[4].update(end=at(4, 21)))),
    ("not a list", {"sessions": "Mon-Fri"}),
    ("nothing", {}),
])
def test_sessions_that_do_not_fit_the_event_are_dropped_whole(name, extras):
    assert parse_extras.public_sessions(extras, utc(at(0, 12)), utc(at(4, 19, 30))) == [], name


def test_sessions_of_another_event_are_not_attached_by_start_alone():
    other_start = utc(at(1, 12))                  # the event row starts a day later than the parse says
    assert parse_extras.public_sessions({"sessions": concert_sessions()}, other_start, utc(at(4, 19, 30))) == []


# --- audience -------------------------------------------------------------------------------------
@pytest.mark.parametrize("basis", ["stated", "inferred"])
def test_a_stated_or_inferred_audience_is_public(basis):
    got = parse_extras.public_audience({"audience": {"text": "기계공학과 학부생", "basis": basis}})
    assert got == {"text": "기계공학과 학부생", "basis": basis}


@pytest.mark.parametrize("audience", [
    None, "기계공학과", {"text": "", "basis": "stated"}, {"text": "  ", "basis": "stated"},
    {"text": "기계공학과", "basis": "guess"}, {"text": "기계공학과"}, {"text": "가" * 61, "basis": "stated"},
    {"text": 7, "basis": "stated"},
])
def test_an_audience_that_is_empty_unknown_or_too_long_is_dropped(audience):
    assert parse_extras.public_audience({"audience": audience}) is None
    assert parse_extras.public_audience(None) is None


def test_personal_data_never_reaches_the_public_audience():
    got = parse_extras.public_audience({"audience": {"text": "기계공학과 (문의 staff.kim@kaist.ac.kr)", "basis": "stated"}})
    assert got is not None and "@" not in got["text"]


# --- export ---------------------------------------------------------------------------------------
def test_the_export_carries_sessions_and_audience_and_passes_the_privacy_validator(settings):
    payload = build_payload([concert_row()], settings, TEST_NOW)
    [event] = payload["events"]
    assert len(event["sessions"]) == 5 and event["audience"] == {"text": "자연과학대학 학사과정 학생", "basis": "stated"}
    assert event["startAt"] == event["sessions"][0]["startAt"] and event["endAt"] == event["sessions"][4]["endAt"]
    assert validate_ggongbab_payload(payload, TEST_NOW) == []


def test_an_event_without_extras_has_exactly_the_keys_it_had_before(settings):
    plain = build_payload([row()], settings, TEST_NOW)["events"][0]
    assert "sessions" not in plain and "audience" not in plain
    assert set(plain) == {"id", "title", "summary", "startAt", "endAt", "dateText", "timeText", "location", "food",
                          "organizer", "eligibility", "registration", "confidence", "sources"}


def test_inconsistent_sessions_cost_the_detail_not_the_event(settings):
    bad = {"sessions": broken(lambda s: s.pop(0))["sessions"], "audience": {"text": "학부생", "basis": "stated"}}
    payload = build_payload([concert_row(_extras=bad)], settings, TEST_NOW)
    [event] = payload["events"]
    assert "sessions" not in event and event["audience"]["text"] == "학부생"
    assert validate_ggongbab_payload(payload, TEST_NOW) == []


def test_the_archive_keeps_sessions_and_audience(settings):
    past = DAY0 - timedelta(days=9)
    sessions = [{"start": (past + timedelta(days=d)).isoformat(timespec="seconds"),
                 "end": (past + timedelta(days=d, hours=1)).isoformat(timespec="seconds")} for d in range(3)]
    old = row(id="22222222-2222-2222-2222-222222222222", title="지난 행사", event_start=utc(sessions[0]["start"]),
              event_end=utc(sessions[2]["end"]), _extras={"sessions": sessions, "audience": {"text": "학부생", "basis": "inferred"}})
    archive = build_archive([old], settings, {old["id"]}, TEST_NOW)
    [event] = archive["events"]
    assert len(event["sessions"]) == 3 and event["audience"]["basis"] == "inferred"
    assert validate_ggongbab_archive_payload(archive) == []


# --- the validator refuses what the exporter never writes --------------------------------------------
def payload_with(settings, **patch):
    payload = copy.deepcopy(build_payload([concert_row()], settings, TEST_NOW))
    payload["events"][0].update(patch)
    return payload


@pytest.mark.parametrize("name,patch,needle", [
    ("one session", lambda e: {"sessions": e["sessions"][:1]}, "sessions must hold"),
    ("out of order", lambda e: {"sessions": list(reversed(e["sessions"]))}, "not after the previous"),
    ("not the first day", lambda e: {"sessions": e["sessions"][1:]}, "first session does not start at startAt"),
    ("an extra key in a session", lambda e: {"sessions": [dict(e["sessions"][0], note="x")] + e["sessions"][1:]},
     "not in the reviewed public schema"),
    ("a mail address in a venue", lambda e: {"sessions": [dict(e["sessions"][0], location={"name": "a@b.kr", "building": "", "room": ""})] + e["sessions"][1:]},
     "e-mail address"),
    ("a session after endAt", lambda e: {"endAt": e["sessions"][3]["endAt"]}, "ends after endAt"),
    ("an unknown audience basis", lambda e: {"audience": {"text": "학부생", "basis": "guess"}}, "audience needs"),
    ("a long audience", lambda e: {"audience": {"text": "가" * 61, "basis": "stated"}}, "audience needs"),
    ("an extra audience key", lambda e: {"audience": {"text": "학부생", "basis": "stated", "who": "x"}},
     "not in the reviewed public schema"),
])
def test_the_validator_refuses_a_bad_sessions_or_audience_field(settings, name, patch, needle):
    base = build_payload([concert_row()], settings, TEST_NOW)
    errors = validate_ggongbab_payload(payload_with(settings, **patch(base["events"][0])), TEST_NOW)
    assert any(needle in error for error in errors), (name, errors)


# --- the JSON schemas -------------------------------------------------------------------------------
def schema(name):
    import json
    return json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("file", ["ggongbab-feed.schema.json"])
def test_the_feed_schema_accepts_the_export_and_refuses_bad_extras(settings, file):
    jsonschema = pytest.importorskip("jsonschema")
    validator = jsonschema.Draft202012Validator(schema(file))
    good = build_payload([concert_row()], settings, TEST_NOW)
    assert list(validator.iter_errors(good)) == []
    for patch in ({"sessions": good["events"][0]["sessions"][:1]},
                  {"sessions": [dict(good["events"][0]["sessions"][0], note="x")] + good["events"][0]["sessions"][1:]},
                  {"audience": {"text": "학부생", "basis": "guess"}}, {"audience": {"text": "", "basis": "stated"}}):
        bad = copy.deepcopy(good)
        bad["events"][0].update(patch)
        assert list(validator.iter_errors(bad)), patch


def test_the_archive_schema_accepts_the_archive_and_refuses_bad_extras(settings):
    jsonschema = pytest.importorskip("jsonschema")
    validator = jsonschema.Draft202012Validator(schema("ggongbab-archive.schema.json"))
    past = DAY0 - timedelta(days=9)
    sessions = [{"start": (past + timedelta(days=d)).isoformat(timespec="seconds"),
                 "end": (past + timedelta(days=d, hours=1)).isoformat(timespec="seconds")} for d in range(3)]
    old = row(id="22222222-2222-2222-2222-222222222222", event_start=utc(sessions[0]["start"]),
              event_end=utc(sessions[2]["end"]), _extras={"sessions": sessions, "audience": {"text": "학부생", "basis": "stated"}})
    good = build_archive([old], settings, {old["id"]}, TEST_NOW)
    assert list(validator.iter_errors(good)) == []
    bad = copy.deepcopy(good)
    bad["events"][0]["audience"] = {"text": "학부생", "basis": "guess"}
    assert list(validator.iter_errors(bad))


# --- reading the stored parse back ------------------------------------------------------------------
def memory_with_run(**run):
    repo = MemoryRepository()
    repo.sources = {"dooray": "src-1"}
    repo.raw_items = {"raw-1": {"source_id": "src-1", "source_url": ""}}
    event = concert_row()
    event.pop("_extras"), event.pop("_sources")
    repo.events[event["id"]] = event
    repo.event_sources[(event["id"], "raw-1")] = 1.0
    parsed = {"event_start": at(0, 12), "sessions": concert_sessions(), "audience": {"text": "학부생", "basis": "stated"}}
    base = {"raw_item_id": "raw-1", "prompt_version": PROMPT_VERSION, "status": "ok", "role": "primary",
            "created_at": "2026-10-18T09:00:00+00:00", "parsed_json": parsed}
    repo.ai_runs.append({**base, **run})
    return repo


def test_the_repository_attaches_the_parse_that_produced_the_events_own_start():
    [event] = memory_with_run().publishable_events()
    assert event["_extras"]["sessions"] == concert_sessions() and event["_extras"]["audience"]["text"] == "학부생"


@pytest.mark.parametrize("name,run", [
    ("an older prompt version", {"prompt_version": "ggongbab-extract-v5"}),
    ("a failed run", {"status": "error"}),
    ("a fallback run", {"role": "fallback"}),
    ("a parse of another start", {"parsed_json": {"event_start": at(1, 12), "sessions": concert_sessions()}}),
    ("a parse without a start", {"parsed_json": {"sessions": concert_sessions()}}),
    ("no parse", {"parsed_json": None}),
])
def test_the_repository_ignores_a_parse_that_is_not_this_events(name, run):
    [event] = memory_with_run(**run).publishable_events()
    assert "_extras" not in event, name


def test_the_newest_parse_wins():
    repo = memory_with_run()
    newer = {"raw_item_id": "raw-1", "prompt_version": PROMPT_VERSION, "status": "ok", "role": "primary",
             "created_at": "2026-10-18T10:00:00+00:00",
             "parsed_json": {"event_start": at(0, 12), "sessions": None, "audience": {"text": "전체", "basis": "stated"}}}
    repo.ai_runs.append(newer)
    [event] = repo.publishable_events()
    assert event["_extras"]["sessions"] is None and event["_extras"]["audience"]["text"] == "전체"


class FakeClient:
    def __init__(self, runs=(), fail=False):
        self.runs, self.fail, self.calls = list(runs), fail, []

    def select_all(self, table, params):
        self.calls.append((table, dict(params)))
        if self.fail:
            raise RuntimeError("boom")
        return self.runs


def test_the_supabase_read_asks_only_for_current_successful_primary_parses_in_short_batches():
    raw_ids = [f"raw-{n:03d}" for n in range(parse_extras.RUN_BATCH + 5)]
    events = [{"id": "e1", "event_start": utc(at(0, 12))}]
    runs = [{"raw_item_id": "raw-001", "created_at": "2026-10-18T09:00:00+00:00",
             "parsed_json": {"event_start": at(0, 12), "sessions": concert_sessions(), "audience": None}}]
    client = FakeClient(runs)
    SupabaseRepository(client)._attach_extras(events, {"e1": raw_ids})
    assert len(client.calls) == 2                                     # 55 ids -> two requests, never one long URL
    table, params = client.calls[0]
    assert table == "ai_parse_runs"
    assert params["prompt_version"] == f"eq.{PROMPT_VERSION}" and params["status"] == "eq.ok"
    assert params["role"] == "eq.primary" and params["order"] == "id.asc"          # select_all needs a unique order
    assert params["raw_item_id"].startswith("in.(raw-000,") and params["select"] == "id,raw_item_id,parsed_json,created_at"
    assert events[0]["_extras"]["sessions"] == concert_sessions()


def test_a_failing_supabase_read_leaves_the_events_untouched():
    events = [{"id": "e1", "event_start": utc(at(0, 12))}]
    SupabaseRepository(FakeClient(fail=True))._attach_extras(events, {"e1": ["raw-1"]})
    assert "_extras" not in events[0]
    SupabaseRepository(FakeClient())._attach_extras([], {})            # nothing to read: no error


def test_the_database_projection_prepares_with_the_new_keys_and_never_carries_them(settings):
    """ggongbab_replace_public_feed refuses a row key outside its allowlist (migrations 004/006), and the
    snapshot is validated before it is projected: the new keys must pass the validator and stay out of the rows."""
    prepared = prepare_public_feed(memory_with_run(), settings, TEST_NOW)
    [event] = prepared.payload["events"]
    assert len(event["sessions"]) == 5 and event["audience"]["basis"] == "stated"
    [public] = prepared.rows
    assert set(public) == set(PUBLIC_FIELDS) | {"content_revision"}
    assert "sessions" not in public and "audience" not in public


# --- the whole chain: model output -> stored parse -> export --------------------------------------------
def test_a_multi_day_extraction_reaches_the_public_snapshot(settings):
    first, last = FUTURE, FUTURE + timedelta(days=2)
    sessions = [SessionExtraction(start=(FUTURE + timedelta(days=d)).isoformat(),
                                  end=(FUTURE + timedelta(days=d, hours=1)).isoformat(),
                                  location_name=None, building=None, room=None,
                                  food_description="도시락" if d == 2 else None) for d in range(3)]

    def extraction(text):
        return make_extraction(
            title="기업 설명회 주간", event_start=first.isoformat(), event_end=(last + timedelta(hours=1)).isoformat(),
            date_text="3일간", sessions=sessions,
            audience=AudienceExtraction(text="기계공학과 학부생", basis="inferred"),
            evidence=Evidence(event_time="3일간 12시", location="N1에서", food="참석자에게 점심 도시락을 제공합니다",
                              registration=None))

    repo = MemoryRepository()
    Pipeline(settings, repo, FakeExtractor(extraction), [ListCollector([_item()])]).run()
    [stored] = repo.ai_runs
    assert len(stored["parsed_json"]["sessions"]) == 3 and stored["parsed_json"]["audience"]["basis"] == "inferred"
    payload = build_payload(repo.publishable_events(), settings, TEST_NOW)
    [event] = payload["events"]
    assert [s["startAt"][:10] for s in event["sessions"]] == [(FUTURE + timedelta(days=d)).date().isoformat() for d in range(3)]
    assert event["sessions"][2]["foodDescription"] == "도시락" and event["audience"] == {"text": "기계공학과 학부생", "basis": "inferred"}
    assert validate_ggongbab_payload(payload, TEST_NOW) == []


# --- the extraction schema and the prompt -------------------------------------------------------------
def test_the_extraction_schema_is_strict_with_the_new_fields_and_an_old_parse_still_validates():
    from openai.lib._pydantic import to_strict_json_schema
    strict = to_strict_json_schema(EventExtraction)
    assert {"sessions", "audience"} <= set(strict["required"])
    assert set(strict["$defs"]["SessionExtraction"]["required"]) == {"start", "end", "location_name", "building", "room",
                                                                       "food_description"}
    assert set(strict["$defs"]["AudienceExtraction"]["required"]) == {"text", "basis"}
    old = make_extraction().model_dump()
    for key in ("sessions", "audience"):
        old.pop(key)
    again = EventExtraction.model_validate(old)
    assert again.sessions is None and again.audience is None


def test_the_prompt_asks_for_sessions_and_a_strict_audience_and_the_version_moved():
    from ggongbab.parsers.ai_parser import SYSTEM_PROMPT
    assert PROMPT_VERSION == "ggongbab-extract-v6"
    for needle in ("4a. sessions", "one item per day", "sessions = null", "6c. audience", 'basis = "inferred" ONLY',
                   "is NOT inferred", "event_start and event_end stay the"):
        assert needle in SYSTEM_PROMPT, needle
    assert "ONE event" in SYSTEM_PROMPT       # still one event; sessions only describe its days
