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


def test_each_game_draws_32_from_a_pool_of_distinct_catalog_dishes():
    assert CUP["size"] == 32 and len(CUP["dishes"]) >= 32 and len(set(CUP["dishes"])) == len(CUP["dishes"])
    assert page_content.worldcup_errors(ROOT) == []
    script = (ROOT / "js/worldcup.js").read_text(encoding="utf-8")
    assert "shuffle(set).slice(0, size)" in script            # a fresh draw from the pool each game


def test_a_broken_bracket_is_refused(tmp_path):
    shutil.copytree(ROOT / "data/foods", tmp_path / "data/foods")
    shutil.copytree(ROOT / "images/worldcup", tmp_path / "images/worldcup")
    (tmp_path / "data/content").mkdir(parents=True)

    def errors(dishes):
        (tmp_path / "data/content/worldcup.json").write_text(json.dumps(dict(CUP, dishes=dishes)), encoding="utf-8")
        return page_content.worldcup_errors(tmp_path)

    assert errors(CUP["dishes"]) == []
    assert any("not a bracket" in e for e in errors(CUP["dishes"][:31]))           # fewer dishes than a game
    assert any("twice" in e for e in errors(CUP["dishes"][:31] + CUP["dishes"][:1]))
    assert any("not a catalog dish" in e for e in errors(CUP["dishes"][:31] + ["kr-made-up-dish"]))


def test_an_activity_page_link_must_be_a_page_of_this_site(tmp_path):
    shutil.copytree(ROOT / "data/content", tmp_path / "data/content")
    shutil.copytree(ROOT / "images/worldcup", tmp_path / "images/worldcup")       # the teaser's pictures

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
    assert 'id="wcStatus" role="status"' in html and "'wc.title': 'Babdoduk Food World Cup'" in html
    # Pictures are decoration inside the pick buttons (the button names the dish); no claims about
    # what is on sale: the catalog is general information.
    main = html.split("<main", 1)[1].split("</main>", 1)[0]
    assert re.findall(r"<img [^>]*>", main) and all('alt=""' in tag for tag in re.findall(r"<img [^>]*>", main))
    assert "판매 여부와 가격은 가게에서 확인" in html and "위키미디어 공용의 자유 이용 사진" in html


def test_every_dish_has_a_credited_free_photo_on_disk():
    photos = CUP["photos"]
    assert set(photos) == set(CUP["dishes"])
    for dish, photo in photos.items():
        assert (ROOT / photo["image"]).is_file() and photo["image"] == f"images/worldcup/{dish}.jpg"
        assert photo["source"].startswith("https://commons.wikimedia.org/wiki/File:") and photo["author"]
        assert "NC" not in photo["license"] and "ND" not in photo["license"]
        assert (ROOT / photo["image"]).stat().st_size < 150_000          # a cropped, resized copy
    script = (ROOT / "js/worldcup.js").read_text(encoding="utf-8")
    assert "showPhoto(" in script and "wc.photoCredit" in script


def test_a_missing_photo_is_refused(tmp_path):
    shutil.copytree(ROOT / "data/foods", tmp_path / "data/foods")
    (tmp_path / "data/content").mkdir(parents=True)
    broken = dict(CUP, photos={k: v for k, v in CUP["photos"].items() if k != CUP["dishes"][0]})
    (tmp_path / "data/content/worldcup.json").write_text(json.dumps(broken), encoding="utf-8")
    errors = page_content.worldcup_errors(tmp_path)
    assert any(f"{CUP['dishes'][0]} has no photo" in e for e in errors)
    assert any("which does not exist" in e for e in errors)              # the files are not in tmp_path
