"""Shared site chrome: one source in shared/, a static copy in every page, and drift fails."""
import re
import shutil
import subprocess
import sys

import sync_site_chrome as chrome
from check_site_ui import ROOT


def test_every_page_carries_the_shared_nav_and_footer():
    result = subprocess.run([sys.executable, str(ROOT / "scripts/sync_site_chrome.py"), "--check"],
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stdout[-3000:]


def test_a_drifted_page_fails_the_check(tmp_path, monkeypatch, capsys):
    shutil.copytree(ROOT / "shared", tmp_path / "shared")
    for page in chrome.PAGES:
        shutil.copy(ROOT / page, tmp_path / page)
    monkeypatch.setattr(chrome, "ROOT", tmp_path)
    monkeypatch.setattr(chrome, "SHARED", tmp_path / "shared")
    assert chrome.main(["--check"]) == 0
    page = tmp_path / "event.html"
    page.write_text(page.read_text(encoding="utf-8").replace('href="choose.html" class="footer-apple-a"',
                                                            'href="mukbang.html#what" class="footer-apple-a"'), encoding="utf-8")
    assert chrome.main(["--check"]) == 1
    assert "event.html" in capsys.readouterr().out
    assert chrome.main([]) == 0 and chrome.main(["--check"]) == 0  # rewriting restores the shared copy


def test_nav_and_footer_work_without_javascript_and_mark_one_current_page():
    for page, config in chrome.PAGES.items():
        html = (ROOT / page).read_text(encoding="utf-8")
        nav = html[html.index('<header class="site-nav"'):html.index("</header>")]
        footer = html[html.index('<footer class="site-footer"'):html.index("</footer>")]
        assert 'href="choose.html"' in nav and 'href="choose.html"' in footer, page
        assert "mukbang.html#what" not in html, page
        current = re.findall(r'href="([^"]+)" aria-current="page"', nav)
        assert current == ([config["current"]] if config["current"] else []), (page, current)
        assert re.search(r'<p class="footer-apple-fine" data-i18n="footer.fine">[^<]+</p>', footer), page
    assert "<script" not in (ROOT / "shared/nav.html").read_text(encoding="utf-8")
    assert "<script" not in (ROOT / "shared/footer.html").read_text(encoding="utf-8")


def test_ci_fails_on_chrome_drift_without_secrets():
    workflow = (ROOT / ".github/workflows/site-chrome.yml").read_text(encoding="utf-8")
    assert "python scripts/sync_site_chrome.py --check" in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "secrets." not in workflow and "schedule:" not in workflow
