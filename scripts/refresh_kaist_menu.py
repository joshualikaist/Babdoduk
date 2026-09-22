# -*- coding: utf-8 -*-
"""Fetch KAIST official cafeteria HTML into data/kaist-menu/."""
from __future__ import annotations

import html as htmlmod
import json
import re
import ssl
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "kaist-menu"
UA = "BabdodukMenu/1.0 (+https://github.com/joshualikaist/Babdoduk)"
KST = timezone(timedelta(hours=9))
BASE = "https://www.kaist.ac.kr/kr/html/campus/053001.html"

# Codes taken from official ActFodlst('...') on 053001.html — not guessed.
RESTAURANTS = [
    {"id": "fclt", "name": "카이마루 N11", "building": "N11"},
    {"id": "west", "name": "서맛골 W2", "building": "W2"},
    {"id": "east1", "name": "동맛골 학생식당 E5", "building": "E5"},
    {"id": "east2", "name": "동맛골 교직원식당 E5", "building": "E5"},
    {"id": "emp", "name": "교수회관 N6", "building": "N6"},
    {"id": "icc", "name": "문지캠퍼스", "building": "문지"},
    {"id": "hawam", "name": "화암 기숙사", "building": "화암"},
    {"id": "seoul", "name": "서울캠퍼스", "building": "서울"},
]

NOTE = re.compile(r"^(\*|안녕하세요|운영시간|금액|알레르기|인스타|주말)")
ALLERGEN = re.compile(r"^\(?\d+(?:\s*,\s*\d+)*\)?$")
PRICE = re.compile(r"(\d{1,3}(?:,\d{3})*\s*원)")
# An explicit calorie line, not a suffix match inside a thousands-separated
# number, allergen list, price, or promotional sentence.
KCAL = re.compile(r"^(?:(?:총\s*칼로리|총\s*열량|칼로리|열량)\s*[:：]?\s*)?"
                  r"(\d{1,3}(?:,\d{3})+|\d+)\s*kcal\s*$", re.I)
BR = re.compile(r"<br\s*/?>", re.I)
TAG = re.compile(r"<[^>]+>")


def now_kst() -> datetime:
    return datetime.now(KST)


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=25, context=ctx) as res:
        return res.read().decode("utf-8", "replace")


def clean_line(raw: str) -> str:
    text = TAG.sub(" ", htmlmod.unescape(raw or ""))
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    text = text.replace("<!--", " ").replace("-->", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_cell(raw: str) -> dict:
    chunks = [clean_line(part) for part in BR.split(raw)]
    items = []
    price = ""
    kcal = ""
    hours = ""
    for line in chunks:
        if not line or NOTE.match(line) or ALLERGEN.match(line):
            continue
        if line in {"-->", "<!--"} or line.startswith("-->"):
            continue
        price_m = PRICE.search(line)
        if price_m and not price:
            price = price_m.group(1).replace(" ", "")
        kcal_m = KCAL.fullmatch(line)
        if kcal_m:
            kcal = f"{int(kcal_m.group(1).replace(',', ''))} kcal"
            continue
        if re.fullmatch(r"조식|중식|석식", line.split("(")[0].strip()):
            continue
        if re.search(r"\d+:\d+", line) and not items:
            hours = line
            continue
        if line.endswith("미운영") or "운영없음" in line.replace(" ", ""):
            continue
        if price_m and PRICE.sub("", line).strip() in {"", "원"}:
            continue
        if len(line) < 2:
            continue
        items.append(line)
    return {"hours": hours, "items": items[:16], "price": price, "kcal": kcal}


def parse_meals(page: str) -> dict:
    page = re.sub(r"<!--.*?-->", " ", page, flags=re.S)
    tables = re.findall(r"<table[^>]*class=\"table\"[\s\S]*?</table>", page, re.I)
    if not tables:
        return {}
    tds = re.findall(r"<td[^>]*>([\s\S]*?)</td>", tables[0], re.I)
    keys = ["breakfast", "lunch", "dinner"]
    meals = {}
    for idx, key in enumerate(keys):
        meals[key] = parse_cell(tds[idx]) if idx < len(tds) else {"items": [], "price": "", "kcal": ""}
    return meals


def fetch_restaurant(code: str, date_s: str) -> dict:
    url = BASE + "?" + urllib.parse.urlencode({"dvs_cd": code, "stt_dt": date_s})
    page = fetch(url)
    meals = parse_meals(page)
    return meals


def build_payload(day: datetime) -> dict:
    date_s = day.strftime("%Y-%m-%d")
    label = f"{day.month}월 {day.day}일"
    restaurants = []
    for row in RESTAURANTS:
        try:
            meals = fetch_restaurant(row["id"], date_s)
        except Exception as exc:
            print(f"[warn] kaist {row['id']}: {exc}")
            continue
        if not any((meals.get(key) or {}).get("items") for key in ("breakfast", "lunch", "dinner")):
            continue
        restaurants.append({
            "id": row["id"],
            "name": row["name"],
            "building": row["building"],
            "breakfast": meals.get("breakfast") or {},
            "lunch": meals.get("lunch") or {},
            "dinner": meals.get("dinner") or {},
        })
    return {
        "date": date_s,
        "dateLabel": label,
        "fetchedAt": day.isoformat(timespec="seconds"),
        "source": BASE,
        "restaurants": restaurants,
    }


def write_payload(payload: dict) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{payload['date']}.json"
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")
    (OUT / "latest.json").write_text(text, encoding="utf-8")
    print(f"wrote {path} restaurants={len(payload['restaurants'])}")
    return path


def main() -> None:
    day = now_kst()
    payload = build_payload(day)
    if not payload["restaurants"]:
        print("[warn] kaist produced no restaurants; keeping previous files")
        sys.exit(2)
    write_payload(payload)


if __name__ == "__main__":
    main()
