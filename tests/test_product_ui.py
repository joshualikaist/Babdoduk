"""Production-scoped UI contracts for the static main site; no accounts, network or data writes."""
from datetime import datetime, timedelta, timezone
import json
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


# 마이 밥도둑 (docs/MY_BABDODUK.md; on production since owner 2026-11-11): the optional account store on
# the hub. It loads the sign-in client only for someone already signed in on this browser and only on the
# hosts js/babdoduk-auth-config.js lists (tests/test_my_babdoduk.py); the renderer never talks to a database,
# and the lab-only Realtime feed (js/ggongbab-public-feed.js) never reaches main.
ACCOUNT_SCRIPTS = ("js/ggongbab-public-config.js", "js/babdoduk-auth-config.js", "js/babdoduk-account.js")
# 별 누른 꽁밥 30분 전 알림 (owner 2026-11-12; docs/PUSH_ALERTS.md): two checking functions only, called only for a
# browser that turned the alert on (tests/test_push_alerts.py).
PUSH_SCRIPTS = ("js/ggongbab-push.js",)


@pytest.mark.parametrize("name", ["index.html", "ggongbab.html", "lab-ggongbab.html"])
def test_static_feed_pages_use_shared_selector_without_live_feed(name):
    """main publishes the free-food feed as a static snapshot only (no Realtime client)."""
    html = (ROOT / name).read_text(encoding="utf-8")
    scripts = re.findall(r'<script\s+src="([^"]+)"', html)
    renderer = "js/home.js" if name == "index.html" else "js/ggongbab.js"
    assert scripts.index("js/ggongbab-select.js") < scripts.index(renderer)
    assert "ggongbab-public-feed.js" not in html
    hub = name != "index.html"
    if hub:
        tail = [*ACCOUNT_SCRIPTS, *(PUSH_SCRIPTS if name == "ggongbab.html" else ()), "js/ggongbab.js"]
        assert scripts[-len(tail):] == tail, scripts
        config = (ROOT / "js/ggongbab-public-config.js").read_text(encoding="utf-8")
        assert not re.search(r"sb_secret_|service_role|SUPABASE_SECRET", config)
    else:
        # Owner 2026-11-12: the home calendar's star keeps the 30-minute alert list, so the home page loads the
        # public config for the alert module only, right before the calendar; no account script, no client.
        i = scripts.index("js/home-calendar.js")
        assert scripts[i - 2:i] == ["js/ggongbab-public-config.js", *PUSH_SCRIPTS] and "babdoduk-account.js" not in html
    for script in scripts:
        assert not script.startswith(("http:", "https:", "//"))
        if hub and script in ACCOUNT_SCRIPTS:
            continue  # the account store: tests/test_my_babdoduk.py
        if script in PUSH_SCRIPTS or (name == "index.html" and script == "js/ggongbab-public-config.js"):
            continue  # the 30-minute alert and its public config: tests/test_push_alerts.py
        source = (ROOT / script.split("?")[0]).read_text(encoding="utf-8")
        for forbidden in ("BabdodukPublicFeed", "BABDODUK_PUBLIC_FEED_CONFIG", "supabase",
                          "createClient(", "WebSocket(", "EventSource("):
            assert forbidden not in source, (script, forbidden)


def test_home_snapshot_copy_names_last_change_without_freshness_claims():
    # An export that changes nothing is not committed, so the stamp is the list's last change.
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    ko, en = re.findall(r"'home\.free\.asOf': '([^']*)'", html)
    assert ko == "마지막 변경 {time}" and en == "Last changed {time}"
    assert not any(word in ko for word in ("최신", "최근", "실시간"))
    assert not any(word in en.lower() for word in ("latest", "live", "real-time", "realtime"))


