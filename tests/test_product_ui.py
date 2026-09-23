"""Production-scoped UI contracts; no accounts, network or generated-data writes."""
from datetime import datetime, timedelta, timezone
import re

import pytest
from playwright.sync_api import sync_playwright

from check_ggongbab_ui import FIXTURE_CLOCK_SCRIPT, one_today_payload
from check_site_ui import ROOT


@pytest.mark.parametrize("hour", [0, 9, 16, 23])
def test_normal_route_radar_payload_is_today_without_overriding_date(hour):
    now = datetime(2026, 9, 20, hour, 59, 59, tzinfo=timezone(timedelta(hours=9)))
    event = one_today_payload(now)["events"][0]
    start, end = (datetime.fromisoformat(event[key]) for key in ("startAt", "endAt"))
    assert start.date() == now.date()
    assert start <= now < end


@pytest.mark.parametrize("name", ["index.html", "ggongbab.html", "lab-ggongbab.html"])
def test_static_feed_pages_use_shared_selector_without_live_controller(name):
    html = (ROOT / name).read_text(encoding="utf-8")
    scripts = re.findall(r'<script\s+src="([^"]+)"', html)
    renderer = "js/home.js" if name == "index.html" else "js/ggongbab.js"
    assert scripts.index("js/ggongbab-select.js") < scripts.index(renderer)
    for script in scripts:
        assert not script.startswith(("http:", "https:"))
        source = (ROOT / script.split("?")[0]).read_text(encoding="utf-8")
        for forbidden in ("BabdodukPublicFeed", "BABDODUK_PUBLIC_FEED_CONFIG",
                          "supabase.co", "createClient(", "WebSocket("):
            assert forbidden not in source
    assert "ggongbab-public-feed.js" not in html
    assert "ggongbab-public-config.js" not in html


def test_fixture_clock_is_scoped_before_date_replacement():
    replacement = FIXTURE_CLOCK_SCRIPT.index("globalThis.Date = FixtureDate")
    for guard in ("location.pathname.endsWith('/lab-ggongbab.html')",
                  "query.get('fixture') !== '1'", "query.get('preview') === '1'"):
        assert FIXTURE_CLOCK_SCRIPT.index(guard) < replacement


def test_shared_selector_keeps_publication_review_expiry_and_sort_semantics():
    # Evaluate pure presentation helpers, without navigating to a live page.
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        page.route("**/*", lambda route: route.abort())
        page.add_script_tag(content=(ROOT / "js/ggongbab-select.js").read_text(encoding="utf-8"))
        result = page.evaluate("""() => {
          const F = BabdodukFreeFood;
          const now = F.toKst('2026-09-20T09:00:00+09:00');
          const row = (id, start, extra={}) => Object.assign({
            id, startAt: start, endAt: start, food: {provided: true}
          }, extra);
          const rows = [
            row('late', '2026-10-01T12:00:00+09:00'),
            row('today', '2026-09-20T12:00:00+09:00', {food:{provided:'true'}}),
            row('false', '2026-09-20T12:00:00+09:00', {food:{provided:false}}),
            row('unknown', '2026-09-20T12:00:00+09:00', {food:{provided:'unknown'}}),
            row('review', '2026-09-20T12:00:00+09:00', {needs_review:true}),
            row('camel', '2026-09-20T12:00:00+09:00', {needsReview:true}),
            row('ended', '2026-09-20T08:59:59+09:00')
          ];
          return {today:F.todayUpcoming(rows,now).map(x=>x.id),
                  future:F.futurePublic(rows,now).map(x=>x.id)};
        }""")
        browser.close()
    assert result == {"today": ["today"], "future": ["today", "late"]}


def test_may_occurrence_is_unknown_and_picker_stays_integrated():
    html = (ROOT / "event.html").read_text(encoding="utf-8")
    rows = re.findall(r'data-start="(2026-05-[^"]+)"[^>]+data-confirmation="([^"]+)"', html)
    assert len(rows) == 3
    assert all(confirmation in ("announced", "tentative") for _, confirmation in rows)
    assert "'event.state.announced.past': '진행 여부 미확인'" in html
    assert "'event.state.tentative.past': '당시 예정 안내 · 진행 여부 미확인'" in html
    for name in ("index.html", "ggongbab.html", "mukbang.html"):
        assert 'href="mukbang.html#what"' in (ROOT / name).read_text(encoding="utf-8")
    assert (ROOT / "lab.html").is_file()
    assert (ROOT / "calendar.ics").is_file()
