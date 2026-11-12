"""scripts/check_all.py and the grouped site-UI run (owner 2026-11-12: checks took too long)."""
import re
import sys

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
        assert re.search(rf"\b{name}\b", body), name
    assert [g for g in GROUPS if g.startswith("matrix-")] == [f"matrix-{w}" for w, _ in SIZES]
    assert "assert not r.api_attempts" in source, "every group still refuses live requests"


def test_the_screenshot_comparison_is_skipped_only_when_asked(monkeypatch):
    monkeypatch.setenv("BABDODUK_CHROME_VISUAL", "skip")
    assert "visual" not in group_names()
    monkeypatch.delenv("BABDODUK_CHROME_VISUAL")
    assert group_names()[-1] == "visual"
