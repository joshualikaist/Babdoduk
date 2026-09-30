"""Home free-food calendar: a Monday-first KST month, today and selection states, event markers,
the next-event default, the day panel and its disclosure, loading failures and the layout.
Synthetic data is served to the test browser only; no generated file is read or changed."""
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
HOST = "home-calendar.invalid"
NOW = "2026-10-01T09:00:00+09:00"   # a Thursday; October 2026 starts on a Thursday
ACCENT = "rgb(180, 61, 39)"
INK = "rgb(30, 29, 26)"
KAIST_E11 = {"name": "창의학습관(E11) 101호", "building": "창의학습관(E11)", "room": "101호"}


def ev(event_id, start, end=None, **extra):
    event = {"id": event_id, "title": event_id, "startAt": start, "endAt": end,
             "food": {"provided": "true", "type": "meal", "description": "샌드위치"},
             "location": dict(KAIST_E11), "registration": None, "sources": [{"type": "dooray", "name": "Dooray"}]}
    event.update(extra)
    return event


FORUM = ev("forum", "2026-10-07T12:00:00+09:00", "2026-10-07T13:00:00+09:00", title="첫수융합포럼",
           food={"provided": "true", "type": "refreshment", "description": "간단한 다과"},
           registration={"required": "true", "deadline": None, "url": "https://forms.gle/example"})
MEETUP = ev("meetup", "2026-10-07T17:00:00+09:00", title="Temp Seoul Meetup",
            location={"name": "KAIST 창업원", "building": "창업원", "room": ""},
            food={"provided": "true", "type": "meal", "description": "식사"},
            registration={"required": "true", "deadline": None, "url": "https://luma.com/example"})
PAST = ev("seminar", "2026-09-29T12:00:00+09:00", "2026-09-29T13:00:00+09:00", title="지난 세미나")
LIVE = {"generatedAt": "2026-10-01T08:30:00+09:00", "events": [FORUM, MEETUP]}
ARCHIVE = {"generatedAt": "2026-10-01T08:30:00+09:00", "windowDays": 30, "events": [PAST]}


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        chrome = pw.chromium.launch(channel="chrome", headless=True)
        yield chrome
        chrome.close()


def open_home(browser, live=LIVE, archive=ARCHIVE, now=NOW, lang="ko", size=(390, 844), tz="Asia/Seoul",
              live_status=200, archive_status=200):
    context = browser.new_context(viewport={"width": size[0], "height": size[1]}, timezone_id=tz,
                                  service_workers="block")
    context.add_init_script(f"localStorage.setItem('babdoduk-lang', '{lang}');")

    def handle(route):
        url = urlparse(route.request.url)
        if url.hostname != HOST:
            return route.abort()
        path = unquote(url.path).lstrip("/")
        if path == "data/ggongbab/latest.json":
            return route.fulfill(json=live) if live_status == 200 else route.fulfill(status=live_status, body="")
        if path == "data/ggongbab/archive/index.json":
            return route.fulfill(json=archive) if archive_status == 200 else route.fulfill(status=archive_status, body="")
        if path.startswith("data/"):
            return route.fulfill(status=404, body="")   # cafeteria and magazine are not under test here
        file = (ROOT / path).resolve()
        if file.is_file() and ROOT in file.parents:
            return route.fulfill(path=str(file))
        return route.fulfill(status=404, body="")

    context.route("**/*", handle)
    page = context.new_page()
    page.clock.set_fixed_time(now)
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(f"https://{HOST}/index.html", wait_until="networkidle")
    page.wait_for_function("document.getElementById('homeCal').dataset.state !== 'loading'")
    return context, page, errors


def cell(page, iso):
    return page.locator(f'#homeCalGrid td[data-date="{iso}"]')


def dots(page, iso):
    return cell(page, iso).evaluate("td => [...td.querySelectorAll('.hc-dot')].map(d => d.classList.contains('is-past') ? 'past' : 'live')")


