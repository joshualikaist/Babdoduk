"""The 먹방 world cup (worldcup.html, owner P4 2026-10-13): a bracket of catalog dishes from
data/content/worldcup.json, played in the browser; on lab only, a finished game is also counted
anonymously (tests/test_worldcup_stats.py). Static checks; the keyboard play-through runs in
scripts/check_site_ui.py (worldcup_play), and the round splash with motion in worldcup_splash."""
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
    assert "shuffle(poolOf(cat)).slice(0, size)" in script    # a fresh draw from the chosen category each game


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

    def event_errors():
        return [e for e in page_content.content_errors(tmp_path) if e.startswith("events.json")]

    assert any("worldcup.html" in e and "not a page of this site" in e for e in event_errors())
    (tmp_path / "worldcup.html").write_text("<!doctype html>", encoding="utf-8")
    assert event_errors() == []


def test_the_page_reads_only_static_files_and_keeps_results_in_this_browser():
    html = (ROOT / "worldcup.html").read_text(encoding="utf-8")
    assert re.findall(r'<script\s+src="([^"]+)"', html) == ["js/site.js", "js/ggongbab-public-config.js", "js/worldcup-gate.js", "js/worldcup.js"]
    script = (ROOT / "js/worldcup.js").read_text(encoding="utf-8")
    assert set(re.findall(r"getJson\('([^']+)'\)", script)) == {"data/foods/catalog.json"}
    # data/content/ is never deployed (.vercelignore): the sync writes the dishes into the page.
    embedded = re.search(r"window\.BABDODUK_WORLDCUP = (\{.*\});", html).group(1)
    assert json.loads(embedded)["dishes"] == CUP["dishes"]
    assert json.loads(embedded)["categories"] == CUP["categories"]
    for forbidden in ("supabase", "XMLHttpRequest", "WebSocket", "sendBeacon", "createClient"):
        assert forbidden not in script, forbidden
    # Stage 2 (lab): the only write is one finished game through the validating RPC.
    assert re.findall(r"api\('([a-z_/]+)", script) == ["worldcup_dish_stats", "worldcup_totals", "rpc/worldcup_record_game"]
    assert "method: body ? 'POST' : 'GET'" in script and "log.length !== size - 1" in script
    assert "var KEY = 'babdoduk-worldcup';" in script and "localStorage.setItem(KEY" in script
    assert html.count('<button type="button" class="wc-card"') == 2
    assert 'id="wcStatus" role="status"' in html and "'wc.title': 'Babdoduk Food World Cup'" in html
    # Pictures are decoration inside the pick buttons (the button names the dish); no claims about
    # what is on sale: the catalog is general information.
    main = html.split("<main", 1)[1].split("</main>", 1)[0]
    assert re.findall(r"<img [^>]*>", main) and all('alt=""' in tag for tag in re.findall(r"<img [^>]*>", main))
    # One small photo chip, no price sentence (owner 2026-10-14); the photos are credited by name large.
    ko = json.loads((ROOT / "i18n/ko.json").read_text(encoding="utf-8"))
    en = json.loads((ROOT / "i18n/en.json").read_text(encoding="utf-8"))
    assert (ko["wc.photoChip"], en["wc.photoChip"]) == ("사진 위키미디어 공용(잘라서 줄임)", "Photos: Wikimedia Commons (cropped, resized)")
    assert html.count('<p class="wc-chip"><span aria-hidden="true">📷</span> <span data-i18n="wc.photoChip">') == 1
    assert "판매 여부" not in html and "wc.scope" not in html and "wc-scope" not in html and "wc.scope" not in ko | en


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
    # The owner says 8강, 4강, 결승: the semifinal's round header too (English keeps Semifinal).
    assert (ko["wc.round.semi"], en["wc.round.semi"]) == ("4강", "Semifinal")
    assert "준결승" not in (ROOT / "js/worldcup.js").read_text(encoding="utf-8")
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


