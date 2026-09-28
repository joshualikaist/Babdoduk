# -*- coding: utf-8 -*-
"""Weekly KAIST cafeteria collection. Fake pages only - the live KAIST site is never called."""
from __future__ import annotations

import json
import urllib.parse
from datetime import date, datetime, timedelta, timezone

import pytest

import refresh_kaist_menu as km

KST = km.KST
WED = datetime(2026, 9, 30, 6, 0, tzinfo=KST)          # a Wednesday, 06:00 KST
IDS = [row["id"] for row in km.RESTAURANTS]


def page(menu):
    """An official-looking page. `menu` maps meal -> items; None renders no table at all."""
    if menu is None:
        return "<html><body><p>점검 중</p></body></html>"
    cells = "".join("<td>" + "<br>".join(menu.get(meal, [])) + "</td>" for meal in km.MEALS)
    return f'<html><table class="table"><tr>{cells}</tr></table></html>'


class Site:
    """Answers per (restaurant, date): a menu dict, "empty" (published, no items), "notable"
    (upstream HTML change) or "down" (network error). Default: a small lunch menu."""

    def __init__(self, rules=None, default="menu"):
        self.rules, self.default, self.calls = dict(rules or {}), default, []

    def __call__(self, url):
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        key = (query["dvs_cd"], query["stt_dt"])
        self.calls.append(key)
        rule = self.rules.get(key, self.rules.get(key[1], self.default))
        if rule == "down":
            raise OSError("network down")
        if rule == "notable":
            return page(None)
        if rule == "empty":
            return page({})
        if rule == "menu":
            return page({"lunch": [f"{key[0]} 점심 {key[1]}", "쌀밥"], "dinner": ["저녁 정식"]})
        return page(rule)


def run(tmp_path, site, now=WED, **kw):
    return km.refresh(tmp_path, now=now, fetcher=site, pause=lambda: None, **kw)


def day_file(tmp_path, iso):
    return json.loads((tmp_path / f"{iso}.json").read_text(encoding="utf-8"))


# --- week arithmetic ----------------------------------------------------------------------
@pytest.mark.parametrize("day,monday,sunday", [
    (date(2026, 9, 30), date(2026, 9, 28), date(2026, 10, 4)),     # month boundary Sep -> Oct
    (date(2026, 9, 28), date(2026, 9, 28), date(2026, 10, 4)),     # Monday is its own start
    (date(2026, 10, 4), date(2026, 9, 28), date(2026, 10, 4)),     # Sunday closes the week
    (date(2026, 12, 31), date(2026, 12, 28), date(2027, 1, 3)),    # year boundary
    (date(2028, 2, 29), date(2028, 2, 28), date(2028, 3, 5)),      # leap day
    (date(2027, 3, 1), date(2027, 3, 1), date(2027, 3, 7)),        # non-leap March 1st
])
def test_week_is_monday_to_sunday(day, monday, sunday):
    week = km.week_of(day)
    assert len(week) == 7 and week[0] == monday and week[-1] == sunday
    assert [d.weekday() for d in week] == list(range(7))
    assert all((b - a).days == 1 for a, b in zip(week, week[1:]))


@pytest.mark.parametrize("instant,expected", [
    (datetime(2026, 9, 27, 15, 30, tzinfo=timezone.utc), date(2026, 9, 28)),                # Mon 00:30 KST
    (datetime(2026, 9, 27, 14, 59, tzinfo=timezone.utc), date(2026, 9, 27)),                # Sun 23:59 KST
    (datetime(2026, 9, 27, 9, 0, tzinfo=timezone(timedelta(hours=-7))), date(2026, 9, 28)),  # LA Sunday evening
])
def test_the_kaist_day_is_decided_in_kst_not_by_the_host_timezone(instant, expected):
    assert km.kst_today(instant) == expected


def test_a_naive_clock_is_refused():
    with pytest.raises(ValueError):
        km.kst_today(datetime(2026, 9, 28, 12, 0))


def test_daily_filename_is_the_iso_date(tmp_path):
    assert km.day_path(tmp_path, date(2026, 10, 1)).name == "2026-10-01.json"


# --- a full week --------------------------------------------------------------------------
def test_first_run_of_a_week_fetches_all_seven_days_and_writes_the_index(tmp_path):
    site = Site({"2026-10-04": "empty"})                                   # Sunday not published yet
    summary = run(tmp_path, site)
    assert summary["requests"] == 56 and len(site.calls) == 56
    week = json.loads((tmp_path / "week.json").read_text(encoding="utf-8"))
    assert (week["weekStart"], week["weekEnd"], week["timezone"]) == ("2026-09-28", "2026-10-04", "Asia/Seoul")
    assert [d["date"] for d in week["days"]] == [f"2026-09-{n}" for n in (28, 29, 30)] + [f"2026-10-0{n}" for n in (1, 2, 3, 4)]
    assert all(set(d) == {"date", "available", "restaurantCount", "status", "fetchedAt"} for d in week["days"])
    assert [d["restaurantCount"] for d in week["days"]] == [8] * 6 + [0]
    sunday = week["days"][-1]
    assert (sunday["available"], sunday["status"], sunday["fetchedAt"]) == (False, km.NOT_PUBLISHED_YET, None)
    assert not (tmp_path / "2026-10-04.json").exists()
    assert "restaurants" not in json.dumps(week)                            # the index never holds menus
    thursday = day_file(tmp_path, "2026-10-01")
    assert thursday["date"] == "2026-10-01" and thursday["dateLabel"] == "10월 1일"
    assert thursday["status"] == km.AVAILABLE and thursday["coverage"] == {
        "requested": 8, "fetched": 8, "failed": [], "carried": []}