def answer(page):
    return page.locator("#homeCalAnswer").inner_text()


def day_title(page):
    return " ".join(page.locator(".hc-day-title").inner_text().split())


def test_month_math_is_monday_first_and_calendar_correct(browser):
    context, page, errors = open_home(browser)
    math = page.evaluate("""() => {
      const C = window.BabdodukHomeCalendar;
      const oct = C.monthGrid('2026-10'), feb27 = C.monthGrid('2027-02'), feb28 = C.monthGrid('2028-02');
      return {octFirst: oct[0][0], octLast: oct[oct.length - 1][6], octRows: oct.length,
              feb27Rows: feb27.length, feb27First: feb27[0][0], feb28Has29: feb28.flat().includes('2028-02-29'),
              after29: feb28.flat()[feb28.flat().indexOf('2028-02-29') + 1],
              days: ['2026-02', '2027-02', '2028-02', '2000-02', '2100-02', '2026-12'].map(C.daysInMonth),
              monday: C.weekdayMon('2026-10-05'), sunday: C.weekdayMon('2026-10-04'),
              clamp: [C.shiftMonth('2026-01-31', 1), C.shiftMonth('2028-01-31', 1), C.shiftMonth('2026-03-31', -1)],
              months: [C.addMonths('2026-01', -1), C.addMonths('2026-12', 1), C.addMonths('2026-10', 14)],
              days7: C.addDays('2026-12-28', 7)};
    }""")
    assert math["octFirst"] == "2026-09-28" and math["octLast"] == "2026-11-01" and math["octRows"] == 5
    assert math["feb27Rows"] == 4 and math["feb27First"] == "2027-02-01"   # starts on a Monday, 28 days
    assert math["feb28Has29"] and math["after29"] == "2028-03-01"          # leap year
    assert math["days"] == [28, 28, 29, 29, 28, 31]                        # 2000 leap, 2100 not
    assert math["monday"] == 0 and math["sunday"] == 6
    assert math["clamp"] == ["2026-02-28", "2028-02-29", "2026-02-28"]
    assert math["months"] == ["2025-12", "2027-01", "2027-12"] and math["days7"] == "2027-01-04"
    assert not errors
    context.close()


def test_rendered_grid_is_monday_first_with_muted_overflow(browser):
    context, page, _ = open_home(browser)
    heads = page.locator("#homeCalGrid thead th").all_inner_texts()
    assert heads == ["월", "화", "수", "목", "금", "토", "일"]
    assert page.locator(".hc-month-title").inner_text() == "10월"
    assert page.locator("#homeCalGrid tbody tr").count() == 5
    first = page.locator("#homeCalGrid tbody td").first
    assert first.get_attribute("data-date") == "2026-09-28" and "is-other" in first.get_attribute("class")
    assert "is-other" in cell(page, "2026-11-01").get_attribute("class")
    assert "is-other" not in cell(page, "2026-10-31").get_attribute("class")
    weekday = page.locator("#homeCalGrid thead abbr").first.get_attribute("title")
    assert weekday == "월요일"
    context.close()


@pytest.mark.parametrize("tz, now, today", [
    ("America/Los_Angeles", "2026-10-01T08:00:00+09:00", "2026-10-01"),   # still Sep 30 in LA
    ("Pacific/Kiritimati", "2026-09-30T23:30:00+09:00", "2026-09-30"),    # already Oct 1 at UTC+14
    ("UTC", "2026-10-01T00:05:00+09:00", "2026-10-01"),                   # just after midnight KST
])
def test_today_is_the_kst_date_whatever_the_browser_zone(browser, tz, now, today):
    context, page, _ = open_home(browser, now=now, tz=tz)
    current = page.locator('#homeCalGrid td[aria-current="date"]')
    assert current.count() == 1 and current.get_attribute("data-date") == today
    month, day = int(today[5:7]), int(today[8:10])
    assert page.locator("#homeCalToday").inner_text().startswith(f"{month}월 {day}일 (")
    context.close()


