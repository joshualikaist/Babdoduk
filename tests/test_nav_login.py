"""The sign-in entry (owner 2026-11-10; on production since owner 2026-11-11): every page's top bar
carries a person icon beside Instagram that opens my.html, on every host. It is a named 44 px link in both
languages, says 마이 밥도둑 once this browser holds a sign-in, and fits a phone. Offline: the pages are
served from this checkout under the tested host name; every other request is refused."""
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
LAB = "babdoduk-lab.vercel.app"


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        chrome = pw.chromium.launch(channel="chrome", headless=True)
        yield chrome
        chrome.close()


def open_page(browser, host, path, width=390, lang="ko", signed_in=False):
    context = browser.new_context(viewport={"width": width, "height": 800}, service_workers="block")
    init = f"localStorage.setItem('babdoduk-lang', '{lang}');"
    if signed_in:
        init += "localStorage.setItem('sb-myjglfynhnptlclawlcc-auth-token', '{}');"
    context.add_init_script(init)

    def handle(route):
        url = urlparse(route.request.url)
        if url.hostname != host:
            return route.abort()
        file = (ROOT / unquote(url.path).lstrip("/")).resolve()
        if not (file.is_file() and ROOT in file.parents):
            return route.fulfill(status=404, body="")
        return route.fulfill(path=str(file))

    context.route("**/*", handle)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(f"https://{host}/{path}", wait_until="load")
    return context, page, errors


HOSTS = [LAB, "www.babdodukms.com"]


@pytest.mark.parametrize("path", ["index.html", "ggongbab.html", "event.html", "privacy.html"])
@pytest.mark.parametrize("width", [360, 1440])
@pytest.mark.parametrize("host", HOSTS)
def test_the_bar_opens_the_sign_in_page(browser, host, path, width):
    context, page, errors = open_page(browser, host, path, width)
    icon = page.locator("#navMy")
    assert icon.count() == 1 and icon.get_attribute("href") == "my.html"
    assert icon.get_attribute("aria-label") == "로그인"
    box = icon.bounding_box()
    assert box and box["width"] >= 44 and box["height"] >= 44
    insta = page.locator("#navInstagram").bounding_box()
    assert abs(box["y"] - insta["y"]) < 2 and box["x"] > insta["x"], "right beside Instagram"
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    # Nothing in the bar overlaps the icon.
    assert page.evaluate("""() => { const r = document.getElementById('navMy').getBoundingClientRect();
        const el = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        return document.getElementById('navMy').contains(el); }""")
    icon.click()
    page.wait_for_url(f"https://{host}/my.html")
    assert page.locator("#navMy").get_attribute("aria-current") == "page"
    assert errors == []
    context.close()


def test_english_and_signed_in_names(browser):
    context, page, errors = open_page(browser, LAB, "index.html", lang="en")
    assert page.locator("#navMy").get_attribute("aria-label") == "Sign in"
    page.locator("#langToggle").click()
    assert page.locator("#navMy").get_attribute("aria-label") == "로그인"
    context.close()
    context, page, errors = open_page(browser, LAB, "index.html", signed_in=True)
    assert page.locator("#navMy").get_attribute("aria-label") == "마이 밥도둑"
    assert errors == []
    context.close()


@pytest.mark.parametrize("host", ["www.babdodukms.com", "babdoduk.vercel.app"])
def test_production_hosts_carry_the_sign_in_entry(browser, host):
    context, page, errors = open_page(browser, host, "index.html")
    assert page.locator("#navMy").count() == 1 and page.locator("#navMy").get_attribute("href") == "my.html"
    # The shared nav HTML itself is unchanged: js/site.js adds the icon, so the chrome baselines stay.
    assert 'href="my.html"' not in (ROOT / "shared/nav.html").read_text(encoding="utf-8")
    assert errors == []
    context.close()
