"""scripts/check_all.py and the grouped site-UI run (owner 2026-11-12: checks took too long)."""
import re
import sys

import check_site_ui
from check_site_ui import GROUPS, ROOT, SIZES, group_names

sys.path.insert(0, str(ROOT / "scripts"))
import check_all  # noqa: E402


def test_quick_leaves_the_slow_browser_runs_to_the_full_check_and_ci():
    quick = dict(check_all.stages(quick=True))
    full = dict(check_all.stages(quick=False))
    assert list(quick) == ["chrome sync", "content", "tests"]
    assert list(full) == ["chrome sync", "content", "tests", "site UI", "food hub UI"]
    assert quick["tests"][-2:] == ["--deselect", check_all.SITE_UI_TEST] == full["tests"][-2:]
    assert full["site UI"][3] == check_all.SITE_UI_TEST, "the deselected run is the full check's own stage"
    assert (ROOT / "tests/test_site_ui.py").read_text(encoding="utf-8").count("def test_all_public_pages_windows_scrollbars_and_overflow") == 1


def test_the_groups_still_run_every_check_of_the_old_sequence():
    source = (ROOT / "scripts/check_site_ui.py").read_text(encoding="utf-8")
    body = source[source.index("def _matrix(size):"):source.index("GROUPS = {")]
    for name in ("inspect_page", "magazine_tools", "pick_tools", "magazine_sparse", "magazine_edition_time", "release_contracts",
                 "lab_menu", "home_page", "home_summary", "home_hero", "home_first_screen", "event_bands", "event_entry",
                 "worldcup_play", "worldcup_categories", "worldcup_splash", "worldcup_gacha", "worldcup_sound", "worldcup_stats",
                 "worldcup_share", "worldcup_kakao", "worldcup_gate", "worldcup_boundaries", "home_wc_promo", "tip_board",
                 "history_archive", "food_provenance", "structure_and_failures", "site_guardian", "chrome_visual"):
        if hasattr(check_site_ui, name):   # lab carries lab_menu and worldcup_stats; main does not
            assert re.search(rf"\b{name}\b", body), name
    assert [g for g in GROUPS if g.startswith("matrix-")] == [f"matrix-{w}" for w, _ in SIZES]
    assert "assert not r.api_attempts" in source, "every group still refuses live requests"


def test_the_screenshot_comparison_is_skipped_only_when_asked(monkeypatch):
    monkeypatch.setenv("BABDODUK_CHROME_VISUAL", "skip")
    assert "visual" not in group_names()
    monkeypatch.delenv("BABDODUK_CHROME_VISUAL")
    assert group_names()[-1] == "visual"


def _tree(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "js").mkdir()
    (tmp_path / "my.html").write_text('<script src="js/my.js?v=1"></script>', encoding="utf-8")
    (tmp_path / "other.html").write_text('<script src="js/other.js"></script>', encoding="utf-8")
    (tmp_path / "tests/test_page.py").write_text('page.goto(f"https://{HOST}/my.html")', encoding="utf-8")
    (tmp_path / "tests/test_lookalike.py").write_text('"my.json", "army.js", "my.js-old"', encoding="utf-8")
    (tmp_path / "tests/test_module.py").write_text("import page_content\n", encoding="utf-8")
    return tmp_path


def test_changed_runs_the_tests_of_the_pages_that_load_a_changed_script(tmp_path):
    root = _tree(tmp_path)
    files, _ = check_all.select_tests(["js/my.js"], root)
    assert files == [root / "tests/test_page.py"], "the page that loads it, never a look-alike name"
    files, _ = check_all.select_tests(["scripts/page_content.py"], root)
    assert files == [root / "tests/test_module.py"]
    files, _ = check_all.select_tests(["tests/test_lookalike.py", "docs/NOTES.md", "README.md"], root)
    assert files == [root / "tests/test_lookalike.py"], "a changed test runs itself; documents need none"


def test_changed_falls_back_to_the_quick_set_when_it_cannot_tell(tmp_path):
    root = _tree(tmp_path)
    for shared in ("css/site.css", "js/site.js", "shared/nav.html", "tests/conftest.py", "pytest.ini"):
        files, why = check_all.select_tests(["js/my.js", shared], root)
        assert files is None and shared in why
    files, why = check_all.select_tests(["js/other.js"], root)
    assert files is None and "js/other.js" in why, "a source file no test names runs everything"


def test_changed_stages_run_only_the_chosen_files():
    assert [name for name, _ in check_all.stages(quick=True, only=[])] == ["chrome sync", "content"]
    chosen = dict(check_all.stages(quick=True, only=[ROOT / "tests/test_check_all.py"]))
    assert "tests/test_check_all.py" in chosen["tests"] and "tests" not in chosen["tests"]
    assert chosen["tests"][-2:] == ["--deselect", check_all.SITE_UI_TEST]


def test_a_python_without_the_parallel_runner_hands_over_to_one_with_it(monkeypatch, tmp_path):
    other = tmp_path / "python"
    other.write_text("")
    other.chmod(0o755)
    monkeypatch.setenv(check_all.SWITCHED, "")   # restored to unset afterwards
    monkeypatch.setattr(check_all, "candidate_pythons", lambda: [str(other)])
    monkeypatch.setattr(check_all, "missing_parts", lambda python=None: ["xdist"] if python is None else [])
    calls = []
    monkeypatch.setattr(check_all.os, "execv", lambda path, args: calls.append((path, args)))
    check_all.choose_python(["--quick"])
    assert calls and calls[0][0] == str(other) and calls[0][1][-1] == "--quick"
    monkeypatch.setenv(check_all.SWITCHED, "1")
    calls.clear()
    assert check_all.choose_python(["--quick"]) == ["xdist"] and not calls, "never hands over twice"
