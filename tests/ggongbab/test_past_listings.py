# -*- coding: utf-8 -*-
"""Past listings (data/ggongbab/archive/index.json): which rows enter, what they carry, and how
the export and the validator keep the live feed and the archive apart. Synthetic rows only."""
from __future__ import annotations

import copy
import itertools
import json
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from ggongbab.config import KST
from ggongbab.db.repository import MemoryRepository
from ggongbab.exporter import (ARCHIVE_WINDOW_DAYS, build_archive, build_payload, previously_listed_ids,
                               write_archive, write_payload)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import refresh_ggongbab  # noqa: E402
from validate_content import validate_ggongbab_archive_payload, validate_ggongbab_payload  # noqa: E402

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=KST)


def row(event_id="evt-a", *, ended_hours_ago=24.0, duration_hours=1.0, **over):
    end = NOW - timedelta(hours=ended_hours_ago)
    base = {
        "id": event_id,
        "title": f"진로 세미나 {event_id}",
        "summary": "점심 도시락을 제공하는 세미나입니다.",
        "event_start": (end - timedelta(hours=duration_hours)).isoformat(),
        "event_end": end.isoformat(),
        "registration_deadline": (end - timedelta(days=2)).isoformat(),
        "date_text": "9월", "time_text": "12시",
        "location_name": "N1", "building": "N1", "room": "101호",
        "food_provided": "true", "food_type": "lunchbox", "food_description": "점심 도시락",
        "organizer": "경력개발센터", "eligibility": "KAIST 학생",
        "registration_required": "true", "registration_url": "https://example.org/register",
        "confidence": 0.95, "needs_review": False, "review_reason": None, "status": "published",
        # Private columns a careless exporter could leak.
        "sender_email": "someone@kaist.ac.kr", "raw_text": "원문 메일 본문", "external_id": "dooray-123",
        "_sources": [{"type": "dooray", "name": "Dooray", "url": "https://kaist.dooray.com/task/123"}],
    }
    base.update(over)
    return base


def archive(rows, settings, listed=None, now=NOW):
    listed = {r["id"] for r in rows} if listed is None else listed
    return build_archive(rows, settings, listed, now)


def ids(payload):
    return [event["id"] for event in payload["events"]]


# ---------------------------------------------------------------------------
# Which rows enter
# ---------------------------------------------------------------------------
def test_an_ended_listing_moves_from_the_live_feed_to_the_archive(settings):
    rows = [row("ended", ended_hours_ago=24)]
    assert ids(build_payload(rows, settings, NOW, food_only=True)) == []
    assert ids(archive(rows, settings)) == ["ended"]


def test_future_and_current_listings_stay_live(settings):
    rows = [row("future", ended_hours_ago=-72), row("now", ended_hours_ago=-1, duration_hours=3)]
    assert ids(build_payload(rows, settings, NOW, food_only=True)) == ["now", "future"]
    assert ids(archive(rows, settings)) == []


def test_the_grace_period_keeps_a_just_ended_listing_live_until_the_feed_drops_it(settings):
    grace = settings.expired_grace_hours
    inside, outside = row("inside", ended_hours_ago=grace - 0.5), row("outside", ended_hours_ago=grace + 0.5)
    assert ids(build_payload([inside, outside], settings, NOW, food_only=True)) == ["inside"]
    assert ids(archive([inside, outside], settings)) == ["outside"]


@pytest.mark.parametrize("hours", [-24 * 70, -24 * 10, -1, 0, 1, 2.9, 3.1, 6, 24, 24 * 29, 24 * 29.9])
def test_a_listed_eligible_row_is_live_or_archived_never_both_or_neither(settings, hours):
    """Both files use the same eligibility and is_expired at the same clock."""
    rows = [row("x", ended_hours_ago=hours)]
    live, past = ids(build_payload(rows, settings, NOW, food_only=True)), ids(archive(rows, settings))
    if hours <= -24 * settings.export_horizon_days:
        assert live == past == []  # beyond the live horizon, and not ended
    else:
        assert sorted(live + past) == ["x"]


