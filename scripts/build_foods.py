# -*- coding: utf-8 -*-
"""Build split food packs under data/foods/. Re-run after adding menus; the picker JS stays the same."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "foods"
PACKS = OUT / "packs"


def flavor(spicy=1, sweet=1, salty=2, sour=1, umami=3, rich=2):
    return {
        "spicy": spicy,
        "sweet": sweet,
        "salty": salty,
        "sour": sour,
        "umami": umami,
        "rich": rich,
    }


def texture(crispy=1, chewy=1, soft=3, soupy=0):
    return {
        "crispy": crispy,
        "chewy": chewy,
        "soft": soft,
        "soupy": soupy,
    }


def F(
    id,
    name_ko,
    name_en,
    parent,
    group,
    cuisine,
    region,
    category,
    dish,
    carb,
    protein,
    flav,
    tex,
    satiety,
    health,
    adventure,
    meals,
    occ,
    modes,
    price,
    pop,
    keywords,
    temp="hot",
    prep=2,
    diet=None,
    allergens=None,
    season=None,
):
    return {
        "id": id,
        "nameKo": name_ko,
        "nameEn": name_en,
        "parentId": parent,
        "cuisine": cuisine,
        "cuisineGroup": group,
        "region": region,
        "category": category,
        "dishType": dish,
        "mainCarb": carb,
        "mainProtein": protein,
        "flavor": flav,
        "texture": tex,
        "temperature": temp,
        "satiety": satiety,
        "healthiness": health,
        "adventurousness": adventure,
        "mealTime": meals,
        "occasion": occ,
        "diningMode": modes,
        "priceLevel": price,
        "prepDifficulty": prep,
        "diet": diet or [],
        "allergens": allergens or [],
        "season": season or ["all"],
        "popularity": pop,
        "keywords": keywords,
    }


LD = ["lunch", "dinner"]
LDN = ["lunch", "dinner", "lateNight"]
ALLDAY = ["breakfast", "lunch", "dinner", "lateNight"]
BRUNCH = ["breakfast", "lunch"]
SOLO = ["solo", "friends"]
GRP = ["solo", "friends", "group"]
DATE = ["solo", "friends", "date"]
ALL_OCC = ["solo", "friends", "date", "group", "drinks"]
DELIVER = ["delivery", "restaurant"]
HOME = ["homeCooking", "delivery"]
REST = ["restaurant"]
ALL_MODE = ["delivery", "restaurant", "homeCooking"]


FOODS = [
    F("kr-kimchi-jjigae", "김치찌개", "Kimchi jjigae", "cluster-kimchi-stew", "korean", "korean", "korea", "main", "stew", "rice", "pork", flavor(4, 1, 3, 3, 4, 3), texture(0, 1, 3, 5), 4, 3, 1, LDN, GRP, ALL_MODE, 1, 5, ["김치", "찌개", "국물"]),
    F("kr-kimchi-jjigae-pork", "돼지고기 김치찌개", "Pork kimchi jjigae", "cluster-kimchi-stew", "korean", "korean", "korea", "main", "stew", "rice", "pork", flavor(4, 1, 3, 3, 4, 4), texture(0, 1, 3, 5), 5, 2, 1, LDN, GRP, ALL_MODE, 1, 4, ["돼지고기", "김치찌개", "국물"]),
    F("kr-kimchi-jjigae-tuna", "참치 김치찌개", "Tuna kimchi jjigae", "cluster-kimchi-stew", "korean", "korean", "korea", "main", "stew", "rice", "fish", flavor(4, 1, 4, 3, 4, 3), texture(0, 1, 3, 5), 3, 3, 1, LDN, SOLO, ALL_MODE, 1, 4, ["참치", "김치찌개", "국물"], allergens=["fish"]),
    F("kr-doenjang-jjigae", "된장찌개", "Doenjang jjigae", "cluster-soy-stew", "korean", "korean", "korea", "main", "stew", "rice", "tofu", flavor(1, 0, 3, 1, 5, 2), texture(0, 1, 3, 5), 3, 4, 1, LD, SOLO, ALL_MODE, 1, 4, ["된장", "찌개"], diet=["vegetarian"]),
    F("kr-sundubu", "순두부찌개", "Sundubu jjigae", "cluster-tofu-stew", "korean", "korean", "korea", "main", "stew", "rice", "tofu", flavor(3, 0, 3, 1, 4, 3), texture(0, 0, 5, 5), 3, 4, 1, LDN, SOLO, ALL_MODE, 2, 4, ["순두부", "찌개"], allergens=["soy", "egg"]),
    F("kr-budae", "부대찌개", "Budae jjigae", "cluster-budae", "korean", "korean", "korea", "main", "stew", "rice", "pork", flavor(3, 1, 4, 1, 4, 4), texture(1, 2, 3, 5), 5, 2, 2, LDN, GRP, ALL_MODE, 2, 5, ["부대찌개", "햄", "국물"], allergens=["soy", "gluten"]),
    F("kr-kimchi-bokkeumbap", "김치볶음밥", "Kimchi fried rice", "cluster-fried-rice", "korean", "korean", "korea", "main", "rice-bowl", "rice", "pork", flavor(3, 1, 3, 2, 3, 3), texture(1, 1, 3, 0), 3, 2, 1, LDN, SOLO, ALL_MODE, 1, 5, ["김치볶음밥"], allergens=["egg"]),
    F("kr-jeyuk", "제육볶음", "Jeyuk bokkeum", "cluster-spicy-pork", "korean", "korean", "korea", "main", "stir-fry", "rice", "pork", flavor(4, 2, 3, 1, 3, 3), texture(0, 2, 3, 0), 4, 2, 1, LD, GRP, ALL_MODE, 2, 5, ["제육", "매콤"]),
    F("kr-bulgogi", "불고기", "Bulgogi", "cluster-grilled-beef", "korean", "korean", "korea", "main", "grill", "rice", "beef", flavor(1, 3, 3, 0, 4, 3), texture(0, 2, 4, 0), 4, 3, 1, LD, DATE, ALL_MODE, 2, 5, ["불고기"]),
    F("kr-samgyeopsal", "삼겹살", "Samgyeopsal", "cluster-pork-bbq", "korean", "korean", "korea", "main", "grill", "none", "pork", flavor(1, 0, 2, 0, 3, 5), texture(2, 2, 3, 0), 5, 1, 1, ["dinner", "lateNight"], ALL_OCC, REST, 3, 5, ["삼겹살", "고기"], temp="hot"),
    F("kr-galbijjim", "갈비찜", "Galbijjim", "cluster-braised-ribs", "korean", "korean", "korea", "main", "braise", "rice", "beef", flavor(1, 3, 3, 0, 4, 4), texture(0, 3, 4, 1), 5, 2, 2, ["dinner"], DATE, DELIVER, 3, 4, ["갈비찜"]),
    F("kr-dakbokkeumtang", "닭볶음탕", "Dakbokkeumtang", "cluster-braised-chicken", "korean", "korean", "korea", "main", "braise", "rice", "chicken", flavor(3, 1, 3, 1, 4, 3), texture(0, 2, 3, 3), 4, 3, 1, LD, GRP, ALL_MODE, 2, 4, ["닭볶음탕"]),
    F("kr-bibimbap", "비빔밥", "Bibimbap", "cluster-bibimbap", "korean", "korean", "korea", "main", "rice-bowl", "rice", "egg", flavor(2, 1, 2, 1, 3, 2), texture(1, 1, 3, 0), 3, 4, 1, LD, SOLO, ALL_MODE, 2, 5, ["비빔밥"], diet=["vegetarian"], allergens=["egg", "sesame"]),
    F("kr-dolsot-bibimbap", "돌솥비빔밥", "Dolsot bibimbap", "cluster-bibimbap", "korean", "korean", "korea", "main", "rice-bowl", "rice", "egg", flavor(2, 1, 2, 1, 3, 3), texture(3, 1, 2, 0), 4, 4, 1, LD, DATE, REST, 2, 4, ["돌솥비빔밥"], allergens=["egg"]),
    F("kr-gimbap", "김밥", "Gimbap", "cluster-gimbap", "korean", "korean", "korea", "snack", "roll", "rice", "egg", flavor(0, 1, 3, 1, 2, 1), texture(1, 2, 3, 0), 2, 3, 1, ALLDAY, SOLO, ALL_MODE, 1, 5, ["김밥"], temp="cold", diet=["vegetarian"], allergens=["egg", "sesame"]),
    F("kr-ramyeon", "라면", "Ramyeon", "cluster-instant-noodle", "korean", "korean", "korea", "main", "noodle", "noodle", "none", flavor(3, 1, 4, 0, 3, 3), texture(0, 3, 2, 4), 3, 1, 1, LDN, SOLO, HOME, 1, 5, ["라면", "면"], allergens=["gluten", "soy"]),
    F("kr-jjajang", "짜장면", "Jjajangmyeon", "cluster-jjajang", "korean", "korean-chinese", "korea", "main", "noodle", "noodle", "pork", flavor(0, 2, 3, 0, 4, 4), texture(0, 3, 3, 0), 4, 2, 1, LDN, SOLO, ALL_MODE, 1, 5, ["짜장면"], allergens=["gluten", "soy"]),
    F("kr-jjamppong", "짬뽕", "Jjamppong", "cluster-spicy-noodle-soup", "korean", "korean-chinese", "korea", "main", "noodle", "noodle", "seafood", flavor(4, 0, 3, 0, 4, 3), texture(0, 3, 2, 5), 4, 2, 1, LDN, SOLO, ALL_MODE, 2, 5, ["짬뽕", "해물"], allergens=["shellfish", "gluten"]),
    F("kr-tangsuyuk", "탕수육", "Tangsuyuk", "cluster-sweet-sour-pork", "korean", "korean-chinese", "korea", "share", "fried", "none", "pork", flavor(0, 4, 2, 3, 2, 3), texture(4, 1, 2, 0), 3, 1, 1, LD, GRP, DELIVER, 2, 4, ["탕수육"], allergens=["gluten"]),
    F("kr-tteokbokki", "떡볶이", "Tteokbokki", "cluster-tteokbokki", "snack", "korean", "korea", "snack", "street", "rice-cake", "none", flavor(4, 2, 3, 0, 3, 3), texture(0, 5, 2, 1), 3, 1, 1, LDN, GRP, ALL_MODE, 1, 5, ["떡볶이", "매콤"], allergens=["fish"]),
    F("kr-sundae-guk", "순대국", "Sundae-guk", "cluster-gukbap", "korean", "korean", "korea", "main", "soup", "rice", "pork", flavor(1, 0, 3, 0, 4, 3), texture(0, 2, 3, 5), 4, 3, 2, LDN, SOLO, REST, 2, 4, ["순대국", "국밥"]),
    F("kr-seolleongtang", "설렁탕", "Seolleongtang", "cluster-gukbap", "korean", "korean", "korea", "main", "soup", "rice", "beef", flavor(0, 0, 2, 0, 4, 3), texture(0, 1, 4, 5), 4, 3, 1, LD, SOLO, REST, 2, 4, ["설렁탕"]),
    F("kr-gamjatang", "감자탕", "Gamjatang", "cluster-pork-bone", "korean", "korean", "korea", "main", "stew", "rice", "pork", flavor(3, 0, 3, 0, 4, 4), texture(0, 3, 3, 4), 5, 2, 1, ["dinner", "lateNight"], GRP, DELIVER, 2, 4, ["감자탕"]),
    F("kr-galbitang", "갈비탕", "Galbitang", "cluster-beef-soup", "korean", "korean", "korea", "main", "soup", "rice", "beef", flavor(0, 1, 2, 0, 4, 3), texture(0, 2, 3, 5), 4, 3, 1, LD, DATE, REST, 3, 4, ["갈비탕"]),
    F("kr-samgyetang", "삼계탕", "Samgyetang", "cluster-ginseng-chicken", "korean", "korean", "korea", "main", "soup", "rice", "chicken", flavor(0, 1, 2, 0, 3, 3), texture(0, 1, 4, 5), 4, 4, 1, LD, SOLO, REST, 3, 4, ["삼계탕"], season=["summer"]),
    F("kr-naengmyeon", "물냉면", "Mul-naengmyeon", "cluster-naengmyeon", "korean", "korean", "korea", "main", "noodle", "noodle", "beef", flavor(0, 1, 3, 3, 3, 1), texture(0, 4, 2, 4), 2, 3, 1, LD, SOLO, ALL_MODE, 2, 4, ["냉면"], temp="cold", season=["summer"], allergens=["gluten", "egg"]),
    F("kr-bibim-naengmyeon", "비빔냉면", "Bibim-naengmyeon", "cluster-naengmyeon", "korean", "korean", "korea", "main", "noodle", "noodle", "beef", flavor(3, 2, 3, 2, 3, 2), texture(0, 4, 2, 0), 3, 3, 1, LD, SOLO, ALL_MODE, 2, 4, ["비빔냉면"], temp="cold", season=["summer"]),
    F("kr-kalguksu", "칼국수", "Kalguksu", "cluster-knife-noodle", "korean", "korean", "korea", "main", "noodle", "noodle", "none", flavor(0, 0, 2, 0, 3, 2), texture(0, 3, 3, 5), 3, 3, 1, LD, SOLO, ALL_MODE, 1, 4, ["칼국수"], allergens=["gluten"]),
    F("kr-kongguksu", "콩국수", "Kongguksu", "cluster-soy-noodle", "korean", "korean", "korea", "main", "noodle", "noodle", "none", flavor(0, 1, 1, 0, 2, 2), texture(0, 3, 4, 4), 3, 4, 2, LD, SOLO, REST, 2, 3, ["콩국수"], temp="cold", season=["summer"], diet=["vegetarian"], allergens=["soy", "gluten"]),
    F("kr-haejangguk", "해장국", "Haejangguk", "cluster-hangover", "korean", "korean", "korea", "main", "soup", "rice", "beef", flavor(2, 0, 3, 0, 4, 3), texture(0, 1, 3, 5), 4, 3, 1, ["breakfast", "lunch", "lateNight"], SOLO, REST, 2, 4, ["해장국"]),
    F("kr-dwaeji-gukbap", "돼지국밥", "Dwaeji-gukbap", "cluster-gukbap", "korean", "korean", "korea", "main", "soup", "rice", "pork", flavor(1, 0, 3, 0, 4, 3), texture(0, 2, 3, 5), 5, 2, 1, LDN, SOLO, REST, 2, 5, ["돼지국밥", "국밥"]),
    F("kr-jokbal", "족발", "Jokbal", "cluster-jokbal", "korean", "korean", "korea", "share", "braise", "none", "pork", flavor(1, 1, 3, 0, 3, 4), texture(0, 4, 3, 0), 4, 1, 2, ["dinner", "lateNight"], ["friends", "group", "drinks"], DELIVER, 3, 4, ["족발"]),
    F("kr-bossam", "보쌈", "Bossam", "cluster-jokbal", "korean", "korean", "korea", "share", "braise", "none", "pork", flavor(0, 1, 2, 1, 3, 3), texture(0, 2, 4, 0), 4, 2, 1, ["dinner"], GRP, DELIVER, 3, 4, ["보쌈"]),
    F("kr-fried-chicken", "후라이드 치킨", "Fried chicken", "cluster-chicken", "korean", "korean", "korea", "share", "fried", "none", "chicken", flavor(0, 1, 2, 0, 2, 4), texture(5, 1, 3, 0), 4, 1, 1, LDN, ALL_OCC, DELIVER, 2, 5, ["치킨"], allergens=["gluten"]),
    F("kr-yangnyeom-chicken", "양념치킨", "Yangnyeom chicken", "cluster-chicken", "korean", "korean", "korea", "share", "fried", "none", "chicken", flavor(3, 3, 2, 1, 2, 4), texture(4, 1, 3, 0), 4, 1, 1, LDN, ALL_OCC, DELIVER, 2, 5, ["양념치킨"], allergens=["gluten"]),
    F("kr-dakgalbi", "닭갈비", "Dakgalbi", "cluster-dakgalbi", "korean", "korean", "korea", "main", "stir-fry", "rice", "chicken", flavor(4, 2, 3, 0, 3, 3), texture(0, 2, 3, 0), 4, 2, 1, ["dinner"], GRP, REST, 2, 4, ["닭갈비"]),
    F("kr-ojingeo", "오징어볶음", "Spicy squid", "cluster-spicy-seafood", "korean", "korean", "korea", "main", "stir-fry", "rice", "seafood", flavor(4, 1, 3, 1, 3, 2), texture(0, 4, 2, 0), 3, 3, 2, LD, SOLO, ALL_MODE, 2, 3, ["오징어볶음"], allergens=["shellfish"]),
    F("kr-godeungeo", "고등어구이", "Grilled mackerel", "cluster-grilled-fish", "korean", "korean", "korea", "main", "grill", "rice", "fish", flavor(0, 0, 3, 1, 4, 3), texture(2, 1, 3, 0), 3, 4, 1, LD, SOLO, HOME, 1, 3, ["고등어"], allergens=["fish"]),
    F("kr-dakbal", "닭발", "Dakbal", "cluster-anju", "korean", "korean", "korea", "share", "grill", "none", "chicken", flavor(5, 1, 3, 0, 3, 3), texture(0, 5, 2, 0), 2, 1, 3, ["dinner", "lateNight"], ["friends", "drinks"], REST, 2, 3, ["닭발", "매콤"]),
    F("kr-gopchang", "곱창구이", "Gopchang", "cluster-anju", "korean", "korean", "korea", "share", "grill", "none", "offal", flavor(1, 0, 3, 0, 4, 5), texture(0, 4, 3, 0), 4, 1, 4, ["dinner", "lateNight"], ["friends", "drinks"], REST, 3, 4, ["곱창"]),
    F("kr-sujebi", "수제비", "Sujebi", "cluster-knife-noodle", "korean", "korean", "korea", "main", "soup", "wheat", "none", flavor(0, 0, 2, 0, 3, 2), texture(0, 2, 4, 5), 3, 3, 1, LD, SOLO, HOME, 1, 3, ["수제비"], allergens=["gluten"]),
    F("kr-makguksu", "막국수", "Makguksu", "cluster-buckwheat", "korean", "korean", "korea", "main", "noodle", "noodle", "none", flavor(1, 1, 2, 2, 2, 1), texture(0, 3, 2, 1), 2, 4, 2, LD, SOLO, REST, 2, 3, ["막국수"], temp="cold", season=["summer"]),
    F("kr-gyeran-mari", "계란말이", "Rolled omelette", "cluster-banchan", "korean", "korean", "korea", "side", "egg", "none", "egg", flavor(0, 1, 2, 0, 2, 2), texture(0, 1, 4, 0), 2, 3, 1, ALLDAY, SOLO, HOME, 1, 3, ["계란말이"], diet=["vegetarian"], allergens=["egg"]),
    F("cn-mara-tang", "마라탕", "Mala tang", "cluster-mala", "chinese", "sichuan", "china", "main", "soup", "noodle", "mixed", flavor(5, 0, 3, 0, 4, 4), texture(1, 3, 3, 5), 4, 2, 3, LDN, GRP, DELIVER, 2, 5, ["마라탕", "마라"], allergens=["soy", "sesame", "peanut"]),
    F("cn-mara-xiangguo", "마라샹궈", "Mala xiangguo", "cluster-mala", "chinese", "sichuan", "china", "main", "stir-fry", "rice", "mixed", flavor(5, 0, 3, 0, 4, 5), texture(2, 3, 2, 0), 4, 2, 3, ["dinner", "lateNight"], GRP, REST, 2, 4, ["마라샹궈"]),
    F("cn-hotpot", "훠궈", "Hotpot", "cluster-hotpot", "chinese", "sichuan", "china", "share", "hotpot", "none", "mixed", flavor(4, 0, 3, 0, 4, 4), texture(1, 2, 3, 5), 5, 2, 3, ["dinner"], GRP, REST, 3, 5, ["훠궈"]),
    F("cn-dandan", "탄탄면", "Dan dan noodles", "cluster-spicy-noodle", "chinese", "sichuan", "china", "main", "noodle", "noodle", "pork", flavor(4, 1, 3, 0, 4, 4), texture(0, 3, 3, 2), 4, 2, 3, LD, SOLO, DELIVER, 2, 4, ["탄탄면"], allergens=["sesame", "soy", "gluten", "peanut"]),
    F("cn-mapo", "마파두부", "Mapo tofu", "cluster-mapo", "chinese", "sichuan", "china", "main", "stir-fry", "rice", "tofu", flavor(4, 0, 3, 0, 4, 3), texture(0, 1, 4, 1), 3, 3, 2, LD, SOLO, ALL_MODE, 2, 4, ["마파두부"], allergens=["soy", "sesame"]),
    F("cn-guobaorou", "꿔바로우", "Guobaorou", "cluster-sweet-sour-pork", "chinese", "dongbei", "china", "share", "fried", "none", "pork", flavor(0, 3, 2, 3, 2, 3), texture(5, 1, 2, 0), 3, 1, 2, LD, GRP, REST, 2, 4, ["꿔바로우"], allergens=["gluten"]),
    F("cn-yang-kkochi", "양꼬치", "Lamb skewers", "cluster-skewer", "chinese", "xinjiang", "china", "share", "grill", "none", "lamb", flavor(3, 0, 3, 0, 4, 4), texture(2, 3, 2, 0), 3, 2, 3, ["dinner", "lateNight"], ["friends", "drinks"], REST, 2, 4, ["양꼬치"]),
    F("cn-dimsum", "딤섬", "Dim sum", "cluster-dimsum", "chinese", "cantonese", "china", "share", "dumpling", "wheat", "pork", flavor(0, 1, 2, 0, 3, 2), texture(1, 2, 4, 1), 3, 3, 2, BRUNCH, GRP, REST, 3, 4, ["딤섬"], allergens=["gluten", "shellfish"]),
    F("cn-wonton-soup", "완탕면", "Wonton noodle soup", "cluster-wonton", "chinese", "cantonese", "china", "main", "noodle", "noodle", "pork", flavor(0, 0, 2, 0, 4, 2), texture(0, 3, 3, 5), 3, 3, 1, LD, SOLO, ALL_MODE, 2, 3, ["완탕"], allergens=["gluten", "egg"]),
    F("cn-fried-rice", "중화볶음밥", "Chinese fried rice", "cluster-fried-rice", "chinese", "cantonese", "china", "main", "rice-bowl", "rice", "egg", flavor(0, 1, 3, 0, 3, 3), texture(1, 1, 3, 0), 3, 2, 1, LDN, SOLO, ALL_MODE, 1, 4, ["볶음밥"], allergens=["egg", "soy"]),
    F("jp-ramen", "라멘", "Ramen", "cluster-ramen", "japanese", "japanese", "japan", "main", "noodle", "noodle", "pork", flavor(1, 1, 3, 0, 5, 4), texture(0, 4, 2, 5), 4, 2, 2, LDN, SOLO, DELIVER, 2, 5, ["라멘"], allergens=["gluten", "soy", "egg"]),
    F("jp-tonkatsu", "돈카츠", "Tonkatsu", "cluster-katsu", "japanese", "japanese", "japan", "main", "fried", "rice", "pork", flavor(0, 1, 2, 1, 3, 4), texture(4, 1, 3, 0), 5, 1, 1, LD, SOLO, ALL_MODE, 2, 5, ["돈카츠", "돈까스"], allergens=["gluten", "egg"]),
    F("jp-sushi", "초밥", "Sushi", "cluster-sushi", "japanese", "japanese", "japan", "main", "rice-bowl", "rice", "fish", flavor(0, 1, 3, 2, 4, 2), texture(0, 2, 4, 0), 3, 4, 2, LD, DATE, REST, 3, 5, ["초밥", "스시"], temp="cold", allergens=["fish", "soy"]),
    F("jp-sashimi", "사시미", "Sashimi", "cluster-sushi", "japanese", "japanese", "japan", "share", "raw", "none", "fish", flavor(0, 0, 2, 1, 4, 2), texture(0, 2, 4, 0), 2, 5, 3, ["dinner"], DATE, REST, 3, 4, ["회", "사시미"], temp="cold", allergens=["fish"]),
    F("jp-udon", "우동", "Udon", "cluster-udon", "japanese", "japanese", "japan", "main", "noodle", "noodle", "none", flavor(0, 1, 3, 0, 3, 2), texture(0, 4, 3, 5), 3, 3, 1, LD, SOLO, ALL_MODE, 2, 4, ["우동"], allergens=["gluten", "soy"]),
    F("jp-soba", "소바", "Soba", "cluster-soba", "japanese", "japanese", "japan", "main", "noodle", "noodle", "none", flavor(0, 0, 2, 1, 2, 1), texture(0, 3, 2, 1), 2, 4, 2, LD, SOLO, ALL_MODE, 2, 4, ["소바"], temp="cold", diet=["vegetarian"], allergens=["gluten", "soy"]),
    F("jp-gyudon", "규동", "Gyudon", "cluster-donburi", "japanese", "japanese", "japan", "main", "rice-bowl", "rice", "beef", flavor(0, 2, 3, 0, 4, 3), texture(0, 2, 4, 1), 4, 2, 1, LDN, SOLO, ALL_MODE, 1, 4, ["규동", "덮밥"], allergens=["soy"]),
    F("jp-okonomiyaki", "오코노미야키", "Okonomiyaki", "cluster-okonomiyaki", "japanese", "kansai", "japan", "main", "savory-pancake", "wheat", "pork", flavor(1, 2, 3, 1, 3, 4), texture(2, 2, 3, 0), 4, 2, 4, LD, GRP, REST, 2, 4, ["오코노미야키"], allergens=["gluten", "egg"]),
    F("jp-takoyaki", "타코야키", "Takoyaki", "cluster-takoyaki", "snack", "japanese", "japan", "snack", "street", "wheat", "seafood", flavor(0, 1, 2, 0, 3, 3), texture(2, 2, 4, 0), 2, 1, 2, LDN, GRP, REST, 1, 4, ["타코야키"], allergens=["shellfish", "gluten", "egg"]),
    F("jp-kare", "카레라이스", "Japanese curry", "cluster-curry-rice", "japanese", "japanese", "japan", "main", "rice-bowl", "rice", "pork", flavor(1, 2, 3, 0, 3, 4), texture(0, 1, 4, 1), 5, 2, 1, LD, SOLO, ALL_MODE, 2, 5, ["카레"]),
    F("jp-nabe", "나베", "Nabe", "cluster-nabe", "japanese", "japanese", "japan", "share", "hotpot", "none", "mixed", flavor(0, 1, 2, 0, 4, 3), texture(0, 1, 4, 5), 4, 3, 2, ["dinner"], GRP, REST, 3, 3, ["나베", "전골"]),
    F("jp-omurice", "오므라이스", "Omurice", "cluster-omurice", "japanese", "japanese", "japan", "main", "rice-bowl", "rice", "egg", flavor(0, 2, 2, 1, 3, 3), texture(0, 1, 5, 0), 4, 2, 1, LD, SOLO, ALL_MODE, 2, 4, ["오므라이스"], allergens=["egg"]),
    F("it-aglio", "알리오올리오", "Aglio e olio", "cluster-pasta-oil", "italian", "italian", "italy", "main", "pasta", "pasta", "none", flavor(1, 0, 2, 0, 3, 2), texture(0, 3, 3, 0), 3, 3, 1, LD, DATE, ALL_MODE, 2, 4, ["파스타", "알리오올리오"], allergens=["gluten"]),
    F("it-carbonara", "까르보나라", "Carbonara", "cluster-pasta-cream", "italian", "italian", "italy", "main", "pasta", "pasta", "pork", flavor(0, 0, 3, 0, 4, 5), texture(0, 3, 4, 0), 4, 1, 1, ["dinner"], DATE, ALL_MODE, 2, 5, ["까르보나라"], allergens=["gluten", "egg", "dairy"]),
    F("it-pizza", "마르게리타 피자", "Margherita pizza", "cluster-pizza", "italian", "italian", "italy", "main", "pizza", "wheat", "none", flavor(0, 1, 2, 1, 3, 3), texture(3, 2, 3, 0), 4, 2, 1, LDN, GRP, DELIVER, 2, 5, ["피자"], diet=["vegetarian"], allergens=["gluten", "dairy"]),
    F("it-risotto", "리조또", "Risotto", "cluster-risotto", "italian", "italian", "italy", "main", "rice-bowl", "rice", "none", flavor(0, 1, 2, 0, 4, 4), texture(0, 1, 5, 0), 4, 2, 2, ["dinner"], DATE, REST, 3, 3, ["리조또"], diet=["vegetarian"], allergens=["dairy"]),
    F("fr-ratatouille", "라따뚜이", "Ratatouille", "cluster-veg-stew", "french", "french", "france", "main", "stew", "none", "none", flavor(0, 2, 2, 1, 3, 2), texture(0, 1, 4, 1), 2, 5, 2, LD, DATE, REST, 3, 2, ["라따뚜이"], diet=["vegan", "vegetarian"]),
    F("fr-croissant", "크루아상", "Croissant", "cluster-pastry", "french", "french", "france", "snack", "bread", "wheat", "none", flavor(0, 2, 2, 0, 2, 4), texture(4, 1, 3, 0), 2, 1, 1, BRUNCH, SOLO, REST, 1, 4, ["크루아상"], diet=["vegetarian"], allergens=["gluten", "dairy", "egg"]),
    F("us-burger", "치즈버거", "Cheeseburger", "cluster-burger", "american", "american", "usa", "main", "sandwich", "wheat", "beef", flavor(0, 2, 3, 1, 3, 4), texture(2, 2, 3, 0), 5, 1, 1, LDN, SOLO, ALL_MODE, 2, 5, ["햄버거"], allergens=["gluten", "dairy"]),
    F("us-club", "클럽샌드위치", "Club sandwich", "cluster-sandwich", "american", "american", "usa", "main", "sandwich", "wheat", "chicken", flavor(0, 1, 2, 0, 2, 2), texture(2, 1, 3, 0), 3, 2, 1, LD, SOLO, ALL_MODE, 2, 3, ["샌드위치"], allergens=["gluten", "egg"]),
    F("us-caesar", "시저샐러드", "Caesar salad", "cluster-salad", "american", "american", "usa", "main", "salad", "none", "chicken", flavor(0, 0, 3, 1, 3, 2), texture(2, 1, 3, 0), 2, 4, 1, LD, SOLO, ALL_MODE, 2, 3, ["샐러드"], temp="cold", allergens=["dairy", "egg", "fish"]),
    F("us-mac", "맥앤치즈", "Mac and cheese", "cluster-pasta-cream", "american", "american", "usa", "main", "pasta", "pasta", "none", flavor(0, 1, 3, 0, 3, 5), texture(0, 2, 5, 0), 4, 1, 1, LD, SOLO, ALL_MODE, 2, 3, ["맥앤치즈"], diet=["vegetarian"], allergens=["gluten", "dairy"]),
    F("us-steak", "스테이크", "Steak", "cluster-steak", "western", "american", "usa", "main", "grill", "none", "beef", flavor(0, 0, 3, 0, 4, 5), texture(1, 3, 3, 0), 5, 2, 1, ["dinner"], DATE, REST, 3, 5, ["스테이크"]),
    F("us-poke", "포케", "Poke bowl", "cluster-poke", "american", "hawaiian", "usa", "main", "rice-bowl", "rice", "fish", flavor(0, 1, 2, 2, 3, 2), texture(1, 2, 3, 0), 3, 5, 2, LD, SOLO, ALL_MODE, 2, 4, ["포케"], temp="cold", allergens=["fish", "soy"]),
    F("us-avocado-toast", "아보카도 토스트", "Avocado toast", "cluster-toast", "western", "american", "usa", "snack", "bread", "wheat", "none", flavor(0, 0, 2, 1, 2, 3), texture(2, 1, 3, 0), 2, 4, 2, BRUNCH, SOLO, REST, 2, 3, ["아보카도", "토스트"], diet=["vegan", "vegetarian"], allergens=["gluten"]),
    F("us-pancake", "팬케이크", "Pancakes", "cluster-pancake", "american", "american", "usa", "snack", "bread", "wheat", "none", flavor(0, 4, 1, 0, 1, 3), texture(0, 1, 5, 0), 3, 1, 1, ["breakfast"], SOLO, REST, 2, 3, ["팬케이크"], diet=["vegetarian"], allergens=["gluten", "egg", "dairy"]),
    F("us-hotdog", "핫도그", "Hot dog", "cluster-hotdog", "american", "american", "usa", "snack", "sandwich", "wheat", "pork", flavor(1, 1, 3, 1, 2, 3), texture(2, 2, 3, 0), 3, 1, 1, LDN, SOLO, ALL_MODE, 1, 3, ["핫도그"], allergens=["gluten"]),
    F("mx-taco", "타코", "Tacos", "cluster-taco", "mexican", "mexican", "mexico", "main", "wrap", "corn", "beef", flavor(3, 1, 3, 2, 3, 3), texture(2, 2, 3, 0), 3, 3, 4, LDN, GRP, ALL_MODE, 2, 4, ["타코"]),
    F("mx-burrito", "부리또", "Burrito", "cluster-burrito", "mexican", "mexican", "mexico", "main", "wrap", "wheat", "beef", flavor(2, 1, 3, 1, 3, 4), texture(0, 2, 4, 0), 5, 2, 2, LD, SOLO, ALL_MODE, 2, 4, ["부리또"], allergens=["gluten", "dairy"]),
    F("mx-quesadilla", "퀘사디아", "Quesadilla", "cluster-quesadilla", "mexican", "mexican", "mexico", "main", "wrap", "wheat", "none", flavor(1, 1, 3, 0, 3, 4), texture(3, 1, 4, 0), 3, 2, 2, LD, SOLO, ALL_MODE, 2, 3, ["퀘사디아"], diet=["vegetarian"], allergens=["gluten", "dairy"]),
    F("sea-pho", "쌀국수", "Pho", "cluster-pho", "southeast-asian", "vietnamese", "vietnam", "main", "noodle", "rice-noodle", "beef", flavor(1, 1, 3, 1, 4, 2), texture(0, 3, 3, 5), 3, 4, 2, LD, SOLO, ALL_MODE, 2, 5, ["쌀국수", "포"]),
    F("sea-banh-mi", "반미", "Banh mi", "cluster-banh-mi", "southeast-asian", "vietnamese", "vietnam", "main", "sandwich", "wheat", "pork", flavor(1, 1, 3, 2, 3, 2), texture(3, 1, 3, 0), 3, 3, 2, LD, SOLO, ALL_MODE, 1, 4, ["반미"], allergens=["gluten"]),
    F("sea-bun-cha", "분짜", "Bun cha", "cluster-bun", "southeast-asian", "vietnamese", "vietnam", "main", "noodle", "rice-noodle", "pork", flavor(1, 2, 3, 2, 3, 2), texture(1, 3, 3, 1), 3, 4, 3, LD, DATE, REST, 2, 3, ["분짜"]),
    F("sea-pad-thai", "팟타이", "Pad thai", "cluster-pad-thai", "southeast-asian", "thai", "thailand", "main", "noodle", "rice-noodle", "shrimp", flavor(2, 3, 3, 3, 3, 3), texture(0, 3, 3, 0), 3, 3, 2, LD, SOLO, ALL_MODE, 2, 5, ["팟타이"], allergens=["shellfish", "peanut", "egg"]),
    F("sea-green-curry", "그린커리", "Green curry", "cluster-thai-curry", "southeast-asian", "thai", "thailand", "main", "curry", "rice", "chicken", flavor(4, 2, 2, 0, 4, 4), texture(0, 1, 4, 3), 4, 3, 3, LD, SOLO, ALL_MODE, 2, 4, ["그린커리"], allergens=["shellfish"]),
    F("sea-tom-yum", "똠얌꿍", "Tom yum goong", "cluster-tom-yum", "southeast-asian", "thai", "thailand", "main", "soup", "none", "shrimp", flavor(4, 1, 3, 4, 4, 2), texture(0, 1, 2, 5), 2, 3, 3, LD, DATE, REST, 2, 4, ["똠얌꿍"], allergens=["shellfish"]),
    F("sea-nasi", "나시고랭", "Nasi goreng", "cluster-fried-rice", "southeast-asian", "indonesian", "indonesia", "main", "rice-bowl", "rice", "chicken", flavor(2, 1, 3, 1, 3, 3), texture(1, 1, 3, 0), 4, 2, 2, LDN, SOLO, ALL_MODE, 1, 4, ["나시고랭"]),
    F("sea-laksa", "락사", "Laksa", "cluster-laksa", "southeast-asian", "malaysian", "malaysia", "main", "noodle", "rice-noodle", "seafood", flavor(3, 1, 3, 1, 4, 4), texture(0, 3, 3, 5), 4, 2, 4, LD, SOLO, REST, 2, 3, ["락사"], allergens=["shellfish", "fish"]),
    F("in-butter-chicken", "버터치킨", "Butter chicken", "cluster-north-indian", "indian", "indian", "india", "main", "curry", "bread", "chicken", flavor(2, 2, 2, 0, 4, 5), texture(0, 1, 4, 2), 4, 2, 3, LD, DATE, ALL_MODE, 2, 5, ["버터치킨"], allergens=["dairy"]),
    F("in-palak", "팔락파니르", "Palak paneer", "cluster-north-indian", "indian", "indian", "india", "main", "curry", "bread", "none", flavor(2, 1, 2, 0, 3, 3), texture(0, 1, 4, 2), 3, 4, 3, LD, SOLO, ALL_MODE, 2, 3, ["팔락파니르"], diet=["vegetarian"], allergens=["dairy"]),
    F("in-biryani", "비리야니", "Biryani", "cluster-biryani", "indian", "indian", "india", "main", "rice-bowl", "rice", "chicken", flavor(3, 1, 2, 0, 4, 4), texture(0, 1, 3, 0), 5, 3, 3, LD, GRP, ALL_MODE, 2, 4, ["비리야니"]),
    F("in-kebab", "케밥", "Kebab", "cluster-kebab", "middle-eastern", "turkish", "turkey", "main", "grill", "bread", "lamb", flavor(2, 1, 3, 1, 4, 3), texture(1, 3, 3, 0), 4, 3, 3, LDN, SOLO, ALL_MODE, 2, 4, ["케밥"]),
    F("me-shawarma", "샤와르마", "Shawarma", "cluster-shawarma", "middle-eastern", "levantine", "lebanon", "main", "wrap", "wheat", "chicken", flavor(2, 1, 3, 1, 3, 3), texture(2, 2, 3, 0), 4, 3, 3, LD, SOLO, ALL_MODE, 2, 4, ["샤와르마"], allergens=["gluten"]),
    F("me-falafel", "팔라펠", "Falafel", "cluster-falafel", "middle-eastern", "levantine", "lebanon", "main", "fried", "wheat", "none", flavor(1, 0, 2, 1, 3, 2), texture(4, 1, 3, 0), 3, 4, 3, LD, SOLO, ALL_MODE, 1, 4, ["팔라펠"], diet=["vegan", "vegetarian", "halal"], allergens=["gluten", "sesame"]),
    F("me-hummus", "후무스", "Hummus", "cluster-mezze", "middle-eastern", "levantine", "lebanon", "side", "dip", "none", "none", flavor(0, 0, 2, 1, 3, 3), texture(0, 1, 5, 0), 2, 4, 2, LD, GRP, REST, 2, 3, ["후무스"], temp="cold", diet=["vegan", "vegetarian"], allergens=["sesame"]),
    F("fx-tteok-cheese", "치즈떡볶이", "Cheese tteokbokki", "cluster-tteokbokki", "fusion", "korean-fusion", "korea", "snack", "street", "rice-cake", "none", flavor(3, 2, 3, 0, 3, 4), texture(0, 5, 3, 1), 3, 1, 2, LDN, GRP, ALL_MODE, 1, 4, ["치즈떡볶이"], allergens=["dairy", "fish"]),
    F("fx-cupbap", "컵밥", "Cupbap", "cluster-cupbap", "fusion", "korean-fusion", "korea", "main", "rice-bowl", "rice", "mixed", flavor(2, 1, 3, 0, 3, 2), texture(1, 1, 3, 0), 3, 2, 1, LDN, SOLO, HOME, 1, 3, ["컵밥"]),
    F("sn-hotteok", "호떡", "Hotteok", "cluster-street-sweet", "snack", "korean", "korea", "snack", "street", "wheat", "none", flavor(0, 5, 1, 0, 1, 3), texture(2, 2, 4, 0), 2, 1, 1, LDN, SOLO, REST, 1, 4, ["호떡"], diet=["vegetarian"], allergens=["gluten"]),
    F("sn-bungeoppang", "붕어빵", "Bungeoppang", "cluster-street-sweet", "snack", "korean", "korea", "snack", "street", "wheat", "none", flavor(0, 4, 1, 0, 1, 3), texture(2, 1, 4, 0), 2, 1, 1, LDN, SOLO, REST, 1, 4, ["붕어빵"], season=["winter"], diet=["vegetarian"], allergens=["gluten"]),
    F("sn-dakgangjeong", "닭강정", "Dakgangjeong", "cluster-chicken", "snack", "korean", "korea", "snack", "fried", "none", "chicken", flavor(2, 4, 2, 1, 2, 3), texture(4, 2, 2, 0), 3, 1, 1, LDN, GRP, DELIVER, 1, 4, ["닭강정"], allergens=["gluten"]),
    F("ds-bingsu", "팥빙수", "Patbingsu", "cluster-bingsu", "dessert", "korean", "korea", "dessert", "ice", "none", "none", flavor(0, 4, 0, 0, 1, 2), texture(0, 1, 5, 0), 1, 2, 1, LD, GRP, REST, 2, 4, ["빙수"], temp="cold", season=["summer"], diet=["vegetarian"], allergens=["dairy"]),
    F("ds-tiramisu", "티라미수", "Tiramisu", "cluster-cake", "dessert", "italian", "italy", "dessert", "cake", "none", "none", flavor(0, 4, 0, 0, 2, 4), texture(0, 1, 5, 0), 2, 1, 1, ["dinner", "lateNight"], DATE, REST, 2, 4, ["티라미수"], temp="cold", diet=["vegetarian"], allergens=["dairy", "egg", "gluten"]),
    F("ds-salt-bread", "소금빵", "Salt bread", "cluster-bakery", "dessert", "korean-fusion", "korea", "snack", "bread", "wheat", "none", flavor(0, 2, 3, 0, 2, 3), texture(3, 1, 3, 0), 2, 2, 1, ALLDAY, SOLO, REST, 1, 5, ["소금빵"], diet=["vegetarian"], allergens=["gluten", "dairy"]),
    F("ds-croffle", "크로플", "Croffle", "cluster-bakery", "dessert", "fusion", "korea", "dessert", "bread", "wheat", "none", flavor(0, 4, 1, 0, 1, 3), texture(4, 1, 3, 0), 2, 1, 2, BRUNCH, DATE, REST, 2, 3, ["크로플"], diet=["vegetarian"], allergens=["gluten", "dairy", "egg"]),
    F("ds-gelato", "젤라또", "Gelato", "cluster-ice-cream", "dessert", "italian", "italy", "dessert", "ice", "none", "none", flavor(0, 5, 0, 0, 1, 3), texture(0, 0, 5, 0), 1, 1, 1, LD, DATE, REST, 2, 4, ["젤라또"], temp="cold", season=["summer"], diet=["vegetarian"], allergens=["dairy"]),
    F("kr-janchi", "잔치국수", "Janchi-guksu", "cluster-knife-noodle", "korean", "korean", "korea", "main", "noodle", "noodle", "none", flavor(0, 1, 2, 0, 2, 1), texture(0, 3, 3, 5), 2, 3, 1, LD, SOLO, HOME, 1, 3, ["잔치국수"], allergens=["gluten"]),
    F("kr-chungmu", "충무김밥", "Chungmu gimbap", "cluster-gimbap", "korean", "korean", "korea", "snack", "roll", "rice", "seafood", flavor(3, 1, 3, 2, 3, 2), texture(1, 2, 3, 0), 3, 3, 2, LD, SOLO, ALL_MODE, 1, 3, ["충무김밥"], temp="cold", allergens=["shellfish", "sesame"]),
    F("us-fish-chips", "피쉬앤칩스", "Fish and chips", "cluster-fried-fish", "western", "british", "uk", "main", "fried", "potato", "fish", flavor(0, 0, 3, 2, 3, 4), texture(5, 1, 3, 0), 4, 1, 2, LD, SOLO, REST, 3, 3, ["피쉬앤칩스"], allergens=["fish", "gluten"]),
    F("fr-onion-soup", "프렌치 어니언 수프", "French onion soup", "cluster-western-soup", "french", "french", "france", "main", "soup", "bread", "none", flavor(0, 1, 3, 0, 4, 3), texture(1, 1, 3, 5), 3, 2, 2, ["dinner"], DATE, REST, 3, 2, ["어니언수프"], allergens=["gluten", "dairy"]),
]


def extra_constants():
    return {
        "LD": LD,
        "LDN": LDN,
        "ALLDAY": ALLDAY,
        "BRUNCH": BRUNCH,
        "SOLO": SOLO,
        "GRP": GRP,
        "DATE": DATE,
        "ALL_OCC": ALL_OCC,
        "DELIVER": DELIVER,
        "HOME": HOME,
        "REST": REST,
        "ALL_MODE": ALL_MODE,
    }


def merge_foods():
    from food_expand import extra_dishes

    extras = extra_dishes(F, flavor, texture, extra_constants())
    seen_id = set()
    seen_ko = set()
    merged = []
    for item in FOODS + extras:
        if item["id"] in seen_id or item["nameKo"] in seen_ko:
            continue
        seen_id.add(item["id"])
        seen_ko.add(item["nameKo"])
        merged.append(item)
    return merged


def pack_of(item: dict) -> str:
    group = item["cuisineGroup"]
    mapping = {
        "korean": "korean",
        "chinese": "chinese",
        "japanese": "japanese",
        "italian": "western",
        "french": "western",
        "american": "western",
        "mexican": "western",
        "western": "western",
        "spanish": "western",
        "southeast-asian": "southeast-asian",
        "indian": "indian-middle-eastern",
        "middle-eastern": "indian-middle-eastern",
        "fusion": "fusion-snack-dessert",
        "snack": "fusion-snack-dessert",
        "dessert": "fusion-snack-dessert",
    }
    return mapping.get(group, "other")


def main() -> None:
    PACKS.mkdir(parents=True, exist_ok=True)
    foods = merge_foods()
    buckets: dict[str, list] = {}
    for item in foods:
        buckets.setdefault(pack_of(item), []).append(item)

    packs_meta = []
    for name in sorted(buckets):
        path = PACKS / f"{name}.json"
        payload = {"pack": name, "items": buckets[name]}
        path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        packs_meta.append({"id": name, "src": f"data/foods/packs/{name}.json", "count": len(buckets[name])})

    catalog = {
        "schemaVersion": 1,
        "count": len(foods),
        "scoreWeights": {
            "taste": 35,
            "craving": 20,
            "context": 15,
            "satietyHealth": 10,
            "budgetDining": 10,
            "popularityNovelty": 10,
        },
        "packs": packs_meta,
    }
    (OUT / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(foods)} foods in {len(packs_meta)} packs")


if __name__ == "__main__":
    main()
