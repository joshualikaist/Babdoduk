"""The calendar is for signed-in visitors only (owner 2026-11-24: "로그인을 하지 않으면 그런 기능을 아예 주지 말고,
로그인 시에만 그 기능이 첨부되도록"). A guest gets no calendar button and no calendar question anywhere, whatever an
older visit left in this browser; signed in, an iPhone points to the one calendar connection of 마이 밥도둑
(tests/test_push_alerts.py) and other devices get Google Calendar's add page and the listing's file, once per
listing (docs/CALENDAR_FEED.md). Synthetic data and a fixed clock (tests/test_ggongbab_live.py); every request
off the test host is refused, so the Google Calendar tab is only checked by its address."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.test_ggongbab_live import browser, card, open_card, open_hub, stored  # noqa: F401  (browser is a fixture)
from tests.test_home_calendar_live import open_home

ROOT = Path(__file__).resolve().parents[1]
IPHONE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
          "Version/18.0 Mobile/15E148 Safari/604.1")
ANDROID = ("Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) "
           "Chrome/131.0.0.0 Mobile Safari/537.36")
KAKAO = ANDROID + " KAKAOTALK 11.0.0"
CHROME_IPHONE = IPHONE.replace("Version/18.0 Mobile/15E148 Safari", "CriOS/131.0.0.0 Mobile/15E148 Safari")
PC = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
# What older visits left in a guest's browser: the star's calendar answer and a sent listing.
OLD_GUEST = {"babdoduk-star-calendar": "on", "babdoduk-calendar-sent": '{"wed": "2026-11-11T17:00:00+09:00"}'}
# Records any link to another app the page clicks (none is expected) and stops it there.
HANDOFFS = """() => document.addEventListener('click', (e) => {
  const a = e.target && e.target.closest && e.target.closest('a');
  if (a && !/^https?:/.test(a.href)) { e.preventDefault(); (window.__handoffs = window.__handoffs || []).push(a.href); }
}, true)"""
ICS = r"""
const fs = require('fs'), vm = require('vm');
const window = { navigator: { userAgent: '' }, document: {}, localStorage: null, location: { origin: '' } };
const context = vm.createContext({ window, URLSearchParams, Date, Intl, Math, JSON, encodeURIComponent, unescape, escape, console });
for (const f of ['js/ggongbab-select.js', 'js/ggongbab-live.js']) vm.runInContext(fs.readFileSync(f, 'utf8'), context);
const ev = {id: 'x', title: '점심', startAt: '2026-11-09T12:00:00+09:00', endAt: '2026-11-09T13:00:00+09:00',
            location: {building: 'E11', room: '', name: ''}, food: {provided: 'true'}};
