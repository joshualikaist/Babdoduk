"""The data contracts in schemas/ (data plan phase 3, 2026-10-12).

Every governed file keeps its contract; each schema accepts a minimal valid example and refuses
the breaks that matter for it; the built-in checker (scripts/schema_check.py) and the reference
implementation (jsonschema, installed in CI) give the same verdict on all of them. No network.
"""
import copy
import json
import shutil

import pytest

import schema_check as sc
import validate_content

NAMES = sorted(path.name[:-len(".schema.json")] for path in sc.SCHEMAS.glob("*.schema.json"))
KST = "2026-10-12T09:00:00+09:00"
EVENT = {"id": "evt-1", "title": "점심 도시락 제공 세미나", "summary": "", "startAt": "2026-10-12T12:00:00+09:00",
         "endAt": None, "dateText": "10월 12일", "timeText": "12:00",
         "location": {"name": "", "building": "N1", "room": "101"},
         "food": {"provided": "true", "type": "lunchbox", "description": "도시락"},
         "organizer": "", "eligibility": "",
         "registration": {"required": "unknown", "deadline": None, "url": ""}, "confidence": 0.9,
         "sources": [{"type": "kaist_public", "name": "KAIST 공지", "url": "https://www.kaist.ac.kr/news/1"}]}
ARCHIVED = {k: v for k, v in EVENT.items() if k not in ("registration", "confidence")}
NEWS = {"id": "news-" + "0" * 32, "contentType": "campus_food_news", "noticeDate": "2026-10-12",
        "title": "교내 신규 식당 오픈 안내", "sources": [{"type": "portal", "name": "KAIST 포탈"}]}
MEAL = {"items": ["김치찌개", "쌀밥"], "price": "5,000원", "kcal": "", "hours": "11:30~13:30"}
STORY = {"title": "양파 간장 조림", "source": "엄마표 집밥", "url": "https://a.example/onion", "medium": "blog",
         "summary": "양파를 먼저 볶는다.", "candidateId": "c_0123456789abcdef", "publishedAt": "2026-10-10T09:00:00+09:00"}
DISH = {"id": "kimchi-jjigae", "parentId": "cluster-jjigae", "nameKo": "김치찌개", "nameEn": "Kimchi stew",
        "category": "main", "cuisine": "korean", "cuisineGroup": "korean", "region": "korea", "dishType": "stew",
        "mainProtein": "pork", "mainCarb": "rice", "temperature": "hot",
        "texture": {"soft": 3, "chewy": 1, "crispy": 0, "soupy": 5},
        "flavor": {"salty": 4, "sweet": 1, "sour": 3, "spicy": 4, "umami": 4, "rich": 3},
        "satiety": 4, "healthiness": 3, "priceLevel": 1, "prepDifficulty": 2, "popularity": 5, "adventurousness": 1,
        "allergens": ["soy"], "diet": [], "diningMode": ["restaurant", "homeCooking"], "mealTime": ["lunch", "dinner"],
        "occasion": ["solo"], "season": ["all"], "keywords": ["찌개"]}