def multi_day(first_day_offset_hours):
    """Three daily noon hand-outs with no event_end, the first `first_day_offset_hours` before NOW."""
    first = NOW - timedelta(hours=first_day_offset_hours)
    days = [first + timedelta(days=d) for d in range(3)]
    return row("multi", event_start=first.isoformat(), event_end=None,
               _extras={"sessions": [{"start": d.isoformat(), "end": None} for d in days]})


@pytest.mark.parametrize("first_day_offset_hours", [1, 21, 24 + 21])
def test_a_multi_day_event_stays_live_until_its_last_session(settings, first_day_offset_hours):
    """Audit 2026-11-13: with sessions and no event_end the event expired three hours after the
    first session, so days two and three vanished from the feed and went to the archive."""
    rows = [multi_day(first_day_offset_hours)]
    live = build_payload(rows, settings, NOW, food_only=True)
    assert ids(live) == ["multi"] and len(live["events"][0]["sessions"]) == 3
    assert ids(archive(rows, settings)) == []
    assert validate_ggongbab_payload(live, now=NOW) == []


def test_a_multi_day_event_is_archived_after_its_last_session(settings):
    rows = [multi_day(48 + settings.expired_grace_hours + 1)]
    assert ids(build_payload(rows, settings, NOW, food_only=True)) == []
    past = archive(rows, settings)
    assert ids(past) == ["multi"]
    assert validate_ggongbab_archive_payload(past, set()) == []


def test_sessions_that_do_not_fit_do_not_extend_an_event(settings):
    """Only sessions the feed would show count; a broken list keeps the old start + grace rule."""
    broken = multi_day(21)
    broken["_extras"]["sessions"].reverse()
    assert ids(build_payload([broken], settings, NOW, food_only=True)) == []


@pytest.mark.parametrize("over", [
    {"needs_review": True}, {"food_provided": "false"}, {"food_provided": "unknown"}, {"food_provided": None},
    {"status": "draft"}, {"status": "review"}, {"status": "rejected"}, {"status": "archived"},
    {"confidence": 0.5}, {"event_start": None, "event_end": None},
])
def test_rows_the_live_feed_would_refuse_never_enter_the_archive(settings, over):
    assert ids(archive([row("x", **over)], settings)) == []


def test_listings_that_ended_more_than_30_days_ago_leave_the_public_window(settings):
    rows = [row("old", ended_hours_ago=24 * ARCHIVE_WINDOW_DAYS + 1), row("recent", ended_hours_ago=24 * ARCHIVE_WINDOW_DAYS - 1)]
    assert ids(archive(rows, settings)) == ["recent"]


def test_a_row_that_was_never_published_is_not_archived(settings):
    """A backfilled event that ended before any export saw it was never a public listing."""
    rows = [row("listed"), row("backfilled", ended_hours_ago=30)]
    assert ids(archive(rows, settings, listed={"listed"})) == ["listed"]


def test_publication_evidence_comes_from_the_previous_live_feed_and_archive(settings, tmp_path):
    write_payload({"events": [{"id": "was-live"}]}, tmp_path)
    write_archive({"events": [{"id": "was-archived"}]}, tmp_path)
    assert previously_listed_ids(tmp_path) == {"was-live", "was-archived"}
    (tmp_path / "latest.json").write_text("{not json", encoding="utf-8")
    assert previously_listed_ids(tmp_path) == {"was-archived"}
    assert previously_listed_ids(tmp_path / "missing") == set()


# ---------------------------------------------------------------------------
# What an archived record carries
# ---------------------------------------------------------------------------
def test_an_archived_record_has_no_sign_up_data_and_no_private_fields(settings):
    event = archive([row("x")], settings)["events"][0]
    assert "registration" not in event and "confidence" not in event
    text = json.dumps(event, ensure_ascii=False)
    for private in ("someone@kaist.ac.kr", "원문 메일 본문", "dooray-123", "dooray.com", "example.org/register"):
        assert private not in text
    assert set(event) == {"id", "title", "summary", "startAt", "endAt", "dateText", "timeText",
                          "location", "food", "organizer", "eligibility", "sources"}


