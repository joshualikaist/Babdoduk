"""The star also adds to the calendar (owner 2026-11-11, docs/GGONGBAB_LIVE.md): a web page cannot write
into a phone's calendar by itself, so the first star asks once, and for visitors who said yes every later
star opens the calendar's own add screen (an .ics file with a 30-minute alert on Apple devices, Google
Calendar's add page elsewhere). The answer stays in this browser and can be changed in 저장한 꽁밥.
Synthetic data and a fixed clock (tests/test_ggongbab_live.py); every request off the test host is refused,
so the Google Calendar tab is only checked by its address."""
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from tests.test_ggongbab_live import browser, card, open_card, open_hub, stored  # noqa: F401  (browser is a fixture)
from tests.test_home_calendar_live import open_home

KEY = "babdoduk-star-calendar"
IPHONE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
          "Version/18.0 Mobile/15E148 Safari/604.1")
ANDROID = ("Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) "
           "Chrome/131.0.0.0 Mobile Safari/537.36")
KAKAO = ANDROID + " KAKAOTALK 11.0.0"


def google_tab(context):
    """Answers Google Calendar's add page with an empty page, so the new tab keeps its address offline."""
    context.route("https://calendar.google.com/**", lambda route: route.fulfill(status=200, content_type="text/html", body=""))


def pref(page):
    return page.evaluate(f"localStorage.getItem('{KEY}')")


def test_the_file_carries_a_30_minute_alert_and_the_route_follows_the_device(browser):  # noqa: F811
    context, page, errors = open_hub(browser)
    out = page.evaluate("""(uas) => {
      const L = window.BabdodukLive;
      const ev = {id: 'x', title: '점심', startAt: '2026-11-09T12:00:00+09:00', endAt: '2026-11-09T13:00:00+09:00',
                  location: {building: 'E11', room: '', name: ''}, food: {provided: 'true'}};
      return {ics: L.icsText(ev, {stamp: '2026-11-09T00:00:00Z'}),
              routes: uas.map((ua) => L.calendarRoute(ua))};
    }""", [IPHONE, ANDROID, KAKAO, "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/605.1.15",
           "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0",
           IPHONE.replace("Version/18.0 Mobile/15E148 Safari", "CriOS/131.0.0.0 Mobile/15E148 Safari")])
    ics = out["ics"]
    alarm = ics[ics.index("BEGIN:VALARM"):ics.index("END:VALARM")]
    assert "TRIGGER:-PT30M" in alarm and "ACTION:DISPLAY" in alarm and "DESCRIPTION:점심" in alarm
    assert ics.index("END:VALARM") < ics.index("END:VEVENT")
    assert out["routes"] == ["ics", "google", "manual", "ics", "google", "google"], "iPhone Chrome downloads .ics files"
    assert errors == []
    context.close()


def test_yes_opens_the_calendar_now_and_on_every_later_star(browser):  # noqa: F811
    context, page, errors = open_hub(browser, user_agent=ANDROID)
    google_tab(context)
    star = card(page, "lunch").locator(".gg-save")
    star.click()
    ask = page.locator("#starCalAsk")
    assert ask.get_attribute("role") == "dialog"
    assert page.locator("#starCalAskTitle").inner_text() == "별 누를 때 내 캘린더에도 넣을까요?"
    assert "30분 전" in page.locator("#starCalAskBody").inner_text()
    assert page.evaluate("document.activeElement.textContent") == "넣을게요"
    assert [i["id"] for i in stored(page)["items"]] == ["lunch"], "saved before the question is answered"
    with context.expect_page() as info:
        ask.locator(".starcal-yes").click()
    q = parse_qs(urlparse(info.value.url).query)
    assert urlparse(info.value.url).hostname == "calendar.google.com"
    assert q["text"] == ["lunch 행사"] and q["dates"] == ["20261109T030000Z/20261109T040000Z"]
    info.value.close()
    assert pref(page) == "on" and page.locator("#starCalAsk").count() == 0
    assert page.locator(".gg-toast").inner_text() == "새 창에서 저장을 눌러 주세요"  # copy cleanup, owner 2026-11-12
    assert page.evaluate("document.activeElement.getAttribute('data-gg-save')") == "lunch"
    # Later stars open it straight away, without asking again.
    with context.expect_page() as info:
        card(page, "wed").locator(".gg-save").click()
    assert parse_qs(urlparse(info.value.url).query)["text"] == ["wed 행사"]
    info.value.close()
    assert page.locator("#starCalAsk").count() == 0
    assert page.locator(".gg-toast").inner_text().startswith("저장했어요")
    # Removing a star opens nothing.
    pages = len(context.pages)
    card(page, "wed").locator(".gg-save").click()
    assert len(context.pages) == pages and page.locator("#starCalAsk").count() == 0
    # The switch in 저장한 꽁밥 turns it off again.
    page.locator("[data-gg-saved]").click()
    switch = page.locator("[data-gg-starcal]")
    assert switch.get_attribute("aria-pressed") == "true" and "켜짐" in switch.inner_text()
    switch.click()
    assert pref(page) == "off" and page.locator("[data-gg-starcal]").get_attribute("aria-pressed") == "false"
    assert page.evaluate("document.activeElement.hasAttribute('data-gg-starcal')")
    card(page, "noend").locator(".gg-save").click()
    assert len(context.pages) == pages and page.locator("#starCalAsk").count() == 0
    assert errors == []
    context.close()


