"""The 3D campus map's building table and event placement (scripts/campus3d/buildings.py,
docs/CAMPUS_MAP.md). No network: the OpenStreetMap shapes are the committed inputs/campus3d/campus.json."""
import json

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


@pytest.mark.parametrize("location, expected", [
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
])
def test_an_event_is_placed_by_its_code_or_a_name_and_never_guessed(location, expected):
    assert cb.place(location, TABLE) == expected


def test_a_code_the_table_does_not_know_is_not_placed():
    assert cb.place({"building": "S9", "name": ""}, TABLE) == {"code": None, "placed": False, "others": 0}
