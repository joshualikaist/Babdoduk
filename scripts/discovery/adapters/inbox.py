# -*- coding: utf-8 -*-
"""The local discovery inbox: research/magazine/inbox/<sourceId>.json.

Sources marked localOnly in the registry (YouTube, which GitHub's runners cannot reach) are
collected on the operator PC by discovery.sidecar, which writes what it found here and does
nothing else. The normal pipeline reads the file as that source's adapter result, so every
local candidate goes through the same normalize, dedup, quality, lane and ranking rules. A
missing inbox is NOT_CONFIGURED; one older than INBOX_MAX_DAYS is a failure (LOCAL_INBOX_STALE),
so a local route that stopped running shows up as DEGRADED in health, never as fresh data.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from ..common import atomic_write, dump_json, iso, parse_time, read_json
from . import FETCH_FAILED, NOT_CONFIGURED, OK, AdapterResult

INBOX_MAX_DAYS = 3
ITEM_KEYS = ("title", "sourceUrl", "sourceItemId", "publishedAt", "publishedAtSource", "text", "imageUrl",
             "imageSource", "medium", "discoveryQuery", "discoveryLane", "discoveryMethod", "trustTier",
             "channelTitle", "viewCount", "likeCount")
# A registered channel keeps the registry's trust tier; only search results are Tier C.
CHANNEL_KEYS = tuple(k for k in ITEM_KEYS if k != "trustTier")


def path_for(folder: Path, source_id: str) -> Path:
    return Path(folder) / f"{source_id}.json"


def write(folder: Path, source: dict, result: AdapterResult, now: datetime, tool: str) -> Path:
    """Public metadata only: the keys above, never cookies, sessions or local paths."""
    items = []
    keys = CHANNEL_KEYS if source.get("type") == "youtube_channel" else ITEM_KEYS
    for raw in result.items:
        item = {k: raw.get(k) for k in keys if raw.get(k) not in (None, "")}
        if isinstance(item.get("publishedAt"), datetime):
            item["publishedAt"] = iso(item["publishedAt"])
        items.append(item)
    path = path_for(folder, source["id"])
    atomic_write(path, dump_json({"version": 1, "sourceId": source["id"], "discoveredAt": iso(now), "tool": tool,
                                  "status": result.status, "code": result.code or None, "queries": result.queries,
                                  "items": items}))
    return path


def read(source: dict, folder: Path, now: datetime) -> AdapterResult:
    data = read_json(path_for(folder, source["id"]), None)
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        return AdapterResult(NOT_CONFIGURED, code="LOCAL_INBOX_MISSING")
    found = parse_time(data.get("discoveredAt"))
    if not found or now - found > timedelta(days=INBOX_MAX_DAYS):
        return AdapterResult(FETCH_FAILED, code="LOCAL_INBOX_STALE")
    items = [dict(item, publishedAt=parse_time(item.get("publishedAt"))) for item in data["items"]
             if isinstance(item, dict) and item.get("sourceUrl")]
    return AdapterResult(OK, items=items, queries=list(data.get("queries") or []))
