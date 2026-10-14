"""Shared site chrome: one source in shared/, a static copy in every page, and drift fails."""
import json
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
    shutil.copytree(ROOT / "i18n", tmp_path / "i18n")
    for page in list(chrome.PAGES) + list(chrome.LABEL_BLOCKS) + list(chrome.CONTENT_SCRIPTS) + ["data/content/labels.json"]:
        (tmp_path / page).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / page, tmp_path / page)
    monkeypatch.setattr(chrome, "ROOT", tmp_path)
    monkeypatch.setattr(chrome, "SHARED", tmp_path / "shared")
    monkeypatch.setattr(chrome, "LABELS", tmp_path / "data/content/labels.json")
    monkeypatch.setattr(chrome, "I18N", tmp_path / "i18n")
    assert chrome.main(["--check"]) == 0
    # A translation is written once, in i18n/: an edit there reaches every page that shows it.
    english = json.loads((tmp_path / "i18n/en.json").read_text(encoding="utf-8"))
    english["footer.contact"] = "Get in touch"
    (tmp_path / "i18n/en.json").write_text(json.dumps(english, ensure_ascii=False), encoding="utf-8")
    assert chrome.main(["--check"]) == 1
    assert chrome.main([]) == 0 and chrome.main(["--check"]) == 0
    for page in chrome.PAGES:
        assert "'footer.contact': 'Get in touch'," in (tmp_path / page).read_text(encoding="utf-8"), page
    # A label is named in one place: an edit there fails the check until the pages are rewritten.
    labels = json.loads((tmp_path / "data/content/labels.json").read_text(encoding="utf-8"))
    labels["freeFood"]["lunchbox"]["en"] = "Packed lunch"
    labels["cuisines"]["byGroup"]["mexican"] = "멕시칸"
    (tmp_path / "data/content/labels.json").write_text(json.dumps(labels, ensure_ascii=False), encoding="utf-8")
    assert chrome.main(["--check"]) == 1
    assert chrome.main([]) == 0 and chrome.main(["--check"]) == 0
    assert "'gg.food.lunchbox': 'Packed lunch'," in (tmp_path / "ggongbab.html").read_text(encoding="utf-8")
    assert "'home.cal.food.lunchbox': 'Packed lunch'," in (tmp_path / "index.html").read_text(encoding="utf-8")
    assert '"mexican": "멕시칸"' in (tmp_path / "js/eat-slot.js").read_text(encoding="utf-8")
    capsys.readouterr()
    page = tmp_path / "event.html"
    drifted = page.read_text(encoding="utf-8").replace('href="mukbang.html" class="footer-apple-a"',
                                                        'href="choose.html" class="footer-apple-a"')
    assert drifted != page.read_text(encoding="utf-8")
    page.write_text(drifted, encoding="utf-8")
    assert chrome.main(["--check"]) == 1
    assert "event.html" in capsys.readouterr().out
    assert chrome.main([]) == 0 and chrome.main(["--check"]) == 0  # rewriting restores the shared copy


def test_nav_and_footer_work_without_javascript_and_mark_one_current_page():
    for page, config in chrome.PAGES.items():
        html = (ROOT / page).read_text(encoding="utf-8")
        nav = html[html.index('<header class="site-nav"'):html.index("</header>")]
        footer = html[html.index('<footer class="site-footer"'):html.index("</footer>")]
        # One magazine product (it carries the picker); no separate picker, no Food Log in the chrome.
        assert 'href="mukbang.html"' in nav and 'href="mukbang.html"' in footer, page
        for gone in ('href="choose.html"', "mukbang.html#what", 'href="food.html"'):
            assert gone not in nav and gone not in footer, (page, gone)
        current = re.findall(r'href="([^"]+)" aria-current="page"', nav)
        assert current == ([config["current"]] if config["current"] else []), (page, current)
        assert re.search(r'<p class="footer-apple-fine" data-i18n="footer.fine">[^<]+</p>', footer), page
    assert "<script" not in (ROOT / "shared/nav.html").read_text(encoding="utf-8")
    assert "<script" not in (ROOT / "shared/footer.html").read_text(encoding="utf-8")


def test_the_contact_label_is_a_chrome_string_in_both_languages():
    for page in chrome.PAGES:
        html = (ROOT / page).read_text(encoding="utf-8")
        footer = html[html.index('<footer class="site-footer"'):html.index("</footer>")]
        assert '<span data-i18n="footer.contact">문의</span>' in footer, page
        ko, en = html[html.index("ko: {"):html.index("en: {")], html[html.index("en: {"):]
        assert "'footer.contact': '문의'," in ko and "'footer.contact': 'Contact'," in en, page
        english = en[:en.index("\n      }")]
        assert "문의" not in english, page  # the English table never shows the Korean label


def test_every_pull_request_runs_the_tests_and_the_content_validator():
    workflow = (ROOT / ".github/workflows/tests.yml").read_text(encoding="utf-8")
    assert "on:\n  pull_request:\n  push:" in workflow
    for step in ("python -m pytest tests -q", "python scripts/validate_content.py",
                 "python scripts/sync_site_chrome.py --check"):
        assert f"run: {step}\n" in workflow, step
    # Content-bot data pushes do not run it; a code push to any working branch does.
    assert "paths-ignore:\n      - 'data/**'\n      - 'research/**'" in workflow
    assert "permissions:\n  contents: read" in workflow and "secrets." not in workflow and "schedule:" not in workflow
    # Only the screenshot comparison is left to ui-guardian, by name; nothing else is skipped.
    assert "BABDODUK_CHROME_VISUAL: skip" in workflow and "--deselect" not in workflow and " -k " not in workflow
    for forbidden in ("--update-chrome-baselines", "--adopt-chrome-baselines", "--approval", "git push", "vercel"):
        assert forbidden not in workflow, forbidden