def test_next_event_date_is_the_default_when_today_is_empty(browser):
    context, page, _ = open_home(browser)
    assert answer(page) == "오늘은 없어요 · 다음 10월 7일 (수)"
    assert page.locator("#homeCal").get_attribute("data-state") == "empty"
    assert cell(page, "2026-10-07").get_attribute("aria-selected") == "true"
    today = cell(page, "2026-10-01")
    assert today.get_attribute("aria-selected") == "false" and today.get_attribute("aria-current") == "date"
    assert page.locator('#homeCalGrid td[aria-selected="true"]').count() == 1
    assert day_title(page) == "10월 7일 (수)"
    assert page.locator(".hc-ev-title").all_inner_texts() == ["첫수융합포럼", "Temp Seoul Meetup"]
    assert page.locator("#homeCalNext").is_hidden()        # nothing after the selected day
    # The row carries no date: the panel heading says it once.
    assert "10월 7일" not in page.locator(".hc-ev-btn").first.inner_text()
    # Today stays selectable.
    today.click()
    assert today.get_attribute("aria-selected") == "true" and page.locator(".hc-empty").inner_text() == "일정 없음"
    assert page.locator(".hc-next-row").count() == 2       # the next dates are one tap away
    context.close()


def test_today_with_events_is_selected_and_counted(browser):
    live = {"generatedAt": LIVE["generatedAt"], "events": [
        ev("lunch", "2026-10-01T12:00:00+09:00", "2026-10-01T13:00:00+09:00", title="점심 간담회"),
        ev("tea", "2026-10-01T15:00:00+09:00", "2026-10-01T16:00:00+09:00", title="티타임"),
        ev("review", "2026-10-01T10:00:00+09:00", needs_review=True, title="검토 중"),
        ev("unknown", "2026-10-01T11:00:00+09:00", food={"provided": "unknown"}, title="음식 미확인"),
        FORUM]}
    context, page, _ = open_home(browser, live=live)
    assert answer(page) == "오늘 2개 · 12:00부터"          # only public rows count
    assert page.locator("#homeCal").get_attribute("data-state") == "ready"
    today = cell(page, "2026-10-01")
    assert today.get_attribute("aria-selected") == "true" and today.get_attribute("aria-current") == "date"
    style = today.locator(".hc-num").evaluate("el => { const s = getComputedStyle(el); return [s.backgroundColor, s.color]; }")
    assert style[0] == ACCENT                               # today + selected: accent disc
    assert day_title(page) == "10월 1일 (목) 오늘"
    assert page.locator(".hc-ev-title").all_inner_texts() == ["점심 간담회", "티타임"]
    assert page.locator(".hc-next-row .hc-next-name").all_inner_texts() == ["첫수융합포럼"]
    cell(page, "2026-10-07").click()
    selected = cell(page, "2026-10-07").locator(".hc-num").evaluate("el => getComputedStyle(el).backgroundColor")
    ring = today.locator(".hc-num").evaluate("el => [getComputedStyle(el).backgroundColor, getComputedStyle(el).borderTopColor]")
    assert selected == INK                                  # selected: ink disc
    assert ring == ["rgba(0, 0, 0, 0)", ACCENT]             # today alone: accent ring only
    context.close()


@pytest.mark.parametrize("future, expected", [
    (True, "오늘 일정은 끝났어요 · 다음 10월 7일 (수)"),
    (False, "오늘 일정은 끝났어요"),
])
def test_answer_when_todays_events_have_ended(browser, future, expected):
    events = [ev("breakfast", "2026-10-01T07:00:00+09:00", "2026-10-01T08:00:00+09:00")] + ([FORUM] if future else [])
    context, page, _ = open_home(browser, live={"generatedAt": LIVE["generatedAt"], "events": events})
    assert answer(page) == expected
    assert dots(page, "2026-10-01") == ["past"]
    context.close()