# ---- categories (owner, 2026-10-14: "너무 좋아") -------------------------------------------------------
# What the owner approved: 전체 plus seven categories, each played as a 32강. The pool was derived from
# the catalog's cuisineGroup, so the counts below are exactly the approved table.
CATEGORY_COUNTS = {"korean": 268, "chinese": 75, "japanese": 75, "western": 132, "world": 86, "snack": 35, "dessert": 92}


def catalog_items():
    items = {}
    for pack in json.loads((ROOT / "data/foods/catalog.json").read_text(encoding="utf-8"))["packs"]:
        for item in json.loads((ROOT / pack["src"]).read_text(encoding="utf-8"))["items"]:
            items[item["id"]] = item
    return items


def test_every_pool_dish_is_in_exactly_one_category_and_the_counts_are_the_approved_ones():
    categories = CUP["categories"]
    assert set(categories) == set(CUP["dishes"])                      # one entry per dish, none for a stranger
    assert set(categories.values()) == set(page_content.WORLDCUP_CATEGORIES) == set(CATEGORY_COUNTS)
    counts = {key: sum(1 for c in categories.values() if c == key) for key in CATEGORY_COUNTS}
    assert counts == CATEGORY_COUNTS
    assert sum(counts.values()) == len(CUP["dishes"]) == 763            # 전체
    assert min(counts.values()) >= CUP["size"]                          # every category fills a 32강
    items = catalog_items()
    for dish, key in categories.items():                               # and it is the catalog's own cuisineGroup
        assert key == page_content.worldcup_category(items[dish]), dish
    assert not [g for g in {i["cuisineGroup"] for i in items.values()} if g not in page_content.WORLDCUP_CATEGORY_BY_GROUP]


def test_a_dish_without_or_in_the_wrong_category_is_refused(tmp_path):
    shutil.copytree(ROOT / "data/foods", tmp_path / "data/foods")
    shutil.copytree(ROOT / "images/worldcup", tmp_path / "images/worldcup")
    (tmp_path / "data/content").mkdir(parents=True)
    first = CUP["dishes"][0]

    def errors(categories):
        (tmp_path / "data/content/worldcup.json").write_text(json.dumps(dict(CUP, categories=categories)), encoding="utf-8")
        return page_content.worldcup_errors(tmp_path)

    assert errors(CUP["categories"]) == []
    assert any(f"{first} has no category" in e for e in errors({k: v for k, v in CUP["categories"].items() if k != first}))
    assert any("not in the bracket" in e for e in errors(dict(CUP["categories"], **{"kr-made-up-dish": "korean"})))
    assert any("does not exist" in e for e in errors(dict(CUP["categories"], **{first: "brunch"})))
    assert any(f"{first} is in the category 'dessert', but the catalog says" in e
               for e in errors(dict(CUP["categories"], **{first: "dessert"})))
    thin = {d: ("korean" if c == "snack" else c) for d, c in CUP["categories"].items()}      # no snacks left
    assert any("the category 'snack' has 0 dishes, fewer than a game of 32" in e for e in errors(thin))