def test_latest_json_stays_todays_payload(tmp_path):
    run(tmp_path, Site())
    latest = (tmp_path / "latest.json").read_text(encoding="utf-8")
    assert latest == (tmp_path / "2026-09-30.json").read_text(encoding="utf-8")
    assert json.loads(latest)["date"] == "2026-09-30"


def test_later_runs_refresh_only_today_and_the_rest_of_the_week(tmp_path):
    run(tmp_path, Site())
    site = Site()
    summary = run(tmp_path, site, now=WED + timedelta(hours=10))           # 16:30 the same day
    assert summary["requests"] == 40 and {d for _, d in site.calls} == {
        "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"}
    sunday = Site()
    assert run(tmp_path, sunday, now=datetime(2026, 10, 4, 6, 0, tzinfo=KST))["requests"] == 8
    week = json.loads((tmp_path / "week.json").read_text(encoding="utf-8"))
    assert [d["status"] for d in week["days"]] == [km.AVAILABLE] * 7          # past days kept, not refetched


def test_a_manual_full_week_refresh_refetches_past_days(tmp_path):
    run(tmp_path, Site())
    site = Site()
    assert run(tmp_path, site, now=WED + timedelta(hours=10), full_week=True)["requests"] == 56


def test_a_new_week_starts_a_new_baseline(tmp_path):
    run(tmp_path, Site())
    site = Site()
    summary = run(tmp_path, site, now=datetime(2026, 10, 5, 6, 0, tzinfo=KST))
    assert summary["requests"] == 56
    week = json.loads((tmp_path / "week.json").read_text(encoding="utf-8"))
    assert (week["weekStart"], week["weekEnd"]) == ("2026-10-05", "2026-10-11")


# --- failures never erase a known-good day --------------------------------------------------
@pytest.mark.parametrize("failure", ["down", "notable", "empty"])
def test_a_known_good_day_survives_failure_parser_change_and_empty_answers(tmp_path, failure):
    run(tmp_path, Site())
    before = (tmp_path / "2026-10-01.json").read_text(encoding="utf-8")
    run(tmp_path, Site({"2026-10-01": failure}), now=WED + timedelta(hours=10))
    assert (tmp_path / "2026-10-01.json").read_text(encoding="utf-8") == before
    week = json.loads((tmp_path / "week.json").read_text(encoding="utf-8"))
    thursday = [d for d in week["days"] if d["date"] == "2026-10-01"][0]
    assert (thursday["available"], thursday["status"]) == (True, km.STALE_SAVED_DATA)


def test_a_parser_failure_is_never_read_as_no_meals(tmp_path):
    with pytest.raises(km.MenuParseError):
        km.fetch_restaurant("fclt", "2026-10-01", lambda url: page(None))
    run(tmp_path, Site({"2026-10-02": "notable"}))
    week = json.loads((tmp_path / "week.json").read_text(encoding="utf-8"))
    friday = [d for d in week["days"] if d["date"] == "2026-10-02"][0]
    assert (friday["available"], friday["status"]) == (False, km.FETCH_FAILED)


def test_a_partial_restaurant_failure_is_recorded_and_carries_saved_entries(tmp_path):
    run(tmp_path, Site())
    run(tmp_path, Site({("west", "2026-10-01"): "down"}), now=WED + timedelta(hours=10))
    thursday = day_file(tmp_path, "2026-10-01")
    assert thursday["coverage"] == {"requested": 8, "fetched": 7, "failed": ["west"], "carried": ["west"]}
    assert [r["id"] for r in thursday["restaurants"]] == IDS                # canonical order kept


def test_a_partial_failure_without_saved_data_does_not_pretend_to_be_complete(tmp_path):
    run(tmp_path, Site({("east1", "2026-09-30"): "down", ("east2", "2026-09-30"): "down"}))
    today = day_file(tmp_path, "2026-09-30")
    assert today["coverage"]["failed"] == ["east1", "east2"] and today["coverage"]["carried"] == []
    assert len(today["restaurants"]) == 6
    assert "OSError" not in json.dumps(today) and "network" not in json.dumps(today)   # no exception text