def test_nothing_scheduled_is_quiet(browser):
    context, page, _ = open_home(browser, live={"generatedAt": LIVE["generatedAt"], "events": []},
                                 archive={"windowDays": 30, "events": []})
    assert answer(page) == "예정된 꽁밥이 없어요"
    assert page.locator("#homeCalGrid .hc-dot").count() == 0
    assert page.locator(".hc-empty").inner_text() == "일정 없음" and page.locator("#homeCalNext").is_hidden()
    context.close()


def test_markers_live_past_multiple_and_labels(browser):
    live = {"generatedAt": LIVE["generatedAt"], "events": [
        FORUM, MEETUP,
        ev("m1", "2026-10-14T12:00:00+09:00"), ev("m2", "2026-10-14T13:00:00+09:00"), ev("m3", "2026-10-14T18:00:00+09:00")]}
    context, page, _ = open_home(browser, live=live)
    assert dots(page, "2026-10-07") == ["live", "live"]
    assert dots(page, "2026-10-14") == ["live", "live"]          # never more than two
    assert dots(page, "2026-09-29") == ["past"]                  # a retained record
    assert dots(page, "2026-10-08") == []
    assert cell(page, "2026-10-14").get_attribute("aria-label") == "10월 14일 수요일, 꽁밥 3개"
    assert cell(page, "2026-09-29").get_attribute("aria-label") == "9월 29일 화요일, 지난 꽁밥 1개"
    live_dot, past_dot = (page.locator(f"{sel}").first.evaluate(
        "el => { const s = getComputedStyle(el); return [s.backgroundColor, s.borderTopStyle]; }")
        for sel in ('#homeCalGrid td[data-date="2026-10-07"] .hc-dot', '#homeCalGrid td[data-date="2026-09-29"] .hc-dot'))
    assert live_dot == [ACCENT, "none"] and past_dot[0] == "rgba(0, 0, 0, 0)" and past_dot[1] == "solid"
    # Marker slots are reserved on every day, so data never shifts the grid.
    heights = page.locator("#homeCalGrid .hc-marks").evaluate_all("els => [...new Set(els.map(e => e.getBoundingClientRect().height))]")
    assert heights == [5]
    cell(page, "2026-10-14").click()
    assert page.locator(".hc-ev").count() == 3
    context.close()


def test_live_and_archive_rows_are_deduplicated(browser):
    ended = ev("dup", "2026-09-30T12:00:00+09:00", "2026-09-30T13:00:00+09:00", title="중복 없는 행사")
    live = {"generatedAt": LIVE["generatedAt"], "events": [ended, FORUM]}
    archive = {"windowDays": 30, "events": [dict(ended, title="아카이브 사본"), PAST]}
    context, page, _ = open_home(browser, live=live, archive=archive)
    assert dots(page, "2026-09-30") == ["past"]
    cell(page, "2026-09-30").click()
    assert page.locator(".hc-ev-title").all_inner_texts() == ["중복 없는 행사"]   # once, the live copy
    assert "종료" in page.locator(".hc-ev-meta").first.inner_text()
    context.close()


def test_a_failed_load_is_never_shown_as_an_empty_schedule(browser):
    context, page, _ = open_home(browser, live_status=503)
    module = page.locator("#homeCal")
    assert module.get_attribute("data-state") == "error"
    assert answer(page) == "꽁밥 일정을 불러오지 못했어요"
    text = module.inner_text()
    assert not any(word in text for word in ("일정 없음", "기록 없음", "예정된 꽁밥이 없어요", "오늘은 없어요"))
    assert page.locator("#homeCalGrid .hc-dot").count() == 0 and page.locator("#homeCalDay").is_hidden()
    link = page.locator("#homeCalAll")
    assert link.inner_text() == "꽁밥 페이지 →" and link.get_attribute("href") == "ggongbab.html#free"
    context.close()