def test_the_start_screen_offers_the_categories_with_counts_and_keeps_the_choice_in_the_saved_game():
    html = (ROOT / "worldcup.html").read_text(encoding="utf-8")
    script = (ROOT / "js/worldcup.js").read_text(encoding="utf-8")
    css = (ROOT / "css/worldcup-entry.css").read_text(encoding="utf-8")        # the start screen's styles
    ko = json.loads((ROOT / "i18n/ko.json").read_text(encoding="utf-8"))
    en = json.loads((ROOT / "i18n/en.json").read_text(encoding="utf-8"))
    keys = ["all", *CATEGORY_COUNTS]
    assert re.search(r"var CATEGORIES = \[(.*?)\];", script).group(1).replace("'", "").replace(" ", "").split(",") == keys
    assert [ko[f"wc.cat.{k}"] for k in keys] == ["전체", "한식", "중식", "일식", "양식", "아시아·세계", "분식·간식", "디저트·카페"]
    assert [en[f"wc.cat.{k}"] for k in keys] == ["All", "Korean", "Chinese", "Japanese", "Western", "Asian & world",
                                                 "Snacks", "Desserts & café"]
    # The tiles sit above the start button, in a labelled group of toggle buttons on a 3 x 3 board
    # (owner 2026-10-14: big tiles rather than pills). The name is the visible text; the emoji is decoration.
    intro = html.split('id="wcIntro"', 1)[1].split('id="wcStart"', 1)[0]
    assert 'id="wcCats" role="group" aria-labelledby="wcCatsLabel"' in intro
    assert "tile.setAttribute('aria-pressed', cat === category ? 'true' : 'false')" in script
    assert "emoji.setAttribute('aria-hidden', 'true');" in script
    assert ".wc-tile:focus-visible" in css and "min-height: 96px" in css.split(".wc-tile {", 1)[1].split("}", 1)[0]
    assert "grid-template-columns: repeat(3, minmax(0, 1fr))" in css.split(".wc-tiles {", 1)[1].split("}", 1)[0]
    # The saved game records its category; an older one has none and is the whole pool.
    assert "category: cat };" in script and "if (g.category == null) return 'all';" in script
    assert "var KEY = 'babdoduk-worldcup';" in script and "{ v: 1, set: signature()" in script      # old saves stay readable
    # The category is shown while playing, on the result, in the share text and on the image.
    assert "$('wcGame').textContent = gameLabel(game.category);" in script
    assert "$('wcResultGame').textContent = gameLabel(result.category);" in script
    assert "{cat}" in ko["wc.shareText"] and "{cat}" in en["wc.shareText"] and "gameLabel(result.category) + ' · '" in script
    assert (ko["wc.catGame"], en["wc.catGame"]) == ("{cat} {n}강", "{cat} · Round of {n}")


# ---- the start screen and the start gacha (owner, 2026-10-14: "초입이 재미있어야") -----------------------
def module(start, end):
    script = (ROOT / "js/worldcup.js").read_text(encoding="utf-8")
    return script.split(start, 1)[1].split(end, 1)[0]


def moved_properties(code):
    """Every property a track() or an .animate() keyframe list in `code` moves."""
    moved = set()
    for call in re.findall(r"track\([^;]*?\]\]\);", code, re.S):
        moved |= set(re.findall(r"[{,] (\w+): (?!function)", call))
    for call in re.findall(r"\.animate\(\[.*?\]", code, re.S):
        moved |= set(re.findall(r"[{,] (\w+): ", call)) - {"offset"}
    return moved


def test_the_start_screen_has_the_owners_headline_and_no_notes():
    html = (ROOT / "worldcup.html").read_text(encoding="utf-8")
    ko = json.loads((ROOT / "i18n/ko.json").read_text(encoding="utf-8"))
    en = json.loads((ROOT / "i18n/en.json").read_text(encoding="utf-8"))
    assert (ko["wc.intro.title"], en["wc.intro.title"]) == ("오늘의 {n}강, 뭐가 나올까?", "What’s in today’s round of {n}?")
    assert (ko["wc.intro.tone"], en["wc.intro.tone"]) == ("시험기간으로 지친 당신! 메뉴나 골라~", "Exam week got you? Just pick a menu~")
    # The static page (before the script) already says it, the round on the highlighter.
    assert '<h3 class="wc-intro-title" id="wcIntroTitle">오늘의 <span class="wc-hl">32강</span>, 뭐가 나올까?</h3>' in html
    # The two notes under the button are gone (owner's mark-up), with their keys, and so is the old line.
    for gone in ("wc.note", "wc.rankingNote"):
        assert gone not in ko and gone not in en and gone not in html
    assert "이 브라우저에 저장돼요" not in html and "익명으로 집계" not in html and "wcStatsNote" not in html
    assert "700개가 넘는 메뉴 중 무작위로 뽑아요" not in html.split('id="wcIntro"', 1)[1].split("</main>", 1)[0]
    # The display lettering is Jua, cut to the letters of its labels in both languages.
    link = re.search(r'<link href="(https://fonts\.googleapis\.com/css2\?family=Jua[^"]+)" rel="stylesheet" />', html).group(1)
    letters = set(parse_qs(urlparse(link).query)["text"][0])
    for strings in (ko, en):
        for key in page_content.WORLDCUP_JUA_KEYS:
            assert set(re.sub(r"\{\w+\}", "", strings[key])) <= letters, key
    css = "".join((ROOT / f"css/{name}.css").read_text(encoding="utf-8") for name in ("worldcup", "worldcup-entry"))
    assert "background-clip: text" not in css                   # the highlighter is a background, never gradient text
    assert "#b43d27" not in css and "#f45e45" not in (ROOT / "js/worldcup.js").read_text(encoding="utf-8")


