"""The calendar lives on 마이 밥도둑 only (owner 2026-11-24: "로그인 시에만 그 기능이 첨부되도록", then "공유 삭제,
캘린더에 추가는 마이 밥도둑에서"). No listing on the food hub or the home calendar has a calendar or share button, for a
guest or for someone signed in, whatever an older visit left in this browser; the star saves with a short toast and
opens nothing (docs/CALENDAR_FEED.md). Synthetic data and a fixed clock (tests/test_ggongbab_live.py)."""
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
@pytest.mark.parametrize("signed_in", [False, True], ids=["guest", "signed-in"])
def test_no_calendar_or_share_on_the_hub(browser, ua, signed_in):  # noqa: F811
    # The old Safari page's address (?cal=1) only opens the listing now.
    context, page, errors = open_hub(browser, user_agent=ua, signed_in=signed_in, storage=OLD_GUEST, query="?e=lunch&cal=1")
    page.evaluate(HANDOFFS)
    downloads = []
    page.on("download", lambda d: downloads.append(d))
    lunch = card(page, "lunch")
    assert lunch.locator(".gg-card-toggle").get_attribute("aria-expanded") == "true"
    assert lunch.locator("[data-gg-share], [data-gg-cal], [data-gg-ics], [data-gg-gcal], .gg-cal, .gg-tool").count() == 0
    # The star saves with a toast and asks nothing about a calendar, even in a browser that once answered yes.
    lunch.locator(".gg-save").click()
    page.wait_for_timeout(400)
    assert page.locator(".gg-toast").inner_text() == "저장했어요"
    assert page.locator("#starCalAsk").count() == 0 and downloads == [] and page.evaluate("window.__handoffs || []") == []
    if not signed_in:
        assert [i["id"] for i in stored(page)["items"]] == ["lunch"]
        page.locator("[data-gg-saved]").click()
        assert page.locator("[data-gg-starcal], [data-gg-calopen]").count() == 0
        assert "캘린더" not in page.locator("#foodHubFree").inner_text()
    assert errors == []
    context.close()


@pytest.mark.parametrize("ua", [IPHONE, CHROME_IPHONE, ANDROID], ids=["safari", "iphone-chrome", "android"])
@pytest.mark.parametrize("signed_in", [False, True], ids=["guest", "signed-in"])
def test_no_calendar_or_share_on_the_home_calendar(browser, ua, signed_in):  # noqa: F811
    from tests.test_my_babdoduk import TOKEN_KEY
    storage = dict(OLD_GUEST, **({TOKEN_KEY: "{}"} if signed_in else {}))
    context, page, errors = open_home(browser, user_agent=ua, storage=storage)
    page.evaluate(HANDOFFS)
    downloads = []
    page.on("download", lambda d: downloads.append(d))
    page.locator('.hc-ev:has([data-hc-save="lunch"]) .hc-ev-btn').click()
    opened = page.locator(".hc-ev.is-open")
    assert opened.locator("[data-hc-share], [data-hc-cal], [data-hc-ics], [data-hc-gcal], .hc-cal-note").count() == 0
    assert "캘린더" not in opened.inner_text() and "공유" not in opened.inner_text()
    page.locator('[data-hc-save="lunch"]').click()
    toast = page.locator(".hc-toast")
    toast.wait_for(state="visible")
    assert toast.inner_text() == "저장했어요" and toast.get_attribute("aria-hidden") == "true"
    live = page.locator("#homeCalLive").inner_text()
    assert "저장했어요" in live and "캘린더" not in live
    assert page.locator("#starCalAsk").count() == 0 and downloads == [] and page.evaluate("window.__handoffs || []") == []
    assert errors == []
    context.close()
