"""The shared labels (data/content/labels.json, data plan phase 4): one place for food types,
sources, cafeterias, cuisines and magazine lanes, read by the pipeline and written into the pages.
No network; the picker's labels come from the real js/eat-slot.js run in Node."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import content_labels
import sync_site_chrome
from schema_check import load_schema, schema_errors

ROOT = Path(__file__).resolve().parents[1]
LABELS = json.loads((ROOT / "data/content/labels.json").read_text(encoding="utf-8"))
# The picker's cuisine map before 2026-10-12, which sent 121 western dishes to 한식.
OLD_CUISINE = {"korean": "한식", "chinese": "중식", "japanese": "일식", "western": "양식", "southeast-asian": "동남아",
               "indian": "인도", "middle-eastern": "중동", "fusion": "퓨전", "snack": "분식", "dessert": "디저트"}


def dishes():
    catalog = json.loads((ROOT / "data/foods/catalog.json").read_text(encoding="utf-8"))
    return [dish for pack in catalog["packs"]
            for dish in json.loads((ROOT / pack["src"]).read_text(encoding="utf-8"))["items"]]


def slot_labels(foods):
    """labelsOf() of the real js/eat-slot.js for every dish, in Node."""
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    script = """
const fs = require('fs'), vm = require('vm');
const sandbox = {window: {}};
vm.runInNewContext(fs.readFileSync('js/eat-slot.js', 'utf8'), sandbox);
const foods = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(foods.map(f => sandbox.window.BabdodukSlot.labelsOf(f)[0])));
"""
    result = subprocess.run(["node", "-e", script], cwd=ROOT, input=json.dumps(foods), capture_output=True,
                            text=True, encoding="utf-8", check=True)
    return json.loads(result.stdout)


def test_the_labels_keep_their_contract():
    assert schema_errors(LABELS, "content-labels") == []


def test_the_picker_calls_a_dish_korean_only_when_it_is():
    foods = dishes()
    shown = slot_labels(foods)
    assert len(shown) == len(foods) == 1314
    for food, label in zip(foods, shown):
        if label == "한식":
            assert food["cuisine"] == "korean" or food["cuisineGroup"] == "korean", food["id"]
    groups = {food["cuisineGroup"] for food in foods}
    assert groups <= set(LABELS["cuisines"]["byGroup"])            # no dish falls back to the default
    # The fix of 2026-10-12, exactly: 121 western dishes stop being 한식, nothing else moves. The MFDS dishes of
    # 2026-10-13 (P5) add 9 more the old map would have sent to 한식 (7 pastas, a potato soup, hotcakes).
    old = [OLD_CUISINE.get(f["cuisine"]) or OLD_CUISINE.get(f["cuisineGroup"]) or "한식" for f in foods]
    moved = [(o, n) for o, n in zip(old, shown) if o != n]
    assert len(moved) == 121 + 9 and set(moved) == {("한식", "양식")}


def test_the_pipeline_reads_the_same_labels():
    import refresh_kaist_menu
    from discovery import select
    from ggongbab import exporter, food_news
    from ggongbab.db import repository
    assert refresh_kaist_menu.RESTAURANTS == LABELS["restaurants"]
    data_names = {kind: spec["dataName"] for kind, spec in LABELS["sources"].items()}
    assert exporter.PUBLIC_SOURCE_NAMES == repository.SOURCE_NAMES == data_names
    assert food_news.SOURCE_NAMES == {kind: spec["newsName"] for kind, spec in LABELS["sources"].items()
                                      if "newsName" in spec}
    assert select.LANE_LEADS == {lane: spec["lead"]["ko"] for lane, spec in LABELS["magazineLanes"].items()}
    assert content_labels.LABELS == ROOT / "data/content/labels.json"


def test_the_public_contracts_name_the_sources_as_the_labels_do():
    data_names = sorted(spec["dataName"] for spec in LABELS["sources"].values())
    news = {kind: spec["newsName"] for kind, spec in LABELS["sources"].items() if "newsName" in spec}
    for name in ("ggongbab-feed", "ggongbab-archive"):
        schema = load_schema(name)
        source = schema["$defs"]["source"] if "source" in schema["$defs"] else \
            schema["$defs"]["event"]["properties"]["sources"]["items"]
        assert sorted(source["properties"]["name"]["enum"]) == data_names, name
        assert sorted(source["properties"]["type"]["enum"]) == sorted(LABELS["sources"]), name
    for name in ("ggongbab-news", "ggongbab-news-input"):
        forms = load_schema(name)["$defs"]["item"]["properties"]["sources"]["items"]["anyOf"]
        assert {f["properties"]["type"]["const"]: f["properties"]["name"]["const"] for f in forms} == news, name


def test_the_pages_carry_the_labels_and_name_them_once():
    # Written by scripts/sync_site_chrome.py: the committed pages and scripts are what it writes.
    assert sync_site_chrome.main(["--check"]) == 0
    home_types = re.search(r"var FOOD_TYPES = \[([^\]]*)\]", (ROOT / "js/home-calendar.js").read_text(encoding="utf-8"))
    assert tuple(re.findall(r"'([a-z]+)'", home_types.group(1))) == sync_site_chrome.HOME_FOOD_TYPES
    # No second copy of a type or source label in the hub's script (its filter chips are another
    # vocabulary: buckets of several types).
    hub = (ROOT / "js/ggongbab.js").read_text(encoding="utf-8")
    assert re.search(r"lunchbox:\s*'", hub) is None
    assert re.findall(r"t\('gg\.(?:food\.[a-z' +]+|source\.\w+)',\s*'([^']+)'\)", hub) == []
    # The Korean text a page shows before its script runs is the label itself.
    for page in ("index.html", "mukbang.html"):
        html = (ROOT / page).read_text(encoding="utf-8")
        for key, pair in sync_site_chrome.label_strings(page).items():
            for text in re.findall(r'data-i18n="' + re.escape(key) + r'"[^>]*>([^<]*)<', html):
                assert text == pair["ko"], (page, key, text)
