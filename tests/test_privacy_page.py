"""개인정보처리방침 (privacy.html, owner 2026-11-08): a public page on every host, since Google's sign-in
consent screen needs its address on the site's own domain. Both languages carry every entry, the
facts it states match the code it describes, it loads nothing from a sign-in or database client, and it
fits a phone. Offline: every request outside the test host is refused."""
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest
from playwright.sync_api import sync_playwright

from sync_site_chrome import unstamped

ROOT = Path(__file__).resolve().parents[1]
HOST = "privacy.invalid"
PAGE = unstamped((ROOT / "privacy.html").read_text(encoding="utf-8"))   # without its ?v= content stamps
KO = json.loads((ROOT / "i18n/ko.json").read_text(encoding="utf-8"))
EN = json.loads((ROOT / "i18n/en.json").read_text(encoding="utf-8"))


def test_every_entry_exists_in_both_languages_and_is_used():
    ko = {k for k in KO if k.startswith("privacy.")}
    assert ko == {k for k in EN if k.startswith("privacy.")}
    used = set(re.findall(r'data-i18n(?:-html|-aria-key)?="(privacy\.[^"]+)"', PAGE))
    assert used == ko, (ko - used, used - ko)
    assert KO["title.privacy"].startswith("개인정보처리방침") and EN["title.privacy"].startswith("Privacy Policy")


def test_the_page_loads_no_sign_in_or_database_client():
    for needle in ("ggongbab-public-config", "babdoduk-auth", "createClient", "supabase-js", "supabase.co"):
        assert needle not in PAGE, needle
    scripts = re.findall(r'<script[^>]*src="([^"]+)"', PAGE)
    assert scripts == ["js/site.js"]


def test_the_facts_match_the_code_they_describe():
    tips = (ROOT / "supabase/migrations/009_ggongbab_tip_reports.sql").read_text(encoding="utf-8")
    assert "char_length(v_text) > 1000" in tips and "not between 0 and 3" in tips
    assert "1,000자" in KO["privacy.s1.tipItems"] and "3장" in KO["privacy.s1.tipItems"]
    assert "interval '1 day'" in tips and "하루" in KO["privacy.s3.i4"]
    # The ops PC's tips worker deletes a tip's photos 14 days after the owner's answer (docs/GGONGBAB_TIPS.md).
    assert "14일 뒤 그 제보의 사진을 지웁니다" in (ROOT / "docs/GGONGBAB_TIPS.md").read_text(encoding="utf-8")
    assert "14일" in KO["privacy.s3.i2"]
    # The site ships no analytics or tracking script, as section 6 says.
    for name in [p.name for p in ROOT.glob("*.html")] + [p.as_posix() for p in (ROOT / "js").glob("*.js")]:
        text = (ROOT / name).read_text(encoding="utf-8") if "/" not in name else Path(name).read_text(encoding="utf-8")
        for tracker in ("googletagmanager", "google-analytics", "gtag(", "va.vercel-scripts", "_vercel/insights"):
            assert tracker not in text, (name, tracker)


def test_the_policy_is_linked_from_my_babdoduk():
    if not (ROOT / "my.html").exists():
        pytest.skip("마이 밥도둑 is lab-only; production has no sign-in page yet")
    my = (ROOT / "my.html").read_text(encoding="utf-8")
    assert '<a href="privacy.html" data-i18n="my.privacyLink">개인정보처리방침</a>' in my


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        chrome = pw.chromium.launch(channel="chrome", headless=True)
        yield chrome
        chrome.close()


def open_page(browser, width, lang="ko"):
    context = browser.new_context(viewport={"width": width, "height": 900}, service_workers="block")
    context.add_init_script(f"localStorage.setItem('babdoduk-lang', '{lang}');")
    requests = []

    def handle(route):
        url = urlparse(route.request.url)
        requests.append(route.request.url)
        if url.hostname != HOST:
            return route.abort()
        path = unquote(url.path).lstrip("/")
        file = (ROOT / path).resolve()
        if file.is_file() and ROOT in file.parents:
            return route.fulfill(path=str(file))
        return route.fulfill(status=404, body="")

    context.route("**/*", handle)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(f"https://{HOST}/privacy.html", wait_until="networkidle")
    return context, page, errors, requests


@pytest.mark.parametrize("width", [360, 390, 768, 1440])
def test_the_page_fits_every_width(browser, width):
    context, page, errors, _ = open_page(browser, width)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert page.locator("h1").inner_text() == "개인정보처리방침"
    assert page.locator(".pv-sec").count() == 13
    # Painted, not just present: nothing (the site's fixed background canvas) covers the text.
    for selector in ("h1", "#s5 h2", ".pv-toc a"):
        assert page.evaluate("""(s) => { const el = document.querySelector(s); el.scrollIntoView({block: 'center', behavior: 'instant'});
            const r = el.getBoundingClientRect();
            return el.contains(document.elementFromPoint(r.left + Math.min(8, r.width / 2), r.top + r.height / 2)); }""",
            selector), selector
    assert errors == []
    context.close()


def test_english_and_the_table_of_contents(browser):
    context, page, errors, requests = open_page(browser, 390, lang="en")
    assert page.title() == EN["title.privacy"]
    assert page.locator("h1").inner_text() == "Privacy Policy"
    mail = page.locator('#s11 a[href^="mailto:"]')
    assert mail.get_attribute("href") == "mailto:joshualiuniv@gmail.com"
    page.locator('.pv-toc a[href="#s5"]').click()
    page.wait_for_function("() => location.hash === '#s5'")
    assert page.locator("#s5 h2").inner_text() == EN["privacy.s5.title"]
    page.locator("#langToggle").click()
    assert page.locator("h1").inner_text() == "개인정보처리방침"
    assert page.locator("#s5 h2").inner_text() == KO["privacy.s5.title"]
    assert not [r for r in requests if "supabase" in r]
    assert errors == []
    context.close()


def test_every_page_footer_links_the_policy():
    footer = (ROOT / "shared/footer.html").read_text(encoding="utf-8")
    link = '<a href="privacy.html" class="footer-apple-a footer-apple-privacy" data-i18n="footer.privacy">개인정보처리방침</a>'
    assert link in footer
    pages = [p for p in ROOT.glob("*.html") if 'class="site-footer"' in p.read_text(encoding="utf-8")]
    assert len(pages) >= 10
    for page in pages:
        assert link in page.read_text(encoding="utf-8"), page.name
    assert KO["footer.privacy"] == "개인정보처리방침"
    assert EN["footer.privacy"] == "Privacy Policy"
