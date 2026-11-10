"""오늘 뭐 먹지 (choose.html, js/pick.js, owner 2026-11-05): what the capsule machine draws from and how, run
in Node on the real dish catalog. The page itself is checked by scripts/check_site_ui.py pick_tools."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def run(expr: str):
    script = ("globalThis.window = {}; globalThis.document = { getElementById: () => null };"
              "const fs = require('fs'); eval(fs.readFileSync('js/pick.js', 'utf8'));"
              "const P = window.BabdodukPick;"
              "const foods = JSON.parse(fs.readFileSync('data/foods/catalog.json', 'utf8')).packs"
              "  .flatMap(p => JSON.parse(fs.readFileSync(p.src, 'utf8')).items);"
              f"console.log(JSON.stringify({expr}));")
    out = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_every_kind_of_delivery_food_has_dishes_and_each_dish_one_kind():
    kinds = run("Object.fromEntries(Object.entries(P.categorize(foods)).map(([k, v]) => [k, v.map(f => f.nameKo)]))")
    assert set(kinds) == {"chicken", "pizza", "burger", "jokbal", "chinese", "bunsik", "japanese", "asian", "western", "korean"}
    assert all(len(names) >= 3 for names in kinds.values()), {k: len(v) for k, v in kinds.items()}
    every = [name for names in kinds.values() for name in names]
    assert len(every) == len(set(every))                                   # one kind each
    assert "족발" in kinds["jokbal"] and "짜장면" in kinds["chinese"] and "떡볶이" in kinds["bunsik"]
    assert "마르게리타 피자" in kinds["pizza"] and "치즈버거" in kinds["burger"]
    assert "치킨버거" not in kinds["chicken"] and "치킨버거" in kinds["burger"]   # a chicken burger is a burger
    assert not set(kinds["chicken"]) & {"치킨반미", "하이난치킨라이스"}
    only_delivery = run("P.categorize(foods.map(f => Object.assign({}, f, {diningMode: ['restaurant']})))")
    assert only_delivery == {}                                             # dishes nobody delivers stay out


def test_only_main_campus_meals_still_being_served_are_offered():
    day = {"restaurants": [
        {"id": "a", "name": "카이마루", "building": "N11", "breakfast": {"items": ["죽"], "hours": "08:00~09:00"},
         "lunch": {"items": ["밥"], "hours": "11:30~13:30"}, "dinner": {"items": ["국수"]}},
        {"id": "b", "name": "서맛골", "building": "W2", "lunch": {"items": []}},
        {"id": "c", "name": "문지캠퍼스", "building": "문지", "lunch": {"items": ["밥"], "hours": "11:30~13:30"}},
        {"id": "d", "name": "서울캠퍼스", "building": "서울", "dinner": {"items": ["밥"]}}]}
    noon = run(f"P.servingMeals({json.dumps(day)}, 12 * 60).map(s => s.resto.id + ':' + s.meal)")
    assert noon == ["a:lunch", "a:dinner"]                                  # breakfast over; no hours: usual end
    evening = run(f"P.servingMeals({json.dumps(day)}, 19 * 60 + 5).map(s => s.resto.id + ':' + s.meal)")
    assert evening == []


def test_a_menu_line_reads_without_allergen_numbers_or_the_calorie_line():
    assert run("P.cleanItems(['백미밥', '제육볶음(5,6,10)', '알감자조림(5,6*)', '[칼로리:890kcal]', '배추김치'])") == [
        "백미밥", "제육볶음", "알감자조림", "배추김치"]


def test_a_draw_stays_on_campus_seven_in_ten_and_is_a_delivery_dish_otherwise():
    meals = [{"resto": {"id": "a"}, "meal": "lunch"}, {"resto": {"id": "b"}, "meal": "lunch"}]
    dishes = [{"id": "x", "popularity": 1}, {"id": "y", "popularity": 3}]

    def draw(meals_, dishes_, values):
        seq = json.dumps(values)
        return run(f"(() => {{ const v = {seq}; let i = 0; const r = P.draw({json.dumps(meals_)}, {json.dumps(dishes_)}, () => v[i++]);"
                   " return r && (r.meal ? 'meal:' + r.meal.resto.id : 'dish:' + r.dish.id); })()")

    assert draw(meals, dishes, [0.69, 0.6]) == "meal:b"          # on campus, no campus menus: the cafeteria, then which meal
    assert draw(meals, dishes, [0.7, 0.2]) == "dish:x"           # delivery 3 in 10; weights 1 and 3: the first quarter is x
    assert draw(meals, dishes, [0.7, 0.3]) == "dish:y"
    assert draw([], dishes, [0.1]) == "dish:x"                   # no meal being served: always a dish
    assert draw(meals, [], [0.1]) == "meal:a"                    # no dishes: always a meal, no share drawn
    assert draw([], [], [0.5]) is None


def test_every_dish_the_machine_can_draw_has_a_kind():
    kinds = run("foods.filter(f => P.kindOf(f)).map(f => P.kindOf(f).id)")
    assert len(kinds) > 400 and set(kinds) <= {"chicken", "pizza", "burger", "jokbal", "chinese", "bunsik",
                                                "japanese", "asian", "western", "korean"}


def test_the_photo_credits_the_page_carries_are_the_world_cups_and_cover_every_drawable_photo():
    script = ("globalThis.window = globalThis; require('./js/pick-photos.js');"
              "console.log(JSON.stringify(window.BABDODUK_PICK_PHOTOS));")
    carried = json.loads(subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, check=True).stdout)
    cup = json.loads((ROOT / "data/content/worldcup.json").read_text(encoding="utf-8"))["photos"]
    drawn = set(run("foods.filter(f => P.kindOf(f) && f.popularity >= P.MIN_POPULARITY).map(f => f.id)"))
    assert drawn & set(cup) == set(carried["photos"])           # exactly the photographed dishes it can draw
    assert len(carried["photos"]) >= 20
    for dish_id, (author, licence, source, link) in carried["photos"].items():
        photo = cup[dish_id]
        assert (author, licence, source, carried["links"][link]) == (photo["author"], photo["license"], photo["source"], photo.get("licenseUrl", ""))
        assert (ROOT / "images/worldcup/thumb" / f"{dish_id}-320.webp").exists(), dish_id


def test_the_machine_draws_the_delivery_staples_not_the_catalogs_rarities():
    """Owner 2026-11-05: "배달음식이 너무나도 한국 정서와 조금 다른 것 같다". Only dishes rated 4 or 5."""
    names = set(run("foods.filter(f => P.kindOf(f) && f.popularity >= P.MIN_POPULARITY).map(f => f.nameKo)"))
    assert {"후라이드 치킨", "양념치킨", "짜장면", "짬뽕", "떡볶이", "마라탕", "족발", "보쌈", "김치찌개", "돈카츠"} <= names
    assert not names & {"루면", "비앙비앙면", "량피", "깨죽", "게국지", "홍어찜", "감자수프"}


def test_campus_menu_source_keeps_stores_sets_and_uncertain_prices():
    items = json.loads((ROOT / "data/foods/campus-kiosk.json").read_text(encoding="utf-8"))["items"]
    assert len(items) == 454 and len({i["id"] for i in items}) == 454
    assert len({i["store"] for i in items}) == 10
    assert all(i["name"] and i["category"] and isinstance(i["drawable"], bool) for i in items)
    assert all(i["priceWon"] is None or isinstance(i["priceWon"], int) and i["priceWon"] >= 0 for i in items)
    assert sum(i["priceWon"] is None for i in items) == 4
    assert any(i["name"] == "별리달리버터알밥+치킨+음료세트" and i["drawable"] for i in items)
    assert all(not i["drawable"] for i in items if i["name"] in {"공기밥", "공기밥 추가", "계란후라이", "돈까스 소스(30g)"})
    assert all(not i["drawable"] for i in items if i["name"] in {"김말이", "쿠키", "올리브 브레드", "군만두7p",
        "제육볶음추가(고기만)", "돼지불백추가(고기만)", "(추가)판모밀전용 육수 고명"})
    assert all(i["drawable"] for i in items if i["name"] in {"반미샌드위치T/O", "명란미니덮밥", "리코타치즈샐러드"})


def test_campus_pick_is_balanced_by_store_and_falls_back_when_sources_are_empty():
    campus = [{"store": "A", "name": "a1"}, {"store": "A", "name": "a2"}, {"store": "B", "name": "b1"}]
    items = json.dumps(campus)
    def draw(meals, dishes, numbers):
        return run(f"(() => {{let i=0, v={json.dumps(numbers)}; return P.draw({json.dumps(meals)}, {json.dumps(dishes)}, () => v[i++], {items});}})()")
    assert draw([], [{"id": "d"}], [0.2, 0.1, 0.9])["campus"]["name"] == "a2"
    assert draw([], [{"id": "d"}], [0.2, 0.9, 0.1])["campus"]["name"] == "b1"
    assert draw([], [{"id": "d"}], [0.8, 0.2])["dish"]["id"] == "d"
    assert draw([], [], [0.9, 0.1])["campus"]["name"] == "b1"
    assert draw([{"meal": "lunch"}], [], [0.1, 0.5])["meal"]["meal"] == "lunch"
    # Owner 2026-11-10: cafeteria and campus restaurants 7 in 10 together, delivery 3; cafeteria 2 of the 10, campus 5.
    lunch, dish = [{"meal": "lunch"}], [{"id": "d"}]
    assert draw(lunch, dish, [0.69, 0.28, 0.0])["meal"]["meal"] == "lunch"     # 0.28 < 2/7
    assert draw(lunch, dish, [0.69, 0.29, 0.9, 0.0])["campus"]["name"] == "b1" # 0.29 >= 2/7
    assert draw(lunch, dish, [0.7, 0.0])["dish"]["id"] == "d"
