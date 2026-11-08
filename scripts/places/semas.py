"""밥약 메이커 places: candidates from public data, the operator's review, the published file (docs/BOBYAK.md).

    python scripts/places/semas.py key        # says whether DATA_GO_KR_KEY is set (never prints it)
    python scripts/places/semas.py fetch      # public data -> inputs/places/candidates.json (needs the key)
    python scripts/places/semas.py review     # candidates vs published -> inputs/places/review.json, and
                                              # pending rows added to inputs/places/approvals.json
    python scripts/places/semas.py publish    # the operator's decisions -> data/places/latest.json

Source: 소상공인시장진흥공단 상가(상권)정보 API (data.go.kr 15012005), the "사각형내 상가업소 조회" operation
(storeListInRectangle). Only food businesses (상권업종 대분류 "음식") in 대전 유성구 구성동 (KAIST main campus),
어은동 and 궁동 inside one rectangle around them are kept. Nothing reaches the site without an operator's
decision in inputs/places/approvals.json: a new store becomes a "candidate" (shown only when a visitor
agrees) or "verified" (the operator checked it, with the facts they confirmed), a store that left the
public data becomes "stale" or "closed" only when the operator says so. Menus, prices and hours are
never generated: a fact exists only when the operator wrote it, with its source and date.

The key comes from the environment (DATA_GO_KR_KEY) or ~/.config/babdoduk/credentials (a file of
NAME=value lines, or, when that is a folder as on the ops PC, its file data-go-kr) and is never
printed, logged or written anywhere.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KST = timezone(timedelta(hours=9))
CANDIDATES = ROOT / "inputs" / "places" / "candidates.json"
REVIEW = ROOT / "inputs" / "places" / "review.json"
APPROVALS = ROOT / "inputs" / "places" / "approvals.json"
PUBLISHED = ROOT / "data" / "places" / "latest.json"
CREDENTIALS = Path.home() / ".config" / "babdoduk" / "credentials"
KEY_NAME = "DATA_GO_KR_KEY"
KEY_FILE = "data-go-kr"     # the file inside the credentials folder, when credentials is a folder

API = "https://apis.data.go.kr/B553077/api/open/sdsc2/storeListInRectangle"
SOURCE = {"name": "소상공인시장진흥공단 상가(상권)정보", "url": "https://www.data.go.kr/data/15012005/openapi.do",
          "terms": "공공데이터포털 표시: 이용허락범위 제한 없음, 무료"}
# One rectangle around KAIST's main campus, 어은동 and 궁동 (WGS84). The 법정동 decides the area.
BBOX = {"minx": 127.338, "miny": 36.352, "maxx": 127.376, "maxy": 36.382}
AREA_OF_DONG = {"구성동": "kaist", "어은동": "eoeun", "궁동": "gung"}
PAGE_ROWS = 1000
MAX_PAGES = 20
PAUSE = 0.5        # seconds between pages: a handful of calls per run, far under any daily limit

# Cuisine from the store's category names (상권업종 중분류/소분류), first match wins.
CUISINE_RULES = (
    ("cafe", ("비알코올", "카페", "커피")),
    ("snack", ("분식", "김밥", "만두", "떡볶이", "라면")),
    ("bakery", ("제과", "제빵", "빵", "떡", "케이크", "디저트", "아이스크림", "빙수", "도넛")),
    ("pub", ("주점", "호프", "맥주", "요리주점", "술")),
    ("fastfood", ("햄버거", "피자", "치킨", "패스트푸드", "토스트", "샌드위치")),
    ("chinese", ("중식", "중국")),
    ("japanese", ("일식", "일본", "초밥", "돈가스", "라멘", "우동", "회")),
    ("western", ("서양식", "양식", "경양식", "파스타", "스테이크", "레스토랑")),
    ("asian", ("동남아", "베트남", "태국", "인도", "기타 외국식", "외국식", "쌀국수")),
    ("korean", ("한식", "백반", "국밥", "찌개", "고기", "갈비", "삼겹살", "냉면", "국수", "족발", "보쌈", "해장국", "칼국수")),
)
FACT_KINDS = ("budget", "menu", "hours", "closedDay", "phone", "note")
BANDS = ("under10k", "10to15k", "over15k")
FACT_SOURCES = ("operator", "official", "public-data", "tip")
DATE_RE = re.compile(r"^20[0-9]{2}-[01][0-9]-[0-3][0-9]$")
ID_RE = re.compile(r"^p-([0-9]{4,24})$")


class PlacesError(Exception):
    """A stop with a message that never contains the key."""


# ---------- key ----------
def read_key(environ=None, credentials: Path | None = None) -> str | None:
    environ = os.environ if environ is None else environ
    value = (environ.get(KEY_NAME) or "").strip()
    if value:
        return value
    path = CREDENTIALS if credentials is None else credentials
    # On the ops PC ~/.config/babdoduk/credentials is a folder with one file per secret, so the key lives
    # in credentials/data-go-kr, written either as DATA_GO_KR_KEY=... or as the key alone on one line.
    alone = path.is_dir()
    if alone:
        path = path / KEY_FILE
    try:
        lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError:
        return None
    for line in lines:
        if line.startswith("export "):
            line = line[len("export "):].strip()
        name, sep, rest = line.partition("=")
        if sep and name.strip() == KEY_NAME:
            rest = rest.strip().strip('"').strip("'")
            return rest or None
    if alone and len(lines) == 1 and not lines[0].startswith("#"):
        return lines[0].strip('"').strip("'") or None
    return None


# ---------- fetch ----------
def cuisine_of(*names: str) -> str:
    text = " ".join(n for n in names if n)
    for cuisine, words in CUISINE_RULES:
        if any(word in text for word in words):
            return cuisine
    return "other"


def normalize(row: dict) -> dict | None:
    """One public-data row -> a candidate, or None when it is not a food business in our three areas."""
    get = lambda key: str(row.get(key) or "").strip()
    if get("indsLclsNm") != "음식":
        return None
    if get("ctprvnNm") not in ("대전광역시", "") or get("signguNm") not in ("유성구", ""):
        return None
    area = AREA_OF_DONG.get(get("ldongNm"))
    if not area or not get("bizesId") or not get("bizesNm"):
        return None
    try:
        lat, lng = float(get("lat")), float(get("lon"))
    except ValueError:
        lat = lng = None
    if lat is not None and not (BBOX["miny"] <= lat <= BBOX["maxy"] and BBOX["minx"] <= lng <= BBOX["maxx"]):
        return None
    address = get("rdnmAdr") or get("lnoAdr")
    if len(address) < 4:
        return None
    candidate = {"ref": re.sub(r"[^A-Za-z0-9_-]", "", get("bizesId"))[:40], "name": get("bizesNm")[:80],
                 "area": area, "address": address[:160],
                 "cuisine": cuisine_of(get("indsMclsNm"), get("indsSclsNm")),
                 "category": " > ".join(n for n in (get("indsMclsNm"), get("indsSclsNm")) if n)}
    if get("brchNm"):
        candidate["branch"] = get("brchNm")[:40]
    if lat is not None:
        candidate["lat"], candidate["lng"] = round(lat, 6), round(lng, 6)
    return candidate if candidate["ref"] else None


def parse_page(text: str) -> tuple[list[dict], int]:
    """The rows and totalCount of one XML page. resultCode 03 is "no data"; anything else stops."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        raise PlacesError("the public-data API answered something that is not XML")
    gateway = root.findtext(".//returnReasonCode")
    if gateway:
        raise PlacesError(f"data.go.kr refused the request (returnReasonCode {gateway}: "
                          f"{(root.findtext('.//returnAuthMsg') or '').strip()[:80]})")
    code = (root.findtext(".//header/resultCode") or "").strip()
    if code == "03":
        return [], 0
    if code != "00":
        raise PlacesError(f"the public-data API answered resultCode {code or '?'}: "
                          f"{(root.findtext('.//header/resultMsg') or '').strip()[:80]}")
    rows = [{child.tag: (child.text or "") for child in item} for item in root.iter("item")]
    total = int((root.findtext(".//body/totalCount") or "0").strip() or 0)
    return rows, total


