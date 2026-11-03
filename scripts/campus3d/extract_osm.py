# -*- coding: utf-8 -*-
"""OpenStreetMap around KAIST -> inputs/campus3d/campus.json (docs/CAMPUS_MAP.md).

The 3D campus map is built from OpenStreetMap (ODbL: "Map data from OpenStreetMap" is shown with
the map). This turns one OSM extract of the Daejeon main campus into plain shapes in meters east (x)
and north (y) of the campus centre, kept inside the KAIST campus outline: buildings (footprint,
code such as E11, names, floors), grass, water, wood, pitches, parking, paths and roads.

    curl -A "Babdoduk campus map" -o .local/kaist.osm \
      "https://api.openstreetmap.org/api/0.6/map?bbox=127.352,36.362,127.372,36.380"
    python scripts/campus3d/extract_osm.py .local/kaist.osm inputs/campus3d/campus.json
"""
import json, math, re, sys, xml.etree.ElementTree as ET
src, out = sys.argv[1], sys.argv[2]
r = ET.parse(src).getroot()
nodes = {n.get("id"): (float(n.get("lat")), float(n.get("lon"))) for n in r.iter("node")}
ways = {}
for w in r.iter("way"):
    ways[w.get("id")] = ([nd.get("ref") for nd in w.iter("nd")], {t.get("k"): t.get("v") for t in w.iter("tag")})
tags_of = lambda el: {t.get("k"): t.get("v") for t in el.iter("tag")}
campus = next(refs for refs, t in ways.values() if t.get("amenity") == "university" and t.get("name") == "한국과학기술원")
lat0 = sum(nodes[n][0] for n in campus) / len(campus); lon0 = sum(nodes[n][1] for n in campus) / len(campus)
K = math.cos(math.radians(lat0))
def xy(nid):
    lat, lon = nodes[nid]; return [round((lon - lon0) * 111320 * K, 2), round((lat - lat0) * 110540, 2)]
boundary = [xy(n) for n in campus]
def inside(p, poly):
    x, y = p; c = False
    for i in range(len(poly)):
        x1, y1 = poly[i]; x2, y2 = poly[i - 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1: c = not c
    return c
def ring(refs): return [xy(n) for n in refs if n in nodes]
def centroid(pts): return [sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)]
def area(pts): return abs(sum(pts[i][0] * pts[i - 1][1] - pts[i - 1][0] * pts[i][1] for i in range(len(pts)))) / 2
code = re.compile(r"(?<![A-Za-z0-9])([EWNS]\d{1,2}(?:-\d)?)(?![0-9])")
def stitch(member_refs):
    segs = [list(s) for s in member_refs if s]; rings = []
    while segs:
        cur = segs.pop(0)
        while cur[0] != cur[-1]:
            for i, s in enumerate(segs):
                if s[0] == cur[-1]: cur += s[1:]; segs.pop(i); break
                if s[-1] == cur[-1]: cur += s[::-1][1:]; segs.pop(i); break
            else: break
        rings.append(cur)
    return rings
features = {"buildings": [], "grass": [], "water": [], "wood": [], "pitch": [], "parking": [], "paths": [], "roads": []}
def add_area(kind, pts, t, holes=()):
    if len(pts) < 4 or not inside(centroid(pts), boundary): return
    item = {"pts": pts}
    if holes: item["holes"] = [h for h in holes if len(h) >= 4]
    if kind == "buildings":
        txt = " ".join(t.get(k, "") for k in ("ref", "name", "name:ko"))
        m = code.search(txt)
        aka = [v for k in ("alt_name", "old_name") for v in (t.get(k) or "").split(";") if v.strip()]
        item.update(code=m.group(1) if m else None, name=t.get("name"), name_en=t.get("name:en"), aka=aka,
                    levels=float(t["building:levels"]) if re.fullmatch(r"\d+(\.\d+)?", t.get("building:levels", "")) else None,
                    btype=t.get("building"), area=round(area(pts), 1))
    features[kind].append(item)
def classify(t):
    if "building" in t: return "buildings"
    if t.get("natural") == "water" or t.get("water"): return "water"
    if t.get("landuse") in ("grass", "meadow", "village_green") or t.get("leisure") in ("park", "garden"): return "grass"
    if t.get("natural") in ("wood", "scrub", "shrubbery") or t.get("landuse") == "forest": return "wood"
    if t.get("leisure") in ("pitch", "track", "sports_centre"): return "pitch"
    if t.get("amenity") == "parking": return "parking"
    return None
for wid, (refs, t) in ways.items():
    if refs and refs[0] == refs[-1]:
        kind = classify(t)
        if kind: add_area(kind, ring(refs), t); continue
    hw = t.get("highway")
    if hw:
        pts = ring(refs)
        if len(pts) >= 2 and any(inside(p, boundary) for p in pts[::max(1, len(pts) // 4)]):
            kind = "paths" if hw in ("footway", "pedestrian", "path", "steps", "cycleway", "corridor") else "roads"
            if hw == "corridor": continue
            features[kind].append({"pts": pts, "hw": hw})
for rel in r.iter("relation"):
    t = tags_of(rel)
    kind = classify(t)
    if not kind or t.get("type") not in ("multipolygon", None): continue
    outers = [ways[m.get("ref")][0] for m in rel.iter("member") if m.get("type") == "way" and m.get("role") == "outer" and m.get("ref") in ways]
    inners = [ways[m.get("ref")][0] for m in rel.iter("member") if m.get("type") == "way" and m.get("role") == "inner" and m.get("ref") in ways]
    holes = [ring(h) for h in stitch(inners)]
    for o in stitch(outers):
        if o[0] == o[-1]: add_area(kind, ring(o), t, holes)
data = {"origin": {"lat": lat0, "lon": lon0}, "boundary": boundary, **features,
        "attribution": "Map data from OpenStreetMap (ODbL)"}
json.dump(data, open(out, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
xs = [p[0] for p in boundary]; ys = [p[1] for p in boundary]
print({k: len(v) for k, v in features.items()}, "extent", round(min(xs)), round(max(xs)), round(min(ys)), round(max(ys)))
print("codes", sum(1 for b in features["buildings"] if b["code"]), "levels", sum(1 for b in features["buildings"] if b["levels"]))
