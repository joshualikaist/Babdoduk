"""꽁밥 LIVE, Phase 1 (docs/GGONGBAB_LIVE.md) on the food hub: saved listings in this browser, changes since
saving, ended and missing saved rows, the optional date/who/where filters, per-listing and weekly share
links, one-listing calendar entries, the new-feature note, English, damaged storage and phone widths.
Synthetic data is served to the test browser only; no generated file is read or changed, and the lab
Realtime config is replaced by an empty one so the page reads only the routed static snapshot."""
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
HOST = "ggongbab-live.invalid"
NOW = "2026-11-09T09:00:00+09:00"      # a Monday, KST
SAVED_KEY = "babdoduk-ggongbab-saved"


def ev(event_id, start, end, building="E11", **extra):
    event = {"id": event_id, "title": f"{event_id} 행사", "summary": "", "startAt": start, "endAt": end,
             "dateText": "", "timeText": "",
             "location": {"name": f"{building} 강의실", "building": building, "room": "101호"},
             "food": {"provided": "true", "type": "meal", "description": "샌드위치"},
             "organizer": "", "eligibility": "",
             "registration": {"required": "unknown", "deadline": None, "url": ""},
             "confidence": 0.95, "sources": [{"type": "dooray", "name": "Dooray"}]}
    event.update(extra)
    return event


LUNCH = ev("lunch", "2026-11-09T12:00:00+09:00", "2026-11-09T13:00:00+09:00", "E11",
           audience={"text": "학부생", "basis": "stated"})
RUNNING = ev("running", "2026-11-09T08:30:00+09:00", "2026-11-09T10:00:00+09:00", "N7",
             food={"provided": "true", "type": "snack", "description": "간식"})
NOEND = ev("noend", "2026-11-10T11:30:00+09:00", None, "E3")
WED = ev("wed", "2026-11-11T17:00:00+09:00", "2026-11-11T18:00:00+09:00", "W8",
         audience={"text": "관심 있는 분 누구나", "basis": "stated"},
         food={"provided": "true", "type": "snack", "description": "간식"})
GIFT = ev("gift", "2026-11-12T23:59:00+09:00", None, "E3",
          food={"provided": "unknown", "type": "unknown", "description": ""},
          giveaway={"provided": "true", "description": "커피 쿠폰"},
          registration={"required": "true", "deadline": "2026-11-12T23:59:00+09:00", "url": "https://forms.gle/x"})
NEXT = ev("nextweek", "2026-11-17T18:00:00+09:00", "2026-11-17T20:00:00+09:00", "",
          location={"name": "1호관", "building": "1호관", "room": ""},
          audience={"text": "대학원생", "basis": "inferred"})
OLD = ev("oldone", "2026-11-05T12:00:00+09:00", "2026-11-05T13:00:00+09:00", "E11", title="지난 세미나")
LIVE = {"schemaVersion": 1, "generatedAt": "2026-11-09T08:30:00+09:00", "timezone": "Asia/Seoul",
        "events": [LUNCH, RUNNING, NOEND, WED, GIFT, NEXT]}
ARCHIVE = {"generatedAt": "2026-11-09T08:30:00+09:00", "windowDays": 30, "events": [OLD]}


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        chrome = pw.chromium.launch(channel="chrome", headless=True)
        yield chrome
        chrome.close()


