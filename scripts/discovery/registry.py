# -*- coding: utf-8 -*-
"""The one source registry.

Authored configuration lives in `scripts/discovery/sources.json`, versioned with the code: id,
name, type, url or channel, enabled, trust tier, categories, discovery method, queries, notes.
Nothing else lists sources. Runtime health lives in `research/magazine/source-health.json`
(lastAttemptAt, lastSuccessAt, lastFailureAt, failureCount, lastFailureCode, lastItemCount,
newestItemAt, status).

Trust tiers: A authoritative / original publisher, B established creator / food publication /
official brand, C discovery or community source (never published on its own as factual advice).

Publishing rules a source carries (docs/MAGAZINE_SOURCES.md; policy_errors checks them): "excerpt":
false shows it by title, source, date and link only (required for a newspaper association
member), "permission" records who allowed collection where a platform needs it (a Naver blog), and
"withdrawn" records an owner's request to leave: the source stays off and its stories leave the
archive.

Status per source:
  DISABLED  enabled is false (for example an adapter that needs a credential not configured)
  DEGRADED  the last attempt failed or was skipped for a known access problem
  STALE     the source answers, but its newest item is older than STALE_DAYS
  ACTIVE    otherwise
"""
from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path
from typing import Optional

from . import hosts
from .common import atomic_write, dump_json, iso, parse_time, read_json

REGISTRY = Path(__file__).resolve().parent / "sources.json"
TYPES = {"rss", "youtube_channel", "youtube_search", "web_search", "instagram"}
TIERS = {"A": 1.0, "B": 0.8, "C": 0.5}
LANES = ("tips", "trend", "health", "habit")
STALE_DAYS = 120
STATUSES = ("ACTIVE", "STALE", "DEGRADED", "DISABLED")
AUTHORED = {"id", "name", "type", "url", "channelId", "enabled", "trustTier", "categories", "discoveryMethod",
            "queries", "note", "knownIssue", "lane", "localOnly", "requireFood", "objective", "kind",
            "pagedFeed", "feedPages", "excerpt", "permission", "withdrawn"}
TEXT_FIELDS = ("permission", "withdrawn")    # when present: a non-empty sentence (who, when, where)
MAX_FEED_PAGES = 5         # adapters.rss.page_urls: the feed and at most four older pages
KINDS = {"recipe", "news", "research", "video", "mixed"}


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
        if s.get("lane") is not None and s.get("lane") not in LANES:
            errors.append(f"{sid}: lane must be one of {LANES}")
        if s.get("kind") is not None and s.get("kind") not in KINDS:
            errors.append(f"{sid}: kind must be one of {sorted(KINDS)}")
        if s.get("type") in ("youtube_search", "web_search") and s.get("enabled") and not s.get("queries"):
            errors.append(f"{sid}: a search source needs queries")
        if s.get("excerpt") is not None and not isinstance(s.get("excerpt"), bool):
            errors.append(f"{sid}: excerpt must be true/false")
        pages = s.get("feedPages")
        if pages is not None and (not isinstance(pages, int) or isinstance(pages, bool) or not 1 <= pages <= MAX_FEED_PAGES):
            errors.append(f"{sid}: feedPages must be a whole number from 1 to {MAX_FEED_PAGES}")
        if s.get("pagedFeed") is not None and (s.get("pagedFeed") != "wordpress" or s.get("type") != "rss"):
            errors.append(f"{sid}: pagedFeed is only \"wordpress\", on an rss source")
        if (pages or 1) > 1 and s.get("pagedFeed") != "wordpress":
            errors.append(f"{sid}: feedPages above 1 needs a feed that pages back (pagedFeed)")
        if s.get("type") == "instagram" and s.get("enabled"):
            errors.append(f"{sid}: Instagram needs an owner-provided local session (OWNER_CHECKPOINT)")
        errors.extend(policy_errors(s))
    return errors


def policy_errors(s: dict) -> list[str]:
    """The publishing rules a proposed source must already satisfy (docs/MAGAZINE_SOURCES.md)."""
    sid, errors, url = s.get("id"), [], s.get("url") or ""
    for field in TEXT_FIELDS:
        if s.get(field) is not None and not (isinstance(s[field], str) and s[field].strip()):
            errors.append(f"{sid}: {field} must say who, when and where")
    if s.get("type") == "rss" and hosts.naver_blog_feed(url) and not s.get("permission"):
        errors.append(f"{sid}: a Naver blog is collected only with its owner's permission (\"permission\")")
    if s.get("type") == "web_search" and s.get("enabled"):
        for site in sorted({d for q in s.get("queries") or [] for d in re.findall(r"site:(\S+)", q)}):
            if not hosts.collectable("https://" + site.strip("/") + "/"):
                errors.append(f"{sid}: open discovery may not read {site}")
    if url and not hosts.excerpt_allowed(url) and s.get("excerpt") is not False:
        errors.append(f"{sid}: a newspaper association member is shown without excerpts (\"excerpt\": false)")
    if s.get("withdrawn") and s.get("enabled"):
        errors.append(f"{sid}: a withdrawn source stays disabled")
    return errors
