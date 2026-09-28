"""The page keeps an event without an end time for the same window the feed does."""
import re
import subprocess
from pathlib import Path

from ggongbab.config import Settings

ROOT = Path(__file__).resolve().parents[2]


def test_node_select_suite():
    result = subprocess.run(["node", "--test", "tests/ggongbab/select.test.cjs"], cwd=ROOT,
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-2000:]


def test_open_ended_window_matches_the_feed_grace(monkeypatch):
    monkeypatch.delenv("GGONGBAB_EXPIRED_GRACE_HOURS", raising=False)
    script = (ROOT / "js/ggongbab-select.js").read_text(encoding="utf-8")
    hours = int(re.search(r"var OPEN_ENDED_HOURS = (\d+);", script).group(1))
    assert hours == Settings().expired_grace_hours == 3