def test_the_tiles_preview_the_dishes_the_next_game_really_draws():
    script = (ROOT / "js/worldcup.js").read_text(encoding="utf-8")
    emoji = dict(re.findall(r"(\w+): '([^']+)'", re.search(r"var CATEGORY_EMOJI = \{(.*?)\};", script, re.S).group(1)))
    assert emoji == {"all": "🎲", "korean": "🍚", "chinese": "🥟", "japanese": "🍣", "western": "🍝", "world": "🍜",
                     "snack": "🍢", "dessert": "🍰"}
    # Choosing draws the bracket; the photos are five of it; a start from this screen plays that bracket.
    assert "pending = { cat: cat, ids: draw(cat) };" in script
    assert "(pending ? pending.ids.slice(2, 7) : [])" in script
    assert "view === 'intro' && pending && pending.cat === cat ? pending.ids : draw(cat)" in script
    # 아무거나 lands on another category, at once with reduced motion, and says which.
    assert "c !== category" in script and "if (!moving()) { landSpin(target); return; }" in script
    ko = json.loads((ROOT / "i18n/ko.json").read_text(encoding="utf-8"))
    assert (ko["wc.cat.random"], ko["wc.preview"], ko["wc.catLanded"]) == ("아무거나", "이 중에서 나와요!", "{cat} 당첨!")
    # The start screen's motion moves only transform, scale and opacity; arrival runs are bounded.
    intro = module("// ---- the start screen", "// `instant`: a round splash")
    assert moved_properties(intro) <= {"transform", "scale", "opacity"}, moved_properties(intro)
    assert "iterations: arriving ? 3 : 2" in intro and "iterations: arriving ? 2 : 1" in intro


def test_the_start_gacha_plays_on_a_start_only_and_never_with_reduced_motion():
    script = (ROOT / "js/worldcup.js").read_text(encoding="utf-8")
    gacha = module("// ---- start gacha", "// ---- result image")
    # Only the starts open it; 이어하기 never does.
    assert "$('wcStart').addEventListener('click', begin);" in script and "$('wcNew').addEventListener('click', begin);" in script
    assert "function begin() {\n    if (locked()) return;\n    stopSpin(true);" in script and "    start(category, true);\n  }" in script
    assert "function resume() {\n    if (locked()) return;\n    if (!game) { start(category, false); return; }\n    show('match');\n    renderMatch(true);\n  }" in script
    # The game is stored and the match rendered, focused and announced before it opens.
    assert "store();                                            // the draw is kept before anything moves" in script
    assert "if (animate && canGacha()) {\n      renderMatch(true, true);\n      showGacha();" in script
    assert "!reduced && !(forcedColors && forcedColors.matches) && !document.hidden" in gacha
    assert "typeof splashEl.showPopover === 'function'" in gacha
    # It plays in the splash's popover, so a tap or a key skips it and never picks (test_a_skip_is_never_a_pick).
    assert "splashEl.setAttribute('data-round', 'start');" in gacha and "splash = {" in gacha
    # About 5 s, only transform, scale and opacity, no flash, a jolt of at most 4 px.
    end = int(re.search(r"end: (\d+) \}", gacha).group(1))
    assert 4500 <= end <= 5200
    assert moved_properties(gacha) <= {"transform", "scale", "opacity"}, moved_properties(gacha)
    assert "wc-splash-flash" not in gacha and "Flash" not in gacha
    jolts = [abs(int(x)) for x in re.findall(r"translate\((-?\d+)px, 0px\)' \}\]", gacha)]
    assert jolts and max(jolts) <= 4
    # One line of text at a time: the drawing line is gone before the question comes.
    ko = json.loads((ROOT / "i18n/ko.json").read_text(encoding="utf-8"))
    assert (ko["wc.gacha.drawing"], ko["wc.gacha.ask"]) == ("{game} 뽑는 중…", "너의 최애는?")
    assert "[tD + 120, { transform: 'translateY(0px)', opacity: 0 }]" in gacha
    assert "[tD + 200, { transform: 'scale(1.6)', opacity: 0 }" in gacha