@pytest.mark.parametrize("status, expected", [(503, "지난 기록을 불러오지 못했어요"), (404, "기록 없음")])
def test_past_days_say_what_the_archive_allows(browser, status, expected):
    context, page, _ = open_home(browser, archive_status=status)
    assert page.locator("#homeCal").get_attribute("data-state") == "empty"   # the live schedule still loads
    cell(page, "2026-09-28").click()                                  # a visible overflow day, no record
    assert page.locator(".hc-empty").inner_text() == expected
    context.close()


def test_selected_future_and_past_days(browser):
    context, page, _ = open_home(browser)
    cell(page, "2026-10-03").click()
    assert cell(page, "2026-10-03").get_attribute("aria-selected") == "true"
    assert day_title(page) == "10월 3일 (토)"
    assert page.locator(".hc-empty").inner_text() == "일정 없음"
    assert page.locator("#homeCalLive").inner_text() == "10월 3일 토요일 · 일정 없음"
    assert page.locator(".hc-next-row").count() == 2                 # 10/7 is after the selected day
    cell(page, "2026-09-28").click()                                  # an overflow day of September
    assert page.locator(".hc-month-title").inner_text() == "10월"     # a visible overflow day keeps the month
    assert page.locator(".hc-empty").inner_text() == "기록 없음"
    cell(page, "2026-09-29").click()
    assert page.locator(".hc-ev-title").all_inner_texts() == ["지난 세미나"]
    assert page.locator(".hc-ev-meta").first.inner_text().startswith("종료 · 12:00")
    context.close()


def test_month_navigation_bounds_and_return_to_today(browser):
    context, page, _ = open_home(browser)
    today_button = page.locator("[data-hc-today]")
    assert today_button.is_hidden()
    page.locator('[data-hc-step="1"]').click()
    assert page.locator(".hc-month-title").inner_text() == "11월" and today_button.is_visible()
    assert page.locator("#homeCalGrid tbody td").first.get_attribute("data-date") == "2026-10-26"
    assert day_title(page) == "10월 7일 (수)"      # the selection is kept
    page.locator('[data-hc-step="-1"]').click()
    page.locator('[data-hc-step="-1"]').click()
    assert page.locator(".hc-month-title").inner_text() == "9월"
    # The retained window starts 30 days before today: earlier days are inert and cannot be focused.
    assert page.locator('[data-hc-step="-1"]').get_attribute("aria-disabled") == "true"
    page.locator('[data-hc-step="-1"]').click(force=True)                   # a disabled arrow does nothing
    assert page.locator(".hc-month-title").inner_text() == "9월"
    off = page.locator("#homeCalGrid td.is-off")
    assert off.count() >= 1 and off.first.get_attribute("tabindex") is None and off.first.get_attribute("data-date") is None
    assert page.locator('#homeCalGrid td.is-off .hc-dot').count() == 0
    today_button.click()
    assert page.locator(".hc-month-title").inner_text() == "10월" and today_button.is_hidden()
    assert cell(page, "2026-10-07").get_attribute("aria-selected") == "true"   # the default policy again
    context.close()


def test_keyboard_follows_the_date_grid_pattern(browser):
    context, page, _ = open_home(browser)
    assert page.locator('#homeCalGrid td[tabindex="0"]').count() == 1
    cell(page, "2026-10-07").focus()

    def active():
        return page.evaluate("document.activeElement.dataset.date")

    for key, expected in (("ArrowRight", "2026-10-08"), ("ArrowDown", "2026-10-15"), ("Home", "2026-10-12"),
                          ("End", "2026-10-18"), ("ArrowUp", "2026-10-11"), ("ArrowLeft", "2026-10-10")):
        page.keyboard.press(key)
        assert active() == expected, key
        assert page.locator('#homeCalGrid td[tabindex="0"]').count() == 1
    assert cell(page, "2026-10-07").get_attribute("aria-selected") == "true"    # moving is not selecting
    page.keyboard.press("PageDown")
    assert active() == "2026-11-10" and page.locator(".hc-month-title").inner_text() == "11월"
    page.keyboard.press("PageUp")
    assert active() == "2026-10-10" and page.locator(".hc-month-title").inner_text() == "10월"
    page.keyboard.press("Enter")
    assert cell(page, "2026-10-10").get_attribute("aria-selected") == "true"
    assert day_title(page) == "10월 10일 (토)"
    page.keyboard.press("ArrowRight")
    page.keyboard.press(" ")
    assert cell(page, "2026-10-11").get_attribute("aria-selected") == "true" and active() == "2026-10-11"
    focus = page.evaluate("getComputedStyle(document.activeElement.querySelector('.hc-num')).outlineStyle")
    assert focus == "solid"                                   # focus-visible ring
    context.close()