VALID = {
    "ggongbab-feed": {"schemaVersion": 1, "generatedAt": KST, "timezone": "Asia/Seoul", "count": 1, "events": [EVENT]},
    "ggongbab-archive": {"generatedAt": KST, "timezone": "Asia/Seoul", "windowDays": 30, "count": 1, "events": [ARCHIVED]},
    "ggongbab-news": {"schemaVersion": 1, "generatedAt": KST, "timezone": "Asia/Seoul", "count": 1, "items": [NEWS]},
    "ggongbab-news-input": {"items": [NEWS]},
    "ggongbab-manual": {"_comment": "hand-written", "items": [{"id": "m1", "text": "10월 12일 N1 101호 도시락 제공",
                                                               "url": "https://a.example/n", "date": "2026-10-11"}]},
    "kaist-menu-day": {"schemaVersion": 1, "date": "2026-10-12", "dateLabel": "10월 12일", "fetchedAt": KST,
                       "source": "https://www.kaist.ac.kr/kr/html/campus/053001.html", "status": "AVAILABLE",
                       "coverage": {"requested": 1, "fetched": 1, "failed": [], "carried": []},
                       "restaurants": [{"id": "west", "name": "서측식당", "building": "W2",
                                        "breakfast": dict(MEAL, items=[]), "lunch": MEAL, "dinner": MEAL}]},
    "kaist-menu-week": {"schemaVersion": 1, "weekStart": "2026-10-12", "weekEnd": "2026-10-18", "generatedAt": KST,
                        "timezone": "Asia/Seoul",
                        "days": [{"date": f"2026-10-{12 + n}", "available": n == 0, "restaurantCount": 1 if n == 0 else 0,
                                  "status": "AVAILABLE" if n == 0 else "NOT_PUBLISHED_YET",
                                  "fetchedAt": KST if n == 0 else None} for n in range(7)]},
    "magazine-edition": {"schemaVersion": 1, "date": "2026-10-12", "generatedAt": KST, "rules": "lanes-v1",
                         "featured": dict(STORY, category="tips", heroKind="pick"),
                         "lanes": {lane: {"lead": lane, "items": [STORY] if lane == "tips" else []}
                                   for lane in ("tips", "trend", "health", "habit")}},
    "magazine-index": {"schemaVersion": 1, "latest": "2026-10-12", "dates": ["2026-10-12", "2026-10-11"]},
    "magazine-candidate": {"candidateId": "c_0123456789abcdef", "sourceUrl": "https://a.example/onion", "title": "t",
                           "selected": False, "score": 0.5, "seenVia": ["rss:x"], "trendSignals": {}},
    "magazine-run": {"runAt": KST, "queries": [{"sourceId": "web", "query": "편의점 신상"}],
                     "counts": {"fabricated": 0, "candidates": 3}, "edition": "2026-10-12"},
    "magazine-health": {"generatedAt": KST, "adapters": {"news-a": {"type": "rss", "adapter": "OK", "status": "ACTIVE"}},
                        "summary": {"fabricated": 0, "candidates": 3}, "lanes": {}, "pending": [], "warnings": []},
    "magazine-source-health": {"version": 1, "sources": {"news-a": {"status": "ACTIVE", "failureCount": 0,
                                                                    "lastFailureCode": None}}},
    "foods-catalog": {"schemaVersion": 1, "count": 1,
                      "packs": [{"id": "korean", "src": "data/foods/packs/korean.json", "count": 1}],
                      "scoreWeights": {"taste": 30, "craving": 20, "context": 15, "satietyHealth": 15,
                                       "budgetDining": 10, "popularityNovelty": 10}},
    "foods-pack": {"pack": "korean", "items": [DISH]},
    "food-log": {"currency": "KRW", "entries": [{"date": "2026-05-06", "total": 9200, "note": "",
                                                 "items": [{"meal": "저녁", "label": "돈까스", "amount": 9200}]}]},
}
COMPACT = {"compact": True, "candidateId": "c_0123456789abcdef", "sourceUrl": "https://a.example/onion",
           "rejectionReason": "NOT_FOOD", "discoveredSeq": 7}


def _set(path, value):
    """A change at a path like events.0.food.type."""
    def change(doc):
        node = doc
        keys = path.split(".")
        for key in keys[:-1]:
            node = node[int(key)] if isinstance(node, list) else node[key]
        last = keys[-1]
        if value is _set.DELETE:
            del node[int(last) if isinstance(node, list) else last]
        else:
            node[int(last) if isinstance(node, list) else last] = value
        return doc
    return change


