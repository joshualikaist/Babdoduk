"""Production-scoped UI contracts for the static main site; no accounts, network or data writes."""
from datetime import datetime, timedelta, timezone
import re

import pytest
from playwright.sync_api import sync_playwright

import check_ggongbab_ui
from check_ggongbab_ui import FIXTURE_CLOCK_SCRIPT, RADAR_NOW, one_today_payload
from check_site_ui import ROOT

KST = timezone(timedelta(hours=9))


def test_radar_fixture_event_is_later_the_same_day():
    event = one_today_payload(RADAR_NOW)["events"][0]
    start, end = (datetime.fromisoformat(event[key]) for key in ("startAt", "endAt"))
    assert RADAR_NOW < start < end
    assert start.date() == end.date() == RADAR_NOW.date()
    assert RADAR_NOW.utcoffset() == timedelta(hours=9)


@pytest.mark.parametrize("hour", [22, 23])
def test_radar_fixture_refuses_a_reference_that_would_cross_midnight(hour):
    with pytest.raises(ValueError):
        one_today_payload(datetime(2026, 9, 20, hour, 30, tzinfo=KST))


def test_radar_scenario_does_not_read_the_host_clock(monkeypatch):
    """A late-night host clock (the original failure) must not change the scenario."""
    class LateNight(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 23, 23, 30, tzinfo=KST)

    expected = one_today_payload()
    monkeypatch.setattr(check_ggongbab_ui, "datetime", LateNight)
    assert one_today_payload() == expected
    assert check_ggongbab_ui.RADAR_NOW == datetime.fromisoformat(check_ggongbab_ui.FIXTURE_NOW)


def test_fixture_clock_is_scoped_before_date_replacement():
    replacement = FIXTURE_CLOCK_SCRIPT.index("globalThis.Date = FixtureDate")
    for guard in ("location.pathname.endsWith('/lab-ggongbab.html')",
                  "query.get('fixture') !== '1'", "query.get('preview') === '1'"):
        assert FIXTURE_CLOCK_SCRIPT.index(guard) < replacement


@pytest.mark.parametrize("name", ["index.html", "ggongbab.html", "lab-ggongbab.html"])
def test_static_feed_pages_use_shared_selector_without_live_feed(name):
    """main publishes the free-food feed as a static snapshot only (no Realtime client)."""
    html = (ROOT / name).read_text(encoding="utf-8")
    scripts = re.findall(r'<script\s+src="([^"]+)"', html)
    renderer = "js/home.js" if name == "index.html" else "js/ggongbab.js"
    assert scripts.index("js/ggongbab-select.js") < scripts.index(renderer)
    assert "ggongbab-public-feed.js" not in html and "ggongbab-public-config.js" not in html
    for script in scripts:
        assert not script.startswith(("http:", "https:", "//"))
        source = (ROOT / script.split("?")[0]).read_text(encoding="utf-8")
        for forbidden in ("BabdodukPublicFeed", "BABDODUK_PUBLIC_FEED_CONFIG", "supabase",
                          "createClient(", "WebSocket(", "EventSource("):
            assert forbidden not in source, (script, forbidden)


def test_home_snapshot_copy_names_last_publication_without_freshness_claims():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    ko, en = re.findall(r"'home\.free\.asOf': '([^']*)'", html)
    assert ko.startswith("마지막 발행 {time}") and "전체 목록" in ko
    assert en.startswith("Last published {time}") and "full list" in en
    assert not any(word in ko for word in ("최신", "최근", "실시간"))
    assert not any(word in en.lower() for word in ("latest", "live", "real-time", "realtime"))


def test_shared_selector_keeps_publication_review_expiry_and_sort_semantics():
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


def test_past_events_are_not_reported_as_held_and_picker_stays_integrated():
    html = (ROOT / "event.html").read_text(encoding="utf-8")
    rows = re.findall(r'data-start="(\d{4}-\d{2}-\d{2})"\s+data-end="(\d{4}-\d{2}-\d{2})"\s+'
                      r'data-confirmation="([^"]+)"', html)
    assert len(rows) == 3
    assert all(confirmation in ("announced", "tentative") for *_, confirmation in rows)
    assert "'event.state.tentative.past': '당시 예정 안내 · 진행 여부 미확인'" in html
    assert "'event.state.held.past'" in html  # only an explicit "held" state may say it took place
    for name in ("index.html", "ggongbab.html", "mukbang.html"):
        assert 'href="mukbang.html#what"' in (ROOT / name).read_text(encoding="utf-8")