@pytest.mark.parametrize("name", ["ggongbab.html", "lab-ggongbab.html"])
def test_hub_feed_note_names_the_last_change_and_claims_no_live_data(name):
    """The list is labelled by its last change only: no lifecycle paragraph and no freshness claim.
    Ended rows leave it for the past listings, which say so in their own short label."""
    html = (ROOT / name).read_text(encoding="utf-8")
    assert "'gg.lifecycle'" not in html and "'gg.tagline'" not in html
    assert re.findall(r"'gg\.updated': '([^']*)'", html) == ["마지막 변경", "Last changed"]
    js = (ROOT / "js/ggongbab.js").read_text(encoding="utf-8")
    note = js[js.index("function feedNoteHtml"):js.index("function", js.index("function feedNoteHtml") + 10)]
    assert "gg.updated" in note and "gg.lifecycle" not in note
    for text in re.findall(r"'gg\.(?:updated|archive\.lead)': '([^']*)'", html):
        assert not any(word in text.lower() for word in ("실시간", "최신", "latest", "live", "real-time", "realtime"))


PAST_KEYS = ("gg.archive.title", "gg.archive.lead", "gg.archive.ended", "gg.archive.record", "gg.archive.source",
             "gg.archive.empty", "gg.archive.error", "gg.archive.loading", "gg.archive.more", "gg.archive.less", "gg.newTab")
# copy cleanup, owner 2026-11-12: shorter record and source labels.
PAST_KO = {"gg.archive.title": "지난 꽁밥 기록", "gg.archive.ended": "종료", "gg.archive.record": "지난 꽁밥 안내",
           "gg.archive.source": "공지 보기", "gg.archive.empty": "최근 30일 기록 없음"}
PAST_EN = {"gg.archive.title": "Past free-food listings", "gg.archive.ended": "Ended",
           "gg.archive.record": "Past free-food listing", "gg.archive.source": "View notice"}


@pytest.mark.parametrize("name", ["ggongbab.html", "lab-ggongbab.html"])
def test_past_listing_copy_is_bilingual_and_never_claims_an_outcome(name):
    """An archived row was a public listing that has ended; it does not say the event took place."""
    html = (ROOT / name).read_text(encoding="utf-8")
    strings = {key: re.findall(r"'%s': '([^']*)'" % re.escape(key), html) for key in PAST_KEYS}
    assert all(len(values) == 2 and all(values) for values in strings.values()), strings
    assert {key: strings[key][0] for key in PAST_KO} == PAST_KO
    assert {key: strings[key][1] for key in PAST_EN} == PAST_EN
    # copy cleanup, owner 2026-11-12: the lead is the window only; the title and the 종료 badge say "ended".
    assert strings["gg.archive.lead"] == ["최근 30일", "Last 30 days"]
    text = " ".join(value for values in strings.values() for value in values).lower()
    for claim in ("진행됨", "진행된", "완료", "성공", "held", "completed", "successful", "took place", "happened"):
        assert claim not in text, claim


def test_past_listing_renderer_has_no_sign_up_path_and_loads_on_its_own():
    js = (ROOT / "js/ggongbab.js").read_text(encoding="utf-8")
    renderer = js[js.index("function pastHtml"):js.index("function archiveHtml")]
    for sign_up in ("registration", "gg-btn", "gg.register", "deadline"):
        assert sign_up not in renderer, sign_up
    loader = js[js.index("function loadArchive"):js.index("function setTab")]
    assert "'data/ggongbab/archive/index.json'" in js and ".catch(" in loader and "state.free" not in loader
    assert js.index("loadFree();") < js.index("loadArchive();")


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


