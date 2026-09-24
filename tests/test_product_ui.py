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


SHELF_ORDER = ["today", "pick", "map", "log"]
SHELF_HREFS = ["ggongbab.html", "mukbang.html#what", "https://naver.me/5NeqUPzI", "food.html"]


def test_home_top_is_one_hero_and_a_manual_banner_shelf():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    top = html.split('<section class="home-group home-read"')[0]
    assert top.count("<h1") == 1
    assert re.findall(r'<a class="btn btn-(?:primary|secondary)" href="([^"]+)"', top) == ["ggongbab.html", "mukbang.html#what"]
    banners = re.findall(r'data-banner="(\w+)">\s*<a class="home-banner-link" href="([^"]+)"([^>]*)>', top)
    assert [name for name, _, _ in banners] == SHELF_ORDER
    assert [href for _, href, _ in banners] == SHELF_HREFS
    assert 'target="_blank" rel="noopener"' in banners[SHELF_ORDER.index("map")][2]
    assert '<ul class="home-shelf-track" id="homeShelf" role="list">' in top
    collage = top.split('<div class="home-collage" aria-hidden="true">')[1].split("</div>\n\n")[0]
    photos = re.findall(r"<img [^>]+>", collage)
    assert len(photos) == 3 and all('alt=""' in img and "width=" in img and "height=" in img for img in photos)
    assert 'loading="lazy"' not in photos[0] and 'fetchpriority="high"' in photos[0]
    assert "오늘 학식 메뉴가 아니에요" in collage  # atmosphere photos never pose as today's menu
    for src in set(re.findall(r'src="(images/home/[^"]+)"', html)):
        assert (ROOT / src).stat().st_size < 200_000, src
    home_js = (ROOT / "js/home.js").read_text(encoding="utf-8")
    assert "setInterval" not in home_js and "setTimeout" not in home_js and "autoplay" not in home_js.lower()


def test_home_strings_exist_in_both_languages():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    blocks = dict(re.findall(r"(ko|en): \{(.*?)\n        \}", html, re.S))
    keys = {lang: set(re.findall(r"^\s*'?([\w.]+)'?\s*:", body, re.M)) for lang, body in blocks.items()}
    assert keys["ko"] == keys["en"]
    used = set(re.findall(r'data-i18n(?:-html|-aria-key)?="([\w.]+)"', html))
    assert used <= keys["ko"], sorted(used - keys["ko"])


def test_home_groups_brand_and_hub_name():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    groups = re.findall(r'<section class="home-group [^"]+" aria-labelledby="(\w+)">', html)
    assert groups == ["homeShelfTitle", "homeReadTitle", "homeNewsTitle"]
    assert re.findall(r'class="home-news-row" href="([^"]+)"', html) == ["event.html#notice", "event.html#archive", "history.html"]
    event = (ROOT / "event.html").read_text(encoding="utf-8")
    assert event.index('id="notice"') < event.index('id="upcoming"') < event.index('id="archive"')
    assert '<ul class="event-notices" id="eventNotices" role="list"></ul>' in event  # no invented notices
    for name in ("index.html", "ggongbab.html", "mukbang.html", "event.html", "food.html", "history.html", "lab.html"):
        page = (ROOT / name).read_text(encoding="utf-8")
        assert 'data-i18n="nav.today">오늘의 꽁밥</a>' in page and "'nav.today': '오늘의 꽁밥'" in page, name
    site = (ROOT / "css/site.css").read_text(encoding="utf-8")
    wordmark = site[site.index(".site-nav-wordmark {"):site.index(".site-nav-wordmark::before")]
    assert "#6366f1 0%" in wordmark and "#db2777 100%" in wordmark and "wordmark-holo" in wordmark
    assert "var(--color-accent)" not in wordmark
    assert re.search(r"@media \(prefers-reduced-motion: reduce\) \{[^@]*?\.site-nav-wordmark,\s*\.scroll-progress-bar \{ animation: none; \}", site)
