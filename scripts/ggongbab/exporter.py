# -*- coding: utf-8 -*-
"""Public exporter: DB events -> data/ggongbab/latest.json and archive/index.json.

Only status=published, needs_review=false, confidence >= threshold and not
expired events are written to the live feed. The payload contains no sender
addresses, raw text/HTML, Dooray ids, prompts or private attachment links.

The archive (past listings) holds the same rows once they have expired, for a
30-day public window, and only if they already appeared in a published file:
eligible now is not proof of having been listed (a mail-archive backfill can
store events that ended before any export saw them). An archived row means
"this was a public listing and it has ended", never that the event took place.
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
ARCHIVE_WINDOW_DAYS = 30
# Rows are read back further than the window, so a multi-day event that started
# before it but ended inside it is not missed.
ARCHIVE_LOOKBACK_DAYS = 60
ARCHIVE_DIR = "archive"
ARCHIVE_FILE = "index.json"


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


def _when(value: Any) -> Optional[datetime]:
    return parse_iso(value) if isinstance(value, str) else value


def publication_eligible(row: dict[str, Any], settings: Settings, *, food_only: bool = False) -> bool:
    """The publication policy apart from time. The live feed and the archive share it."""
    if food_only and tri_state(row.get("food_provided")) != "true":
        return False
    if row.get("status") != "published" or row.get("needs_review"):
        return False
    return float(row.get("confidence") or 0) >= settings.publish_confidence_threshold


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
        if not publication_eligible(row, settings, food_only=food_only):
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


# ---------------------------------------------------------------------------
# Past listings (data/ggongbab/archive/index.json)
# ---------------------------------------------------------------------------
def archived_event(row: dict[str, Any]) -> dict[str, Any]:
    """A past listing: the public fields without registration or confidence.

    Nothing in an archived record can be signed up for, so the page has no
    registration link or deadline to render.
    """
    event = public_event(row)
    event.pop("registration", None)
    event.pop("confidence", None)
    return event


def previously_listed_ids(out_dir: Path = DATA_DIR) -> set[str]:
    """IDs that already appeared in a published file: the live feed or archive on disk.

    Read before the new export replaces them. Only these rows may enter the
    archive, so "당시 공개된 꽁밥 안내 기록" is always true.
    """
    ids: set[str] = set()
    for path in (out_dir / "latest.json", out_dir / ARCHIVE_DIR / ARCHIVE_FILE):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for event in (data.get("events") if isinstance(data, dict) else None) or []:
            if isinstance(event, dict) and isinstance(event.get("id"), str):
                ids.add(event["id"])
    return ids


def archive_sort(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Most recently ended first; ties by id, so the order never depends on the input."""
    return sorted(sorted(events, key=lambda e: e["id"]),
                  key=lambda e: e.get("endAt") or e.get("startAt") or "", reverse=True)


def build_archive(rows: list[dict[str, Any]], settings: Settings, listed: set[str],
                  now: Optional[datetime] = None, *, window_days: int = ARCHIVE_WINDOW_DAYS) -> dict[str, Any]:
    """Past listings: eligible rows that the live feed drops as expired.

    Uses the live feed's own eligibility and is_expired at the same `now`, so a
    row is never both live and archived, and never current in one and ended in
    the other.
    """
    now = now or datetime.now(KST)
    cutoff = now - timedelta(days=window_days)
    events: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        event_id = row.get("id")
        if not isinstance(event_id, str) or event_id in seen or event_id not in listed:
            continue
        if not publication_eligible(row, settings, food_only=True):
            continue
        last = _when(row.get("event_end")) or _when(row.get("event_start"))
        if last is None or last < cutoff:
            continue  # undated rows are never published; older ones leave the public window
        if not is_expired(row, now, settings.expired_grace_hours):
            continue  # still in latest.json
        seen.add(event_id)
        events.append(archived_event(row))
    events = archive_sort(events)
    return {
        "generatedAt": now.astimezone(KST).isoformat(timespec="seconds"),
        "timezone": "Asia/Seoul",
        "windowDays": window_days,
        "count": len(events),
        "events": events,
    }


def write_archive(payload: dict[str, Any], out_dir: Path = DATA_DIR) -> Path:
    folder = out_dir / ARCHIVE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / ARCHIVE_FILE
    tmp = folder / (ARCHIVE_FILE + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path