def open_hub(browser, query="", storage=None, lang="ko", size=(390, 844), share=None, clipboard="ok",
             notice_seen=True):
    context = browser.new_context(viewport={"width": size[0], "height": size[1]}, timezone_id="Asia/Seoul",
                                  service_workers="block", accept_downloads=True)
    init = [f"localStorage.setItem('babdoduk-lang', '{lang}');"]
    if notice_seen:
        init.append("localStorage.setItem('babdoduk-notice-ggongbab-live', '1');")
    for key, value in (storage or {}).items():
        init.append(f"localStorage.setItem({json.dumps(key)}, {json.dumps(value)});")
    # Share and clipboard are stubbed and recorded: the test never reaches a real share sheet.
    init.append("window.__shared = []; window.__copied = [];")
    if share == "native":
        init.append("navigator.share = (data) => { window.__shared.push(data); return Promise.resolve(); };")
    else:
        init.append("try { delete Navigator.prototype.share; } catch (e) {} navigator.share = undefined;")
    if clipboard == "ok":
        init.append("Object.defineProperty(navigator, 'clipboard', {value: {writeText: (t) => { window.__copied.push(t); return Promise.resolve(); }}});")
    else:
        init.append("Object.defineProperty(navigator, 'clipboard', {value: {writeText: () => Promise.reject(new Error('denied'))}});")
    context.add_init_script(" ".join(init))

    def handle(route):
        url = urlparse(route.request.url)
        if url.hostname != HOST:
            return route.abort()
        path = unquote(url.path).lstrip("/")
        if path == "data/ggongbab/latest.json":
            return route.fulfill(json=LIVE)
        if path == "data/ggongbab/archive/index.json":
            return route.fulfill(json=ARCHIVE)
        if path == "js/ggongbab-public-config.js":
            return route.fulfill(content_type="application/javascript", body="window.BABDODUK_PUBLIC_FEED_CONFIG = {};")
        if path.startswith("data/"):
            return route.fulfill(status=404, body="")
        file = (ROOT / path).resolve()
        if file.is_file() and ROOT in file.parents:
            return route.fulfill(path=str(file))
        return route.fulfill(status=404, body="")

    context.route("**/*", handle)
    page = context.new_page()
    page.clock.set_fixed_time(NOW)
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(f"https://{HOST}/ggongbab.html{query}", wait_until="networkidle")
    page.locator(".gg-card").first.wait_for()
    return context, page, errors


def ids(page):
    return page.locator(".gg-card").evaluate_all("els => els.map(el => el.dataset.id)")


def stored(page):
    return page.evaluate(f"JSON.parse(localStorage.getItem('{SAVED_KEY}') || 'null')")


def card(page, event_id):
    return page.locator(f'.gg-card[data-id="{event_id}"]')


def open_card(page, event_id):
    card(page, event_id).locator(".gg-card-toggle").click()


def test_module_rules(browser):
    context, page, errors = open_hub(browser)
    out = page.evaluate("""() => {
      const L = window.BabdodukLive, F = window.BabdodukFreeFood;
      const now = F.toKst('2026-11-09T09:00:00+09:00');
      const area = b => L.areaOf({location: {building: b}});
      const who = (text, basis) => L.whoOf({audience: text == null ? null : {text, basis: basis || 'stated'}});
      return {
        areas: ['E11', '창의학습관(E11)', 'N13-1', 'W1-1', '1호관', '', 'KAIST E6 공동강의실'].map(area),
        who: [who('새내기 학생'), who('학부생 및 대학원생'), who('관심 있는 분 누구나'), who('대학원생', 'inferred'),
              who(null), who('카이스트 재학생과 교수 및 임직원'), who('기계공학과 교수')],
        week: L.dayRange('week', now), next: L.dayRange('next', now), today: L.dayRange('today', now),
        shared: L.dayRange('w:2026-11-16', now), bad: L.dayRange('w:2026-13-40', now),
        monday: [L.mondayOf('2026-11-15'), L.mondayOf('2026-11-16'), L.mondayOf('2026-11-12')],
        sameTime: L.changes({seen: {startAt: '2026-11-09T03:00:00Z', endAt: '', place: 'E11'}},
                            {startAt: '2026-11-09T12:00:00+09:00', endAt: null, location: {building: 'E11'}}),
        moved: L.changes({seen: {startAt: '2026-11-09T11:00:00+09:00', endAt: '', place: 'E3'}},
                         {startAt: '2026-11-09T12:00:00+09:00', endAt: null, location: {building: 'E11'}}).map(c => c.field),
        phases: [L.phaseOf({startAt: '2026-11-09T08:30:00+09:00', endAt: '2026-11-09T10:00:00+09:00', food: {provided: 'true'}}, now),
                 L.phaseOf({startAt: '2026-11-09T12:00:00+09:00', endAt: '2026-11-09T13:00:00+09:00', food: {provided: 'true'}}, now),
                 L.phaseOf({startAt: '2026-11-08T12:00:00+09:00', endAt: '2026-11-08T13:00:00+09:00', food: {provided: 'true'}}, now)],
        link: L.eventLink('abc-1#2', 'https://www.babdodukms.com/index.html?x=1#y'),
        week_link: L.weekLink('2026-11-16', 'https://www.babdodukms.com/'),
      };
    }""")
    assert out["areas"] == ["east", "east", "north", "west", "unknown", "unknown", "east"]
    assert out["who"] == [["fresh", "undergrad"], ["undergrad", "grad"], ["open"], ["check"], ["check"],
                          ["undergrad"], ["check"]]
    assert out["week"] == ["2026-11-09", "2026-11-15"] and out["next"] == ["2026-11-16", "2026-11-22"]
    assert out["today"] == ["2026-11-09", "2026-11-09"] and out["shared"] == ["2026-11-16", "2026-11-22"]
    assert out["bad"] is None
    assert out["monday"] == ["2026-11-09", "2026-11-16", "2026-11-09"]
    assert out["sameTime"] == []                       # the same instant in another spelling is no change
    assert out["moved"] == ["time", "place"]
    assert out["phases"] == ["now", "soon", "ended"]
    assert out["link"] == "https://www.babdodukms.com/ggongbab.html?e=abc-1%232"
    assert out["week_link"] == "https://www.babdodukms.com/ggongbab.html?week=2026-11-16"
    assert not errors, errors
    context.close()


