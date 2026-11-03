# -*- coding: utf-8 -*-
"""The campus building table, data/campus/buildings.json, and where an event sits on it.

Generated from inputs/campus3d/campus.json (OpenStreetMap, scripts/campus3d/extract_osm.py) and
inputs/campus3d/buildings-extra.json (a person: aliases and the buildings OSM lacks). One row per
building code: its names, the aliases events use, its anchor (area centroid of its largest outline,
meters east and north of the campus centre) and the height of its roof. The 3D map puts a pin
there; the model is built from the same campus.json, so the two always agree.

    python scripts/campus3d/buildings.py            # write data/campus/buildings.json
    python scripts/campus3d/buildings.py --check    # fail when it is out of date
    python scripts/campus3d/buildings.py --coverage data/ggongbab/latest.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CAMPUS = ROOT / "inputs" / "campus3d" / "campus.json"
EXTRA = ROOT / "inputs" / "campus3d" / "buildings-extra.json"
TABLE = ROOT / "data" / "campus" / "buildings.json"
LEVEL = 3.6                     # meters per floor in the model (scripts/campus3d/build_model.py)
CODE = re.compile(r"(?<![A-Za-z0-9])([EWNS]\d{1,2}(?:-\d)?)(?![0-9])")
SUFFIX = re.compile(r"\s*\(\s*[EWNS]\d{1,2}(?:-\d)?\s*\)\s*$")


def height(b: dict) -> float:
    """Roof height in meters: OSM floors, else a guess from the footprint area."""
    if b.get("levels"):
        return b["levels"] * LEVEL + 1.0
    area = b.get("area") or 0
    return (1 if area < 150 else 2 if area < 600 else 4) * LEVEL + 1.0


def centroid(pts: list) -> tuple[float, float]:
    a = cx = cy = 0.0
    for i in range(len(pts)):
        x0, y0 = pts[i - 1]
        x1, y1 = pts[i]
        cross = x0 * y1 - x1 * y0
        a += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if abs(a) < 1e-9:
        return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
    return cx / (3 * a), cy / (3 * a)


def clean(name: str | None, code: str) -> str:
    text = SUFFIX.sub("", (name or "").strip())
    text = re.sub(r"\(\s*" + re.escape(code) + r"\s*\)", "", text).strip()
    return text or code


def code_key(code: str) -> tuple:
    zone, rest = code[0], code[1:]
    main, _, sub = rest.partition("-")
    return ("EWNS".index(zone), int(main), int(sub or 0))


def build(campus: dict, extra: dict) -> dict:
    by_code: dict[str, list[dict]] = {}
    for b in campus["buildings"]:
        if b.get("code"):
            by_code.setdefault(b["code"], []).append(b)
    rows = []
    for code in sorted(by_code, key=code_key):
        parts = by_code[code]
        main = max(parts, key=lambda b: b.get("area") or 0)
        x, y = centroid(main["pts"][:-1] if main["pts"][0] == main["pts"][-1] else main["pts"])
        named = next((b for b in parts if b.get("name")), main)
        aliases = [a for b in parts for a in b.get("aka") or []] + list(extra.get("aliases", {}).get(code, []))
        name = clean(named.get("name"), code)
        rows.append({"code": code, "name": name, "nameEn": clean(named.get("name_en"), code),
                     "aliases": sorted({a.strip() for a in aliases
                                        if len(a.strip()) >= 2 and a.strip() != name and not CODE.fullmatch(a.strip())}),
                     "at": [round(x, 1), round(y, 1)], "top": round(max(height(b) for b in parts), 1)})
    placed = {r["code"] for r in rows}
    unplaced = [u for u in extra.get("unplaced", []) if u["code"] not in placed]
    # An alias two buildings share would place an event on a guess: it is dropped from both.
    counts: dict[str, int] = {}
    for r in rows + unplaced:
        for a in {r["name"], *r["aliases"]}:
            counts[a] = counts.get(a, 0) + 1
    for r in rows + unplaced:
        r["aliases"] = [a for a in r["aliases"] if counts[a] == 1]
    return {"schemaVersion": 1, "attribution": campus["attribution"],
            "origin": {"lat": round(campus["origin"]["lat"], 7), "lon": round(campus["origin"]["lon"], 7)},
            "buildings": rows, "unplaced": unplaced}


def render(table: dict) -> str:
    return json.dumps(table, ensure_ascii=False, indent=1) + "\n"


def place(location: dict | None, table: dict) -> dict:
    """Where an event's location sits: {"code", "placed", "others"}; code None when unknown.

    A building code anywhere in the building or place name wins (the first one when an event names
    two, "E6-1 / E4": `others` counts the rest); otherwise the longest name or alias found in them."""
    location = location or {}
    text = " ".join(str(location.get(k) or "") for k in ("building", "name"))
    known = {r["code"]: True for r in table["buildings"]} | {u["code"]: False for u in table["unplaced"]}
    codes = list(dict.fromkeys(CODE.findall(text)))
    if codes:
        first = codes[0]
        return {"code": first if first in known else None, "placed": known.get(first, False), "others": len(codes) - 1}
    best = None
    for row in table["buildings"] + table["unplaced"]:
        for name in [row["name"], *row["aliases"]]:
            if name != row["code"] and name in text and (best is None or len(name) > len(best[0])):
                best = (name, row["code"])
    if best:
        return {"code": best[1], "placed": known[best[1]], "others": 0}
    return {"code": None, "placed": False, "others": 0}


def coverage(feed: Path, table: dict) -> str:
    events = json.loads(feed.read_text(encoding="utf-8")).get("events", [])
    placed = [e for e in events if place(e.get("location"), table)["placed"]]
    missing = sorted({str((e.get("location") or {}).get("building") or (e.get("location") or {}).get("name") or "-")
                      for e in events if not place(e.get("location"), table)["placed"]})
    return f"{len(placed)}/{len(events)} events placed; not placed: {missing}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--coverage", type=Path)
    args = parser.parse_args(argv)
    table = build(json.loads(CAMPUS.read_text(encoding="utf-8")), json.loads(EXTRA.read_text(encoding="utf-8")))
    if args.coverage:
        print(coverage(args.coverage, table))
        return 0
    text = render(table)
    if args.check:
        if not TABLE.exists() or TABLE.read_text(encoding="utf-8") != text:
            print("data/campus/buildings.json is out of date: run python scripts/campus3d/buildings.py")
            return 1
        print(f"campus buildings in date: {len(table['buildings'])} placed, {len(table['unplaced'])} unplaced")
        return 0
    TABLE.parent.mkdir(parents=True, exist_ok=True)
    TABLE.write_text(text, encoding="utf-8")
    print(f"wrote {TABLE.relative_to(ROOT)}: {len(table['buildings'])} placed, {len(table['unplaced'])} unplaced")
    return 0


if __name__ == "__main__":
    sys.exit(main())
