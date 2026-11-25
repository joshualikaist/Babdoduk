"""가상 평가단 page (panel.html, lab only; docs/PANEL.md): renders the panel's conversation as text."""
import json
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
HOST = "babdoduk-lab.vercel.app"
REPORT = {
    "run": {"at": "2026-11-25T21:00:00+09:00", "base": "https://babdoduk-lab.vercel.app", "pages": 10, "views": 30},
    "overall": "전체적으로 깔끔하지만 휴대폰에서 누르는 곳이 작아요.",
    "members": [
        {"id": "designer", "name": "디자이너", "emoji": "🎨", "role": "시각 디자인과 사용성"},
        {"id": "developer", "name": "개발자", "emoji": "🛠️", "role": "속도, 오류, 접근성"},
        {"id": "critic", "name": "비판자", "emoji": "🧐", "role": "증거 확인과 순위"},
    ],
    "summary": {"designer": "홈의 첫 화면이 분명해요."},
    "top": ["g1", "g2"],
    "threads": [
        {"id": "g1", "title": "꽁밥 카드의 저장 버튼이 작아요", "severity": 3, "verdict": "accept", "by": ["designer", "developer"],
         "page": "ggongbab.html", "device": "iphone", "shot": "data/panel/shots/ggongbab-iphone.webp",
         "fix": "버튼을 44px로 키우기", "ask": "",
         "messages": [
             {"from": "designer", "kind": "finding", "text": "저장 버튼이 36px이에요.\n\n엄지로 누르기 어려워요."},
             {"from": "critic", "kind": "verdict", "text": "facts.json에서 확인했어요. 인정해요."}]},
        {"id": "g2", "title": "<img src=x onerror=alert(1)> 제목", "severity": 1, "verdict": "reject", "by": ["developer"],
         "page": "index.html", "device": "desktop", "shot": "https://evil.example/x.png", "fix": "원래 안", "ask": "",
         "decision": "반대가 맞아서 고치지 않아요.",
         "messages": [{"from": "developer", "kind": "finding", "text": "<b>굵게</b>"},
                      {"from": "critic", "kind": "verdict", "text": "증거와 달라요. 기각해요."}]},
    ],
}


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        chrome = pw.chromium.launch(channel="chrome", headless=True)
        yield chrome
        chrome.close()


def open_panel(browser, report=REPORT, width=390, lang="ko"):
    context = browser.new_context(viewport={"width": width, "height": 900}, service_workers="block")
    context.add_init_script(f"localStorage.setItem('babdoduk-lang', '{lang}'); localStorage.setItem('babdoduk-nocount', '1');")
    errors = []

    def handle(route):
        url = urlparse(route.request.url)
        if url.hostname != HOST:
            return route.abort()
        name = unquote(url.path).lstrip("/")
        if name == "data/panel/latest.json":
            return route.fulfill(status=200 if report is not None else 404, body=json.dumps(report or {}),
                                 content_type="application/json")
        if name.startswith(("data/", "api/")):
            return route.fulfill(status=404, body="")
        file = (ROOT / name).resolve()
        if file.is_file() and ROOT in file.parents:
            return route.fulfill(path=str(file))
        return route.fulfill(status=404, body="")

    context.route("**/*", handle)
    page = context.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"https://{HOST}/panel.html")
    page.wait_for_function("document.getElementById('pnApp').dataset.state !== 'loading'")
    return context, page, errors


def test_the_top_list_members_and_the_accepted_conversation(browser):
    context, page, errors = open_panel(browser)
    app = page.locator("#pnApp")
    assert app.get_attribute("data-state") == "ready"
    text = app.inner_text()
    assert page.locator(".pn-meta").inner_text().startswith("11월 25일 21:00 평가")
    assert "지적 2개 (인정 1, 기각 1)" in text
    assert "먼저 고칠 것" in text and "말한 평가자: 디자이너, 개발자" in text and "고칠 방법: 버튼을 44px로 키우기" in text
    assert page.locator(".pn-thread").count() == 1, "accepted threads show first"
    assert "토론 후 결론: 반대가 맞아서 고치지 않아요." in text and "원래 안" not in text
    page.locator(".pn-top-link").first.click()
    assert page.locator("#g1").evaluate("d => d.open")
    bubbles = page.locator("#g1 .pn-msg")
    assert bubbles.count() == 2 and page.locator("#g1 .pn-msg--critic").count() == 1
    assert page.locator("#g1 .pn-text").count() == 3, "blank lines split paragraphs"
    assert page.locator("#g1 .pn-shot img").get_attribute("src") == "data/panel/shots/ggongbab-iphone.webp"
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert errors == []
    context.close()


def test_filters_are_pressed_buttons_and_text_stays_text(browser):
    context, page, errors = open_panel(browser)
    rejected = page.locator(".pn-chip", has_text="기각")
    rejected.click()
    assert rejected.get_attribute("aria-pressed") == "true"
    assert page.evaluate("document.activeElement.dataset.key") == "v-reject"
    assert page.locator(".pn-thread").count() == 1
    assert page.locator("#g2 img").count() == 0, "a shot outside data/panel/shots is never loaded"
    page.locator("#g2 summary").click()
    assert "<b>굵게</b>" in page.locator("#g2 .pn-text").first.inner_text()
    assert "<img src=x onerror=alert(1)> 제목" in page.locator("#g2 .pn-thread-title").inner_text()
    page.locator(".pn-chip", has_text="전체").click()
    page.locator(".pn-chip", has_text="개발자").click()
    assert page.locator(".pn-thread").count() == 2
    assert page.locator(".pn-count").inner_text() == "대화 2개"
    for chip in page.locator(".pn-chip").all():
        assert chip.bounding_box()["height"] >= 44
    assert errors == []
    context.close()


@pytest.mark.parametrize("report, state", [(None, "off"), ({"run": {}, "members": [], "threads": []}, "empty"),
                                           ({"threads": "x"}, "off")])
def test_missing_empty_or_broken_data(browser, report, state):
    context, page, errors = open_panel(browser, report=report)
    assert page.locator("#pnApp").get_attribute("data-state") == state
    assert errors == []
    context.close()


def test_english_chrome_and_widths(browser):
    for width in (360, 768, 1440):
        context, page, errors = open_panel(browser, width=width, lang="en")
        text = page.locator("#pnApp").inner_text()
        assert "Fix first" in text and "Raised by" in text
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), width
        assert errors == []
        context.close()


def test_the_page_is_lab_only_and_uncounted():
    vercel = (ROOT / "vercel.json").read_text(encoding="utf-8")
    assert "panel\\\\.html|data/panel/.+" in vercel
    html = (ROOT / "panel.html").read_text(encoding="utf-8")
    assert '<meta name="robots" content="noindex, nofollow" />' in html
    assert "page === 'panel') return null;" in (ROOT / "js/site.js").read_text(encoding="utf-8")