def test_no_escape_and_listings_without_a_time(browser):  # noqa: F811
    context, page, errors = open_hub(browser, user_agent=ANDROID)
    # A giveaway listed only by its sign-up deadline has no time to add: no question.
    card(page, "gift").locator(".gg-save").click()
    assert page.locator("#starCalAsk").count() == 0 and pref(page) is None
    # Escape answers nothing, so the next star asks again.
    card(page, "lunch").locator(".gg-save").click()
    page.locator("#starCalAsk").wait_for()
    page.keyboard.press("Escape")
    assert page.locator("#starCalAsk").count() == 0 and pref(page) is None
    assert page.evaluate("document.activeElement.getAttribute('data-gg-save')") == "lunch"
    pages = len(context.pages)
    card(page, "wed").locator(".gg-save").click()
    page.locator("#starCalAsk .starcal-no").click()
    assert pref(page) == "off" and len(context.pages) == pages
    assert page.locator(".gg-toast").inner_text() == "캘린더에는 넣지 않을게요"  # copy cleanup, owner 2026-11-12
    card(page, "noend").locator(".gg-save").click()
    assert page.locator("#starCalAsk").count() == 0
    assert errors == []
    context.close()


def test_an_iphone_gets_the_file_and_kakaotalk_gets_the_buttons(browser):  # noqa: F811
    context, page, errors = open_hub(browser, user_agent=IPHONE, storage={KEY: "on"})
    with page.expect_download() as info:
        card(page, "lunch").locator(".gg-save").click()
    text = Path(info.value.path()).read_text(encoding="utf-8")
    assert info.value.suggested_filename == "babdoduk-2026-11-09.ics"
    assert "DTSTART:20261109T030000Z" in text and "TRIGGER:-PT30M" in text
    assert page.locator(".gg-toast").inner_text() == "저장했어요 · 추가를 눌러 주세요"  # copy cleanup, owner 2026-11-12
    assert errors == []
    context.close()

    context, page, errors = open_hub(browser, user_agent=KAKAO, storage={KEY: "on"})
    pages = len(context.pages)
    card(page, "lunch").locator(".gg-save").click()
    assert len(context.pages) == pages
    assert "카카오톡에선 바로 안 돼요" in page.locator(".gg-toast").inner_text()  # copy cleanup, owner 2026-11-12
    assert errors == []
    context.close()


