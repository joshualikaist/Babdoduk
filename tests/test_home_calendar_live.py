"""꽁밥 LIVE on the home calendar (owner 2026-11-08: "캘린더에도 누르면 저장되도록", docs/GGONGBAB_LIVE.md):
a ☆ on each listing still to come saves it into the same browser store as the hub, without opening
the row; the opened listing shares its hub link (share sheet, then clipboard, then text to copy).
Past listings have neither. Synthetic data and a fixed clock; share and clipboard are stubbed."""
import json
from urllib.parse import unquote, urlparse

import pytest
from playwright.sync_api import sync_playwright

from tests.test_ggongbab_live import ARCHIVE, LIVE, NOW, ROOT, SAVED_KEY

HOST = "home-live.invalid"


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        chrome = pw.chromium.launch(channel="chrome", headless=True)
        yield chrome
        chrome.close()


def open_home(browser, share=None, clipboard="ok", lang="ko", width=390, user_agent=None, storage=None):
    extra = {"user_agent": user_agent} if user_agent else {}
    context = browser.new_context(viewport={"width": width, "height": 900}, timezone_id="Asia/Seoul", service_workers="block",
                                  accept_downloads=True, **extra)
    init = [f"localStorage.setItem('babdoduk-lang', '{lang}');", "localStorage.setItem('babdoduk-notice-ggongbab-live', '1');",
            "window.__shared = []; window.__copied = [];"]
    for key, value in (storage or {}).items():
        init.append(f"localStorage.setItem({json.dumps(key)}, {json.dumps(value)});")
    if share == "native":
        init.append("navigator.share = (d) => { window.__shared.push(d); return Promise.resolve(); };")
    else:
        init.append("try { delete Navigator.prototype.share; } catch (e) {} navigator.share = undefined;")
    if clipboard == "ok":
        init.append("Object.defineProperty(navigator, 'clipboard', {value: {writeText: (t) => { window.__copied.push(t); return Promise.resolve(); }}});")
    else:
        init.append("Object.defineProperty(navigator, 'clipboard', {value: {writeText: () => Promise.reject(new Error('no'))}});")
    context.add_init_script(" ".join(init))

    def handle(route):
        url = urlparse(route.request.url)
        if url.hostname != HOST:
            return route.abort()
        path = unquote(url.path).lstrip("/") or "index.html"
        if path == "data/ggongbab/latest.json":
            return route.fulfill(json=LIVE)
        if path == "data/ggongbab/archive/index.json":
            return route.fulfill(json=ARCHIVE)
        if path == "js/ggongbab-public-config.js":
            return route.fulfill(content_type="application/javascript", body="window.BABDODUK_PUBLIC_FEED_CONFIG = {};")
        if path.startswith("data/ggongbab/"):
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
    page.goto(f"https://{HOST}/index.html", wait_until="networkidle")
    page.locator(".hc-ev").first.wait_for()
    return context, page, errors


def stored(page):
    return page.evaluate(f"JSON.parse(localStorage.getItem('{SAVED_KEY}') || 'null')")


def test_the_star_saves_without_opening_and_the_hub_shows_it(browser):
    context, page, errors = open_home(browser)
    lunch = page.locator('.hc-ev:has([data-hc-save="lunch"])')
    star = page.locator('[data-hc-save="lunch"]')
    assert star.get_attribute("aria-pressed") == "false" and star.get_attribute("aria-label") == "lunch 행사 저장"
    box = star.bounding_box()
    assert box["width"] >= 44 and box["height"] >= 44
    star.click()
    assert page.locator('[data-hc-save="lunch"]').get_attribute("aria-pressed") == "true"
    assert lunch.locator(".hc-ev-btn").get_attribute("aria-expanded") == "false", "the star does not open the row"
    # The first star asks once whether stars should also add to the calendar (tests/test_star_calendar.py);
    # closing the question with Escape answers nothing and gives the focus back to the star.
    page.locator("#starCalAsk").wait_for()
    page.keyboard.press("Escape")
    assert page.locator("#starCalAsk").count() == 0
    assert page.evaluate("document.activeElement.getAttribute('data-hc-save')") == "lunch"
    assert "저장했어요" in page.locator("#homeCalLive").inner_text()
    assert [i["id"] for i in stored(page)["items"]] == ["lunch"]
    page.goto(f"https://{HOST}/ggongbab.html", wait_until="networkidle")
    page.locator(".gg-card").first.wait_for()
    assert page.locator('.gg-card[data-id="lunch"] .gg-save').get_attribute("aria-pressed") == "true"
    assert page.locator("#ggSaved .gg-saved-n").inner_text() == "1"
    page.goto(f"https://{HOST}/index.html", wait_until="networkidle")
    page.locator('[data-hc-save="lunch"]').click()
    assert page.locator('[data-hc-save="lunch"]').get_attribute("aria-pressed") == "false"
    assert stored(page)["items"] == []
    assert errors == []
    context.close()


