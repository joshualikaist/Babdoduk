"""The dish a free-food row leads with (owner 2026-11-05: "시간과 메뉴가 더 중요"):
js/ggongbab-select.js `dishes` reads only the food description, real descriptions from the feed."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

CASES = [
    ("현장 참석자 샌드위치 제공", "meal", ["sandwich"]),
    ("도시락, 다과", "lunchbox", ["lunchbox", "refreshment"]),
    ("사전 신청자 점심 제공", "meal", ["lunch"]),
    ("BBQ 황금올리브 반반치킨 1마리 쿠폰", "coupon", ["chicken", "coupon"]),   # a chicken brand, not a barbecue
    ("소고기 BBQ 식사", "meal", ["bbq"]),
    ("샌드위치+음료 박스", "meal", ["sandwich", "drink"]),
    ("커피 및 다과", "refreshment", ["coffee", "refreshment"]),
    ("상무초밥 세트 (사전 신청자 선착순 190명)", "meal", ["sushi"]),
    ("쉑쉑버거와 음료", "meal", ["burger", "drink"]),
    ("점심 도시락 지원", "lunchbox", ["lunchbox"]),                          # a named dish beats a general word
    ("전 일정 식사·간식 제공", "meal", ["meal", "snack"]),                    # a general word leads light food
    ("석식 케이터링", "meal", ["dinner"]),
    ("Sandwiches will be provided to the first 130 attendees.", "meal", ["sandwich"]),
    ("", "refreshment", ["refreshment"]),                                    # no description: the type
    ("", "unknown", ["food"]),
]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_dishes_read_the_food_description():
    script = ("global.window = global; require(process.argv[1]); const F = window.BabdodukFreeFood;"
              "const cases = JSON.parse(process.argv[2]);"
              "const keys = c => F.dishes({ food: { provided: 'true', type: c[1], description: c[0] } }).map(d => d.key);"
              "const none = F.dishes({ food: { provided: 'false', description: '샌드위치' } });"
              "const label = F.dishLabel({ food: { provided: 'true', description: '도시락, 다과' } }, (k, f) => ({'dish.lunchbox': '도시락', 'dish.refreshment': '다과'})[k] || f);"
              "console.log(JSON.stringify({ got: cases.map(keys), none: none, label: label,"
              "  lang: [F.inLang('샌드위치', 'ko'), F.inLang('Sandwiches', 'ko'), F.inLang('Sandwiches', 'en'), F.inLang('샌드위치', 'en')] }));")
    out = subprocess.run(["node", "-e", script, str(ROOT / "js/ggongbab-select.js"), json.dumps(CASES, ensure_ascii=False)],
                         capture_output=True, text=True, check=True)
    result = json.loads(out.stdout)
    assert result["got"] == [case[2] for case in CASES]
    assert result["none"] == []                     # no explicit food, no dish
    assert result["label"] == "도시락 · 다과"
    assert result["lang"] == [True, False, True, False]