def test_calendar_text_is_one_exact_event(browser):
    context, page, errors = open_hub(browser)
    out = page.evaluate("""() => {
      const L = window.BabdodukLive;
      const ev = {id: 'x#2', title: '긴 제목; 쉼표, 그리고 \\\\ 역슬래시 ' + '가'.repeat(40), startAt: '2026-11-09T12:00:00+09:00',
                  endAt: '2026-11-09T13:30:00+09:00', location: {building: 'E11', room: '101호', name: ''}, food: {provided: 'true'}};
      const noEnd = Object.assign({}, ev, {endAt: null});
      const gift = {id: 'g', startAt: '2026-11-12T23:59:00+09:00', registration: {deadline: '2026-11-12T23:59:00+09:00'},
                    giveaway: {provided: 'true'}, food: {provided: 'unknown'}};
      return {ics: L.icsText(ev, {details: 'a\\nb', url: 'https://x/ggongbab.html?e=x', stamp: '2026-11-09T00:00:00Z'}),
              noEnd: L.icsText(noEnd, {stamp: '2026-11-09T00:00:00Z'}),
              google: L.googleCalendarUrl(ev, {details: 'd'}), googleNoEnd: L.googleCalendarUrl(noEnd),
              can: [L.canCalendar(ev), L.canCalendar(gift), L.canCalendar({id: 'n', startAt: ''})]};
    }""")
    ics = out["ics"]
    assert ics.startswith("BEGIN:VCALENDAR\r\n") and ics.endswith("END:VCALENDAR\r\n")
    assert ics.count("BEGIN:VEVENT") == 1
    assert "DTSTART:20261109T030000Z" in ics and "DTEND:20261109T043000Z" in ics
    assert "UID:x-2@babdodukms.com" in ics
    assert all(len(line.encode("utf-8")) <= 75 for line in ics.split("\r\n")), "lines fold at 75 octets"
    unfolded = ics.replace("\r\n ", "")
    assert "SUMMARY:긴 제목\\; 쉼표\\, 그리고 \\\\ 역슬래시 " in unfolded
    assert "DESCRIPTION:a\\nb" in unfolded and "LOCATION:E11 · 101호" in unfolded
    assert "DTEND" not in out["noEnd"]                 # no end is made up
    q = parse_qs(urlparse(out["google"]).query)
    assert q["dates"] == ["20261109T030000Z/20261109T043000Z"] and q["ctz"] == ["Asia/Seoul"]
    assert parse_qs(urlparse(out["googleNoEnd"]).query)["dates"] == ["20261109T030000Z/20261109T030000Z"]
    assert out["can"] == [True, False, False]
    assert not errors, errors
    context.close()