# ---- the start screen in the news page's card (owner, 2026-10-14) ------------------------------------
def event_page():
    return (ROOT / "event.html").read_text(encoding="utf-8")


def test_the_event_card_shows_the_start_screen_instead_of_a_teaser_and_a_button():
    html = event_page()
    events = json.loads((ROOT / "data/content/events.json").read_text(encoding="utf-8"))
    cup_event = next(a for a in events["activities"] if a.get("link") == "worldcup.html")
    assert cup_event["entry"] == "worldcup" and "pictures" not in cup_event
    # The teaser photos with their vs badge, their credit and the 지금 해보기 button are gone.
    for gone in ("event-teaser", "event.e2.credit", "Startandstar", "event.cta.page'", "지금 해보기"):
        assert gone not in html and gone not in (ROOT / "css/event.css").read_text(encoding="utf-8"), gone
    row = html.split('data-i18n="event.e2.summary"', 1)[1].split("</li>", 1)[0]
    entry = row.split('<div class="wc-embed" data-wc-embed>', 1)[1].split('<a class="event-link"', 1)[0]
    # The same markup as worldcup.html's start screen: one source (page_content.worldcup_entry).
    wc = (ROOT / "worldcup.html").read_text(encoding="utf-8")
    wc_entry = wc.split('id="wcIntro" hidden>', 1)[1].split('<div class="wc-view wc-match"', 1)[0]
    squash = lambda markup: re.sub(r"\s+", " ", markup)
    for part in page_content.worldcup_entry():
        assert squash(part.strip()) in squash(entry) and squash(part.strip()) in squash(wc_entry), part
    assert 'id="wcStart"' in entry and 'id="wcCats" role="group" aria-labelledby="wcCatsLabel"' in entry
    assert entry.count('<p class="wc-chip">') == 1 and 'id="wcStatus" role="status"' in entry     # the one chip, announcements
    # The card keeps its date range, title and state; the link stays for a past row and a failed load.
    assert '<time datetime="2026-10-16">2026.10.16</time> — <time datetime="2026-10-23">10.23</time>' in html
    assert 'href="worldcup.html" data-event-page><span data-event-cta>페이지 보기</span>' in row
    assert "자세히" in row


