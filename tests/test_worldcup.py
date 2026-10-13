"""The 먹방 world cup (worldcup.html, owner P4 2026-10-13): a bracket of catalog dishes from
data/content/worldcup.json, played in the browser with nothing sent anywhere. Static checks; the
keyboard play-through runs in scripts/check_site_ui.py (worldcup_play), and the round splash with
motion in worldcup_splash."""
import json
import re
import shutil
from pathlib import Path
from urllib.parse import parse_qs, urlparse

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
    assert "판매 여부와 가격은 가게에서 확인" in html and "사진: 위키미디어 공용, 잘라서 줄임" in html


def test_undo_and_restart_are_an_icon_and_a_short_label():
    # Owner, 2026-10-13: fewer words, and the two controls under the match less bland than a plain
    # underline. The icon is decoration (aria-hidden); the visible word is the button's name, and
    # the translation goes on the inner span so the language switch never wipes the icon.
    html = (ROOT / "worldcup.html").read_text(encoding="utf-8")
    tools = html.split('<div class="wc-tools">', 1)[1].split("</div>", 1)[0]
    for button, key in (("wcUndo", "wc.undo"), ("wcRestart", "wc.restart")):
        markup = tools.split(f'id="{button}">', 1)[1].split("</button>", 1)[0]
        assert re.search(r'<svg class="wc-tool-icon"[^>]*aria-hidden="true"', markup), button
        assert f'<span data-i18n="{key}">' in markup and "data-i18n" not in tools.split(f'id="{button}"', 1)[0].rsplit("<button", 1)[1]
    ko = json.loads((ROOT / "i18n/ko.json").read_text(encoding="utf-8"))
    en = json.loads((ROOT / "i18n/en.json").read_text(encoding="utf-8"))
    assert (ko["wc.undo"], en["wc.undo"]) == ("되돌리기", "Undo")
    assert (ko["wc.restart"], en["wc.restart"]) == (ko["eat.reset"], en["eat.reset"])   # the picker's word
    css = (ROOT / "css/worldcup.css").read_text(encoding="utf-8")
    assert ".wc-tool:focus-visible" in css and "min-height: 44px" in css.split(".wc-tool {", 1)[1].split("}", 1)[0]
    script = (ROOT / "js/worldcup.js").read_text(encoding="utf-8")
    assert "if (previous.game)" in script            # 되돌리기 takes back 처음부터


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


def test_the_pool_is_large_and_varied_as_the_copy_says():
    # The page, the event and the share text all say "more than 700 dishes" (owner, 2026-10-13:
    # aim for 1,000, at most five variants of the same dish).
    assert len(CUP["dishes"]) > 700
    events = json.loads((ROOT / "data/content/events.json").read_text(encoding="utf-8"))
    teaser = next(a for a in events["activities"] if a.get("link") == "worldcup.html")
    for text in (CUP["basis"]["ko"], teaser["details"]["summary"]["ko"]):
        assert "700개가 넘는 메뉴" in text
    assert "more than 700 dishes" in CUP["basis"]["en"]
    names = {}
    for pack in json.loads((ROOT / "data/foods/catalog.json").read_text(encoding="utf-8"))["packs"]:
        names |= {f["id"]: f["nameKo"] for f in json.loads((ROOT / pack["src"]).read_text(encoding="utf-8"))["items"]}
    families = {}
    for dish in CUP["dishes"]:
        families.setdefault(page_content.same_dish(dish, names[dish]), []).append(dish)
    assert max(len(members) for members in families.values()) <= page_content.SAME_DISH_LIMIT == 5
    assert page_content.same_dish("x", "치즈 볶음밥") == "볶음밥" and page_content.same_dish("x", "잡채") == "x"


def test_a_sixth_variant_of_the_same_dish_is_refused(tmp_path):
    shutil.copytree(ROOT / "data/foods", tmp_path / "data/foods")
    (tmp_path / "data/content").mkdir(parents=True)
    names = {}
    for pack in json.loads((ROOT / "data/foods/catalog.json").read_text(encoding="utf-8"))["packs"]:
        names |= {f["id"]: f["nameKo"] for f in json.loads((ROOT / pack["src"]).read_text(encoding="utf-8"))["items"]}
    gimbap = [d for d, name in names.items() if page_content.same_dish(d, name) == "김밥"][:6]
    others = [d for d in CUP["dishes"] if d not in gimbap and page_content.same_dish(d, names[d]) != "김밥"]
    dishes = gimbap + others[:32 - len(gimbap)]
    (tmp_path / "data/content/worldcup.json").write_text(json.dumps(dict(CUP, dishes=dishes, photos={})), encoding="utf-8")
    assert len(gimbap) == 6
    assert "worldcup.json: 6 dishes are 김밥; at most 5 of the same dish" in page_content.worldcup_errors(tmp_path)


def splash_module():
    script = (ROOT / "js/worldcup.js").read_text(encoding="utf-8")
    return script.split("// ---- round splash", 1)[1].split("// ---- celebration", 1)[0]


