"""Contracts for the lab polish: midnight menu choice, quiet home, event list, history."""
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