def test_past_events_are_not_reported_as_held_and_there_is_one_picker():
    html = (ROOT / "event.html").read_text(encoding="utf-8")
    rows = re.findall(r'data-start="(\d{4}-\d{2}-\d{2})"\s+data-end="(\d{4}-\d{2}-\d{2})"\s+'
                      r'data-confirmation="([^"]+)"', html)
    # One row per authored activity (data/content/events.json); the owner adds events over time.
    activities = json.loads((ROOT / "data/content/events.json").read_text(encoding="utf-8"))["activities"]
    n, on_site = len(activities), sum(1 for a in activities if not a["link"].startswith("http"))
    assert len(rows) == n >= 4
    assert "STROKE" not in html and "언빌리버블" not in html   # it did not happen
    # The third row is the site's own menu world cup (2026-10-13), held on worldcup.html.
    assert "'event.e2.summary': '먹방 월드컵 32강'" in html and 'href="worldcup.html" data-event-page>' in html
    assert all(confirmation in ("announced", "tentative") for *_, confirmation in rows)
    assert "'event.state.tentative.past': '미확정'" in html  # copy cleanup, owner 2026-11-12
    assert "'event.state.announced.past'" not in html  # an unrecorded outcome claims nothing, visibly
    assert "'event.state.held.past'" in html  # only an explicit "held" state may say it took place
    # copy cleanup, owner 2026-11-12: the status notes behind 자세히 are gone; the state chip stays.
    assert "'event.note." not in html and "data-event-note" not in html
    # Each row's link is labelled by the page script from its date band; a past row links to
    # the original post as a record, and each authored instruction block can be marked historical.
    assert html.count("<span data-event-cta>") == n and "event.openPageBtn" not in html
    # An activity held on a page of this site opens it in place; an original post opens a new tab.
    assert html.count('target="_blank" rel="noopener noreferrer"><span data-event-cta>') == n - on_site
    assert "'event.cta.page'" not in html and "'event.cta.pagePast': 'Open the page'" in html   # no 지금 해보기 button: the start screen is in the card
    # copy cleanup, owner 2026-11-12: a past row's link reads the same as a live one's.
    assert "'event.cta.live': '게시물 보기'" in html and "'event.cta.past': '게시물 보기'" in html
    assert "'event.cta.live': 'View post'" in html and "'event.cta.past': 'View post'" in html
    assert html.count('<details class="event-more">') == n and "event-tab" not in html
    # Every activity, in the Korean markup and in the ko and en tables (data/content/events.json).
    assert html.count('<div class="event-detail-row" data-detail="participation">') == 3 * n
    assert "event-elsewhere" not in html and "event-num" not in html and 'class="page-num"' not in html
    assert 'class="event-instagram"' in html and "@babdodukms" in html
    assert 'id="eventEmpty"' in html and "event.emptyLink" not in html
    # One picker product: 오늘 뭐 먹지 at choose.html (owner 2026-11-04), js/pick.js; since 2026-11-05 one
    # button and the world cup's capsule machine, no choices and no slot reel. The magazine keeps a card
    # pointing there and sends an old #what link on.
    for name in ("index.html", "ggongbab.html", "mukbang.html", "event.html", "food.html", "history.html"):
        page = (ROOT / name).read_text(encoding="utf-8")
        assert 'id="pickApp"' not in page and "js/pick.js" not in page and 'id="eatApp"' not in page, name
    assert not (ROOT / "js/food-picker.js").exists()
    choose = (ROOT / "choose.html").read_text(encoding="utf-8")
    assert "noindex" not in choose and "location.replace" not in choose and choose.count('id="pickApp"') == 1
    assert choose.count('<script src="js/pick.js"></script>') == 1 and "eat-slot.js" not in choose
    assert choose.count('<button type="button" class="pick-go" id="pickGo">') == 1 and 'class="pk-gacha"' in choose
    assert "data-mode=" not in choose and 'id="pickTiles"' not in choose
    magazine = (ROOT / "mukbang.html").read_text(encoding="utf-8")
    assert 'id="eatApp"' not in magazine and magazine.count('id="kaistToday"') == 1 and 'id="what"' in magazine
    assert '<a class="mg-pick-link" href="choose.html">' in magazine
    assert "if (location.hash === '#what') location.replace('choose.html');" in magazine
    index = (ROOT / "index.html").read_text(encoding="utf-8")
    assert 'href="choose.html" data-i18n="home.ctaChoose"' in index   # the home call to action reaches the picker


# Food Log is unreleased (lab only): no home link. Since 2026-11-02 (owner) the home page is its hero
# alone: the eat (banner shelf), read and news groups below it are gone.