def fetch(key: str, opener=urllib.request.urlopen, pause: float = PAUSE) -> list[dict]:
    rows: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        query = urllib.parse.urlencode({"serviceKey": key, "pageNo": page, "numOfRows": PAGE_ROWS, **BBOX})
        try:
            with opener(f"{API}?{query}", timeout=30) as response:
                text = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raise PlacesError(f"the public-data API answered HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PlacesError(f"could not reach the public-data API ({type(exc).__name__})") from None
        found, total = parse_page(text)
        rows += found
        if not found or len(rows) >= total:
            break
        time.sleep(pause)
    else:
        raise PlacesError(f"more than {MAX_PAGES * PAGE_ROWS} stores in the rectangle: narrow it before trusting a partial list")
    return rows


def build_candidates(rows: list[dict], now: datetime) -> dict:
    stores: dict[str, dict] = {}
    for row in rows:
        candidate = normalize(row)
        if candidate:
            stores[candidate["ref"]] = candidate
    return {"fetchedAt": now.isoformat(timespec="seconds"), "source": SOURCE["name"], "operation": "storeListInRectangle",
            "bbox": BBOX, "count": len(stores), "stores": [stores[ref] for ref in sorted(stores)]}


# ---------- review ----------
def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def empty_feed() -> dict:
    return {"schemaVersion": 1, "updatedAt": None, "source": dict(SOURCE), "places": []}


def semas_ref(place: dict) -> str | None:
    for source in place.get("sources") or []:
        if source.get("kind") == "semas":
            return source.get("ref")
    return None


def review(candidates: dict, published: dict, approvals: dict) -> tuple[dict, dict]:
    """What changed between the public data and the published file, and the approvals file with a
    pending row for every change nobody has decided yet (decisions already written are kept)."""
    stores = {store["ref"]: store for store in candidates.get("stores") or []}
    places = {semas_ref(place): place for place in published.get("places") or [] if semas_ref(place)}
    report = {"fetchedAt": candidates.get("fetchedAt"), "new": [], "missing": [], "changed": []}
    for ref, store in stores.items():
        place = places.get(ref)
        if place is None:
            report["new"].append(store)
        elif (store["name"], store["address"]) != (place["name"], place["address"]):
            report["changed"].append({"ref": ref, "id": place["id"], "before": {"name": place["name"], "address": place["address"]},
                                      "after": {"name": store["name"], "address": store["address"]}})
    for ref, place in places.items():
        if ref not in stores and place.get("status") != "closed":
            report["missing"].append({"ref": ref, "id": place["id"], "name": place["name"], "address": place["address"],
                                      "status": place["status"]})
    items = list(approvals.get("items") or [])
    pending = {(item.get("kind"), item.get("ref")) for item in items}
    for store in report["new"]:
        if ("new", store["ref"]) not in pending:
            items.append({"kind": "new", "ref": store["ref"], "name": store["name"], "address": store["address"],
                          "category": store.get("category", ""), "decision": "", "checkedAt": "", "facts": []})
    for row in report["missing"]:
        if ("missing", row["ref"]) not in pending:
            items.append({"kind": "missing", "ref": row["ref"], "id": row["id"], "name": row["name"],
                          "address": row["address"], "decision": ""})
    for row in report["changed"]:
        if ("changed", row["ref"]) not in pending:
            items.append({"kind": "changed", "ref": row["ref"], "id": row["id"], "before": row["before"],
                          "after": row["after"], "decision": ""})
    return report, {"_how": APPROVALS_HOW, "items": items}


APPROVALS_HOW = ("Fill in decision for each row, then run: python scripts/places/semas.py publish. "
                 "new: verified | candidate | skip (verified also needs checkedAt and may carry facts). "
                 "missing: stale | closed | keep. changed: accept | keep. "
                 "promote (add by hand with ref or id): verified, with checkedAt and facts. "
                 "Empty decision = not decided; nothing happens to that row.")


# ---------- publish ----------
def clean_facts(facts, where: str) -> list[dict]:
    out = []
    for n, fact in enumerate(facts or []):
        if not isinstance(fact, dict):
            raise PlacesError(f"{where}: fact {n} is not an object")
        row = {key: fact[key] for key in ("kind", "text", "textEn", "band", "source", "url", "checkedAt") if fact.get(key)}
        problems = feed_fact_errors(row)
        if problems:
            raise PlacesError(f"{where}: fact {n}: {'; '.join(problems)}")
        out.append(row)
    return out


def next_id(places: list[dict]) -> str:
    numbers = [int(m.group(1)) for m in (ID_RE.match(p["id"]) for p in places) if m]
    return f"p-{(max(numbers) + 1 if numbers else 1):04d}"


def publish(candidates: dict, published: dict, approvals: dict, today: str) -> tuple[dict, dict]:
    """Apply every decided row. Returns the new feed and a summary; never touches an undecided row."""
    stores = {store["ref"]: store for store in candidates.get("stores") or []}
    feed = json.loads(json.dumps(published)) if published.get("places") is not None else empty_feed()
    feed["source"] = dict(SOURCE)
    places = feed["places"]
    by_ref = {semas_ref(place): place for place in places if semas_ref(place)}
    by_id = {place["id"]: place for place in places}
    summary = {"added": 0, "verified": 0, "stale": 0, "closed": 0, "updated": 0, "skipped": 0, "undecided": 0}
    for n, item in enumerate(approvals.get("items") or []):
        decision, kind = str(item.get("decision") or "").strip(), item.get("kind")
        where = f"approvals row {n} ({kind} {item.get('ref') or item.get('id')})"
        if not decision:
            summary["undecided"] += 1
            continue
        place = by_id.get(item.get("id")) or by_ref.get(item.get("ref"))
        if decision in ("skip", "keep"):
            summary["skipped"] += 1
            continue
        if decision in ("verified", "candidate"):
            if place is None:
                store = stores.get(item.get("ref"))
                if store is None:
                    raise PlacesError(f"{where}: no candidate with this ref; run fetch and review first")
                place = {"id": next_id(places), "name": store["name"], "area": store["area"], "address": store["address"],
                         "cuisine": store["cuisine"], "status": "candidate", "verifiedAt": None, "facts": [],
                         "sources": [{"kind": "semas", "ref": store["ref"], "checkedAt": candidates["fetchedAt"][:10]}],
                         "updatedAt": today}
                for key in ("branch", "lat", "lng"):
                    if key in store:
                        place[key] = store[key]
                places.append(place)
                by_ref[store["ref"]] = by_id[place["id"]] = place
                summary["added"] += 1
            if item.get("cuisine"):
                place["cuisine"] = item["cuisine"]
            if item.get("nameEn"):
                place["nameEn"] = str(item["nameEn"])[:120]
            if decision == "verified":
                checked = str(item.get("checkedAt") or "")
                if not DATE_RE.match(checked):
                    raise PlacesError(f"{where}: verified needs checkedAt (YYYY-MM-DD, the day you checked it)")
                facts = clean_facts(item.get("facts"), where)
                if (place["status"], place["verifiedAt"], place["facts"]) != ("verified", checked, facts):
                    place.update(status="verified", verifiedAt=checked, facts=facts, updatedAt=today)
                    summary["verified"] += 1
            continue
        if place is None:
            raise PlacesError(f"{where}: no published place with this ref or id")
        if decision in ("stale", "closed") and kind in ("missing", "status"):
            if place["status"] != decision:
                place.update(status=decision, updatedAt=today)
                summary[decision] += 1
        elif decision == "accept" and kind == "changed":
            after = item.get("after") or {}
            name = str(after.get("name") or place["name"])[:80]
            address = str(after.get("address") or place["address"])[:160]
            if (name, address) != (place["name"], place["address"]):
                place.update(name=name, address=address, updatedAt=today)
                summary["updated"] += 1
        else:
            raise PlacesError(f"{where}: decision {decision!r} does not fit a {kind!r} row")
    places.sort(key=lambda place: place["id"])
    feed["updatedAt"] = today
    problems = feed_errors(feed)
    if problems:
        raise PlacesError("the new file would break its contract: " + "; ".join(problems[:5]))
    return feed, summary


# ---------- rules a schema cannot state (also run by scripts/validate_content.py) ----------
def feed_fact_errors(fact: dict) -> list[str]:
    errors = []
    if fact.get("kind") not in FACT_KINDS:
        errors.append(f"kind must be one of {', '.join(FACT_KINDS)}")
    if not str(fact.get("text") or "").strip():
        errors.append("text is required")
    if fact.get("source") not in FACT_SOURCES:
        errors.append(f"source must be one of {', '.join(FACT_SOURCES)}")
    if not DATE_RE.match(str(fact.get("checkedAt") or "")):
        errors.append("checkedAt must be YYYY-MM-DD")
    if fact.get("kind") == "budget" and fact.get("band") not in BANDS:
        errors.append(f"a budget fact needs band {', '.join(BANDS)}")
    if fact.get("kind") != "budget" and "band" in fact:
        errors.append("only a budget fact has a band")
    return errors


def feed_errors(feed: dict) -> list[str]:
    """The contract (schemas/places-feed.schema.json) and the rules below."""
    from schema_check import schema_errors
    return list(schema_errors(feed, "places-feed", "data/places/latest.json")) + feed_rule_errors(feed)


def feed_rule_errors(feed: dict) -> list[str]:
    errors: list[str] = []
    ids, refs = set(), set()
    for place in feed.get("places") or []:
        tag = f"data/places/latest.json {place.get('id')}"
        if place.get("id") in ids:
            errors.append(f"{tag}: id used twice")
        ids.add(place.get("id"))
        ref = semas_ref(place)
        if ref and ref in refs:
            errors.append(f"{tag}: public-data store {ref} is published twice")
        refs.add(ref)
        if place.get("status") == "verified" and not place.get("verifiedAt"):
            errors.append(f"{tag}: a verified place says when it was checked (verifiedAt)")
        if place.get("status") == "candidate" and place.get("verifiedAt"):
            errors.append(f"{tag}: a candidate was never verified (verifiedAt is null)")
        if place.get("status") == "candidate" and place.get("facts"):
            errors.append(f"{tag}: a candidate carries no facts (nobody confirmed them)")
        for fact in place.get("facts") or []:
            errors += [f"{tag}: {problem}" for problem in feed_fact_errors(fact)]
    return errors


# ---------- command line ----------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=("key", "fetch", "review", "publish"))
    args = parser.parse_args(argv)
    now = datetime.now(KST)
    try:
        if args.command == "key":
            print(f"{KEY_NAME}: {'set' if read_key() else 'not set'}")
            return 0
        if args.command == "fetch":
            key = read_key()
            if not key:
                raise PlacesError(f"{KEY_NAME} is not set (environment or {CREDENTIALS}); no request was made")
            data = build_candidates(fetch(key), now)
            write(CANDIDATES, data)
            print(f"candidates: {data['count']} food stores in KAIST/어은동/궁동 -> {CANDIDATES.relative_to(ROOT)}")
            return 0
        candidates = load(CANDIDATES, None)
        if candidates is None:
            raise PlacesError(f"{CANDIDATES.relative_to(ROOT)} is missing: run fetch first")
        published = load(PUBLISHED, empty_feed())
        approvals = load(APPROVALS, {"items": []})
        if args.command == "review":
            report, approvals = review(candidates, published, approvals)
            write(REVIEW, report)
            write(APPROVALS, approvals)
            print(f"review: {len(report['new'])} new, {len(report['missing'])} missing, {len(report['changed'])} changed; "
                  f"decide in {APPROVALS.relative_to(ROOT)}")
            return 0
        feed, summary = publish(candidates, published, approvals, now.date().isoformat())
        write(PUBLISHED, feed)
        print("published: " + ", ".join(f"{k} {v}" for k, v in summary.items()) + f" -> {PUBLISHED.relative_to(ROOT)}")
        return 0
    except PlacesError as exc:
        print(f"places: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "scripts"))
    sys.exit(main())