def test_the_home_calendar_star_asks_and_adds_too(browser):  # noqa: F811
    context, page, errors = open_home(browser, user_agent=IPHONE)
    page.locator('[data-hc-save="lunch"]').click()
    ask = page.locator("#starCalAsk")
    ask.wait_for()
    assert page.evaluate("document.activeElement.textContent") == "넣을게요"
    with page.expect_download() as info:
        ask.locator(".starcal-yes").click()
    assert "TRIGGER:-PT30M" in Path(info.value.path()).read_text(encoding="utf-8")
    assert pref(page) == "on"
    assert page.locator("#homeCalLive").inner_text() == "추가를 눌러 주세요"  # copy cleanup, owner 2026-11-12
    assert page.evaluate("document.activeElement.getAttribute('data-hc-save')") == "lunch"
    # Saved on the home calendar, the answer holds on the hub too: its next star opens the file at once.
    page.goto(page.url.replace("index.html", "ggongbab.html"), wait_until="networkidle")
    page.locator(".gg-card").first.wait_for()
    with page.expect_download():
        card(page, "wed").locator(".gg-save").click()
    assert page.locator("#starCalAsk").count() == 0
    assert errors == []
    context.close()


def test_the_question_fits_a_phone_in_both_languages(browser):  # noqa: F811
    for lang, title in (("ko", "별 누를 때 내 캘린더에도 넣을까요?"), ("en", "Add starred events to your calendar too?")):
        context, page, errors = open_hub(browser, user_agent=ANDROID, lang=lang, size=(360, 740))
        card(page, "lunch").locator(".gg-save").click()
        ask = page.locator("#starCalAsk")
        assert page.locator("#starCalAskTitle").inner_text() == title
        box = ask.bounding_box()
        assert box["x"] >= 16 and box["x"] + box["width"] <= 344 and box["y"] + box["height"] <= 740
        for button in (".starcal-yes", ".starcal-no"):
            b = ask.locator(button).bounding_box()
            assert b["height"] >= 44
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert errors == []
        context.close()


def test_the_same_listing_never_goes_into_the_calendar_twice(browser):  # noqa: F811
    """Owner 2026-11-19: two events saved to the iPhone calendar, then a third, and the first two showed twice
    ("동일한 행사가 두개 뜨는거지. 그거는 불필요한거잖아"). A calendar file always makes a new entry, so this
    browser remembers what it sent: the star does not send a listing again, a button asks for a second tap."""
    context, page, errors = open_hub(browser, user_agent=IPHONE, storage={KEY: "on"})
    downloads = []
    page.on("download", lambda d: downloads.append(d))
    star = card(page, "lunch").locator(".gg-save")
    with page.expect_download():
        star.click()
    assert page.evaluate("JSON.parse(localStorage.getItem('babdoduk-calendar-sent'))") == {"lunch": "2026-11-09T12:00:00+09:00"}
    star.click()           # unstar
    star.click()           # and star again: nothing new for the calendar
    page.wait_for_timeout(300)
    assert len(downloads) == 1
    assert page.locator(".gg-toast").inner_text() == "저장했어요 · 이미 캘린더에 넣은 꽁밥이에요"
    # Another listing still goes in once.
    with page.expect_download():
        card(page, "wed").locator(".gg-save").click()
    # The card's own button asks first, then sends on the second tap.
    open_card(page, "lunch")
    card(page, "lunch").locator("[data-gg-cal]").click()
    card(page, "lunch").locator("[data-gg-ics]").click()
    page.wait_for_timeout(300)
    assert len(downloads) == 2
    assert page.locator(".gg-toast").inner_text() == "이미 캘린더에 넣은 꽁밥이에요 · 한 번 더 누르면 또 넣어요"
    with page.expect_download():
        card(page, "lunch").locator("[data-gg-ics]").click()
    assert errors == []
    context.close()


def test_a_listing_whose_time_moved_goes_in_again_with_a_note(browser):  # noqa: F811
    sent = '{"lunch": "2026-11-08T12:00:00+09:00"}'
    context, page, errors = open_hub(browser, user_agent=IPHONE, storage={KEY: "on", "babdoduk-calendar-sent": sent})
    with page.expect_download() as info:
        card(page, "lunch").locator(".gg-save").click()
    assert "DTSTART:20261109T030000Z" in Path(info.value.path()).read_text(encoding="utf-8")
    assert page.locator(".gg-toast").inner_text() == "저장했어요 · 추가를 눌러 주세요 · 시간이 바뀌었어요 · 캘린더의 예전 일정은 지워 주세요"
    assert page.evaluate("JSON.parse(localStorage.getItem('babdoduk-calendar-sent')).lunch") == "2026-11-09T12:00:00+09:00"
    assert errors == []
    context.close()
