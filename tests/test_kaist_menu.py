from pathlib import Path

import pytest
from refresh_kaist_menu import parse_cell, parse_meals


@pytest.mark.parametrize("text,expected", [
    ("635 kcal", "635 kcal"), ("총칼로리:1,313kcal", "1313 kcal"),
    ("총칼로리:1,050kcal", "1050 kcal"), ("총 열량 : 50 kcal", "50 kcal"),
    ("알레르기 1, 2, 50", ""), ("50<br>제공량 50g", ""),
    ("행사 안내: 50 kcal 할인", ""), ("총칼로리:1,05kcal", ""),
    ("총칼로리:kcal", ""), ("총칼로리:-50kcal", ""),
    ("총칼로리:1.050kcal", ""), ("쌀밥<br>된장국", ""),
])
def test_only_explicit_well_formed_calorie_lines(text, expected):
    assert parse_cell(text)["kcal"] == expected


def test_official_east1_html_thousands_separator_regression():
    page = (Path(__file__).parent / "fixtures" / "kaist-menu-east1-2026-09-20.html").read_text(encoding="utf-8")
    meals = parse_meals(page)
    assert meals["breakfast"]["kcal"] == "815 kcal"
    assert meals["lunch"]["kcal"] == "1050 kcal"
    assert meals["dinner"]["kcal"] == "925 kcal"