def test_the_event_page_loads_the_world_cup_only_for_its_running_card():
    html = event_page()
    # Static: the small stylesheet and the Jua letters; the script and its data are added by the page
    # script only while a row that shows the start screen is running or coming up.
    assert 'href="css/worldcup-entry.css"' in html and "family=Jua" in html
    # (the launch gate is the one script it carries up front: js/worldcup-gate.js, a few hundred bytes of logic)
    assert re.findall(r'<script[^>]+src="(js/worldcup[^"]*)"', html) == ["js/worldcup-gate.js"] and "BABDODUK_WORLDCUP" not in html
    assert "['js/worldcup-entry-data.js', 'js/worldcup.js']" in html and "script.async = false;" in html
    assert '.event-item:not([data-band="past"]) [data-wc-embed]' in html
    assert len(html.encode("utf-8")) < 40_000                 # no pool inlined: the page stays light
    # The slim data: names, categories and the photo path; no photo credits, no 1.3 MB catalog.
    data = (ROOT / "js/worldcup-entry-data.js").read_text(encoding="utf-8")
    slim = json.loads(re.search(r"window.BABDODUK_WORLDCUP = (\{.*\});", data).group(1))
    assert sorted(slim) == ["dishes", "photoPath", "size"] and slim["size"] == 32 and slim["photoPath"] == page_content.WORLDCUP_PHOTO_PATH
    assert list(slim["dishes"]) == CUP["dishes"] and {d: v[2] for d, v in slim["dishes"].items()} == CUP["categories"]
    names = page_content.catalog_names(ROOT)
    assert all(v[:2] == names[d] for d, v in slim["dishes"].items())
    assert "author" not in data and "license" not in data and len(data.encode("utf-8")) < 60_000
    assert all(photo["image"] == page_content.WORLDCUP_PHOTO_PATH.format(id=dish) for dish, photo in CUP["photos"].items())
    # The page's table carries the start screen's keys only, not the whole `wc` family.
    table = html.split("window.BABDODUK_STR = {", 1)[1]
    keys = set(re.findall(r"'(wc\.[\w.]+)':", table.split("    en: {", 1)[0]))
    assert keys == set(page_content.WORLDCUP_ENTRY_KEYS)


def test_the_embedded_start_opens_the_game_page_and_the_game_page_starts_only_for_go():
    script = (ROOT / "js/worldcup.js").read_text(encoding="utf-8")
    # In the card there is no match, result, splash or stored game; the start navigates.
    assert "var embedded = !document.getElementById('wcMatch');" in script
    assert "location.href = 'worldcup.html?cat=' + encodeURIComponent(category) + '&go=1';" in script
    assert "if (!embedded) restore();" in script and "if (embedded) return;" in script
    assert "data/foods/catalog.json" in script and "embedded ? new Promise" in script       # the catalog only on the game page
    # The game page: only go=1; a category is checked against the known ones, else the whole pool;
    # the address is cleaned; the start is the same call as the button's.
    requested = module("function requested() {", "function cleanAddress()")
    assert "query.get('go') !== '1'" in requested and "CATEGORIES.indexOf(cat) >= 0 && poolOf(cat).length >= size ? cat : 'all'" in requested
    assert "history.replaceState(null, '', location.pathname + location.hash)" in script
    assert "// as if 32강 시작 had been pressed here\n      start(asked, true);" in script
    # Starting replaces a saved game exactly as 새로 시작 does (start(cat, true) keeps its undo step).
    assert "$('wcNew').addEventListener('click', begin);" in script


def test_the_entry_markup_and_the_chip_have_one_source():
    blocks = page_content.worldcup_blocks()
    assert blocks["worldcup-entry"] == page_content.worldcup_entry() and blocks["worldcup-chip"] == page_content.worldcup_chip()
    css = (ROOT / "css/worldcup-entry.css").read_text(encoding="utf-8")
    assert ".wc-chip {" in css and ".wc-tile {" in css and ".wc-tile {" not in (ROOT / "css/worldcup.css").read_text(encoding="utf-8")
    for page in ("worldcup.html", "event.html"):
        assert 'href="css/worldcup-entry.css"' in (ROOT / page).read_text(encoding="utf-8")