def test_an_unconfirmed_empty_day_with_failures_is_a_failure_not_unpublished(tmp_path):
    rules = {(rid, "2026-10-03"): "empty" for rid in IDS}
    rules[("fclt", "2026-10-03")] = "down"
    run(tmp_path, Site(rules))
    week = json.loads((tmp_path / "week.json").read_text(encoding="utf-8"))
    saturday = [d for d in week["days"] if d["date"] == "2026-10-03"][0]
    assert saturday["status"] == km.FETCH_FAILED


def test_the_breaker_stops_a_dead_site_and_keeps_every_saved_file(tmp_path):
    run(tmp_path, Site())
    before = {p.name: p.read_text(encoding="utf-8") for p in tmp_path.glob("2026-*.json")}
    site = Site(default="down")
    summary = run(tmp_path, site, now=WED + timedelta(hours=10))
    assert summary["requests"] == km.MAX_CONSECUTIVE_FAILURES == len(site.calls)
    assert {p.name: p.read_text(encoding="utf-8") for p in tmp_path.glob("2026-*.json")} == before
    assert json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))["date"] == "2026-09-30"


def test_the_time_budget_stops_the_run(tmp_path):
    ticks = iter(range(0, 10_000, 100))
    budget = km.Budget(clock=lambda: next(ticks), seconds=1000)
    site = Site()
    run(tmp_path, site, budget=budget)
    assert len(site.calls) < 56


def test_today_without_any_menu_exits_2_and_keeps_the_previous_latest(tmp_path, monkeypatch):
    run(tmp_path, Site())
    monkeypatch.setattr(km, "OUT", tmp_path)
    monkeypatch.setattr(km, "fetch", Site({"2026-10-01": "empty"}))
    monkeypatch.setattr(km, "now_kst", lambda: datetime(2026, 10, 1, 6, 0, tzinfo=KST))
    monkeypatch.setattr(km.time, "sleep", lambda _: None)
    real_refresh = km.refresh
    monkeypatch.setattr(km, "refresh", lambda **kw: real_refresh(tmp_path, fetcher=km.fetch, **kw))
    # 10-01 was saved by the first run, so empty answers keep it: today still has a menu.
    assert km.main([]) == 0
    before = (tmp_path / "latest.json").read_text(encoding="utf-8")
    assert json.loads(before)["date"] == "2026-10-01"
    (tmp_path / "2026-10-01.json").unlink()
    assert km.main([]) == 2
    assert (tmp_path / "latest.json").read_text(encoding="utf-8") == before   # never replaced by nothing


def test_writes_are_atomic_and_leave_no_temp_files(tmp_path):
    run(tmp_path, Site())
    assert not list(tmp_path.glob(".kaist-*"))


# --- generated-data validation ----------------------------------------------------------
def _validated(tmp_path):
    import validate_content
    return validate_content.validate_kaist_dir(tmp_path)


def test_generated_week_and_dated_files_validate(tmp_path):
    run(tmp_path, Site({"2026-10-04": "empty", ("west", "2026-10-02"): "down"}))
    assert _validated(tmp_path) == []


@pytest.mark.parametrize("tamper,message", [
    (lambda w: w["days"].__setitem__(1, dict(w["days"][0])), "duplicate days"),
    (lambda w: w.__setitem__("weekStart", "2026-09-29"), "Monday-Sunday"),
    (lambda w: w["days"][2].__setitem__("restaurantCount", 3), "does not match its dated file"),
    (lambda w: w["days"][2].__setitem__("restaurantCount", -1), "restaurantCount invalid"),
    (lambda w: w["days"][6].__setitem__("available", True), "does not match its dated file"),
    (lambda w: w["days"][2].__setitem__("status", "NOT_PUBLISHED_YET"), "status contradicts"),
    (lambda w: w.__setitem__("generatedAt", "2026-10-06T06:00:00+09:00"), "not generated during its own week"),
    (lambda w: w.__setitem__("timezone", "UTC"), "timezone"),
])
def test_a_tampered_week_index_fails_validation(tmp_path, tamper, message):
    run(tmp_path, Site({"2026-10-04": "empty"}))
    week = json.loads((tmp_path / "week.json").read_text(encoding="utf-8"))
    tamper(week)
    (tmp_path / "week.json").write_text(json.dumps(week, ensure_ascii=False), encoding="utf-8")
    assert any(message in e for e in _validated(tmp_path)), _validated(tmp_path)


def test_a_dated_file_must_match_its_filename_and_latest_must_match_today(tmp_path):
    run(tmp_path, Site())
    data = day_file(tmp_path, "2026-10-01")
    data["date"] = "2026-10-02"
    (tmp_path / "2026-10-01.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    latest = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    latest["restaurants"] = latest["restaurants"][:1]
    (tmp_path / "latest.json").write_text(json.dumps(latest, ensure_ascii=False), encoding="utf-8")
    errors = _validated(tmp_path)
    assert any("does not match its filename" in e for e in errors)
    assert any("latest.json does not match its dated file" in e for e in errors)