def test_home_is_one_hero_and_nothing_below_it():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    top = html[html.index("<main"):html.index("</main>")]
    assert top.count("<h1") == 1
    assert re.findall(r'<a class="btn btn-(?:primary|secondary)" href="([^"]+)"', top) == ["ggongbab.html", "choose.html"]
    assert 'href="food.html"' not in html and 'data-banner=' not in html
    for gone in ("home-group", "homeShelf", "homeFeature", "home-news", "explore-card", "data-shelf", "home-read"):
        assert gone not in top, gone
    assert re.findall(r'<section class="(home-[\w-]+)"', top) == ["home-wc", "home-hero", "home-cal", "home-map"]
    # Owner 2026-11-04: the 3D campus map took the food photo collage's place (docs/CAMPUS_MAP.md). Its
    # poster is decorative (the pins are the buttons), sized, and lazy: phones open the map on request.
    assert "home-collage" not in html and "images/home/" not in html
    section = top.split('<section class="home-map"')[1].split("</section>")[0]
    photos = re.findall(r"<img [^>]+>", section)
    assert len(photos) == 1 and 'src="data/campus/poster.webp"' in photos[0] and 'alt=""' in photos[0]
    assert 'width="1200"' in photos[0] and 'height="750"' in photos[0] and 'loading="lazy"' in photos[0]
    assert '<canvas class="home-map-canvas" aria-hidden="true">' in section
    row = top.split('<div class="home-title-row">')[1].split("</div>")[0]
    assert re.search(r'<button type="button" class="home-map-open" id="homeMapOpen"[^>]*\bhidden>꽁밥 지도</button>', row)
    assert '<script type="importmap">' in html and '<script type="module" src="js/home-map.js"></script>' in html
    home_js = (ROOT / "js/home.js").read_text(encoding="utf-8")
    assert "setInterval" not in home_js and "setTimeout" not in home_js and "autoplay" not in home_js.lower()
    assert "data/magazine" not in home_js and "homeShelf" not in home_js     # no magazine request, no shelf


def test_home_strings_exist_in_both_languages():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    blocks = dict(re.findall(r"(ko|en): \{(.*?)\n      \}", html, re.S))
    keys = {lang: set(re.findall(r"^\s*'?([\w.]+)'?\s*:", body, re.M)) for lang, body in blocks.items()}
    assert keys["ko"] == keys["en"]
    used = set(re.findall(r'data-i18n(?:-html|-aria-key)?="([\w.]+)"', html))
    assert used <= keys["ko"], sorted(used - keys["ko"])


def test_brand_and_hub_name():
    event = (ROOT / "event.html").read_text(encoding="utf-8")
    assert event.index('id="now"') < event.index('id="archive"')
    # No invented notices: the list the sync writes from data/content/events.json is empty.
    assert re.search(r'<ul class="event-notices" id="eventNotices" role="list">\s*<!-- @content:notices -->'
                     r'\s*<!-- @end content -->\s*</ul>', event)
    for name in ("index.html", "ggongbab.html", "mukbang.html", "choose.html", "event.html", "food.html", "history.html", "lab.html"):
        page = (ROOT / name).read_text(encoding="utf-8")
        assert 'data-i18n="nav.today">오늘의 꽁밥</a>' in page and "'nav.today': '오늘의 꽁밥'" in page, name
        assert 'data-i18n="nav.choose">오늘 뭐 먹지</a>' in page and "'nav.choose': '오늘 뭐 먹지'" in page, name
    site = (ROOT / "css/site.css").read_text(encoding="utf-8")
    wordmark = site[site.index(".site-nav-wordmark {"):site.index(".site-nav-wordmark::before")]
    assert "#6366f1 0%" in wordmark and "#db2777 100%" in wordmark and "wordmark-holo" in wordmark
    assert "var(--color-accent)" not in wordmark
    assert re.search(r"@media \(prefers-reduced-motion: reduce\) \{[^@]*?\.site-nav-wordmark,\s*\.scroll-progress-bar \{ animation: none; \}", site)
