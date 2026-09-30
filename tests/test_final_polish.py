"""Contracts for the lab polish: midnight menu choice, quiet home, event list, history, link preview."""
from pathlib import Path
import re

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def test_history_hub_is_2026_and_ver2_is_recorded():
    html = (ROOT / "history.html").read_text(encoding="utf-8")
    assert 'datetime="2026-05-07"' in html
    assert "2025-05-07" not in html and "2025.5.7" not in html and "May 7, 2025" not in html
    assert 'datetime="2026-09-30"' in html
    assert "Babdoduk ver2. 오픈" in html and "Babdoduk ver2. Open" in html
    assert "오늘의 꽁밥·학식·매거진" in html


def test_home_and_event_drop_the_noisy_chrome():
    home = (ROOT / "index.html").read_text(encoding="utf-8")
    event = (ROOT / "event.html").read_text(encoding="utf-8")
    assert "home-today-note" not in home and "지금 확인된 정보" not in home
    assert "공개 조건을 통과" not in home and "오늘 학식 메뉴가 아니에요" not in home
    assert "home-photo-tag" not in home
    assert 'class="page-num"' not in event and "event-num" not in event and "event-elsewhere" not in event
    empty = event.split('id="eventEmpty"')[1].split("</p>")[0]
    assert "instagram.com" not in empty
    assert 'class="event-instagram"' in event and "@babdodukms" in event


LOOPY = "https://babdoduk.vercel.app/images/kakao-loopy.jpg"


def head_meta(html: str) -> dict:
    head = html.split("</head>", 1)[0]
    return dict(re.findall(r'<meta property="(og:[\w:]+)" content="([^"]*)"', head))


def jpeg_size(data: bytes) -> tuple[int, int]:
    assert data[:2] == b"\xff\xd8", "not a JPEG"
    i = 2
    while i < len(data):
        marker, length = data[i + 1], int.from_bytes(data[i + 2:i + 4], "big")
        if marker in (0xC0, 0xC1, 0xC2):
            return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")
        i += 2 + length
    raise AssertionError("no frame header")


def test_home_link_preview_is_the_loopy_card():
    # Kakao once showed the first food photo (kimchi-jjigae) because the page had no preview image.
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    meta = head_meta(html)
    assert meta["og:title"] == "밥도둑 Babdoduk"
    assert meta["og:description"] == "KAIST 꽁밥 일정"
    assert meta["og:image"] == LOOPY
    assert f'<link rel="image_src" href="{LOOPY}" />' in html
    width, height = jpeg_size((ROOT / "images/kakao-loopy.jpg").read_bytes())
    assert (meta["og:image:width"], meta["og:image:height"]) == (str(width), str(height))
    body = html.split("<body", 1)[1]
    assert re.search(r'<img src="([^"]+)"', body).group(1) == "images/kakao-loopy.jpg"  # first image a scraper sees
    for page in ("ggongbab.html", "mukbang.html", "event.html", "history.html"):
        assert head_meta((ROOT / page).read_text(encoding="utf-8"))["og:image"] == LOOPY, page


def test_footer_contact_uses_the_copyright_color():
    css = (ROOT / "css/site.css").read_text(encoding="utf-8")
    email = css.split(".footer-apple-email-plain {", 1)[1].split("}", 1)[0]
    copy = css.split(".footer-apple-copy {", 1)[1].split("}", 1)[0]
    assert "var(--color-ink-muted)" in email and "var(--color-ink-muted)" in copy
    assert "var(--color-ink)" not in email


def test_resolve_today_choice_across_midnight():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        page.route("**/*", lambda route: route.abort())
        page.add_script_tag(content=(ROOT / "js/kaist-menu.js").read_text(encoding="utf-8"))
        choice = page.evaluate("""() => {
          const M = window.BabdodukKaistMenu;
          const saved = {date:'2026-09-29', restaurants:[{id:'a'}]};
          const dated = {date:'2026-09-30', restaurants:[{id:'b'}]};
          const open = {days:[{date:'2026-09-30', available:true}]};
          const closed = {days:[{date:'2026-09-30', available:false}]};
          return {
            night: M.resolveTodayChoice(saved, open, dated, '2026-09-29').use,
            morning: M.resolveTodayChoice(saved, open, dated, '2026-09-30').use,
            absent: M.resolveTodayChoice(saved, closed, dated, '2026-09-30').use,
            nofile: M.resolveTodayChoice(saved, open, null, '2026-09-30').use
          };
        }""")
        browser.close()
    assert choice == {"night": "latest", "morning": "dated", "absent": "stale", "nofile": "stale"}