def test_a_new_round_takes_the_screen_from_the_quarterfinals_on():
    # Owner, 2026-10-14: no banner over the cards ("8강 진출 16강 진출이 음식이랑 같이 떠 있어");
    # from 8강 a black full-screen beat, 결승 with the finalists' crash. Nothing for 16강.
    html = (ROOT / "worldcup.html").read_text(encoding="utf-8")
    css = (ROOT / "css/worldcup.css").read_text(encoding="utf-8")
    module = splash_module()
    assert "wcBanner" not in html and "wc-banner" not in css and "function banner" not in module
    spec = re.search(r"var SPLASH = \{(.*?)\n  \};", module, re.S).group(1)
    assert re.findall(r"^\s*(\d+): \{ key: '(wc\.splash\.\w+)', text: '([^']+)', ms: (\d+) \}", spec, re.M) == [
        ("8", "wc.splash.quarter", "8강 진출!", "800"), ("4", "wc.splash.semi", "4강 진출!", "800"),
        ("2", "wc.splash.final", "결승!", "2000")]
    ko = json.loads((ROOT / "i18n/ko.json").read_text(encoding="utf-8"))
    en = json.loads((ROOT / "i18n/en.json").read_text(encoding="utf-8"))
    assert [ko[f"wc.splash.{k}"] for k in ("quarter", "semi", "final")] == ["8강 진출!", "4강 진출!", "결승!"]
    assert [en[f"wc.splash.{k}"] for k in ("quarter", "semi", "final")] == ["Quarterfinals!", "Semifinals!", "The Final!"]
    assert not any(k.startswith("wc.banner") for k in ko)
    # A top-layer popover above the navigation, decoration only; reduced motion, forced colours or
    # no popover support: straight to the match.
    assert '<div class="wc-splash" id="wcSplash" popover="manual" aria-hidden="true"></div>' in html
    assert "!reduced && !(forcedColors && forcedColors.matches)" in module and "typeof splashEl.showPopover === 'function'" in module
    assert "if (reduced) { renderMatch(true); return; }" in (ROOT / "js/worldcup.js").read_text(encoding="utf-8")


def test_the_splash_moves_only_transform_and_opacity_and_flashes_once_in_white():
    module = splash_module()
    moved = set()
    for call in re.findall(r"track\([^;]*?\]\]\);", module, re.S):
        moved |= set(re.findall(r"[{,] (\w+): (?!function)", call))
    assert moved == {"transform", "opacity"}, moved
    assert module.count("'wc-splash-flash'") == 1                       # one flash, in the final only
    css = (ROOT / "css/worldcup.css").read_text(encoding="utf-8")
    flash = css.rsplit(".wc-splash-flash {", 1)[1].split("}", 1)[0]          # its own rule, after the shared one
    assert "background: #fff;" in flash
    # Black and white with the wordmark gradient: never red, never the old red-brown accent.
    block = css.split("/* The round splash", 1)[1].split(".wc-confetti {", 1)[0]
    colours = set(re.findall(r"#[0-9a-fA-F]{3,6}\b", block))
    assert colours <= {"#000", "#fff", "#ec4899", "#a855f7", "#6366f1", "#c44fd0"}, colours
    # The shake stays within 8 px; the stages are 0.8 s and 2 s.
    amps = [float(a) for a in re.findall(r"amp = phone \? (\d+) : (\d+)", module)[0]]
    assert max(amps) <= 8


def test_the_splash_font_is_jua_cut_to_its_letters_with_a_fallback():
    html = (ROOT / "worldcup.html").read_text(encoding="utf-8")
    link = re.search(r'<link href="(https://fonts\.googleapis\.com/css2\?family=Jua[^"]+)" rel="stylesheet" />', html).group(1)
    letters = set(parse_qs(urlparse(link).query)["text"][0])
    for lang in ("ko", "en"):
        strings = json.loads((ROOT / f"i18n/{lang}.json").read_text(encoding="utf-8"))
        for key in ("wc.splash.quarter", "wc.splash.semi", "wc.splash.final", "wc.vs"):
            assert set(strings[key]) - {" "} <= letters, (lang, key, set(strings[key]) - letters)
    css = (ROOT / "css/worldcup.css").read_text(encoding="utf-8")
    title = css.split(".wc-splash-title,\n.wc-splash-vs {", 1)[1].split("}", 1)[0]
    assert "font-family: 'Jua', 'Noto Sans KR'," in title and "sans-serif;" in title and "font-synthesis: none;" in title


def test_a_skip_is_never_a_pick():
    script = (ROOT / "js/worldcup.js").read_text(encoding="utf-8")
    pick = script.split("function pick(side) {", 1)[1]
    assert pick.lstrip().startswith("if (splash) { endSplash('skip'); return; }")
    assert "splashEl.addEventListener('click', function () { endSplash('skip'); });" in script
    assert "if (e.detail && Date.now() < quietUntil) return;" in script                 # a tap just after
    keyup = script.split("document.addEventListener('keyup', function (e) {", 1)[1].split("}, true);", 1)[0]
    assert "e.preventDefault();" in keyup and "heldKey" in keyup                         # Space clicks on release
    # The match is rendered and focused before the splash, and gets focus again after it.
    assert "renderMatch(true, splashing);\n      if (splashing) showSplash(round);" in script
    assert "if (reason !== 'quiet' && view === 'match') cards[0].focus({ preventScroll: true });" in script
