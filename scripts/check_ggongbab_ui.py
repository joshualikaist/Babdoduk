"""Local fixture/preview screenshots and executable layout/security checks."""
from __future__ import annotations

import argparse
import json
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".local" / "ui-shots"
SIZES = [(390, 844), (430, 932), (1440, 900)]
SELECTORS = {"nav": ".site-nav", "page": ".ggongbab-page-wrap", "hero": ".gg-hero",
             "tabs": ".food-hub-tabs", "radar": ".gg-radar",
             "filter": ".gg-filters", "day": ".gg-day", "card": ".gg-card",
             "top": ".gg-card-top", "title": ".gg-title", "actions": ".gg-actions",
             "menuCard": ".km-card"}
FIXTURE_NOW = "2026-09-20T09:00:00+09:00"
FIXTURE_CLOCK_SCRIPT = f"""(() => {{
  const query = new URLSearchParams(location.search);
  if (!location.pathname.endsWith('/lab-ggongbab.html') || query.get('fixture') !== '1') return;
  // Preview takes precedence over fixture in the application's mode selection.
  if (query.get('preview') === '1') return;

  const NativeDate = Date;
  const fixedNow = NativeDate.parse('{FIXTURE_NOW}');
  function FixtureDate(...args) {{
    if (!new.target) return new NativeDate(fixedNow).toString();
    return Reflect.construct(NativeDate, args.length ? args : [fixedNow], new.target);
  }}
  Object.setPrototypeOf(FixtureDate, NativeDate);
  FixtureDate.prototype = NativeDate.prototype;
  FixtureDate.now = () => fixedNow;
  FixtureDate.parse = NativeDate.parse;
  FixtureDate.UTC = NativeDate.UTC;
  globalThis.Date = FixtureDate;
}})();"""
# One synthetic reference time for the normal-route radar scenario: the page
# clock and the synthetic event both derive from it, so the host clock never
# decides which calendar day the event falls on.
RADAR_NOW = datetime.fromisoformat(FIXTURE_NOW)
# UI checks must not use an operator's local public DB configuration (lab's read-only Realtime
# experiment reads js/ggongbab-public-config.js). Every browser context gets the empty config,
# so the checks always exercise the static snapshot. Where no page loads the file, it never matches.
EMPTY_PUBLIC_CONFIG = "window.BABDODUK_PUBLIC_FEED_CONFIG = {};"


def neutralize_public_config(context):
    context.route("**/js/ggongbab-public-config.js", lambda route: route.fulfill(
        content_type="application/javascript", body=EMPTY_PUBLIC_CONFIG))


def one_today_payload(now=RADAR_NOW):
    """One published event starting two hours after `now`, on the same KST day.

    Refuses a reference so late that the event would cross midnight, instead of
    silently turning "today" into "tomorrow".
    """
    start, end = now + timedelta(hours=2), now + timedelta(hours=4)
    if not start.date() == end.date() == now.date():
        raise ValueError(f"reference {now.isoformat()} leaves no same-day window for the radar event")
    return {"events": [{"id": "one", "title": "one", "startAt": start.isoformat(), "endAt": end.isoformat(),
                        "food": {"provided": "true", "type": "meal", "description": "점심"},
                        "sources": [{"type": "dooray"}]}]}


def radar_one_today(browser, base, report):
    """Normal route with one event later today, under a fixed page clock.

    Runs in its own context so the fixed clock cannot leak into the checks that
    assert the native clock on normal and preview routes.
    """
    context = browser.new_context(timezone_id="Asia/Seoul", locale="ko-KR", reduced_motion="reduce")
    neutralize_public_config(context)
    try:
        context.clock.set_fixed_time(RADAR_NOW)
        page = context.new_page()
        page.route("**/data/ggongbab/latest.json", lambda route: route.fulfill(json=one_today_payload(RADAR_NOW)))
        page.route("**/data/kaist-menu/latest.json", lambda route: route.fulfill(status=404, body=""))
        page.goto(base + "/lab-ggongbab.html")
        page.locator(".gg-card").first.wait_for()
        page_now = datetime.fromisoformat(page.evaluate("new Date().toISOString()").replace("Z", "+00:00"))
        assert page_now == RADAR_NOW, (page_now, RADAR_NOW)
        assert "한 끼" in page.locator(".gg-radar-title").inner_text()
        page.locator("#foodHubTabMenu").click()
        page.get_by_text("오늘 메뉴를 불러오지 못했어요.").wait_for()
        page.locator("#foodHubTabFree").click()
        assert page.locator(".gg-card").count() >= 1
        report["checks"] += 4
    finally:
        context.close()


def open_ended_hand_out(browser, base, report):
    """A hand-out with no end time ("11:30 ~ 소진 시까지", MISS-001) stays live for the feed's
    three-hour grace window after it starts, then leaves for the past listings. Beverage
    rows are grouped under 다과. Fixed page clock, synthetic data only."""
    now = RADAR_NOW

    def event(event_id, start):
        return {"id": event_id, "title": event_id, "startAt": start.isoformat(), "endAt": None,
                "timeText": "소진 시까지", "location": {"building": "", "room": "", "name": "문화관 앞"},
                "food": {"provided": "true", "type": "beverage", "description": "커피"},
                "registration": {"required": "unknown"}, "sources": [{"type": "dooray", "name": "Dooray"}]}

    live = {"generatedAt": now.isoformat(), "events": [
        event("open-running", now - timedelta(hours=1)), event("open-over", now - timedelta(hours=4))]}
    archive = {"generatedAt": now.isoformat(), "windowDays": 30, "events": []}
    context = browser.new_context(timezone_id="Asia/Seoul", locale="ko-KR", reduced_motion="reduce")
    neutralize_public_config(context)
    try:
        context.clock.set_fixed_time(now)
        page = context.new_page()
        page.route("**/data/ggongbab/latest.json", lambda route: route.fulfill(json=live))
        page.route("**/data/ggongbab/archive/index.json", lambda route: route.fulfill(json=archive))
        page.route("**/data/kaist-menu/latest.json", lambda route: route.fulfill(status=404, body=""))
        page.goto(base + "/lab-ggongbab.html")
        page.locator(".gg-card").first.wait_for()

        def live_ids():
            return page.locator(".gg-card").evaluate_all("els => els.map(el => el.dataset.id)")

        assert live_ids() == ["open-running"], live_ids()
        assert page.locator('.gg-past[data-past-id="open-over"]').count() == 1
        assert page.locator('.gg-past[data-past-id="open-running"]').count() == 0
        assert "사전 신청" not in page.locator(".gg-card").first.inner_text()
        page.locator('.gg-chip[data-group="food"][data-value="refreshment"]').click()
        assert live_ids() == ["open-running"], live_ids()
        page.locator('.gg-chip[data-group="food"][data-value="meal"]').click()
        assert live_ids() == [], live_ids()
        report["checks"] += 6
    finally:
        context.close()