console.log(JSON.stringify(window.BabdodukLive.icsText(ev, {stamp: '2026-11-09T00:00:00Z'})));
"""


def test_the_file_carries_a_30_minute_alert():
    """The file a signed-in computer or Android phone downloads keeps the 30-minute alert (owner 2026-11-11)."""
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    out = subprocess.run(["node", "-e", ICS], cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    ics = json.loads(out.stdout)
    alarm = ics[ics.index("BEGIN:VALARM"):ics.index("END:VALARM")]
    assert "TRIGGER:-PT30M" in alarm and "ACTION:DISPLAY" in alarm and "DESCRIPTION:점심" in alarm
    assert ics.index("END:VALARM") < ics.index("END:VEVENT")


@pytest.mark.parametrize("ua", [IPHONE, CHROME_IPHONE, ANDROID, KAKAO, PC], ids=["safari", "iphone-chrome", "android", "kakao", "pc"])
def test_a_guest_gets_no_calendar_on_the_hub(browser, ua):  # noqa: F811
    # The old Safari page's address (?cal=1) only opens the listing now.
    context, page, errors = open_hub(browser, user_agent=ua, storage=OLD_GUEST, query="?e=lunch&cal=1")
    page.evaluate(HANDOFFS)
    downloads = []
    page.on("download", lambda d: downloads.append(d))
    lunch = card(page, "lunch")
    assert lunch.locator(".gg-card-toggle").get_attribute("aria-expanded") == "true"
    assert lunch.locator("[data-gg-share]").count() == 1 and lunch.locator("[data-gg-cal], .gg-cal").count() == 0
    # The star saves and asks nothing about a calendar, even in a browser that once answered yes.
    lunch.locator(".gg-save").click()
    page.wait_for_timeout(400)
    assert page.locator(".gg-toast").inner_text() == "저장했어요"
    assert page.locator("#starCalAsk").count() == 0 and downloads == [] and page.evaluate("window.__handoffs || []") == []
    assert [i["id"] for i in stored(page)["items"]] == ["lunch"]
    page.locator("[data-gg-saved]").click()
    assert page.locator("[data-gg-starcal], [data-gg-calopen]").count() == 0
    assert "캘린더" not in page.locator("#foodHubFree").inner_text()
    assert errors == []
    context.close()


@pytest.mark.parametrize("ua", [IPHONE, CHROME_IPHONE, ANDROID], ids=["safari", "iphone-chrome", "android"])
def test_a_guest_gets_no_calendar_on_the_home_calendar(browser, ua):  # noqa: F811
    context, page, errors = open_home(browser, user_agent=ua, storage=OLD_GUEST)
    page.evaluate(HANDOFFS)
    downloads = []
    page.on("download", lambda d: downloads.append(d))
    page.locator('.hc-ev:has([data-hc-save="lunch"]) .hc-ev-btn').click()
    opened = page.locator(".hc-ev.is-open")
    assert opened.locator("[data-hc-share]").count() == 1
    assert opened.locator("[data-hc-cal], [data-hc-ics], [data-hc-gcal]").count() == 0
    page.locator('[data-hc-save="lunch"]').click()
    page.wait_for_timeout(400)
    live = page.locator("#homeCalLive").inner_text()
    assert "저장했어요" in live and "캘린더" not in live
    assert page.locator("#starCalAsk").count() == 0 and downloads == [] and page.evaluate("window.__handoffs || []") == []
    assert errors == []
    context.close()


def test_signed_in_a_phone_gets_google_and_the_file_once_per_listing(browser):  # noqa: F811
    """Owner 2026-11-19: the same event twice in the calendar is never wanted, so a button asks for a second tap
    for a listing this browser already sent; a listing whose time moved goes in again with a note."""
    sent = '{"wed": "2026-11-10T17:00:00+09:00"}'
    context, page, errors = open_hub(browser, user_agent=ANDROID, signed_in=True, storage={"babdoduk-calendar-sent": sent})
    downloads = []
    page.on("download", lambda d: downloads.append(d))
    # The star saves to the account and opens nothing.
    card(page, "lunch").locator(".gg-save").click()
    page.wait_for_timeout(400)
    assert page.locator("#starCalAsk").count() == 0 and downloads == []
    open_card(page, "lunch")
    card(page, "lunch").locator("[data-gg-cal]").click()
    panel = card(page, "lunch").locator(".gg-cal")
    assert panel.locator("a[data-gg-gcal]").get_attribute("href").startswith("https://calendar.google.com/calendar/render?")
    with page.expect_download() as info:
        panel.locator("[data-gg-ics]").click()
    assert "TRIGGER:-PT30M" in Path(info.value.path()).read_text(encoding="utf-8")
    assert page.locator(".gg-toast").inner_text() == "캘린더 파일을 받았어요"
    panel.locator("[data-gg-ics]").click()
    page.wait_for_timeout(300)
    assert len(downloads) == 1
    assert page.locator(".gg-toast").inner_text() == "이미 캘린더에 넣은 꽁밥이에요 · 한 번 더 누르면 또 넣어요"
    with page.expect_download():
        panel.locator("[data-gg-ics]").click()
    # A listing sent for another start goes in again, with a note to delete the old entry.
    open_card(page, "wed")
    card(page, "wed").locator("[data-gg-cal]").click()
    with page.expect_download():
        card(page, "wed").locator("[data-gg-ics]").click()
    assert page.locator(".gg-toast").inner_text() == "캘린더 파일을 받았어요 · 시간이 바뀌었어요 · 캘린더의 예전 일정은 지워 주세요"
    assert page.evaluate("JSON.parse(localStorage.getItem('babdoduk-calendar-sent')).wed") == "2026-11-11T17:00:00+09:00"
    assert errors == []
    context.close()


@pytest.mark.parametrize("ua", [ANDROID, CHROME_IPHONE], ids=["android", "iphone-chrome"])
def test_signed_in_the_home_calendar_offers_the_calendar_too(browser, ua):  # noqa: F811
    from tests.test_my_babdoduk import TOKEN_KEY
    context, page, errors = open_home(browser, user_agent=ua, storage={TOKEN_KEY: "{}"})
    page.locator('.hc-ev:has([data-hc-save="lunch"]) .hc-ev-btn').click()
    page.locator('[data-hc-cal="lunch"]').click()
    opened = page.locator(".hc-ev.is-open")
    if ua == ANDROID:
        assert opened.locator("[data-hc-gcal]").count() == 1 and opened.locator("[data-hc-ics]").count() == 1
    else:
        # On an iPhone the one connection of 마이 밥도둑 takes every star: no file or add page beside it.
        assert "별을 누르면 연결한 아이폰 캘린더에 들어가요." in opened.locator(".hc-cal-note").inner_text()
        assert opened.locator("[data-hc-gcal], [data-hc-ics]").count() == 0
        assert opened.locator(".hc-cal-note a").get_attribute("href") == "my.html#myCal"
    assert errors == []
    context.close()
