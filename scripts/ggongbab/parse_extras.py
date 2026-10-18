# -*- coding: utf-8 -*-
"""Sessions and audience of an event, read back from the stored AI parse.

`events` has no column for them (and a migration is a protected change), but every parse is kept whole
in ai_parse_runs.parsed_json. The repository attaches the parse that produced an event's own start to
each export row as `_extras`; this module turns it into the public shape and refuses anything that does
not hold together, so a bad extraction can only cost the extra detail, never the event.

Public shape (data/ggongbab/latest.json, optional keys of an event):
  sessions: [{startAt, endAt|null, location?: {name, building, room}, foodDescription?}]   2..14 items, in order
  audience: {text, basis: "stated" | "inferred"}
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Iterable, Optional

from .config import KST
from .parsers.validator import parse_iso
from .public_sanitizer import public_text

MIN_SESSIONS = 2          # one session is just the event itself
MAX_SESSIONS = 14
MAX_SESSION_HOURS = 24    # a session is at most a day long
AUDIENCE_MAX_CHARS = 60
AUDIENCE_BASES = ("stated", "inferred")
RUN_BATCH = 50            # raw item ids per ai_parse_runs read, to keep the request URL short


def aware(value: Any) -> Optional[datetime]:
    """An aware datetime in Asia/Seoul from a datetime or an ISO string; None for anything else."""
    dt = value if isinstance(value, datetime) else (parse_iso(value) if isinstance(value, str) else None)
    return dt.astimezone(KST) if isinstance(dt, datetime) and dt.tzinfo is not None else None


def kst_text(dt: datetime) -> str:
    return dt.astimezone(KST).isoformat(timespec="seconds")


def attach_extras(events: list[dict[str, Any]], raw_ids_by_event: dict[str, list[str]],
                  runs: Iterable[dict[str, Any]]) -> None:
    """Set event["_extras"] = {sessions, audience} from the newest stored parse (of one of the event's
    raw items) whose own start equals the event's start. `runs` holds only successful primary parses of
    the current prompt version, with raw_item_id, parsed_json and created_at."""
    newest: dict[str, dict[str, Any]] = {}
    for run in sorted(runs, key=lambda r: str(r.get("created_at") or ""), reverse=True):
        newest.setdefault(run.get("raw_item_id"), run)
    for event in events:
        start = aware(event.get("event_start"))
        if start is None:
            continue
        for raw_id in raw_ids_by_event.get(event.get("id"), []):
            parsed = (newest.get(raw_id) or {}).get("parsed_json")
            if isinstance(parsed, dict) and aware(parsed.get("event_start")) == start:
                event["_extras"] = {"sessions": parsed.get("sessions"), "audience": parsed.get("audience")}
                break


def _text(value: Any) -> str:
    try:
        return public_text(value if isinstance(value, str) else None).strip()
    except ValueError:
        return ""


def public_sessions(extras: Optional[dict[str, Any]], event_start: Any, event_end: Any) -> list[dict[str, Any]]:
    """The public sessions of an event, or [] when there are none or anything is inconsistent."""
    raw = (extras or {}).get("sessions")
    if not isinstance(raw, list) or not MIN_SESSIONS <= len(raw) <= MAX_SESSIONS:
        return []
    start, end = aware(event_start), aware(event_end)
    if start is None:
        return []
    out: list[dict[str, Any]] = []
    previous: Optional[datetime] = None
    for item in raw:
        if not isinstance(item, dict):
            return []
        s, e = aware(item.get("start")), aware(item.get("end")) if item.get("end") else None
        if s is None or (item.get("end") and e is None):
            return []
        if e is not None and (e < s or e - s > timedelta(hours=MAX_SESSION_HOURS)):
            return []
        if previous is not None and s <= previous:
            return []                              # not in order, or the same start twice
        previous = s
        session: dict[str, Any] = {"startAt": kst_text(s), "endAt": kst_text(e) if e else None}
        place = {key: _text(item.get(src)) for key, src in (("name", "location_name"), ("building", "building"), ("room", "room"))}
        if any(place.values()):
            session["location"] = place
        food = _text(item.get("food_description"))
        if food:
            session["foodDescription"] = food
        out.append(session)
    first = aware(out[0]["startAt"])
    last = aware(out[-1]["endAt"] or out[-1]["startAt"])
    if first != start or (end is not None and last > end):
        return []                                  # the sessions do not describe THIS event
    return out


def public_audience(extras: Optional[dict[str, Any]]) -> Optional[dict[str, str]]:
    audience = (extras or {}).get("audience")
    if not isinstance(audience, dict):
        return None
    text, basis = _text(audience.get("text")), audience.get("basis")
    if not text or len(text) > AUDIENCE_MAX_CHARS or basis not in AUDIENCE_BASES:
        return None
    return {"text": text, "basis": basis}
