# -*- coding: utf-8 -*-
"""The one source registry.

Authored configuration lives in `scripts/discovery/sources.json`, versioned with the code: id,
name, type, url or channel, enabled, trust tier, categories, discovery method, queries, notes.
Nothing else lists sources. Runtime health lives in `research/magazine/source-health.json`
(lastAttemptAt, lastSuccessAt, lastFailureAt, failureCount, lastFailureCode, lastItemCount,
newestItemAt, status); `view()` merges both for reports.

Trust tiers: A authoritative / original publisher, B established creator / food publication /
official brand, C discovery or community source (never published on its own as factual advice).

Status per source:
  DISABLED  enabled is false (for example an adapter that needs a credential not configured)
  DEGRADED  the last attempt failed or was skipped for a known access problem
  STALE     the source answers, but its newest item is older than STALE_DAYS
  ACTIVE    otherwise
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Optional

from .common import atomic_write, dump_json, iso, parse_time, read_json

REGISTRY = Path(__file__).resolve().parent / "sources.json"
TYPES = {"rss", "youtube_channel", "youtube_search", "web_search", "instagram"}
TIERS = {"A": 1.0, "B": 0.8, "C": 0.5}
LANES = ("tips", "trend", "health", "habit")
STALE_DAYS = 120
STATUSES = ("ACTIVE", "STALE", "DEGRADED", "DISABLED")
AUTHORED = {"id", "name", "type", "url", "channelId", "enabled", "trustTier", "categories", "discoveryMethod",
            "queries", "note", "knownIssue"}


def load(path: Path = REGISTRY) -> list[dict]:
    data = read_json(path, None)
    sources = data.get("sources") if isinstance(data, dict) else None
    if not isinstance(sources, list):
        raise ValueError("source registry unreadable")
    return sources


def load_health(path: Path) -> dict:
    data = read_json(path, {"sources": {}})
    return data.get("sources") if isinstance(data, dict) and isinstance(data.get("sources"), dict) else {}


def save_health(path: Path, health: dict) -> None:
    atomic_write(path, dump_json({"version": 1, "sources": health}))


def enabled(sources: list[dict]) -> list[dict]:
    return [s for s in sources if s.get("enabled")]


def record(entry: dict, *, ok: bool, now, code: Optional[str] = None, count: int = 0) -> dict:
    entry["lastAttemptAt"] = iso(now)
    entry["lastItemCount"] = count
    if ok:
        entry["lastSuccessAt"] = iso(now)
        entry["failureCount"] = 0
        entry["lastFailureCode"] = None
    else:
        entry["lastFailureAt"] = iso(now)
        entry["failureCount"] = int(entry.get("failureCount") or 0) + 1
        entry["lastFailureCode"] = code
    return entry


def status(source: dict, entry: dict, now) -> str:
    if not source.get("enabled"):
        return "DISABLED"
    if int(entry.get("failureCount") or 0) > 0 or entry.get("lastFailureCode"):
        return "DEGRADED"
    newest = parse_time(entry.get("newestItemAt"))
    if entry.get("lastSuccessAt") and (newest is None or now - newest > timedelta(days=STALE_DAYS)):
        return "STALE"
    return "ACTIVE" if entry.get("lastSuccessAt") else "DEGRADED"


def view(sources: list[dict], health: dict) -> list[dict]:
    """Registry rows with their health, for reports and validation."""
    return [dict(s, **(health.get(s["id"]) or {})) for s in sources]


def validate(sources: list[dict]) -> list[str]:
    errors, seen = [], set()
    for s in sources:
        sid = s.get("id")
        if not sid or sid in seen:
            errors.append(f"source id missing or duplicate: {sid!r}")
        seen.add(sid)
        extra = set(s) - AUTHORED
        if extra:
            errors.append(f"{sid}: runtime or unknown fields in the authored registry: {sorted(extra)}")
        if s.get("type") not in TYPES:
            errors.append(f"{sid}: unknown type {s.get('type')!r}")
        if s.get("trustTier") not in TIERS:
            errors.append(f"{sid}: trustTier must be A, B or C")
        if not set(s.get("categories") or []) <= set(LANES):
            errors.append(f"{sid}: unknown category")
        if not isinstance(s.get("enabled"), bool):
            errors.append(f"{sid}: enabled must be true/false")
        if s.get("type") in ("rss", "youtube_channel") and not (s.get("url") or s.get("channelId")):
            errors.append(f"{sid}: url or channelId required")
    return errors