def test_save_toggle_survives_reload_without_duplicates(browser):
    context, page, errors = open_hub(browser)
    star = card(page, "lunch").locator(".gg-save")
    assert star.get_attribute("aria-pressed") == "false"
    assert star.get_attribute("aria-label") == "lunch 행사 저장"
    assert page.locator(".gg-saved").count() == 0          # nothing saved, no section
    star.click()
    assert page.locator(".gg-toast").inner_text() == "저장했어요 · 이 브라우저에만 저장돼요"
    data = stored(page)
    assert data["v"] == 1 and [item["id"] for item in data["items"]] == ["lunch"]
    assert set(data["items"][0]) == {"id", "savedAt", "seen"}
    assert set(data["items"][0]["seen"]) == {"title", "startAt", "endAt", "place"}   # never the whole event
    # The store refuses a second copy of the same listing.
    assert page.evaluate("window.BabdodukLive.createStore().add({id: 'lunch', title: 'x'})") is False
    page.reload()
    page.locator(".gg-card").first.wait_for()
    assert card(page, "lunch").locator(".gg-save").get_attribute("aria-pressed") == "true"
    assert page.locator(".gg-saved-n").inner_text() == "1"
    page.locator("[data-gg-saved]").click()
    assert page.locator("[data-gg-saved]").get_attribute("aria-expanded") == "true"
    assert page.locator('.gg-saved-row[data-saved-id="lunch"]').count() == 1
    assert "이 브라우저에만 저장돼요" in page.locator(".gg-saved-foot").inner_text()
    # The saved row opens the listing itself.
    page.locator('[data-gg-goto="lunch"]').click()
    assert card(page, "lunch").locator(".gg-card-toggle").get_attribute("aria-expanded") == "true"
    assert page.evaluate("document.activeElement.dataset.id") == "lunch"
    # Unsaving from the detail toolbar.
    card(page, "lunch").locator('.gg-tool[data-gg-save]').click()
    assert stored(page)["items"] == []
    assert card(page, "lunch").locator(".gg-save").get_attribute("aria-pressed") == "false"
    assert not errors, errors
    context.close()


def saved_store(*items):
    return {SAVED_KEY: json.dumps({"v": 1, "items": list(items)})}


def item(event_id, start, end="", place="E11 · 101호 · E11 강의실", title=None):
    return {"id": event_id, "savedAt": "2026-11-01T00:00:00.000Z",
            "seen": {"title": title or f"{event_id} 행사", "startAt": start, "endAt": end, "place": place}}


def test_changes_since_saving_ended_and_missing(browser):
    storage = saved_store(
        item("lunch", "2026-11-09T11:00:00+09:00", "2026-11-09T12:00:00+09:00", place="E3 · 201호"),
        item("wed", "2026-11-11T17:00:00+09:00", "2026-11-11T18:00:00+09:00", place="W8 · 101호 · W8 강의실"),
        item("oldone", "2026-11-05T12:00:00+09:00", "2026-11-05T13:00:00+09:00", title="지난 세미나"),
        item("gone", "2026-11-20T12:00:00+09:00", "2026-11-20T13:00:00+09:00", title="사라진 행사"),
        item("gonepast", "2026-11-01T12:00:00+09:00", "2026-11-01T13:00:00+09:00", title="끝난 행사"))
    context, page, errors = open_hub(browser, storage=storage)
    # The changed listing says so on its row and, opened, says what changed against the visitor's own copy.
    assert card(page, "lunch").locator(".gg-changed-label").inner_text() == "변경됨"
    assert card(page, "wed").locator(".gg-changed-label").count() == 0
    open_card(page, "lunch")
    changes = card(page, "lunch").locator(".gg-change").all_inner_texts()
    assert len(changes) == 2
    assert changes[0].startswith("시간 변경") and "11:00" in changes[0] and "12:00" in changes[0]
    assert changes[1].startswith("장소 변경") and "E3 · 201호" in changes[1]
    # The saved list: the change counted, ended and missing listings kept apart.
    assert "변경 1" in page.locator("[data-gg-saved]").inner_text()
    page.locator("[data-gg-saved]").click()
    rows = page.locator(".gg-saved-row")
    tags = dict(zip(rows.evaluate_all("els => els.map(el => el.dataset.savedId)"),
                    rows.locator(".gg-saved-tags").all_inner_texts()))
    assert tags["lunch"] == "변경됨" and tags["wed"] == ""
    assert tags["gone"] == "목록에서 빠짐"
    assert tags["oldone"] == "종료" and tags["gonepast"] == "종료"
    body = page.locator(".gg-saved-body").inner_text()
    assert "취소됐" in body and "취소됨" not in body and "취소 확정" not in body   # never asserted as cancelled
    assert "참석한 것으로 기록하지 않아요" in body
    assert page.locator('.gg-saved-row[data-saved-id="oldone"] [data-gg-goto]').count() == 0
    # "확인했어요" makes the newest copy the visitor's, and the marks go.
    card(page, "lunch").locator("[data-gg-ack]").click()
    assert card(page, "lunch").locator(".gg-changed-label").count() == 0
    seen = [i for i in stored(page)["items"] if i["id"] == "lunch"][0]["seen"]
    assert seen["startAt"] == LUNCH["startAt"]
    # Removing a past one.
    page.locator('[data-gg-unsave="oldone"]').click()
    assert "oldone" not in [i["id"] for i in stored(page)["items"]]
    assert not errors, errors
    context.close()