def test_past_listings_have_no_star_or_share(browser):
    context, page, errors = open_home(browser)
    page.locator('td[data-date="2026-11-05"]').click()
    page.locator(".hc-ev.is-past").first.wait_for()
    assert page.locator(".hc-ev.is-past [data-hc-save]").count() == 0
    page.locator(".hc-ev.is-past .hc-ev-btn").first.click()
    assert page.locator(".hc-ev.is-past [data-hc-share]").count() == 0
    assert errors == []
    context.close()


def test_share_uses_the_sheet_then_the_clipboard_then_text_to_copy(browser):
    context, page, errors = open_home(browser, share="native")
    page.locator('.hc-ev:has([data-hc-save="lunch"]) .hc-ev-btn').click()
    page.locator('[data-hc-share="lunch"]').click()
    page.wait_for_function("() => window.__shared.length === 1")
    shared = page.evaluate("window.__shared[0]")
    assert shared["url"] == f"https://{HOST}/ggongbab.html?e=lunch" and "lunch 행사" in shared["text"]
    assert "11월 9일" in shared["text"] or "11/9" in shared["text"] or "9" in shared["text"]
    context.close()

    context, page, errors = open_home(browser)
    page.locator('.hc-ev:has([data-hc-save="lunch"]) .hc-ev-btn').click()
    page.locator('[data-hc-share="lunch"]').click()
    page.wait_for_function("() => window.__copied.length === 1")
    assert page.evaluate("window.__copied[0]").endswith(f"https://{HOST}/ggongbab.html?e=lunch")
    page.locator(".hc-ev-note").wait_for()
    assert page.locator(".hc-ev-note").inner_text() == "링크를 복사했어요"
    context.close()

    context, page, errors = open_home(browser, clipboard="fail", lang="en")
    page.locator('.hc-ev:has([data-hc-save="lunch"]) .hc-ev-btn').click()
    share = page.locator('[data-hc-share="lunch"]')
    assert share.inner_text().strip().endswith("Share")
    share.click()
    page.locator(".hc-ev-copy textarea").wait_for()
    assert page.locator(".hc-ev-copy textarea").input_value().endswith("ggongbab.html?e=lunch")
    assert "Press and hold to copy" in page.locator(".hc-ev-copy").inner_text()
    assert errors == []
    context.close()


@pytest.mark.parametrize("width", [360, 1440])
def test_the_star_fits_at_every_width(browser, width):
    context, page, errors = open_home(browser, width=width)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    star = page.locator('[data-hc-save="lunch"]').bounding_box()
    row = page.locator('.hc-ev:has([data-hc-save="lunch"]) .hc-ev-row').bounding_box()
    assert star["x"] + star["width"] <= row["x"] + row["width"] + 8
    assert errors == []
    context.close()


def test_an_opened_listing_adds_itself_to_a_calendar(browser):
    context = None
    context, page, errors = open_home(browser)
    page.locator('.hc-ev:has([data-hc-save="lunch"]) .hc-ev-btn').click()
    assert page.locator('.hc-ev.is-open a.hc-ev-cal').count() == 0, "closed, the choice holds no link"
    toggle = page.locator('[data-hc-cal="lunch"]')
    assert toggle.get_attribute("aria-expanded") == "false"
    toggle.click()
    assert page.locator('[data-hc-cal="lunch"]').get_attribute("aria-expanded") == "true"
    assert page.evaluate("document.activeElement.getAttribute('data-hc-cal')") == "lunch"
    google = page.locator('.hc-ev.is-open a.hc-ev-cal')
    href = google.get_attribute("href")
    assert href.startswith("https://calendar.google.com/calendar/render?") and "action=TEMPLATE" in href
    assert "ctz=Asia%2FSeoul" in href and "20261109T030000Z%2F20261109T040000Z" in href
    assert "minical" in page.locator(".hc-ev.is-open .hc-ev-calnote").inner_text()
    with page.expect_download() as info:
        page.locator('[data-hc-ics="lunch"]').click()
    download = info.value
    assert download.suggested_filename == "babdoduk-2026-11-09.ics"
    text = open(download.path(), encoding="utf-8").read()
    assert "DTSTART:20261109T030000Z" in text and "ggongbab.html?e=lunch" in text.replace("\r\n ", "")
    assert errors == []
    context.close()
