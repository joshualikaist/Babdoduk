"""The lab page's synthetic data (data plan phase 4) lives with the tests, in
tests/fixtures/ggongbab-lab.js, and the scripts every visitor loads carry none of it. The fixture
runs here in Node on a fixed clock; scripts/check_ggongbab_ui.py drives it in the browser."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = "tests/fixtures/ggongbab-lab.js"


def run_fixture(expression: str):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    script = (
        "const fs = require('fs'), vm = require('vm'); const sandbox = {window: {}};\n"
        f"vm.runInNewContext(fs.readFileSync({json.dumps(FIXTURE)}, 'utf8'), sandbox);\n"
        "const F = sandbox.window.BabdodukLabFixtures;\n"
        f"process.stdout.write(JSON.stringify({expression}));\n")
    result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(result.stdout)


def test_the_public_scripts_carry_no_synthetic_data():
    hub = (ROOT / "js/ggongbab.js").read_text(encoding="utf-8")
    menu = (ROOT / "js/kaist-menu.js").read_text(encoding="utf-8")
    for script in (hub, menu):
        for marker in ("fixtureData", "fixtureArchive", "fixtureMenu", "fixtureDay", "캠퍼스 진로 이야기", "'fixture-'",
                       "교내 새 식당 오픈 안내", "특제 돈가스"):
            assert marker not in script, marker
    # The hub loads the fixture only in fixture mode, which only the lab page has.
    assert re.findall(r"\.src = '([^']+)'", hub) == ["tests/fixtures/ggongbab-lab.js"]
    loader = hub[hub.index("if (mode === 'fixture') {\n    var fixtureScript"):]
    assert "fixtureScript.src = 'tests/fixtures/ggongbab-lab.js';" in loader
    assert re.search(r"if \(!isLab\) return 'normal';", hub)
    # tests/ is never deployed, so no visitor of either site can load it.
    assert "tests" in (ROOT / ".vercelignore").read_text(encoding="utf-8").splitlines()


def test_the_fixture_follows_the_page_clock():
    out = run_fixture("""(() => {
      const today = new Date(2026, 9, 12, 12, 0);          // Monday 12:00, as the page clock gives it
      const feed = F.freeFeed(today), past = F.archive(today, 30), news = F.news(today);
      return {ids: feed.events.map(e => e.id), firstStart: feed.events[0].startAt,
              sources: [...new Set(feed.events.map(e => e.sources[0].type))].sort(),
              window: past.windowDays, pastIds: past.events.map(e => e.id), news: news.items[0].noticeDate,
              menu: F.menu(false, today).date, stale: F.menu(true, today).date,
              saturday: F.menuDay('2026-10-17').restaurants.map(r => r.lunch.items.length > 0),
              sunday: F.menuDay('2026-10-18')};
    })()""")
    assert out["ids"] == [f"fixture-{i}" for i in range(10)]
    assert out["firstStart"] == "2026-10-12T12:00:00+09:00"
    assert out["sources"] == ["dooray", "kaist_public", "manual", "portal"]
    assert out["window"] == 30 and "past-review" in out["pastIds"] and "past-future" in out["pastIds"]
    assert out["news"] == "2026-10-12"
    assert out["menu"] == "2026-10-12" and out["stale"] == "2026-10-11"
    assert out["saturday"] == [True, True] and out["sunday"] is None