def test_optional_filters_never_persist(browser):
    context, page, errors = open_hub(browser)
    everything = ["running", "lunch", "noend", "wed", "gift", "nextweek"]
    assert ids(page) == everything
    assert page.locator('.gg-chip[data-group="day"]').count() == 0      # closed panel: no hidden chips
    more = page.locator("[data-gg-more]")
    assert more.get_attribute("aria-expanded") == "false"
    more.click()
    assert more.get_attribute("aria-expanded") == "true"
    assert page.locator('.gg-chip[data-group="day"]').evaluate_all("els => els.map(e => e.dataset.value)") == [
        "all", "today", "week", "next"]

    def pick(group, value):
        page.locator(f'.gg-chip[data-group="{group}"][data-value="{value}"]').click()

    pick("day", "today")
    assert ids(page) == ["running", "lunch"]
    assert card(page, "running").locator(".gg-now-label").inner_text() == "진행 중"
    assert card(page, "lunch").locator(".gg-now-label").count() == 0
    pick("day", "week")
    assert ids(page) == ["running", "lunch", "noend", "wed", "gift"]
    pick("day", "next")
    assert ids(page) == ["nextweek"]
    pick("day", "all")
    pick("who", "undergrad")
    assert ids(page) == ["lunch"]
    pick("who", "open")
    assert ids(page) == ["wed"]
    pick("who", "check")                       # no stated audience, or only an inferred one
    assert ids(page) == ["running", "noend", "gift", "nextweek"]
    pick("who", "all")
    pick("area", "west")
    assert ids(page) == ["wed"]
    pick("area", "unknown")
    assert ids(page) == ["nextweek"]
    assert page.locator(".gg-more-count").inner_text() == "1"
    pick("who", "grad")                        # inferred 대학원생 is not a statement
    assert ids(page) == []
    empty = page.locator('[data-gg-empty="filtered"]')
    assert "고른 조건에 맞는 꽁밥이 없어요" in empty.inner_text() and "대학원생" in empty.inner_text()
    empty.locator("[data-gg-reset]").click()
    assert ids(page) == everything
    assert page.evaluate("document.activeElement.dataset.value") == "all"
    pick("area", "east")
    saved_filter = page.evaluate("JSON.parse(localStorage.getItem('babdoduk-ggongbab-filter'))")
    assert saved_filter == {"when": "all", "food": "all"}     # the saved filter keeps its old shape
    page.reload()
    page.locator(".gg-card").first.wait_for()
    assert ids(page) == everything                            # date, who and where are not kept
    assert not errors, errors
    context.close()


def test_share_one_listing_and_the_week(browser):
    context, page, errors = open_hub(browser)
    open_card(page, "wed")
    card(page, "wed").locator("[data-gg-share]").click()
    page.wait_for_function("window.__copied.length === 1")
    copied = page.evaluate("window.__copied[0]")
    assert copied.splitlines()[0] == "간식 · wed 행사"
    assert copied.splitlines()[-1] == f"https://{HOST}/ggongbab.html?e=wed"
    assert page.locator(".gg-toast").inner_text() == "링크를 복사했어요"
    page.locator("[data-gg-share-week]").click()
    page.wait_for_function("window.__copied.length === 2")
    week = page.evaluate("window.__copied[1]").splitlines()
    assert week[0] == "밥도둑 꽁밥 · 11월 9일 주"
    assert week[-1] == f"https://{HOST}/ggongbab.html?week=2026-11-09"
    assert len(week) == 7 and not any("nextweek" in line for line in week)   # this week only
    context.close()

    # The device's share sheet when there is one; no copy then.
    context, page, errors = open_hub(browser, share="native")
    open_card(page, "lunch")
    card(page, "lunch").locator("[data-gg-share]").click()
    page.wait_for_function("window.__shared.length === 1")
    data = page.evaluate("window.__shared[0]")
    assert data["url"] == f"https://{HOST}/ggongbab.html?e=lunch" and data["title"] == "lunch 행사"
    assert page.evaluate("window.__copied.length") == 0
    context.close()

    # Neither works (some in-app browsers): the text to copy by hand.
    context, page, errors = open_hub(browser, clipboard="denied")
    open_card(page, "lunch")
    card(page, "lunch").locator("[data-gg-share]").click()
    box = card(page, "lunch").locator(".gg-copy textarea")
    box.wait_for()
    assert box.input_value().endswith("?e=lunch")
    assert not errors, errors
    context.close()