WEEK_NOW = datetime(2026, 9, 30, 12, 30, tzinfo=timezone(timedelta(hours=9)))   # a Wednesday
MENU_IDS = ["fclt", "west", "east1", "east2", "emp", "icc", "hawam", "seoul"]
XSS = '<img src=x onerror="window.__kmXss=1">'


def menu_day(iso, places, marker):
    """A synthetic daily payload: every place has lunch, even-numbered places also have dinner."""
    rows = []
    for idx, rid in enumerate(MENU_IDS[:places]):
        rows.append({"id": rid, "name": f"식당 {rid}", "building": "N11", "breakfast": {"items": []},
                     "lunch": {"items": [f"{marker} 점심 {idx}", "쌀밥"], "price": "5,000원", "kcal": ""},
                     "dinner": {"items": [f"{marker} 저녁 {idx}"] if idx % 2 == 0 else [], "price": "", "kcal": ""}})
    return {"date": iso, "dateLabel": iso, "fetchedAt": iso + "T06:00:00+09:00", "source": "fixture", "restaurants": rows}


def week_index(days):
    return {"weekStart": "2026-09-28", "weekEnd": "2026-10-04", "generatedAt": "2026-09-30T06:00:00+09:00",
            "timezone": "Asia/Seoul", "days": [{"date": d, "available": a, "restaurantCount": n, "status": s,
                                                "fetchedAt": None} for d, a, n, s in days]}