def test_ci_runs_the_structural_and_the_visual_guardian_and_never_rebaselines():
    workflow = (ROOT / ".github/workflows/ui-guardian.yml").read_text(encoding="utf-8")
    assert not (ROOT / ".github/workflows/site-chrome.yml").exists()
    assert "python scripts/sync_site_chrome.py --check" in workflow
    assert "python3 scripts/check_site_ui.py --chrome-only" in workflow
    assert "BABDODUK_BROWSER: chromium" in workflow
    assert re.search(r"image: mcr\.microsoft\.com/playwright/python:v[\d.]+-noble-amd64@sha256:[0-9a-f]{64}", workflow)
    assert "if: failure()" in workflow and "path: .local/visual-diff/" in workflow
    for path in ("'**.html'", "'css/**'", "'js/**'", "'shared/**'", "'scripts/check_site_ui.py'",
                 "'scripts/sync_site_chrome.py'", "'tests/visual/chrome/**'", "'.github/workflows/ui-guardian.yml'"):
        assert workflow.count(path) == 2, path  # push and pull_request
    assert "data/" not in workflow  # generated-data bot pushes do not run the browser job
    assert "permissions:\n  contents: read" in workflow and "secrets." not in workflow and "schedule:" not in workflow
    for forbidden in ("--update-chrome-baselines", "--adopt-chrome-baselines", "--approval"):
        assert forbidden not in workflow, forbidden


def test_baseline_changes_refuse_to_run_in_ci(monkeypatch):
    import check_site_ui
    monkeypatch.setattr(check_site_ui, "IN_CI", True)
    for action in (lambda: check_site_ui.update_chrome_baselines("approved"),
                   lambda: check_site_ui.adopt_chrome_baselines(ROOT, "linux-chromium", "approved")):
        try:
            action()
        except SystemExit as exc:
            assert "refusing" in str(exc)
        else:
            raise AssertionError("baseline change ran in CI")


def test_every_platform_set_is_complete_and_owner_approved():
    import check_site_ui
    names = set(check_site_ui.expected_shots())
    sets = sorted(p for p in (ROOT / "tests/visual/chrome").iterdir() if p.is_dir())
    assert [p.name for p in sets] == ["linux-chromium", "windows-chrome"]
    for folder in sets:
        assert {p.name for p in folder.glob("*.png")} == names, folder.name
        manifest = json.loads((folder / "BASELINES.json").read_text(encoding="utf-8"))
        assert manifest["platform"] == folder.name and "PENDING" not in manifest["approval"]
        assert manifest["approval"].startswith("Owner approved"), manifest["approval"]


def test_a_guardian_failure_still_runs_the_visual_comparison_and_names_the_page(tmp_path, monkeypatch):
    import check_site_ui as ui

    class Page:
        def screenshot(self, **_):
            return b"capture"

    class Browser:
        def close(self):
            pass

    class Playwright:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def guardian(page):
        detail = ("event.html ko 1440x900", "the footer sits on the page canvas on every page", {"background-color": "x"})
        raise AssertionError(f"site guardian: {detail}", detail)

    ran = []
    monkeypatch.setattr(ui, "DIFF_DIR", tmp_path / "visual-diff")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.setattr(ui, "sync_playwright", Playwright)
    monkeypatch.setattr(ui, "launch", lambda pw: Browser())
    monkeypatch.setattr(ui, "new_context", lambda browser: type("Context", (), {"new_page": lambda self: Page()})())
    monkeypatch.setattr(ui, "site_guardian", guardian)
    monkeypatch.setattr(ui, "chrome_visual", lambda page: ran.append("visual") or 84)
    try:
        ui.run_chrome_checks()
    except AssertionError as exc:
        assert "site guardian" in str(exc)
    else:
        raise AssertionError("a guardian failure passed the gate")
    assert ran == ["visual"]
    summary = (tmp_path / "visual-diff/SUMMARY.md").read_text(encoding="utf-8")
    assert "| guardian-event-ko-1440px.png | event.html | ko | 1440px | the footer sits on the page canvas on every page |" in summary
    assert (tmp_path / "visual-diff/guardian-event-ko-1440px.png").read_bytes() == b"capture"


def test_a_tree_without_the_lab_only_feed_still_syncs(tmp_path, monkeypatch):
    """main has no js/ggongbab-public-feed.js (the public feed is lab-only): the sync leaves its block
    out there, and any other missing script still stops it."""
    for folder in ("shared", "i18n"):
        if (ROOT / folder).exists():
            shutil.copytree(ROOT / folder, tmp_path / folder)
    for page in list(chrome.PAGES) + ["js/eat-slot.js", *chrome.CONTENT_SCRIPTS, "data/content/labels.json"]:
        (tmp_path / page).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / page, tmp_path / page)
    for name, value in (("ROOT", tmp_path), ("SHARED", tmp_path / "shared"), ("I18N", tmp_path / "i18n"),
                        ("LABELS", tmp_path / "data/content/labels.json")):
        if hasattr(chrome, name):
            monkeypatch.setattr(chrome, name, value)
    monkeypatch.setattr(chrome, "LABEL_BLOCKS", chrome.present(chrome.ALL_LABEL_BLOCKS, tmp_path))
    assert list(chrome.LABEL_BLOCKS) == ["js/eat-slot.js"]
    assert chrome.main(["--check"]) == 0
    (tmp_path / "js/eat-slot.js").unlink()
    try:
        chrome.main(["--check"])
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("a missing script passed the sync")