def test_grid_and_rows_expose_their_states(browser):
    context, page, _ = open_home(browser)
    grid = page.locator("#homeCalGrid table")
    assert grid.get_attribute("role") == "grid" and grid.get_attribute("aria-labelledby") == "homeCalMonth"
    assert page.locator('[aria-current="date"]').count() == 1
    assert page.locator("#homeCalLive").get_attribute("aria-live") == "polite"
    for button in page.locator(".hc-nav, [data-hc-today]").all():
        assert button.get_attribute("aria-label") or button.inner_text()
    rows = page.locator(".hc-ev-btn")
    for i in range(rows.count()):
        target = rows.nth(i).get_attribute("aria-controls")
        assert rows.nth(i).get_attribute("aria-expanded") == "false" and page.locator(f"#{target}").is_hidden()
    context.close()


def test_rows_open_inline_one_at_a_time(browser):
    context, page, _ = open_home(browser)
    first, second = page.locator(".hc-ev-btn").nth(0), page.locator(".hc-ev-btn").nth(1)
    first.click()
    detail = page.locator("#" + first.get_attribute("aria-controls"))
    assert first.get_attribute("aria-expanded") == "true" and detail.is_visible()
    text = detail.inner_text()
    assert "12:00–13:00 · 창의학습관(E11) 101호" in text and "출처 · KAIST 메일" in text
    apply = detail.locator("a.hc-ev-apply")
    assert apply.get_attribute("href") == "https://forms.gle/example"
    assert apply.get_attribute("target") == "_blank" and "noopener" in apply.get_attribute("rel")
    second.click()
    assert first.get_attribute("aria-expanded") == "false" and detail.is_hidden()
    assert second.get_attribute("aria-expanded") == "true"
    second.click()
    assert second.get_attribute("aria-expanded") == "false"
    assert not page.locator(".modal, [role=dialog]").count()
    context.close()


def test_links_are_public_only_and_first_come_is_never_inferred(browser):
    private = ev("private", "2026-10-07T12:00:00+09:00", "2026-10-07T13:00:00+09:00", title="커피 나눔",
                 summary="선착순 100명 커피 제공, 소진 시 종료", supply_limited=True, supply_limit_text="선착순 100명",
                 food={"provided": "true", "type": "beverage", "description": "커피"},
                 sources=[{"type": "dooray", "name": "Dooray", "url": "https://nhnent.dooray.com/mail/abc"}],
                 registration={"required": "false", "deadline": None, "url": "https://nhnent.dooray.com/share/x"})
    public = ev("public", "2026-10-07T15:00:00+09:00", title="공개 공지 행사",
                sources=[{"type": "kaist_public", "name": "KAIST", "url": "https://www.kaist.ac.kr/news/1"}])
    context, page, _ = open_home(browser, live={"generatedAt": LIVE["generatedAt"], "events": [private, public]})
    for button in page.locator(".hc-ev-btn").all():
        button.click()
    hrefs = page.locator("#homeCalDay a").evaluate_all("els => els.map(a => a.href)")
    assert hrefs == ["https://www.kaist.ac.kr/news/1"]                   # the public notice only
    assert page.locator("#homeCalDay a.hc-ev-link").inner_text().startswith("원문 보기")
    shown = page.locator("#homeCalDay").inner_text()
    assert "선착순" not in shown and "소진" not in shown and "dooray" not in shown.lower()
    assert "confidence" not in page.content()
    context.close()