def test_an_entry_must_belong_to_the_world_cup_page(tmp_path):
    shutil.copytree(ROOT / "data/content", tmp_path / "data/content")
    (tmp_path / "worldcup.html").write_text("<!doctype html>", encoding="utf-8")
    path = tmp_path / "data/content/events.json"
    events = json.loads(path.read_text(encoding="utf-8"))
    cup_event = next(a for a in events["activities"] if a.get("link") == "worldcup.html")
    assert [e for e in page_content.content_errors(tmp_path) if e.startswith("events.json")] == []
    cup_event["link"] = "https://example.com/post"
    path.write_text(json.dumps(events), encoding="utf-8")
    assert any("shows the entry 'worldcup'" in e for e in page_content.content_errors(tmp_path))


def test_every_photo_must_follow_the_shared_path(tmp_path):
    shutil.copytree(ROOT / "data/foods", tmp_path / "data/foods")
    shutil.copytree(ROOT / "images/worldcup", tmp_path / "images/worldcup")
    (tmp_path / "data/content").mkdir(parents=True)
    dish = CUP["dishes"][0]
    (tmp_path / "images/worldcup/other.jpg").write_bytes(b"x")
    photos = dict(CUP["photos"], **{dish: dict(CUP["photos"][dish], image="images/worldcup/other.jpg")})
    (tmp_path / "data/content/worldcup.json").write_text(json.dumps(dict(CUP, photos=photos)), encoding="utf-8")
    assert any(f"{dish} shows images/worldcup/other.jpg, not images/worldcup/{dish}.jpg" in e
               for e in page_content.worldcup_errors(tmp_path))


# ---- the launch gate (owner 2026-10-14): 10/16 - 10/23, lab opens it early --------------------------------------

EVENTS = json.loads((ROOT / "data/content/events.json").read_text(encoding="utf-8"))
CUP_EVENT = next(a for a in EVENTS["activities"] if a.get("entry") == "worldcup")


def gate_script():
    return (ROOT / "js/worldcup-gate.js").read_text(encoding="utf-8")


def test_the_launch_window_is_the_events_dates_written_into_the_gate():
    assert (CUP_EVENT["start"], CUP_EVENT["end"]) == ("2026-10-16", "2026-10-23")
    window = json.loads(re.search(r"window.BABDODUK_WC_WINDOW = (\{.*\});", gate_script()).group(1))
    expected = {"start": CUP_EVENT["start"], "end": CUP_EVENT["end"]}
    if "previewFrom" in CUP_EVENT:                      # lab only: production's data carries none
        expected["previewFrom"] = CUP_EVENT["previewFrom"]
    assert window == expected and window == page_content.worldcup_gate()
    assert "previewFrom" not in window or window["previewFrom"] < window["start"]
    # The event's own duration text names the same days.
    assert "10월 16일" in CUP_EVENT["details"]["duration"]["ko"] and "10월 23일" in CUP_EVENT["details"]["duration"]["ko"]
    assert "October 16" in CUP_EVENT["details"]["duration"]["en"] and "October 23" in CUP_EVENT["details"]["duration"]["en"]


def test_only_lab_and_localhost_honour_the_preview_date():
    script = gate_script()
    assert script.count("previewFrom") >= 2 and "location.hostname" in script
    assert re.search(r"host === 'babdoduk-lab\.vercel\.app' \|\| host === 'localhost' \|\| host === '127\.0\.0\.1'", script)
    # The page never trusts a query string or storage for it: the date comes from the data and the host alone.
    assert "location.search" not in script and "localStorage" not in script


def test_a_preview_date_needs_an_entry_and_is_not_after_the_start(tmp_path):
    shutil.copytree(ROOT / "data/content", tmp_path / "data/content")
    (tmp_path / "worldcup.html").write_text("<!doctype html>", encoding="utf-8")
    path = tmp_path / "data/content/events.json"

    def errors(**change):
        data = json.loads(path.read_text(encoding="utf-8"))
        item = next(a for a in data["activities"] if a.get("entry") == "worldcup")
        item.update(change)
        path.write_text(json.dumps(data), encoding="utf-8")
        return [e for e in page_content.content_errors(tmp_path) if "previewFrom" in e]

    assert errors() == []
    assert errors(previewFrom="2026-10-17") and not errors(previewFrom="2026-10-16")
    data = json.loads(path.read_text(encoding="utf-8"))
    first = data["activities"][0]
    first["previewFrom"] = "2026-05-01"                     # an activity without a start screen has none
    path.write_text(json.dumps(data), encoding="utf-8")
    assert any("previewFrom" in e for e in page_content.content_errors(tmp_path))


