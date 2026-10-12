"""The KAIST menu world cup (worldcup.html, owner P4 2026-10-13): a bracket of catalog dishes from
data/content/worldcup.json, played in the browser with nothing sent anywhere. Static checks; the
keyboard play-through runs in scripts/check_site_ui.py (worldcup_play)."""
import json
import re
import shutil
from pathlib import Path

import page_content

ROOT = Path(__file__).resolve().parents[1]
CUP = json.loads((ROOT / "data/content/worldcup.json").read_text(encoding="utf-8"))


def test_the_bracket_is_32_distinct_catalog_dishes():
    assert len(CUP["dishes"]) == 32 and len(set(CUP["dishes"])) == 32
    assert page_content.worldcup_errors(ROOT) == []


def test_a_broken_bracket_is_refused(tmp_path):
    shutil.copytree(ROOT / "data/foods", tmp_path / "data/foods")
    (tmp_path / "data/content").mkdir(parents=True)

    def errors(dishes):
        (tmp_path / "data/content/worldcup.json").write_text(json.dumps(dict(CUP, dishes=dishes)), encoding="utf-8")
        return page_content.worldcup_errors(tmp_path)

    assert errors(CUP["dishes"]) == []
    assert any("bracket" in e for e in errors(CUP["dishes"][:31]))
    assert any("twice" in e for e in errors(CUP["dishes"][:31] + CUP["dishes"][:1]))
    assert any("not a catalog dish" in e for e in errors(CUP["dishes"][:31] + ["kr-made-up-dish"]))


def test_an_activity_page_link_must_be_a_page_of_this_site(tmp_path):
    shutil.copytree(ROOT / "data/content", tmp_path / "data/content")

    def event_errors():
        return [e for e in page_content.content_errors(tmp_path) if e.startswith("events.json")]

    assert any("worldcup.html" in e and "not a page of this site" in e for e in event_errors())
    (tmp_path / "worldcup.html").write_text("<!doctype html>", encoding="utf-8")
    assert event_errors() == []


def test_the_page_reads_only_static_files_and_keeps_results_in_this_browser():
    html = (ROOT / "worldcup.html").read_text(encoding="utf-8")
    assert re.findall(r'<script\s+src="([^"]+)"', html) == ["js/site.js", "js/worldcup.js"]
    script = (ROOT / "js/worldcup.js").read_text(encoding="utf-8")
    assert set(re.findall(r"getJson\('([^']+)'\)", script)) == {"data/foods/catalog.json"}
    # data/content/ is never deployed (.vercelignore): the sync writes the dishes into the page.
    embedded = re.search(r"window\.BABDODUK_WORLDCUP = (\{.*\});", html).group(1)
    assert json.loads(embedded)["dishes"] == CUP["dishes"]
    for forbidden in ("supabase", "XMLHttpRequest", "WebSocket", "sendBeacon", "POST"):
        assert forbidden not in script, forbidden
    assert "var KEY = 'babdoduk-worldcup';" in script and "localStorage.setItem(KEY" in script
    assert html.count('<button type="button" class="wc-card"') == 2
    assert 'id="wcStatus" role="status"' in html and "'wc.title': 'KAIST Menu World Cup'" in html
    # No pictures and no claims about what is on sale: the catalog is general information.
    assert "<img" not in html.split("<main", 1)[1].split("</main>", 1)[0]
    assert "판매 여부와 가격은 가게에서 확인" in html