def test_internal_source_links_are_dropped_and_public_notice_links_kept(settings):
    sources = [{"type": "dooray", "name": "Dooray", "url": "https://kaist.dooray.com/task/1"},
               {"type": "kaist_public", "name": "KAIST 공지", "url": "https://www.kaist.ac.kr/kr/html/news/1"},
               {"type": "manual", "name": "Manual", "url": "javascript:alert(1)"}]
    event = archive([row("x", _sources=sources)], settings)["events"][0]
    assert event["sources"] == [{"type": "dooray", "name": "Dooray"},
                                {"type": "kaist_public", "name": "KAIST 공지", "url": "https://www.kaist.ac.kr/kr/html/news/1"},
                                {"type": "manual", "name": "Manual"}]


def test_duplicate_rows_are_archived_once(settings):
    assert ids(archive([row("x"), row("x", title="같은 행사")], settings)) == ["x"]


def test_order_is_most_recently_ended_first_and_independent_of_input(settings):
    rows = [row("b", ended_hours_ago=48), row("a", ended_hours_ago=48), row("c", ended_hours_ago=5), row("d", ended_hours_ago=200)]
    orders = {tuple(ids(archive(list(perm), settings))) for perm in itertools.permutations(rows)}
    assert orders == {("c", "a", "b", "d")}


def test_the_payload_shape(settings):
    payload = archive([row("x")], settings)
    assert payload["generatedAt"] == NOW.isoformat(timespec="seconds")
    assert payload["timezone"] == "Asia/Seoul" and payload["windowDays"] == 30 and payload["count"] == 1


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def valid_archive(settings):
    return archive([row("a", ended_hours_ago=5), row("b", ended_hours_ago=50,
                    _sources=[{"type": "kaist_public", "name": "KAIST 공지", "url": "https://www.kaist.ac.kr/kr/html/n/2"}])], settings)


def test_a_generated_archive_passes_validation(settings):
    assert validate_ggongbab_archive_payload(valid_archive(settings)) == []
    assert validate_ggongbab_archive_payload(archive([], settings)) == []


def _broken(settings, change):
    payload = copy.deepcopy(valid_archive(settings))
    change(payload, payload["events"][0])
    return validate_ggongbab_archive_payload(payload)


@pytest.mark.parametrize("change, message", [
    (lambda p, e: e.update(endAt=(NOW + timedelta(hours=1)).isoformat()), "had not ended"),
    (lambda p, e: e.update(startAt=(NOW - timedelta(days=40)).isoformat(), endAt=(NOW - timedelta(days=31)).isoformat()), "outside the 30-day"),
    (lambda p, e: p["events"].append(copy.deepcopy(p["events"][0])) or p.update(count=3), "duplicate id"),
    (lambda p, e: e.update(registration={"required": "true", "url": "https://example.org/r"}), "carries registration"),
    (lambda p, e: e.update(confidence=0.9), "carries confidence"),
    (lambda p, e: e.update(sources=[{"type": "dooray", "name": "Dooray", "url": "https://example.org/x"}]), "exposes a dooray source URL"),
    (lambda p, e: e.update(review_reason="ambiguous"), "private field"),
    (lambda p, e: e.update(summary="문의 someone@kaist.ac.kr"), "e-mail"),
    (lambda p, e: e["food"].update(provided="unknown"), "food.provided must be true"),
    (lambda p, e: p["events"].reverse(), "most-recently-ended order"),
    (lambda p, e: p.update(windowDays=365), "windowDays"),
    (lambda p, e: p.update(count=9), "count does not match"),
    (lambda p, e: e.update(startAt="2026-09-20T03:00:00+00:00", endAt=None), "not +09:00"),
])
def test_the_validator_rejects_unsafe_or_inconsistent_archives(settings, change, message):
    errors = _broken(settings, change)
    assert any(message in err for err in errors), errors


def test_the_validator_rejects_a_listing_that_is_also_live(settings):
    payload = valid_archive(settings)
    assert any("also in the live feed" in err for err in validate_ggongbab_archive_payload(payload, {"a"}))
    assert validate_ggongbab_archive_payload(payload, {"someone-else"}) == []


