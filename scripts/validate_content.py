# -*- coding: utf-8 -*-
"""Validate generated magazine / KAIST JSON before production push."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
LANES = ("tips", "trend", "health", "habit")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def host(url: str) -> str:
    return urlparse(url or "").netloc.replace("www.", "")


def video_id(url: str) -> str:
    match = re.search(r"(?:youtu\.be/|v=|shorts/|embed/)([A-Za-z0-9_-]{11})", url or "")
    return match.group(1) if match else ""


def validate_magazine(path: Path) -> list[str]:
    errors = []
    data = load(path)
    if not data.get("date"):
        errors.append("magazine missing date")
    lanes = data.get("lanes") or {}
    for lane in LANES:
        if lane not in lanes:
            errors.append(f"missing lane {lane}")
            continue
        items = lanes[lane].get("items") or []
        if len(items) < 4:
            errors.append(f"{lane} has only {len(items)} items")
    featured = data.get("featured") or {}
    used_urls = set()
    used_vids = set()
    used_titles = set()
    feat_url = (featured.get("url") or "").split("?")[0].rstrip("/").lower()
    feat_title = featured.get("title") or ""
    for lane in LANES:
        sources = []
        for item in (lanes.get(lane) or {}).get("items") or []:
            title = item.get("title") or ""
            url = (item.get("url") or "").split("?")[0].rstrip("/").lower()
            vid = video_id(item.get("url") or "")
            src = item.get("source") or ""
            if title in used_titles:
                errors.append(f"duplicate title {title[:40]}")
            if url and url in used_urls:
                errors.append(f"duplicate url {url}")
            if vid and vid in used_vids:
                errors.append(f"duplicate video {vid}")
            if feat_title and title == feat_title:
                errors.append("featured repeated in lane " + lane)
            if feat_url and url and url == feat_url:
                errors.append("featured url repeated in lane " + lane)
            if src in sources and item.get("medium") == "youtube":
                errors.append(f"{lane} repeats youtube source {src}")
            sources.append(src)
            used_titles.add(title)
            if url:
                used_urls.add(url)
            if vid:
                used_vids.add(vid)
    trend = (lanes.get("trend") or {}).get("items") or []
    sources = {item.get("source") for item in trend if item.get("source")}
    if len(trend) >= 4 and len(sources) == 1:
        errors.append("trend is single-source-only")
    return errors


def validate_kaist(path: Path) -> list[str]:
    errors = []
    data = load(path)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(data.get("date") or "")):
        errors.append("kaist date invalid")
    restos = data.get("restaurants")
    if not isinstance(restos, list) or not restos:
        errors.append("kaist restaurants empty")
        return errors
    for row in restos:
        if not row.get("name") or not row.get("id"):
            errors.append("kaist restaurant missing name/id")
    return errors


def main() -> None:
    mag_index = ROOT / "data" / "magazine" / "index.json"
    errors = []
    if mag_index.exists():
        index = load(mag_index)
        latest = index.get("latest")
        mag = ROOT / "data" / "magazine" / f"{latest}.json"
        if not mag.exists():
            errors.append("index.latest file missing")
        else:
            errors.extend(validate_magazine(mag))
            latest_copy = ROOT / "data" / "magazine" / "latest.json"
            if latest_copy.exists() and latest_copy.read_text(encoding="utf-8") != mag.read_text(encoding="utf-8"):
                errors.append("latest.json does not match dated edition")
    kaist = ROOT / "data" / "kaist-menu" / "latest.json"
    if kaist.exists():
        errors.extend(validate_kaist(kaist))
    if errors:
        print("\n".join(errors))
        sys.exit(1)
    print("content validation ok")


if __name__ == "__main__":
    main()