def test_shared_links_open_the_listing_or_say_why_not(browser):
    context, page, errors = open_hub(browser, query="?e=wed")
    page.wait_for_function("document.activeElement && document.activeElement.dataset.id === 'wed'")
    assert card(page, "wed").locator(".gg-card-toggle").get_attribute("aria-expanded") == "true"
    assert page.locator(".gg-entry").count() == 0
    context.close()

    # A filter saved earlier never hides the listing someone shared.
    context, page, errors = open_hub(browser, query="?e=lunch",
                                     storage={"babdoduk-ggongbab-filter": json.dumps({"when": "all", "food": "giveaway"})})
    page.wait_for_function("document.activeElement && document.activeElement.dataset.id === 'lunch'")
    context.close()

    context, page, errors = open_hub(browser, query="?e=oldone")
    page.locator(".gg-entry").wait_for()
    assert "공유받은 꽁밥은 끝났어요" in page.locator(".gg-entry").inner_text()
    assert "지난 세미나" in page.locator(".gg-entry").inner_text()
    context.close()

    context, page, errors = open_hub(browser, query="?e=nothere")
    page.locator(".gg-entry").wait_for()
    assert "찾지 못했어요" in page.locator(".gg-entry").inner_text()
    page.locator("[data-gg-entry-close]").click()
    assert page.locator(".gg-entry").count() == 0
    context.close()

    # A week link (any day of it) shows that week; "전체 일정 보기" clears it.
    context, page, errors = open_hub(browser, query="?week=2026-11-18")
    assert ids(page) == ["nextweek"]
    assert "11월 16일 주" in page.locator(".gg-entry").inner_text()
    page.locator(".gg-entry [data-gg-reset]").click()
    assert len(ids(page)) == 6 and page.locator(".gg-entry").count() == 0
    context.close()

    context, page, errors = open_hub(browser, query="?e=%3Cscript%3E&week=2026-02-30")
    assert len(ids(page)) == 6 and page.locator(".gg-entry").count() == 0     # malformed: ignored
    assert not errors, errors
    context.close()


def test_calendar_one_listing_at_a_time(browser):
    context, page, errors = open_hub(browser)
    open_card(page, "lunch")
    cal_button = card(page, "lunch").locator("[data-gg-cal]")
    assert cal_button.get_attribute("aria-expanded") == "false"
    cal_button.click()
    panel = card(page, "lunch").locator(".gg-cal")
    assert panel.is_visible() and cal_button.get_attribute("aria-expanded") == "true"
    google = panel.locator("a").get_attribute("href")
    q = parse_qs(urlparse(google).query)
    assert q["dates"] == ["20261109T030000Z/20261109T040000Z"] and q["text"] == ["lunch 행사"]
    assert f"https://{HOST}/ggongbab.html?e=lunch" in q["details"][0]
    assert panel.locator("a").get_attribute("rel") == "noopener"
    with page.expect_download() as info:
        panel.locator("[data-gg-ics]").click()
    download = info.value
    assert download.suggested_filename == "babdoduk-2026-11-09.ics"
    text = Path(download.path()).read_text(encoding="utf-8")
    assert text.count("BEGIN:VEVENT") == 1 and "DTSTART:20261109T030000Z" in text
    # No end in the notice: said so, and the file has no made-up end.
    open_card(page, "noend")
    card(page, "noend").locator("[data-gg-cal]").click()
    assert card(page, "noend").locator(".gg-cal-note").inner_text() == "끝나는 시간은 공지에 없어요"
    # A giveaway listed only by its sign-up deadline has no event time to add.
    open_card(page, "gift")
    assert card(page, "gift").locator("[data-gg-cal]").count() == 0
    assert card(page, "gift").locator("[data-gg-share]").count() == 1
    assert not errors, errors
    context.close()