def test_every_page_that_shows_the_world_cup_loads_the_gate_before_its_own_script():
    for name, own in (("worldcup.html", '<script src="js/worldcup.js">'), ("event.html", "var rows = [].slice"),
                      ("index.html", '<script src="js/home.js">')):
        html = (ROOT / name).read_text(encoding="utf-8")
        assert html.count('<script src="js/worldcup-gate.js"></script>') == 1, name
        tag = html.index('<script src="js/worldcup-gate.js">')
        assert tag < html.index(own), name
        assert html.index("window.BABDODUK_STR") < tag, name        # the texts it fills are there first


def test_the_start_screen_has_a_locked_pill_and_an_ended_note_driven_by_the_gate():
    entry = "\n".join(page_content.worldcup_entry())
    assert 'id="wcLocked" data-wc-show="soon" hidden' in entry and "data-wc-countdown" in entry and 'data-wc-fmt="wc.locked"' in entry
    assert 'class="wc-ended" data-wc-show="ended" hidden' in entry
    script = (ROOT / "js/worldcup.js").read_text(encoding="utf-8")
    # Nothing starts before the launch, by any path: the start, 이어하기, a start from the address and the games themselves.
    for guarded in ("function start(cat, animate) {\n    if (locked()) return;", "function resume() {\n    if (locked()) return;",
                    "function begin() {\n    if (locked()) return;", "if (asked && locked()) asked = null;"):
        assert guarded in script, guarded


def test_the_gate_texts_exist_in_both_languages_on_the_pages_that_show_them():
    ko = json.loads((ROOT / "i18n/ko.json").read_text(encoding="utf-8"))
    en = json.loads((ROOT / "i18n/en.json").read_text(encoding="utf-8"))
    keys = [*page_content.WORLDCUP_GATE_KEYS, "wc.ended", "wc.state.soon", "home.wc.title", "home.wc.soon", "home.wc.live",
            "home.wc.cta.soon", "home.wc.cta.live"]
    for key in keys:
        assert ko[key] and en[key], key
    assert ko["wc.locked"] == "{date} 오픈" and en["wc.locked"] == "Opens {date}"
    assert ko["wc.state.soon"] == "{date} 공개 예정" and ko["home.wc.soon"] == "{date} 오픈!"
    for name in ("event.html", "index.html"):
        html = (ROOT / name).read_text(encoding="utf-8")
        for key in page_content.WORLDCUP_GATE_KEYS:
            assert f"'{key}':" in html, (name, key)


def test_the_home_promo_is_text_from_i18n_with_real_dish_photos_and_hides_itself_after_the_end():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    promo = html.split('<section class="home-wc"', 1)[1].split("</section>", 1)[0]
    assert 'data-wc-show="soon live" hidden' in html and 'class="home-wc-cta home-wc-cta--soon" href="event.html"' in promo
    assert 'class="home-wc-cta home-wc-cta--live" href="worldcup.html"' in promo
    for photo in re.findall(r'src="(images/worldcup/[^"]+)"', promo):
        assert (ROOT / photo).is_file() and photo.split("/")[-1][:-4] in CUP["photos"], photo
    assert len(re.findall(r'src="images/worldcup/', promo)) == 2
    assert html.index('<div class="home-top">') < html.index('<section class="home-wc"') < html.index('<section class="home-hero"')
    assert "family=Jua" in html                                                                      # the letters the sync asks for
    css = (ROOT / "css/index.css").read_text(encoding="utf-8")
    assert "linear-gradient(115deg, #be185d, #a21caf 50%, #4f46e5)" in css and ".home-wc[hidden]" in css
