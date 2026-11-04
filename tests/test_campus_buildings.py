"""The 3D campus map's building table and event placement (scripts/campus3d/buildings.py,
docs/CAMPUS_MAP.md). No network: the OpenStreetMap shapes are the committed inputs/campus3d/campus.json."""
import json
import shutil
import subprocess

import pytest

from campus3d import buildings as cb

TABLE = json.loads(cb.TABLE.read_text(encoding="utf-8"))


def test_the_table_is_generated_from_its_inputs():
    fresh = cb.build(json.loads(cb.CAMPUS.read_text(encoding="utf-8")), json.loads(cb.EXTRA.read_text(encoding="utf-8")))
    assert cb.TABLE.read_text(encoding="utf-8") == cb.render(fresh)


def test_the_buildings_our_events_use_most_are_placed_with_their_names():
    rows = {r["code"]: r for r in TABLE["buildings"]}
    for code, name in (("E11", "창의학습관"), ("E9", "학술문화관"), ("E4", "홍&박 KI빌딩"), ("E15", "대강당"),
                       ("N7", "기계공학동"), ("W8", "교육지원동"), ("N4", "디지털인문사회과학부동"), ("N13", "태울관")):
        assert rows[code]["name"] == name, code
        assert rows[code]["nameEn"] and len(rows[code]["at"]) == 2 and rows[code]["top"] >= 4
    # The 9-floor IT building stands taller than a 3-floor one.
    assert rows["N1"]["top"] > rows["E11"]["top"]


def test_no_alias_is_shared_and_none_is_a_code():
    seen = {}
    for row in TABLE["buildings"] + TABLE["unplaced"]:
        for alias in row["aliases"]:
            assert alias not in seen, (alias, seen.get(alias), row["code"])
            assert not cb.CODE.fullmatch(alias)
            seen[alias] = row["code"]


CASES = [
    ({"building": "E11", "name": "창의학습관 터만홀"}, {"code": "E11", "placed": True, "others": 0}),
    ({"building": "창의학습관(E11)", "name": ""}, {"code": "E11", "placed": True, "others": 0}),
    # Two buildings in one event: the first gets the pin, the map says "외 1곳".
    ({"building": "E6-1 / E4", "name": "자연과학동 (E6-1) / KI빌딩 (E4)"}, {"code": "E6-1", "placed": True, "others": 1}),
    # A name without a code, through the building's name or an alias.
    ({"building": "KI빌딩", "name": ""}, {"code": "E4", "placed": True, "others": 0}),
    ({"building": "", "name": "학술문화관 2층 양승택오디토리움"}, {"code": "E9", "placed": True, "others": 0}),
    # Known to us, but OpenStreetMap has no outline yet: listed as 위치 미정.
    ({"building": "E9-1", "name": "KAIST 미술관"}, {"code": "E9-1", "placed": False, "others": 0}),
    ({"building": "", "name": "KAIST 미술관 2F"}, {"code": "E9-1", "placed": False, "others": 0}),
    # Unknown or off campus: no pin, never a guess.
    ({"building": "1호관", "name": ""}, {"code": None, "placed": False, "others": 0}),
    ({"building": "", "name": "KAIST 문지캠퍼스, 강의동 L507호"}, {"code": None, "placed": False, "others": 0}),
    ({"building": "대전 본원", "name": ""}, {"code": None, "placed": False, "others": 0}),
    (None, {"code": None, "placed": False, "others": 0}),
]
CASES = [pytest.param(*case) for case in CASES]


@pytest.mark.parametrize("location, expected", CASES)
def test_an_event_is_placed_by_its_code_or_a_name_and_never_guessed(location, expected):
    assert cb.place(location, TABLE) == expected


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_browser_places_events_exactly_like_the_pipeline():
    """js/campus-place.js (the map's pins) and buildings.place() agree on every case above."""
    cases = [case.values[0] for case in CASES]
    script = ("import { place } from './js/campus-place.js';"
              "import { readFileSync } from 'node:fs';"
              "const table = JSON.parse(readFileSync('data/campus/buildings.json', 'utf8'));"
              f"console.log(JSON.stringify({json.dumps(cases)}.map((loc) => place(loc, table))));")
    out = subprocess.run(["node", "--input-type=module", "-e", script], cwd=cb.ROOT, capture_output=True, text=True, check=True)
    assert json.loads(out.stdout) == [cb.place(loc, TABLE) for loc in cases]


def test_a_code_the_table_does_not_know_is_not_placed():
    assert cb.place({"building": "S9", "name": ""}, TABLE) == {"code": None, "placed": False, "others": 0}


def test_the_web_model_stays_within_its_budget_and_describes_its_view():
    """docs/CAMPUS_MAP.md: the model, its baked ground light and the poster are built by
    scripts/campus3d/export_web.py; the home page must not grow by more than these."""
    folder = cb.TABLE.parent
    budget = {"campus.glb": 1_500_000, "ground-light.webp": 500_000, "poster.webp": 160_000, "model.json": 80_000}
    for name, limit in budget.items():
        assert (folder / name).stat().st_size <= limit, name
    assert (folder / "campus.glb").read_bytes()[:4] == b"glTF"
    model = json.loads((folder / "model.json").read_text(encoding="utf-8"))
    assert model["attribution"] == TABLE["attribution"]
    assert set(model) == {"attribution", "palette", "sun", "camera", "light", "trees"}
    assert len(model["camera"]["position"]) == 3 and model["camera"]["position"][1] > 1000   # above the island
    assert model["light"]["span"] > 1000 and 500 < len(model["trees"]) < 5000
    assert all(len(t) == 5 and t[4] in (0, 1, 2) for t in model["trees"])
    for key in ("grass", "path", "wall", "roof", "water", "highlight"):
        assert len(model["palette"][key]) == 3, key