def weekly_cafeteria(browser, base, report):
    """This week's cafeteria on the normal route: date strip, today vs selected, meal kept across
    dates, on-demand per-date loading with a page cache, distinct no-menu and failure states,
    favorites across dates, escaping, keyboard, KO/EN and 360/390/1440. Fixed page clock and
    synthetic data only; it runs in its own context (see radar_one_today)."""
    today = menu_day("2026-09-30", 8, "수요일")
    thursday = menu_day("2026-10-01", 5, "목요일")
    thursday["restaurants"][0]["dinner"]["items"].append(XSS)
    monday = menu_day("2026-09-28", 3, "월요일")
    index = week_index([("2026-09-28", True, 3, "AVAILABLE"), ("2026-09-29", True, 8, "AVAILABLE"),
                        ("2026-09-30", True, 8, "AVAILABLE"), ("2026-10-01", True, 5, "AVAILABLE"),
                        ("2026-10-02", True, 8, "AVAILABLE"), ("2026-10-03", False, 0, "FETCH_FAILED"),
                        ("2026-10-04", False, 0, "NOT_PUBLISHED_YET")])
    dated = {"2026-09-28": monday, "2026-09-30": today, "2026-10-01": thursday}

    def serve_day(route):
        name = route.request.url.rsplit("/", 1)[-1].split("?")[0]
        iso = name[:-5]
        if iso == "2026-10-02":
            route.abort()                                   # network failure
        elif iso in dated:
            route.fulfill(json=dated[iso])
        else:
            route.fulfill(status=404, body="")

    for width, height, lang in ((390, 844, "ko"), (360, 740, "en"), (1440, 900, "ko")):
        context = browser.new_context(viewport={"width": width, "height": height}, timezone_id="America/Los_Angeles",
                                      locale="ko-KR", reduced_motion="reduce")
        neutralize_public_config(context)
        try:
            context.clock.set_fixed_time(WEEK_NOW)          # 2026-09-29 20:30 in Los Angeles
            page = context.new_page()
            requests = []
            page.on("request", lambda r: requests.append(urlparse(r.url).path))
            page.route("**/data/ggongbab/latest.json", lambda route: route.fulfill(json={"events": []}))
            page.route("**/data/kaist-menu/latest.json", lambda route: route.fulfill(json=today))
            page.route("**/data/kaist-menu/week.json", lambda route: route.fulfill(json=index))
            page.route("**/data/kaist-menu/2026-*.json", serve_day)
            page.add_init_script(f"localStorage.setItem('babdoduk-lang', '{lang}');"
                                 "localStorage.setItem('babdoduk-menu-meal', 'dinner');"
                                 "localStorage.setItem('babdoduk-menu-favorites', JSON.stringify(['east1']));")
            page.goto(base + "/ggongbab.html#menu")
            page.locator(".km-card").first.wait_for()
            en = lang == "en"
            days = page.locator(".km-day")
            assert days.count() == 7
            assert days.evaluate_all("els => els.map(el => el.dataset.kmDate)") == [
                "2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"]
            # Default: today in KST (the browser itself is in Los Angeles, still on the 29th).
            wed = page.locator('[data-km-date="2026-09-30"]')
            assert wed.get_attribute("aria-pressed") == "true" and wed.get_attribute("aria-current") == "date"
            assert wed.locator(".km-day-today").inner_text() == ("Today" if en else "오늘")
            assert page.locator(".km-day-today").count() == 1
            assert page.locator("#foodHubMenu h2").inner_text() == ("This week's cafeteria" if en else "이번 주 학식")
            assert page.locator("#foodHubTabMenu").inner_text().strip() == ("🍚 Cafeteria" if en else "🍚 학식")
            assert page.locator(".km-date").inner_text() == ("Sep 30 · Wednesday" if en else "9월 30일 · 수요일")
            assert page.locator('[data-km-meal="dinner"]').get_attribute("aria-pressed") == "true"
            assert page.locator(".km-card").count() == 4 and page.locator(".km-card").first.get_attribute("data-km-id") == "east1"
            metric = page.locator(".gg-counts").inner_text()
            assert ("8 cafeterias" if en else "학식 8곳") in metric
            # The today view asks for nothing new: no week index and no other date on load.
            assert not any(path.endswith(("/week.json", "2026-09-28.json", "2026-10-01.json", "2026-10-02.json"))
                           for path in requests)
            # Tomorrow, across the month boundary: same meal, that day's cards and count.
            page.locator('[data-km-date="2026-10-01"]').click()
            page.locator(".km-card").first.wait_for()
            assert page.locator(".km-date").inner_text() == ("Oct 1 · Thursday" if en else "10월 1일 · 목요일")
            assert page.locator('[data-km-date="2026-10-01"]').get_attribute("aria-pressed") == "true"
            assert wed.get_attribute("aria-pressed") == "false" and wed.get_attribute("aria-current") == "date"
            assert page.locator('[data-km-date="2026-10-01"] .km-day-num').inner_text() == "10/1"
            assert page.locator('[data-km-meal="dinner"]').get_attribute("aria-pressed") == "true"
            assert page.locator(".km-card").count() == 3
            assert ("Dinner: 3 cafeterias" if en else "저녁 메뉴 3곳") in page.locator(".km-count").inner_text()
            assert page.locator(".km-card").first.get_attribute("data-km-id") == "east1"      # favorites are not per date
            assert "목요일 저녁 2" in page.locator(".km-card").first.inner_text()
            assert not page.locator("[data-km-stale]").count()                                 # future is not stale
            assert page.locator(".gg-counts").inner_text() == metric                          # the today metric stays
            assert page.evaluate("window.__kmXss") is None and not page.locator(".km-items img").count()
            assert XSS in page.locator('[data-km-id="fclt"] .km-items').inner_text()
            # Back and forth: a loaded date is not fetched again.
            wed.click()
            page.locator('[data-km-date="2026-10-01"]').click()
            page.locator(".km-card").first.wait_for()
            assert sum(path.endswith("/2026-10-01.json") for path in requests) == 1
            assert sum(path.endswith("/week.json") for path in requests) == 1
            # Sunday: the index says nothing is posted yet, so it is not even requested.
            page.locator('[data-km-date="2026-10-04"]').click()
            page.locator('[data-km-day-state="none"]').wait_for()
            assert page.locator('[data-km-day-state="none"]').inner_text() == (
                "No menu has been posted yet." if en else "아직 올라온 메뉴가 없어요.")
            assert not any(path.endswith("/2026-10-04.json") for path in requests)
            assert page.locator('[data-km-meal="dinner"]').get_attribute("aria-pressed") == "true"
            # Friday: the request fails, which is not the same as "no menu".
            page.locator('[data-km-date="2026-10-02"]').click()
            page.locator('[data-km-day-state="failed"]').wait_for()
            assert ("Couldn’t load the menu." if en else "메뉴를 불러오지 못했어요.") in page.locator(
                '[data-km-day-state="failed"]').inner_text()
            assert page.locator("[data-km-retry-day]").count() == 1
            # Saturday: the collector could not fetch it and there is no file: a failure state,
            # without requesting a file the index already lists as missing (no 404).
            page.locator('[data-km-date="2026-10-03"]').click()
            page.locator('[data-km-day-state="failed"]').wait_for()
            assert not any(path.endswith("/2026-10-03.json") for path in requests)
            weeks_before = sum(path.endswith("/week.json") for path in requests)
            page.locator("[data-km-retry-day]").click()
            page.locator('[data-km-day-state="failed"]').wait_for()
            assert sum(path.endswith("/week.json") for path in requests) == weeks_before + 1   # retry re-reads the index
            # A past day of this week is browsable too.
            page.locator('[data-km-date="2026-09-28"]').click()
            page.locator(".km-card").first.wait_for()
            assert "월요일 저녁" in page.locator(".km-card").first.inner_text()
            # Keyboard: arrows move between dates, Enter selects, focus survives the re-render.
            page.locator('[data-km-date="2026-09-28"]').focus()
            page.keyboard.press("ArrowRight")
            assert page.evaluate("document.activeElement.dataset.kmDate") == "2026-09-29"
            page.keyboard.press("End")
            page.keyboard.press("ArrowLeft")
            page.keyboard.press("ArrowLeft")
            page.keyboard.press("ArrowLeft")
            page.keyboard.press("Enter")
            page.locator(".km-card").first.wait_for()
            assert page.evaluate("document.activeElement.dataset.kmDate") == "2026-10-01"
            assert page.locator('[data-km-date="2026-10-01"]').get_attribute("aria-pressed") == "true"
            # Layout: seven usable buttons inside the page, no page-level horizontal overflow.
            boxes = days.evaluate_all("els => els.map(el => { const r = el.getBoundingClientRect();"
                                      " return {l: r.left, r: r.right, w: r.width, h: r.height}; })")
            assert all(b["l"] >= 0 and b["r"] <= width and b["w"] >= 36 and b["h"] >= 44 for b in boxes), boxes
            assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
            # A new page load starts at today again (the date is not persisted), the meal is.
            page.reload()
            page.locator(".km-card").first.wait_for()
            assert page.locator('[data-km-date="2026-09-30"]').get_attribute("aria-pressed") == "true"
            assert page.locator('[data-km-meal="dinner"]').get_attribute("aria-pressed") == "true"
            report["checks"] += 42
        finally:
            context.close()
    # Without week.json (for example before the weekly collector runs) dates still load on demand.
    context = browser.new_context(timezone_id="Asia/Seoul", locale="ko-KR", reduced_motion="reduce")
    neutralize_public_config(context)
    try:
        context.clock.set_fixed_time(WEEK_NOW)
        page = context.new_page()
        page.route("**/data/ggongbab/latest.json", lambda route: route.fulfill(json={"events": []}))
        page.route("**/data/kaist-menu/latest.json", lambda route: route.fulfill(json=today))
        page.route("**/data/kaist-menu/week.json", lambda route: route.fulfill(status=404, body=""))
        page.route("**/data/kaist-menu/2026-*.json", serve_day)
        page.goto(base + "/ggongbab.html#menu")
        page.locator(".km-card").first.wait_for()
        page.locator('[data-km-date="2026-10-01"]').click()
        page.locator(".km-card").first.wait_for()
        page.locator('[data-km-date="2026-10-04"]').click()
        page.locator('[data-km-day-state="none"]').wait_for()
        report["checks"] += 2
    finally:
        context.close()