_set.DELETE = object()
# The breaks that matter for each contract: a private or unknown key, a wrong vocabulary, a broken
# id or time, a missing field. Each must fail.
BREAKS = {
    "ggongbab-feed": [("a private field", _set("events.0.sender_email", "a@b.c")),
                      ("an unknown food type", _set("events.0.food.type", "pizza")),
                      ("a time without +09:00", _set("events.0.startAt", "2026-10-12T03:00:00Z")),
                      ("a source URL that is not http(s)", _set("events.0.sources.0.url", "javascript:alert(1)")),
                      ("a future schemaVersion", _set("schemaVersion", 2))],
    "ggongbab-archive": [("registration in a past listing", _set("events.0.registration", EVENT["registration"])),
                         ("no window", _set("windowDays", _set.DELETE))],
    "ggongbab-news": [("a source URL", _set("items.0.sources.0.url", "https://portal.kaist.ac.kr/x")),
                      ("review evidence", _set("items.0.evidence", "원문")),
                      ("an id that is not derived", _set("items.0.id", "news-1")),
                      ("an events array", _set("events", []))],
    "ggongbab-news-input": [("review evidence", _set("items.0.campusEvidence", "교내")),
                            ("the old review format", _set("records", []))],
    "ggongbab-manual": [("an item without text", _set("items.0.text", _set.DELETE)),
                        ("a typo in a key", _set("items.0.titel", "x"))],
    "kaist-menu-day": [("no restaurant", _set("restaurants", [])),
                       ("a meal without items", _set("restaurants.0.lunch.items", _set.DELETE)),
                       ("a source outside kaist.ac.kr", _set("source", "https://a.example/menu")),
                       ("a status other than AVAILABLE", _set("status", "STALE"))],
    "kaist-menu-week": [("six days", _set("days.6", _set.DELETE)),
                        ("an unknown status", _set("days.0.status", "OK"))],
    "magazine-edition": [("a desk story", _set("lanes.tips.items.0.medium", "desk")),
                         ("a story without a real URL", _set("lanes.tips.items.0.url", "javascript:alert(1)")),
                         ("empty trend evidence", _set("lanes.tips.items.0.trendEvidence", [])),
                         ("an idea desk", _set("desks", {})),
                         ("a lane missing", _set("lanes.habit", _set.DELETE))],
    "magazine-index": [("a date that is not a date", _set("dates.0", "latest"))],
    "magazine-candidate": [("a cookie", _set("cookie", "x")), ("a broken id", _set("candidateId", "x")),
                           ("a URL that is not http(s)", _set("sourceUrl", "javascript:alert(1)"))],
    "magazine-run": [("a fabricated story", _set("counts.fabricated", 1))],
    "magazine-health": [("a fabricated story", _set("summary.fabricated", 1)),
                        ("an unknown status", _set("adapters.news-a.status", "BROKEN"))],
    "magazine-source-health": [("an unknown status", _set("sources.news-a.status", "BROKEN"))],
    "foods-catalog": [("a pack outside data/foods/packs", _set("packs.0.src", "../secret.json")),
                      ("a missing weight", _set("scoreWeights.taste", _set.DELETE))],
    "foods-pack": [("an unknown category", _set("items.0.category", "brunch")),
                   ("a score above 5", _set("items.0.satiety", 6)),
                   ("a field missing", _set("items.0.keywords", _set.DELETE)),
                   ("an upper-case id", _set("items.0.id", "Kimchi"))],
    "food-log": [("another currency", _set("currency", "USD")), ("a negative amount", _set("entries.0.items.0.amount", -1))],
}


def test_every_schema_is_used_and_every_contract_governs_files():
    assert {name for _, name, _, _ in sc.CONTRACTS} == set(NAMES) == set(VALID)
    found = {name for _, name, _ in sc.contract_files()}
    assert found == set(NAMES)                                  # every contract has at least one real file
    for name in NAMES:
        sc.load_schema(name)                                    # only the supported keyword subset


def test_every_governed_file_keeps_its_contract():
    assert sc.contract_errors() == []