def test_new_feature_note_closes_for_good(browser):
    context, page, errors = open_hub(browser, notice_seen=False)
    note = page.locator(".gg-new")
    assert "저장 · 공유 · 캘린더" in note.inner_text()
    # It sits in the page head, above the list, and covers nothing.
    assert page.evaluate("getComputedStyle(document.querySelector('.gg-new')).position") == "static"
    page.locator("[data-gg-new-close]").click()
    assert page.locator(".gg-new").count() == 0
    assert page.evaluate("localStorage.getItem('babdoduk-notice-ggongbab-live')") == "1"
    page.reload()
    page.locator(".gg-card").first.wait_for()
    assert page.locator(".gg-new").count() == 0
    assert not errors, errors
    context.close()


def test_damaged_or_newer_saved_data_never_breaks_the_page(browser):
    context, page, errors = open_hub(browser, storage={SAVED_KEY: "{not json"})
    assert len(ids(page)) == 6
    assert page.evaluate("localStorage.getItem('babdoduk-ggongbab-saved-unreadable')") == "{not json"
    assert page.locator(".gg-saved").count() == 1          # says it started again
    page.locator("[data-gg-saved]").click()
    assert "새로 시작했어요" in page.locator(".gg-saved-body").inner_text()
    assert not errors, errors
    context.close()

    newer = json.dumps({"v": 2, "items": [{"id": "lunch", "seen": {}}], "extra": True})
    context, page, errors = open_hub(browser, storage={SAVED_KEY: newer})
    assert card(page, "lunch").locator(".gg-save").get_attribute("aria-pressed") == "true"
    card(page, "wed").locator(".gg-save").click()
    assert page.locator(".gg-toast").inner_text() == "이 브라우저에서는 저장할 수 없어요"
    assert page.evaluate(f"localStorage.getItem('{SAVED_KEY}')") == newer   # never rewritten by an older page
    assert not errors, errors
    context.close()

    junk = json.dumps({"v": 1, "items": [{"id": "<img src=x onerror=alert(1)>"}, {"id": "lunch"}, {"id": "lunch"}, 5]})
    context, page, errors = open_hub(browser, storage={SAVED_KEY: junk})
    assert page.locator(".gg-saved-n").inner_text() == "1"
    assert not errors, errors
    context.close()


def test_english_and_phone_layout(browser):
    for width in (360, 390, 768, 1440):
        context, page, errors = open_hub(browser, lang="en", size=(width, 900), notice_seen=False,
                                         storage=saved_store(item("lunch", "2026-11-09T12:00:00+09:00",
                                                                  "2026-11-09T13:00:00+09:00")))
        assert page.locator("[data-gg-more]").inner_text().startswith("Date · who · where")
        page.locator("[data-gg-more]").click()
        page.locator("[data-gg-saved]").click()
        open_card(page, "lunch")
        card(page, "lunch").locator("[data-gg-cal]").click()
        live_ui = " ".join(page.locator(".gg-more-panel, .gg-saved, .gg-tools, .gg-cal, .gg-new").all_inner_texts())
        assert not re.search(r"[가-힣]", live_ui.replace("lunch 행사", "")), live_ui
        assert "Saved in this browser only" in live_ui and "Add to calendar" in live_ui
        assert page.evaluate("document.documentElement.scrollWidth") <= width
        # Every new control is a 44 px tap target with a name.
        for box in page.locator(".gg-save, .gg-tool, .gg-more, .gg-chip, .gg-unsave, .gg-new-close, .gg-saved-toggle, .gg-cal .gg-btn").evaluate_all(
                "els => els.filter(el => el.offsetParent).map(el => { const r = el.getBoundingClientRect();"
                " return [r.width, r.height, (el.getAttribute('aria-label') || el.textContent).trim()]; })"):
            assert min(box[0], box[1]) >= 43.5 and box[2], box
        star = card(page, "lunch").locator(".gg-save").bounding_box()
        row = card(page, "lunch").bounding_box()
        assert star["x"] + star["width"] <= row["x"] + row["width"] + 0.5
        assert not errors, errors
        context.close()