def test_the_live_feed_still_refuses_expired_events(settings):
    """The archive does not relax latest.json: an expired row there is still an error."""
    live = build_payload([row("x", ended_hours_ago=-5)], settings, NOW - timedelta(hours=12), food_only=True)
    assert ids(live) == ["x"]
    assert any("expired" in err for err in validate_ggongbab_payload(live, now=NOW + timedelta(hours=12)))
    assert validate_ggongbab_payload(live, now=NOW) == []


def test_a_committed_live_feed_is_judged_at_its_own_generation_time(settings):
    """Without an explicit `now` the validator uses the file's generatedAt, as the archive does:
    a committed snapshot never starts failing later and blocking another family's publish."""
    live = build_payload([row("x", ended_hours_ago=-5)], settings, NOW - timedelta(hours=12), food_only=True)
    assert validate_ggongbab_payload(live) == []          # the wall clock is weeks past this file
    assert any("expired" in err for err in validate_ggongbab_payload(live, now=NOW + timedelta(hours=12)))


# ---------------------------------------------------------------------------
# The export writes both files, from one clock, with the live feed first
# ---------------------------------------------------------------------------
class StubRepo:
    def __init__(self, rows):
        self.rows = rows
        self.projected: list[list[str]] = []

    def publishable_events(self):
        return [dict(r) for r in self.rows]

    def recent_published_events(self, days):
        return [dict(r) for r in self.rows]

    # Where the export also synchronizes the public DB projection (lab), record what reaches it.
    def public_feed_generation(self):
        return len(self.projected)

    def public_feed_has_links(self):
        return True

    def replace_public_feed(self, generation, rows):
        self.projected.append([row["id"] for row in rows])
        return generation + 1


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    folder = tmp_path / "data" / "ggongbab"
    folder.mkdir(parents=True)
    monkeypatch.setattr(refresh_ggongbab, "DATA_DIR", folder)
    monkeypatch.setattr(refresh_ggongbab, "ROOT", tmp_path)
    public_news = tmp_path / "inputs/ggongbab/food-news.json"
    public_news.parent.mkdir(parents=True)
    public_news.write_text('{"items": []}', encoding="utf-8")
    return folder


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def uid(name):
    """A canonical UUID, as the database assigns (lab's public projection refuses anything else)."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "babdoduk-test/" + name))


def _fresh_row(name, **over):
    """Relative to the real clock, because export() stamps datetime.now()."""
    real = datetime.now(KST)
    return row(uid(name), ended_hours_ago=(NOW - real).total_seconds() / 3600 + over.pop("ended_hours_ago", 24), **over)


def test_export_archives_what_the_previous_feed_listed(settings, data_dir, capsys):
    write_payload({"events": [{"id": uid("listed")}]}, data_dir)
    rows = [_fresh_row("listed"), _fresh_row("backfilled"), _fresh_row("upcoming", ended_hours_ago=-48)]
    repo = StubRepo(rows)
    assert refresh_ggongbab.export(settings, repo, dry_run=False) == 0
    assert ids(_read(data_dir / "latest.json")) == [uid("upcoming")]
    assert ids(_read(data_dir / "archive" / "index.json")) == [uid("listed")]
    # audit 2026-11-13: the export no longer writes the public DB projection; the workflow's
    # sync step does, after publication (it mirrors the live snapshot, never the archive).
    assert repo.projected == []
    assert not (data_dir / ".staging").exists()
    assert "events=1 archive=1" in capsys.readouterr().out


def test_an_invalid_archive_keeps_the_previous_one_without_holding_back_the_live_feed(settings, data_dir, monkeypatch, capsys):
    write_archive({"generatedAt": "previous", "events": []}, data_dir)
    monkeypatch.setattr(refresh_ggongbab, "validate_archive_export", lambda path, live: ["synthetic failure"])
    assert refresh_ggongbab.export(settings, StubRepo([_fresh_row("upcoming", ended_hours_ago=-48)]), dry_run=False) == 0
    assert ids(_read(data_dir / "latest.json")) == [uid("upcoming")]
    assert _read(data_dir / "archive" / "index.json")["generatedAt"] == "previous"
    assert "keeping previous archive" in capsys.readouterr().out


def test_a_failing_archive_query_never_costs_the_live_feed_a_refresh(settings, data_dir, capsys):
    class Flaky(StubRepo):
        def recent_published_events(self, days):
            raise ConnectionError("https://private.example/rest/v1/events?apikey=SECRET")

    write_archive({"generatedAt": "previous", "events": []}, data_dir)
    assert refresh_ggongbab.export(settings, Flaky([_fresh_row("upcoming", ended_hours_ago=-48)]), dry_run=False) == 0
    assert ids(_read(data_dir / "latest.json")) == [uid("upcoming")]
    assert _read(data_dir / "archive" / "index.json")["generatedAt"] == "previous"
    out = capsys.readouterr().out
    assert "archive not built (ConnectionError)" in out and "archive=kept" in out
    assert "SECRET" not in out and "private.example" not in out  # Actions logs are public
    assert not (data_dir / ".staging").exists()


def test_one_failing_event_is_left_out_instead_of_blocking_the_export(settings, data_dir, capsys):
    """Audit 2026-11-13: one event the validator refused failed the whole export (exit 23), so
    every other listing went stale. Now it alone is left out, with a value-free count."""
    rows = [_fresh_row("good", ended_hours_ago=-48),
            _fresh_row("empty-title", ended_hours_ago=-48, title="<br>"),            # nothing left after markup
            _fresh_row("twin-a", ended_hours_ago=-30, title="공학관 피자 나눔"),
            _fresh_row("twin-b", ended_hours_ago=-30, title="공학관 피자 나눔")]       # same-day look-alike
    assert refresh_ggongbab.export(settings, StubRepo(rows), dry_run=False) == 0
    listed = ids(_read(data_dir / "latest.json"))
    assert uid("good") in listed and uid("empty-title") not in listed
    assert len([i for i in listed if i in (uid("twin-a"), uid("twin-b"))]) == 1
    assert validate_ggongbab_payload(_read(data_dir / "latest.json")) == []
    out = capsys.readouterr().out
    assert "2 event(s) failed public validation" in out
    assert uid("empty-title") not in out and "피자" not in out      # Actions logs are public


def test_a_bracketed_title_is_kept_and_real_markup_is_removed():
    """Audit 2026-11-13: every <...> span was stripped, so "<2026 가을 축제 푸드트럭>" became an empty title."""
    from ggongbab.public_sanitizer import public_text
    assert public_text("<2026 가을 축제 푸드트럭>") == "<2026 가을 축제 푸드트럭>"
    assert public_text("<KAIST 창업원> 점심 특강") == "<KAIST 창업원> 점심 특강"
    assert public_text("점심 특강 <선착순 50명>") == "점심 특강 <선착순 50명>"
    assert public_text("<b>피자</b> 제공<br/>") == "피자 제공"
    assert public_text('<img alt="사진" src=x>점심') == "점심"
    assert public_text("&lt;script&gt;x&lt;/script&gt;<!-- note -->") == "x"
    assert public_text("문의 010-1234-5678") == "문의 [phone]"           # masking still runs before validation


def test_dry_run_writes_neither_file(settings, data_dir, capsys):
    assert refresh_ggongbab.export(settings, StubRepo([_fresh_row("x")]), dry_run=True) == 0
    assert not (data_dir / "latest.json").exists() and not (data_dir / "archive").exists()
    assert not (data_dir / "news.json").exists()
    assert "archive: 0 ended listing(s) in the last 30 days" in capsys.readouterr().out


def test_memory_repository_returns_recently_started_published_rows():
    repo = MemoryRepository()
    now = datetime.now(KST)
    for event_id, days_ago, extra in (("recent", 5, {}), ("old", 90, {}), ("future", -3, {}),
                                      ("review", 5, {"needs_review": True}), ("draft", 5, {"status": "draft"})):
        repo.insert_event({"status": "published", "needs_review": False, "title": event_id,
                           "event_start": (now - timedelta(days=days_ago)).isoformat(), **extra})
    assert [r["title"] for r in repo.recent_published_events(60)] == ["recent"]