@pytest.mark.parametrize("name", NAMES)
def test_each_contract_accepts_its_example_and_refuses_its_breaks(name):
    assert sc.schema_errors(VALID[name], name) == []
    assert BREAKS[name]
    for label, change in BREAKS[name]:
        assert sc.schema_errors(change(copy.deepcopy(VALID[name])), name), label


def test_a_store_row_is_whole_or_compact_never_a_mix():
    assert sc.schema_errors(COMPACT, "magazine-candidate") == []
    assert sc.schema_errors(dict(COMPACT, sourceExcerpt="본문"), "magazine-candidate")   # compact keeps no text
    assert sc.schema_errors(dict(VALID["magazine-candidate"], compact=True), "magazine-candidate")


def test_a_schema_outside_the_supported_subset_is_refused(tmp_path, monkeypatch):
    (tmp_path / "odd.schema.json").write_text(json.dumps({"type": "object", "if": {}}), encoding="utf-8")
    monkeypatch.setattr(sc, "SCHEMAS", tmp_path)
    sc.load_schema.cache_clear()
    with pytest.raises(ValueError, match="outside the supported subset"):
        sc.load_schema("odd")
    sc.load_schema.cache_clear()


def test_the_reference_implementation_agrees():
    jsonschema = pytest.importorskip("jsonschema")
    for name in NAMES:
        schema = sc.load_schema(name)
        jsonschema.Draft202012Validator.check_schema(schema)
        reference = jsonschema.Draft202012Validator(schema)
        cases = [VALID[name]] + [change(copy.deepcopy(VALID[name])) for _, change in BREAKS[name]]
        if name == "magazine-candidate":
            cases.append(COMPACT)
        for case in cases:
            assert reference.is_valid(case) == (not sc.schema_errors(case, name)), (name, case)
    for path, name, lines in sc.contract_files():
        reference = jsonschema.Draft202012Validator(sc.load_schema(name))
        text = path.read_text(encoding="utf-8")
        for value in ([json.loads(line) for line in text.splitlines() if line.strip()] if lines else [json.loads(text)]):
            assert reference.is_valid(value), path


def test_a_broken_file_fails_its_own_family_only(tmp_path):
    (tmp_path / "data/kaist-menu").mkdir(parents=True)
    (tmp_path / "data/magazine").mkdir(parents=True)
    (tmp_path / "data/kaist-menu/week.json").write_text(json.dumps({"weekStart": "2026-10-12"}), encoding="utf-8")
    (tmp_path / "data/magazine/index.json").write_text(json.dumps(VALID["magazine-index"]), encoding="utf-8")
    assert sc.contract_errors({"kaist-menu"}, tmp_path)
    assert sc.contract_errors({"magazine"}, tmp_path) == []


def test_authored_data_agrees_with_itself(tmp_path):
    shutil.copytree(sc.ROOT / "data" / "foods", tmp_path / "data" / "foods")
    (tmp_path / "inputs/ggongbab").mkdir(parents=True)
    assert validate_content.validate_authored(tmp_path) == []
    catalog = json.loads((tmp_path / "data/foods/catalog.json").read_text(encoding="utf-8"))
    catalog["count"] += 1
    (tmp_path / "data/foods/catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
    (tmp_path / "data/food-log.json").write_text(json.dumps(
        {"currency": "KRW", "entries": [{"date": "2026-05-06", "total": 1, "items": [{"meal": "a", "label": "b", "amount": 2}]}]}),
        encoding="utf-8")
    forged = dict(NEWS, title="교내 신규 카페 오픈 안내")                 # the id no longer derives from the facts
    (tmp_path / "inputs/ggongbab/food-news.json").write_text(json.dumps({"items": [forged]}), encoding="utf-8")
    errors = validate_content.validate_authored(tmp_path)
    assert any("catalog count" in e for e in errors) and any("food-log" in e for e in errors)
    assert any("public news check" in e for e in errors)
