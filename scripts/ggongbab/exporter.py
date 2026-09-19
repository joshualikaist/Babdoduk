# -*- coding: utf-8 -*-
"""Public exporter: DB events -> data/ggongbab/latest.json.

Only status=published, needs_review=false, confidence >= threshold and not
expired events are written. The payload contains no sender addresses, raw
text/HTML, Dooray ids, prompts or private attachment links.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from .config import DATA_DIR, KST, Settings
from .parsers.validator import parse_iso

PUBLIC_SOURCE_NAMES = {"dooray": "Dooray", "dooray_mailbox": "Dooray 메일함", "kaist_public": "KAIST 공지",
                       "manual": "Manual", "portal": "KAIST Portal"}
TRI = ("true", "false", "unknown")


def kst_iso(value: Any) -> Optional[str]:
    """Render a timestamp in Asia/Seoul (+09:00).

    Postgres returns timestamptz in UTC. The feed is campus-local, so every public
    timestamp is converted before export; the database keeps its own representation.
    """
    if value is None or value == "":
        return None
    dt = value if isinstance(value, datetime) else parse_iso(str(value))
    if dt is None:
        return None
    return dt.astimezone(KST).isoformat(timespec="seconds")


def tri_state(value: Any) -> str:
    """Keep true/false/unknown intact. 'not stated' must never collapse into 'no'."""
    text = str(value or "unknown").strip().lower()
    return text if text in TRI else "unknown"


def is_expired(row: dict[str, Any], now: datetime, grace_hours: int) -> bool:
    start = parse_iso(row.get("event_start")) if isinstance(row.get("event_start"), str) else row.get("event_start")
    end = parse_iso(row.get("event_end")) if isinstance(row.get("event_end"), str) else row.get("event_end")
    if end is not None:
        return end + timedelta(hours=grace_hours) < now
    if start is not None:
        return start + timedelta(hours=grace_hours) < now
    return True  # undated events are never published


def public_event(row: dict[str, Any]) -> dict[str, Any]:
    sources = []
    seen: set[str] = set()
    for src in row.get("_sources") or []:
        stype = src.get("type") or "unknown"
        if stype in seen:
            continue
        seen.add(stype)
        entry = {"type": stype, "name": PUBLIC_SOURCE_NAMES.get(stype, src.get("name") or stype)}
        url = src.get("url") or ""
        if stype in {"kaist_public", "manual"} and url.startswith("http"):
            entry["url"] = url  # only public web links; Dooray/task links are never exported
        sources.append(entry)
    return {
        "id": row["id"],
        "title": row.get("title") or "",
        "summary": row.get("summary") or "",
        "startAt": kst_iso(row.get("event_start")),
        "endAt": kst_iso(row.get("event_end")),
        "dateText": row.get("date_text") or "",
        "timeText": row.get("time_text") or "",
        "location": {
            "name": row.get("location_name") or "",
            "building": row.get("building") or "",
            "room": row.get("room") or "",
        },
        "food": {
            "provided": tri_state(row.get("food_provided")),
            "type": row.get("food_type") or "unknown",
            "description": row.get("food_description") or "",
        },
        "organizer": row.get("organizer") or "",
        "eligibility": row.get("eligibility") or "",
        "registration": {
            "required": tri_state(row.get("registration_required")),
            "deadline": kst_iso(row.get("registration_deadline")),
            "url": row.get("registration_url") or "",
        },
        "confidence": round(float(row.get("confidence") or 0), 3),
        "sources": sources,
    }


def build_payload(rows: list[dict[str, Any]], settings: Settings, now: Optional[datetime] = None,
                  *, food_only: bool = False) -> dict[str, Any]:
    now = now or datetime.now(KST)
    horizon = now + timedelta(days=settings.export_horizon_days)
    events = []
    for row in rows:
        # Keep the generic tri-state serializer reusable; the ggongbab feed
        # opts into its explicit-food publication policy at the export boundary.
        if food_only and tri_state(row.get("food_provided")) != "true":
            continue
        if row.get("status") != "published" or row.get("needs_review"):
            continue
        if float(row.get("confidence") or 0) < settings.publish_confidence_threshold:
            continue
        if is_expired(row, now, settings.expired_grace_hours):
            continue
        start = parse_iso(row.get("event_start")) if isinstance(row.get("event_start"), str) else row.get("event_start")
        if start and start > horizon:
            continue
        events.append(public_event(row))
    events.sort(key=lambda e: (e["startAt"] or "9999", e["title"]))
    return {
        "generatedAt": now.astimezone(KST).isoformat(timespec="seconds"),
        "timezone": "Asia/Seoul",
        "count": len(events),
        "events": events,
    }


def write_payload(payload: dict[str, Any], out_dir: Path = DATA_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "latest.json"
    tmp = out_dir / "latest.json.tmp"
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path