def midnight_dated_menu(browser, base, report):
    """After midnight, yesterday's latest.json must not hide a dated file week.json already lists."""
    yesterday = menu_day("2026-09-29", 8, "화요일")
    today = menu_day("2026-09-30", 8, "수요일")
    today["restaurants"][0]["lunch"]["items"].insert(0, "오늘수요일밥")
    opened = week_index([("2026-09-29", True, 8, "AVAILABLE"), ("2026-09-30", True, 8, "AVAILABLE")])
    closed = week_index([("2026-09-29", True, 8, "AVAILABLE"), ("2026-09-30", False, 0, "NOT_PUBLISHED_YET")])
    before = datetime(2026, 9, 29, 23, 59, tzinfo=timezone(timedelta(hours=9)))
    after = datetime(2026, 9, 30, 0, 1, tzinfo=timezone(timedelta(hours=9)))

    def scenario(clock, week, stale, marker, forbid):
        context = browser.new_context(timezone_id="Asia/Seoul", locale="ko-KR", reduced_motion="reduce")
        neutralize_public_config(context)
        try:
            context.clock.set_fixed_time(clock)
            page = context.new_page()
            requests = []
            page.on("request", lambda request: requests.append(urlparse(request.url).path))
            page.add_init_script("localStorage.setItem('babdoduk-menu-meal', 'lunch');")
            page.route("**/data/ggongbab/latest.json", lambda route: route.fulfill(json={"events": []}))
            page.route("**/data/kaist-menu/latest.json", lambda route: route.fulfill(json=yesterday))
            page.route("**/data/kaist-menu/week.json", lambda route: route.fulfill(json=week))
            page.route("**/data/kaist-menu/2026-09-30.json", lambda route: route.fulfill(json=today))
            page.goto(base + "/ggongbab.html#menu")
            if stale:
                page.locator("[data-km-stale]").wait_for()
                assert "오늘수요일밥" not in page.locator("#foodHubMenu").inner_text()
            else:
                page.locator(".km-card").first.wait_for()
                assert page.locator("[data-km-stale]").count() == 0
                if marker:
                    assert "오늘수요일밥" in page.locator("#foodHubMenu").inner_text()
                else:
                    assert "화요일 점심" in page.locator("#foodHubMenu").inner_text()
            for path in forbid:
                assert not any(item.endswith(path) for item in requests), (path, requests)
            if marker:
                page.goto(base + "/index.html")
                status = page.locator("#homeMenuStatus[data-state='ready']")
                status.wait_for()
                assert status.get_attribute("data-state") == "ready"
                assert "오늘 8곳" in status.inner_text() and "아직 올라오지" not in status.inner_text()
            report["checks"] += 1
        finally:
            context.close()

    scenario(before, opened, False, False, ("/week.json", "/2026-09-30.json"))
    scenario(after, opened, False, True, ())
    scenario(after, closed, True, False, ("/2026-09-30.json",))


def past_listings(browser, base, report):
    """Past listings on the public page: a separate, quiet record with no sign-up actions,
    loaded on its own so that its failure never touches the live feed. Synthetic data only."""
    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst).replace(microsecond=0)

    def event(event_id, start, end, **extra):
        return {"id": event_id, "title": event_id, "startAt": start.isoformat(), "endAt": end.isoformat() if end else None,
                "location": {"building": "N1", "room": "101호", "name": ""},
                "food": {"provided": "true", "type": "meal", "description": "점심"},
                "sources": [{"type": "dooray", "name": "Dooray"}], **extra}

    register = {"required": "true", "url": "https://example.org/register", "deadline": (now - timedelta(days=3)).isoformat()}
    live = {"generatedAt": now.isoformat(), "events": [
        event("live-upcoming", now + timedelta(days=2), now + timedelta(days=2, hours=1), registration=register),
        # Ended an hour ago: inside the export grace, so still in latest.json, but no longer live on the page.
        event("live-just-ended", now - timedelta(hours=2), now - timedelta(hours=1), registration=register)]}
    notice = [{"type": "kaist_public", "name": "KAIST 공지", "url": "https://example.org/notice"}]
    past = {"generatedAt": now.isoformat(), "windowDays": 30, "events": [
        event("past-notice", now - timedelta(days=2, hours=1), now - timedelta(days=2), sources=notice, registration=register),
        event("past-mail", now - timedelta(days=5, hours=1), now - timedelta(days=5)),
        event("past-script", now - timedelta(days=6, hours=1), now - timedelta(days=6),
              sources=[{"type": "manual", "name": "Manual", "url": "javascript:alert(1)"}]),
        event("past-review", now - timedelta(days=3), None, needs_review=True),
        event("past-unknown", now - timedelta(days=3), None, food={"provided": "unknown"}),
        event("past-old", now - timedelta(days=45), now - timedelta(days=45)),
        event("past-not-ended", now + timedelta(days=1), None)]}
    visible_past = ["live-just-ended", "past-notice", "past-mail", "past-script"]
    context = browser.new_context(timezone_id="Asia/Seoul", locale="ko-KR", reduced_motion="reduce")
    neutralize_public_config(context)
    try:
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(type(error).__name__))
        page.route("**/data/kaist-menu/latest.json", lambda route: route.fulfill(status=404, body=""))
        page.route("**/data/ggongbab/latest.json", lambda route: route.fulfill(json=live))
        page.route("**/data/ggongbab/archive/index.json", lambda route: route.fulfill(json=past))

        def ids(selector, key):
            return page.locator(selector).evaluate_all(f"els => els.map(el => el.dataset.{key})")

        for width, height in ((390, 844), (1440, 900)):
            page.set_viewport_size({"width": width, "height": height})
            page.goto(base + "/ggongbab.html")
            page.locator(".gg-past").first.wait_for()
            assert ids(".gg-card", "id") == ["live-upcoming"]
            assert ids(".gg-past", "pastId") == visible_past
            archive = page.locator(".gg-archive")
            assert archive.locator(".gg-btn, .gg-deadline, .gg-reg-badge, [href*='register']").count() == 0
            assert "신청" not in archive.inner_text()
            assert archive.locator(".gg-past-badge").all_inner_texts() == ["종료"] * len(visible_past)
            links = archive.locator("a").evaluate_all(
                "els => els.map(a => [a.closest('.gg-past').dataset.pastId, a.getAttribute('href'), a.target, a.rel, a.textContent])")
            assert links == [["past-notice", "https://example.org/notice", "_blank", "noopener", "당시 공지 보기 ↗(새 창)"]], links
            assert all("당시 공개된 꽁밥 안내 기록" in text for text in archive.locator(".gg-past-note").all_inner_texts())
            # Secondary: below the live list, flat, and out of reach of the sticky live filters.
            archive.scroll_into_view_if_needed()
            box, filters = archive.bounding_box(), page.locator(".gg-filters").bounding_box()
            assert box["y"] > page.locator(".gg-card").last.bounding_box()["y"]
            assert filters["y"] + filters["height"] <= box["y"] + 1, ("sticky filters stop at the archive", filters, box)
            assert page.evaluate("getComputedStyle(document.querySelector('.gg-past')).boxShadow") == "none"
            assert page.evaluate("document.documentElement.scrollWidth") <= width
            report["checks"] += 12
        page.locator("#langToggle").click()
        assert page.locator("#ggArchiveTitle").inner_text() == "Past free-food listings"
        assert page.locator(".gg-past-link").inner_text().startswith("View original notice")
        assert page.locator(".gg-past-badge").first.inner_text() == "Ended"
        assert "Previously published free-food listing" in page.locator(".gg-past-note").first.inner_text()
        page.locator("#langToggle").click()
        report["checks"] += 4

        # More than five: the rest stay behind a labelled toggle that keeps keyboard focus.
        many = dict(past, events=[event(f"past-{i}", now - timedelta(days=i + 1, hours=1), now - timedelta(days=i + 1))
                                  for i in range(7)])
        page.unroute("**/data/ggongbab/archive/index.json")
        page.route("**/data/ggongbab/archive/index.json", lambda route: route.fulfill(json=many))
        page.goto(base + "/ggongbab.html")
        page.locator(".gg-past").first.wait_for()
        more = page.locator("[data-gg-archive-more]")
        assert page.locator(".gg-past").count() == 5 and more.get_attribute("aria-expanded") == "false"
        more.focus()
        page.keyboard.press("Enter")
        assert page.locator(".gg-past").count() == 8 and more.get_attribute("aria-expanded") == "true"
        assert page.evaluate("document.activeElement.hasAttribute('data-gg-archive-more')")
        report["checks"] += 3

        # Empty, missing, failing and malformed archives: the live feed is untouched every time,
        # and the live row that just ended still shows as past, whatever the archive file did.
        empty = "최근 30일 기록 없음"
        failed = "지난 기록을 불러오지 못했어요."
        for label, handler, expected in (
                ("empty", lambda route: route.fulfill(json={"events": []}), empty),
                ("missing", lambda route: route.fulfill(status=404, body=""), empty),
                ("failing", lambda route: route.fulfill(status=503, body=""), failed),
                ("malformed", lambda route: route.fulfill(content_type="application/json", body="{not json"), failed)):
            page.unroute("**/data/ggongbab/archive/index.json")
            page.route("**/data/ggongbab/archive/index.json", handler)
            page.goto(base + "/ggongbab.html")
            page.locator(".gg-past").first.wait_for()
            assert ids(".gg-card", "id") == ["live-upcoming"], label
            assert ids(".gg-past", "pastId") == ["live-just-ended"], label
            state = page.locator(".gg-archive-state")
            assert (state.count() == 0) == (label in ("empty", "missing")), (label, "one past row is not an empty archive")
            if label in ("failing", "malformed"):
                assert state.inner_text().startswith(expected), (label, state.inner_text())
            report["checks"] += 3
        # With nothing live that has ended, an empty archive says so in words.
        page.unroute("**/data/ggongbab/latest.json")
        page.route("**/data/ggongbab/latest.json", lambda route: route.fulfill(json=dict(live, events=live["events"][:1])))
        page.unroute("**/data/ggongbab/archive/index.json")
        page.route("**/data/ggongbab/archive/index.json", lambda route: route.fulfill(json={"events": []}))
        page.goto(base + "/ggongbab.html")
        page.locator(".gg-archive-state").wait_for()
        assert page.locator(".gg-archive-state").inner_text() == empty and page.locator(".gg-card").count() == 1
        report["checks"] += 1

        # And the reverse: a failed live feed leaves the archive readable.
        page.unroute("**/data/ggongbab/latest.json")
        page.route("**/data/ggongbab/latest.json", lambda route: route.fulfill(status=503, body=""))
        page.unroute("**/data/ggongbab/archive/index.json")
        page.route("**/data/ggongbab/archive/index.json", lambda route: route.fulfill(json=past))
        page.goto(base + "/ggongbab.html")
        page.locator(".gg-past").first.wait_for()
        assert page.locator("[data-gg-retry]").count() == 1
        assert ids(".gg-past", "pastId") == ["past-notice", "past-mail", "past-script"]
        assert not errors, errors
        report["checks"] += 3
    finally:
        context.close()


class LocalHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if any(part.startswith(".") for part in Path(path).parts) and path != "/.local/ggongbab-preview.json":
            self.send_error(404)
            return
        super().do_GET()

    def list_directory(self, path):
        self.send_error(404)
        return None


@contextmanager
def local_server(port=0):
    server = ThreadingHTTPServer(("127.0.0.1", port), partial(LocalHandler, directory=str(ROOT)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def rectangles(page):
    return page.evaluate("""selectors => Object.fromEntries(Object.entries(selectors).map(([key, sel]) => {
      const el = document.querySelector(sel); if (!el) return [key, null];
      const r = el.getBoundingClientRect();
      return [key, {x:Math.round(r.x), y:Math.round(r.y), w:Math.round(r.width), h:Math.round(r.height)}];
    }))""", SELECTORS)


def near(actual, expected):
    assert abs(actual - expected) <= 2, (actual, expected)


def reset_storage(page):
    page.evaluate("""() => {
      localStorage.removeItem('babdoduk-ggongbab-filter');
      localStorage.removeItem('babdoduk-foodhub-tab');
      localStorage.removeItem('babdoduk-menu-meal');
      localStorage.removeItem('babdoduk-menu-favorites');
    }""")


def assert_fixture_clock(page):
    assert page.evaluate("""() => ({
      name: Date.name,
      now: new Date().toISOString(),
      explicit: new Date('1970-01-01T00:00:01Z').getTime(),
      parsed: Date.parse('1970-01-01T00:00:01Z'),
      utc: Date.UTC(1970, 0, 1, 0, 0, 1)
    })""") == {
        "name": "FixtureDate",
        "now": "2026-09-20T00:00:00.000Z",
        "explicit": 1000,
        "parsed": 1000,
        "utc": 1000,
    }


def assert_native_clock(page):
    assert page.evaluate("Date.name") == "Date"


def hub_layout(page, width, report):
    page.locator(".food-hub-tabs").wait_for()
    page.locator(".gg-radar").wait_for()
    r = rectangles(page)
    if width < 720:
        near(r["radar"]["x"], 16)
        near(r["radar"]["w"], width - 32)
        near(r["tabs"]["x"], 16)
        near(r["tabs"]["w"], width - 32)
    else:
        near(r["page"]["x"], 360)
        near(r["page"]["w"], 720)
        near(r["radar"]["x"], 384)
        near(r["radar"]["w"], 672)
        near(r["tabs"]["x"], 384)
        near(r["tabs"]["w"], 672)
    assert page.locator(".food-hub-tab").count() == 2
    assert "풍년" in page.locator(".gg-radar-title").inner_text()
    assert page.locator("[data-featured]").count() == 1
    report["checks"] += 8


def hub_menu_flow(page, width, report):
    page.locator("#foodHubTabMenu").click()
    page.locator("#foodHubMenu").wait_for()
    assert page.locator("#foodHubTabMenu").get_attribute("aria-selected") == "true"
    assert page.locator("#foodHubFree").is_hidden()
    page.locator('[data-km-meal="lunch"]').click()
    assert page.locator('[data-km-meal="lunch"]').get_attribute("aria-pressed") == "true"
    page.locator(".km-card").first.wait_for()
    assert "영업 중" not in page.inner_text("body")
    page.evaluate("localStorage.setItem('babdoduk-menu-favorites', JSON.stringify(['east1']))")
    page.locator("#foodHubTabMenu").click()
    page.reload()
    page.locator("#foodHubTabMenu").click()
    page.locator('[data-km-meal="lunch"]').click()
    page.locator(".km-card").first.wait_for()
    assert page.locator(".km-card").first.get_attribute("data-km-id") == "east1"
    expander = page.locator('[data-km-id="icc"] [data-km-expand]')
    expander.click()
    assert expander.get_attribute("aria-expanded") == "true"
    assert page.locator('[data-km-id="icc"] .km-items li').count() >= 8
    if width >= 720:
        boxes = page.locator(".km-card").evaluate_all(
            "els => els.slice(0,2).map(el => { const r = el.getBoundingClientRect(); return {x:r.x,w:r.width}; })")
        near(round(boxes[0]["w"]), 330)
        near(round(boxes[1]["w"]), 330)
        near(round(boxes[0]["x"] + boxes[0]["w"] + 12), round(boxes[1]["x"]))
        report["checks"] += 3
    page.locator("#foodHubTabFree").click()
    assert page.locator("#foodHubTabFree").get_attribute("aria-selected") == "true"
    report["checks"] += 8


def run_checks(preview=False):
    OUT.mkdir(parents=True, exist_ok=True)
    report = {"fixture": {}, "preview": {}, "production": {}, "checks": 0}
    with local_server() as base, sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(timezone_id="Asia/Seoul", locale="ko-KR", reduced_motion="reduce")
        neutralize_public_config(context)
        page = context.new_page()
        page.add_init_script(FIXTURE_CLOCK_SCRIPT)
        errors = []
        page.on("pageerror", lambda error: errors.append(type(error).__name__))
        for width, height in SIZES:
            page.set_viewport_size({"width": width, "height": height})
            page.goto(base + "/lab-ggongbab.html?fixture=1")
            reset_storage(page)
            page.goto(base + "/lab-ggongbab.html?fixture=1&debug-layout=1")
            page.locator(".gg-card").first.wait_for()
            page.locator(".gg-radar").wait_for()
            assert page.locator('[data-group="when"][data-value="all"]').get_attribute("aria-pressed") == "true"
            assert page.locator(".gg-card").count() == 10
            assert page.locator('[data-group="when"]').evaluate_all(
                "els => els.map(el => el.dataset.value)") == ["today", "tomorrow", "week", "all"]
            report["checks"] += 3
            # The list is labelled only by its publication time: no lifecycle paragraph, no freshness claim.
            note = page.locator(".gg-feed-note").inner_text()
            assert note.startswith("마지막 발행") and "자동으로" not in note, note
            assert not any(word in note for word in ("실시간", "최신", "업데이트")), note
            report["checks"] += 2
            assert_fixture_clock(page)
            page.evaluate("document.fonts.ready")
            page.wait_for_timeout(150)
            hub_layout(page, width, report)
            report["checks"] += 5
            r = rectangles(page)
            if width < 720:
                near(r["page"]["w"], width)
                near(r["card"]["x"], 16)
                near(r["card"]["w"], width - 32)
                near(r["filter"]["x"], 0)
                near(r["filter"]["w"], width)
            else:
                near(r["page"]["x"], 360)
                near(r["filter"]["x"], 360)
                near(r["filter"]["w"], 720)
                near(r["card"]["x"], 384)
                near(r["card"]["w"], 672)
            assert page.evaluate("document.documentElement.scrollWidth") <= width
            report["checks"] += 6
            for selector in (".gg-title", ".gg-summary"):
                assert page.locator(selector).first.evaluate("el => getComputedStyle(el).overflow") == "hidden"
                report["checks"] += 1
            page.screenshot(path=str(OUT / f"ggongbab-{width}x{height}.png"))
            report["fixture"][f"{width}x{height}"] = r
            # Scroll past the filter's own resting place so the check does not
            # depend on the exact height of the hero and radar above it.
            page.evaluate("window.scrollTo(0, document.querySelector('.gg-filters').getBoundingClientRect().top + scrollY + 120)")
            page.wait_for_timeout(100)
            sticky = rectangles(page)
            near(sticky["filter"]["y"], sticky["nav"]["h"])
            report["checks"] += 1
            page.locator('[data-group="when"][data-value="all"]').click()
            assert page.locator(".gg-card").count() == 10
            assert page.locator('[data-id="fixture-7"] .gg-title').evaluate(
                "el => el.scrollHeight > el.clientHeight && el.clientHeight <= 48")
            assert page.locator('[data-id="fixture-8"] .gg-summary').evaluate(
                "el => el.scrollHeight > el.clientHeight && el.clientHeight <= 42")
            assert not page.locator('[data-id="fixture-5"] .gg-btn--primary').count()
            assert page.evaluate("document.documentElement.scrollWidth") <= width
            assert page.locator('.gg-actions').evaluate_all("els => els.every(el => [...el.children].every(btn => btn.getBoundingClientRect().right <= el.closest('.gg-card').getBoundingClientRect().right))")
            assert page.locator('[data-id="fixture-0"] .gg-source').inner_text() == "KAIST 메일"
            assert page.locator('[data-id="fixture-1"] .gg-source').inner_text() == "KAIST 포탈"
            assert page.locator('[data-id="fixture-2"] .gg-source').inner_text() == "KAIST 공식 공지"
            assert page.locator('[data-id="fixture-3"] .gg-source').inner_text() == "밥도둑 등록"
            report["checks"] += 10
            page.evaluate("window.scrollTo(0, 0)")
            hub_menu_flow(page, width, report)
            reset_storage(page)
            if preview:
                page.goto(base + "/lab-ggongbab.html?preview=1")
                page.wait_for_function("document.querySelector('.gg-updated') || document.querySelector('.gg-state')")
                assert not page.get_by_text("Preview 데이터가 아직 없습니다.").count()
                page.evaluate("document.fonts.ready")
                page.wait_for_timeout(100)
                report["preview"][f"{width}x{height}"] = rectangles(page)
                page.screenshot(path=str(OUT / f"ggongbab-preview-{width}x{height}.png"))
                assert page.evaluate("document.documentElement.scrollWidth") <= width
                report["checks"] += 2
        # Public host: serve the same lab files without making any network call
        # to an actual public deployment. No .local request may be attempted.
        requests = []
        page.on("request", lambda req: requests.append(urlparse(req.url).path))
        def public_route(route):
            if urlparse(route.request.url).path == "/js/ggongbab-public-config.js":
                route.fulfill(content_type="application/javascript", body=EMPTY_PUBLIC_CONFIG)
                return
            path = ROOT / urlparse(route.request.url).path.lstrip("/")
            if path.is_file() and ROOT in path.resolve().parents:
                route.fulfill(path=str(path))
            else:
                route.fulfill(status=404, body="")
        page.route("https://preview.invalid/**", public_route)
        page.goto("https://preview.invalid/lab-ggongbab.html?preview=1")
        page.get_by_text("Preview mode is available only on localhost.").wait_for()
        assert not any(path.startswith("/.local/") for path in requests)
        report["checks"] += 1
        # Normal mode still fetches the public feed; unsafe food states never
        # become public cards or inflate hero counts.
        future = (datetime.now(timezone(timedelta(hours=9))) + timedelta(days=8)).isoformat()
        events = [{"id": state, "title": state, "startAt": future,
                   "food": {"provided": state}, "registration": {}} for state in ("true", "false", "unknown")]
        events.append({**events[0], "id": "review", "needs_review": True})
        events[0]["registration"] = {"required": "true", "deadline": "2020-01-01T00:00:00+09:00", "url": "https://example.org/register"}
        events[0]["location"] = {"building": "N1", "room": "101호", "name": "N1 101호"}
        page.goto(base + "/lab-ggongbab.html?fixture=1")
        reset_storage(page)
        requests.clear()
        page.route("**/data/ggongbab/latest.json", lambda route: route.fulfill(json={"events": events}))
        page.goto(base + "/lab-ggongbab.html")
        page.locator(".gg-card").first.wait_for()
        assert_native_clock(page)
        assert page.locator('[data-group="when"][data-value="all"]').get_attribute("aria-pressed") == "true"
        page.locator('[data-group="when"][data-value="all"]').click()
        assert page.locator(".gg-card").count() == 1
        assert "/data/ggongbab/latest.json" in requests
        assert not page.locator(".gg-diagnostic-toggle").count()
        assert not page.locator('.gg-btn--primary').count()
        assert "N1 · 101호 · N1" not in page.locator('.gg-place').inner_text()
        assert not errors, errors
        report["checks"] += 8
        page.evaluate("localStorage.setItem('babdoduk-ggongbab-filter', JSON.stringify({when:'today',food:'all'}))")
        page.reload()
        page.locator('#foodHubFree .gg-state').first.wait_for()
        assert page.locator('[data-group="when"][data-value="today"]').get_attribute("aria-pressed") == "true"
        page.evaluate("localStorage.removeItem('babdoduk-ggongbab-filter')")
        report["checks"] += 1
        # Preview diagnostics only render allowlisted numeric counters, even if
        # an unexpected local payload contains sensitive-looking extra fields.
        page.route("**/.local/ggongbab-preview.json", lambda route: route.fulfill(json={
            "events": [events[0]], "_preview": {"publicCount": 1, "subject": "PRIVATE_TEST", "aiCalls": "PRIVATE_TEST"}}))
        page.goto(base + "/lab-ggongbab.html?preview=1")
        page.locator('.gg-card').first.wait_for()
        assert_native_clock(page)
        page.locator('.gg-diagnostic-toggle').click()
        assert "PRIVATE_TEST" not in page.locator('.gg-diagnostic-panel').inner_text()
        assert page.locator('.gg-diagnostic-panel dd').all_text_contents() == ["1"]
        report["checks"] += 3
        page.unroute("**/.local/ggongbab-preview.json")
        page.route("**/.local/ggongbab-preview.json", lambda route: route.fulfill(status=404, body=""))
        page.goto(base + "/lab-ggongbab.html?preview=1")
        page.get_by_text("Preview 데이터가 아직 없습니다.").wait_for()
        assert "--preview-feed" in page.locator('.gg-state code').inner_text()
        report["checks"] += 1
        page.unroute("**/.local/ggongbab-preview.json")
        page.goto(base + "/lab-ggongbab.html?fixture=1")
        reset_storage(page)
        page.goto(base + "/lab-ggongbab.html?fixture=1")
        page.locator(".gg-radar").wait_for()
        assert page.evaluate("BabdodukKaistMenu.defaultMeal(new Date('2026-09-20T09:00:00+09:00'))") == "breakfast"
        assert page.evaluate("BabdodukKaistMenu.defaultMeal(new Date('2026-09-20T11:00:00+09:00'))") == "lunch"
        assert page.evaluate("BabdodukKaistMenu.defaultMeal(new Date('2026-09-20T15:30:00+09:00'))") == "dinner"
        assert page.evaluate("localStorage.getItem('babdoduk-foodhub-tab')") in (None, "free")
        page.locator("#foodHubTabMenu").click()
        assert page.evaluate("localStorage.getItem('babdoduk-foodhub-tab')") == "menu"
        report["checks"] += 5
        page.goto(base + "/lab-ggongbab.html?fixture=1&stale-menu=1")
        page.locator("#foodHubTabMenu").click()
        page.locator("[data-km-stale]").wait_for()
        assert "학식 업데이트 중" in page.locator(".gg-counts").inner_text()
        assert page.locator("#foodHubMenu h2").count() == 0 or "오늘" not in page.locator("#foodHubMenu h2").inner_text()
        page.locator("[data-km-stale-toggle]").click()
        page.locator(".km-card").first.wait_for()
        assert "최근 학식" in page.locator("#foodHubMenu .km-date").inner_text()
        assert page.locator("#foodHubMenu h2").inner_text() == "이번 주 학식"
        report["checks"] += 3
        drought = {"events": []}
        page.unroute("**/data/ggongbab/latest.json")
        page.route("**/data/ggongbab/latest.json", lambda route: route.fulfill(json=drought))
        reset_storage(page)
        page.goto(base + "/lab-ggongbab.html")
        page.locator(".gg-radar-title").wait_for()
        assert "가뭄" in page.locator(".gg-radar-title").inner_text()
        page.locator('.km-cta[data-hub-tab="menu"]').click()
        assert page.locator("#foodHubTabMenu").get_attribute("aria-selected") == "true"
        page.locator("#foodHubTabFree").click()
        report["checks"] += 3
        # A same-day upcoming event makes the radar report one meal. The page
        # clock is fixed for this scenario only (see radar_one_today).
        radar_one_today(browser, base, report)
        open_ended_hand_out(browser, base, report)
        past_listings(browser, base, report)
        weekly_cafeteria(browser, base, report)
        midnight_dated_menu(browser, base, report)
        page.unroute("**/data/ggongbab/latest.json")
        published = datetime.now(timezone(timedelta(hours=9))).replace(microsecond=0).isoformat()
        page.route("**/data/ggongbab/latest.json", lambda route: route.fulfill(json={"generatedAt": published, "events": events}))
        # Production page. It carries no lab affordances, so fixture and preview
        # are not merely hidden - they are unreachable, and the page can only
        # ever read the public feed.
        page.unroute("**/.local/ggongbab-preview.json")
        local_hits = []
        page.route("**/.local/**", lambda route: (local_hits.append(route.request.url),
                                                  route.fulfill(status=404, body="")))
        for width, height in SIZES:
            page.set_viewport_size({"width": width, "height": height})
            for query in ("", "?fixture=1", "?preview=1", "?fixture=1&debug-layout=1"):
                requests.clear()
                page.goto(base + "/ggongbab.html" + query)
                page.locator(".gg-card").first.wait_for()
                assert_native_clock(page)
                page.locator('[data-group="when"][data-value="all"]').click()
                # Only the explicit-food, not-under-review event is public. The
                # false, unknown and needs_review rows must never render.
                assert page.locator(".gg-card").count() == 1, query
                assert page.locator(".gg-card").first.get_attribute("data-id") == "true"
                assert "/data/ggongbab/latest.json" in requests
                assert not local_hits, local_hits
                assert not page.locator(".gg-diagnostic-toggle").count()
                assert not page.locator(".lab-fork-ribbon").count()
                assert not page.evaluate("document.body.hasAttribute('data-gg-lab')")
                assert not page.locator('meta[name="robots"]').count()
                assert page.title() == "오늘의 꽁밥 · 밥도둑 Babdoduk"
                assert page.evaluate("document.documentElement.scrollWidth") <= width
                assert page.locator(".gg-updated").is_visible()
                assert page.locator(".gg-archive").count() == 1
                report["checks"] += 13
            report["production"][f"{width}x{height}"] = rectangles(page)
            page.screenshot(path=str(OUT / f"ggongbab-prod-{width}x{height}.png"))
        # Keyboard users keep their place through re-renders; tabs follow the
        # ARIA arrow-key pattern; the picker is a separate, labelled next step.
        page.set_viewport_size({"width": 390, "height": 844})
        reset_storage(page)
        page.goto(base + "/ggongbab.html")
        page.locator(".gg-card").first.wait_for()
        assert page.locator(".gg-choose-link").get_attribute("href") == "mukbang.html#what"   # the one picker
        page.locator('[data-group="when"][data-value="today"]').focus()
        page.keyboard.press("Enter")
        assert page.evaluate("document.activeElement.dataset.value") == "today"
        page.keyboard.press("Tab")
        page.keyboard.press("Shift+Tab")
        page.locator('[data-group="when"][data-value="all"]').focus()
        page.keyboard.press("Enter")
        page.locator("#foodHubTabFree").focus()
        page.keyboard.press("ArrowRight")
        assert page.locator("#foodHubTabMenu").get_attribute("aria-selected") == "true"
        assert page.evaluate("document.activeElement.id") == "foodHubTabMenu"
        assert page.locator("#foodHubTabFree").get_attribute("tabindex") == "-1"
        page.keyboard.press("Home")
        assert page.locator("#foodHubTabFree").get_attribute("aria-selected") == "true"
        reset_storage(page)
        page.goto(base + "/ggongbab.html#menu")
        page.locator(".food-hub-tabs").wait_for()
        assert page.locator("#foodHubTabMenu").get_attribute("aria-selected") == "true"
        reset_storage(page)
        report["checks"] += 8
        # All upcoming includes later weeks, sorts dates, and excludes even a
        # just-ended event from today. Normal mode keeps the real browser clock.
        now_kst = datetime.now(timezone(timedelta(hours=9)))
        def event_row(event_id, start, end):
            return {"id": event_id, "title": event_id, "startAt": start.isoformat(),
                    "endAt": end.isoformat(), "food": {"provided": True}}
        future_early = event_row("future-early", now_kst + timedelta(days=8), now_kst + timedelta(days=9))
        future_late = event_row("future-late", now_kst + timedelta(days=15), now_kst + timedelta(days=16))
        ended = event_row("ended-today", now_kst.replace(hour=0, minute=0, second=0), now_kst)
        page.route("**/data/ggongbab/latest.json", lambda route: route.fulfill(json={"events": [
            future_late, ended, future_early,
            {**future_early, "id": "review-snake", "needs_review": True},
            {**future_early, "id": "review-camel", "needsReview": True},
            {**future_early, "id": "no-food", "food": {"provided": False}},
            {**future_early, "id": "unknown-food", "food": {"provided": "unknown"}},
        ]}))
        reset_storage(page)
        page.goto(base + "/lab-ggongbab.html")
        page.locator(".gg-card").first.wait_for()
        assert_native_clock(page)
        assert page.locator('[data-group="when"][data-value="all"]').get_attribute("aria-pressed") == "true"
        assert page.locator(".gg-card").evaluate_all("els => els.map(el => el.dataset.id)") == [
            "future-early", "future-late"]
        page.locator('[data-group="when"][data-value="week"]').click()
        page.reload()
        page.locator("#foodHubFree .gg-state").first.wait_for()
        assert page.locator('[data-group="when"][data-value="week"]').get_attribute("aria-pressed") == "true"
        assert page.locator(".gg-card").count() == 0
        report["checks"] += 5
        assert not errors, errors
        report["checks"] += 1
        browser.close()
    (OUT / "layout-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--serve", action="store_true", help="serve the local lab safely on loopback")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if args.serve:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), partial(LocalHandler, directory=str(ROOT)))
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    else:
        run_checks(args.preview)