def test_english_strings(browser):
    context, page, _ = open_home(browser, lang="en")
    assert page.locator(".home-cal-title [data-i18n]").inner_text() == "Free food today"
    assert answer(page) == "None today · next Oct 7 (Wed)"
    assert page.locator("#homeCalGrid thead th").all_inner_texts() == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    assert page.locator(".hc-month-title").inner_text() == "October"
    assert day_title(page) == "Oct 7 (Wed)"
    assert page.locator(".hc-ev-meta").nth(1).inner_text() == "Refreshments · Sign-up required"
    assert page.locator("#homeCalAll").inner_text() == "All events →"
    assert page.locator("#homeCalPublished").inner_text().startswith("Last published Oct 1 (Thu)")
    page.locator("#langToggle").click()
    assert answer(page) == "오늘은 없어요 · 다음 10월 7일 (수)"
    assert page.locator(".hc-ev-meta").nth(1).inner_text() == "간단한 다과 제공 · 사전 신청"
    context.close()


@pytest.mark.parametrize("width", [320, 390])
def test_phones_put_the_calendar_first_without_overflow(browser, width):
    context, page, _ = open_home(browser, size=(width, 844))
    box = page.evaluate("""() => { const r = s => document.querySelector(s).getBoundingClientRect();
      return {overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
              cal: r('#homeCal').top, collage: r('.home-collage').top, menu: r('.home-menu-line').top,
              grid: r('#homeCalGrid .hc-grid'), cell: r('#homeCalGrid td[data-date]'), hero: r('.home-hero').bottom}; }""")
    assert box["overflow"] <= 0
    assert box["hero"] <= box["cal"] < box["menu"] < box["collage"]      # copy, calendar, cafeteria, collage
    # 44 px targets at phone width; at 320 px (small phones, 400% zoom) still well above WCAG's 24 px.
    assert box["grid"]["right"] <= width and box["cell"]["width"] >= (44 if width >= 390 else 36)
    if width == 390:
        assert box["grid"]["bottom"] <= 844                                # the whole month in the first screen
    assert page.locator('[data-banner="today"], #homeFreeStatus, .home-today').count() == 0
    assert page.locator("#homeMenuStatus").count() == 1
    context.close()


def test_desktop_split_keeps_the_grid_compact(browser):
    context, page, _ = open_home(browser, size=(1440, 900))
    box = page.evaluate("""() => { const r = s => document.querySelector(s).getBoundingClientRect();
      const month = document.querySelector('#homeCalGrid');
      return {grid: r('#homeCalGrid .hc-grid'), day: r('#homeCalDay'), collage: r('.home-collage'), cal: r('#homeCal'),
              hero: r('.home-hero'), divider: getComputedStyle(month).borderLeftStyle}; }""")
    assert 320 <= box["grid"]["width"] <= 340
    assert box["grid"]["left"] > box["day"]["right"] and box["divider"] == "solid"
    assert box["collage"]["top"] < box["cal"]["top"] and abs(box["collage"]["top"] - box["hero"]["top"]) < 200
    assert box["grid"]["bottom"] <= 900
    context.close()


def test_no_weight_900_or_decoration_in_the_module(browser):
    context, page, _ = open_home(browser, size=(1440, 900))
    styles = page.locator("#homeCal, #homeCal *").evaluate_all("""els => els.map(el => {
      const s = getComputedStyle(el); return [s.fontWeight, s.boxShadow, s.backgroundImage]; })""")
    assert all(weight != "900" for weight, _, _ in styles)
    assert all(shadow == "none" for _, shadow, _ in styles) and all(image == "none" for _, _, image in styles)
    text = page.locator("#homeCal").inner_text()
    for word in ("실시간", "LIVE", "놓치지", "서둘러", "최신"):
        assert word not in text
    assert re.search(r"[☀-➿\U0001F300-\U0001FAFF]", text) is None   # no emoji
    context.close()
