"""Contracts for the lab polish: midnight menu choice, quiet home, event list, history, link preview."""
from pathlib import Path
import re
import subprocess

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


PREVIEW = "https://babdoduk.vercel.app/images/og-babdoduk.png"
# The character pictures used before (a preview card and the home kicker's avatar) were not ours to use;
# the Babdoduk wordmark replaced them (owner 2026-11-10), under new file names so cached previews refresh.
GONE = ("kakao-loopy", "profile-instagram")


def head_meta(html: str) -> dict:
    head = html.split("</head>", 1)[0]
    return dict(re.findall(r'<meta property="(og:[\w:]+)" content="([^"]*)"', head))


def png_size(data: bytes) -> tuple[int, int]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def test_home_link_preview_is_the_babdoduk_wordmark():
    # Kakao once showed the first food photo (kimchi-jjigae) because the page had no preview image.
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    meta = head_meta(html)
    assert meta["og:title"] == "밥도둑 Babdoduk"
    assert meta["og:description"] == "KAIST 꽁밥 일정"
    assert meta["og:image"] == PREVIEW and meta["og:image:alt"] == "밥도둑 로고"
    assert f'<link rel="image_src" href="{PREVIEW}" />' in html
    width, height = png_size((ROOT / "images/og-babdoduk.png").read_bytes())
    assert (meta["og:image:width"], meta["og:image:height"]) == (str(width), str(height)) == ("1200", "1200")
    body = html.split("<body", 1)[1]
    assert re.search(r'<img src="([^"]+)"', body).group(1) == "images/og-babdoduk.png"  # first image a scraper sees
    kicker = body.split('class="home-kicker"', 1)[1].split("</p>", 1)[0]
    assert '<img src="images/avatar-babdoduk.png" alt=""' in kicker
    assert png_size((ROOT / "images/avatar-babdoduk.png").read_bytes()) == (256, 256)
    for page in ("ggongbab.html", "mukbang.html", "history.html", "privacy.html"):
        page_html = (ROOT / page).read_text(encoding="utf-8")
        assert head_meta(page_html)["og:image"] == PREVIEW, page
        assert f'<link rel="image_src" href="{PREVIEW}" />' in page_html, page
    # The news page and the world cup show the world cup's teaser instead (owner 2026-10-14,
    # tests/test_worldcup_share.py).
    for page in ("event.html", "worldcup.html"):
        assert head_meta((ROOT / page).read_text(encoding="utf-8"))["og:image"].endswith("/images/worldcup/og-worldcup.jpg"), page


def test_the_old_character_pictures_are_gone_everywhere():
    for name in GONE:
        assert not list((ROOT / "images").glob(f"{name}.*")), name
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    for path in tracked:
        if path.startswith("data/") or not path.endswith((".html", ".js", ".css", ".json", ".md", ".py")):
            continue
        if path == "tests/test_final_polish.py":
            continue
        text = (ROOT / path).read_text(encoding="utf-8")
        for name in GONE:
            assert name not in text, (path, name)


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
