"""Backend-only sanitized projection. No collector, browser, AI or local pending input."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from .config import KST
from .exporter import PUBLIC_SOURCE_NAMES, build_payload, kst_iso
from .public_sanitizer import public_url
from .source_origin import ORIGINS, instagram_post_url

PUBLIC_FIELDS = (
    "id", "title", "summary", "start_at", "end_at", "date_text", "time_text",
    "location_name", "building", "room", "food_provided", "food_type", "food_description",
    "organizer", "eligibility", "registration_required", "registration_deadline",
    "registration_url", "source_types", "confidence",
    # Migration 006 (2026-10-14): a giveaway listing and where the food evidence was read.
    "food_source", "giveaway", "giveaway_description",
)
# Migration 007 (2026-10-31): the public links the snapshot's sources carry, and the `instagram`
# and `tip` source types. A projection without it keeps the 006 shape: no links, and those two
# origins written as the Dooray items they were collected as (prepare_public_feed asks the database).
LINK_FIELDS = ("source_links",)
PUBLIC_COLUMNS = PUBLIC_FIELDS + LINK_FIELDS + ("content_revision", "updated_at")


class PublicFeedError(Exception):
    """Value-free failure: callers must return a non-green exit."""


def content_revision(row):
    canonical = json.dumps({key: row[key] for key in PUBLIC_FIELDS + LINK_FIELDS if key in row}, sort_keys=True,
                           ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def public_row(event, *, links=True):
    """Flatten the selected/sanitized snapshot shape; no dictionary expansion. `links=False` is the
    shape of a projection that migration 007 has not reached yet."""
    event_id = str(UUID(event["id"]))  # canonical UUID, never a Portal/Dooray ID
    row = {
        "id": event_id, "title": event["title"], "summary": event["summary"],
        "start_at": event["startAt"], "end_at": event["endAt"],
        "date_text": event["dateText"], "time_text": event["timeText"],
        "location_name": event["location"]["name"], "building": event["location"]["building"],
        "room": event["location"]["room"], "food_provided": event["food"]["provided"],
        "food_type": event["food"]["type"], "food_description": event["food"]["description"],
        "organizer": event["organizer"], "eligibility": event["eligibility"],
        "registration_required": event["registration"]["required"],
        "registration_deadline": event["registration"]["deadline"],
        "registration_url": event["registration"]["url"],
        "source_types": sorted({s["type"] if links or s["type"] not in ORIGINS else "dooray" for s in event["sources"]}),
        "confidence": event["confidence"],
        "food_source": event["food"].get("source", ""),
        "giveaway": (event.get("giveaway") or {}).get("provided", "false"),
        "giveaway_description": (event.get("giveaway") or {}).get("description", ""),
    }
    if links:
        row["source_links"] = [{"type": s["type"], "url": s["url"]} for s in event["sources"] if s.get("url")]
    row["content_revision"] = content_revision(row)
    return row


def to_snapshot_event(row):
    """Phase 2B reference mapping; public row only, timestamps normalized to KST."""
    food = {"provided": row["food_provided"], "type": row["food_type"], "description": row["food_description"]}
    if row.get("food_source") in ("text", "poster"):
        food["source"] = row["food_source"]
    event = {
        "id": row["id"], "title": row["title"], "summary": row["summary"],
        "startAt": kst_iso(row["start_at"]), "endAt": kst_iso(row["end_at"]),
        "dateText": row["date_text"], "timeText": row["time_text"],
        "location": {"name": row["location_name"], "building": row["building"], "room": row["room"]},
        "food": food,
        "organizer": row["organizer"], "eligibility": row["eligibility"],
        "registration": {"required": row["registration_required"],
                         "deadline": kst_iso(row["registration_deadline"]), "url": row["registration_url"]},
        "confidence": row["confidence"],
        "sources": [_snapshot_source(kind, row.get("source_links")) for kind in row["source_types"]],
    }
    if row.get("giveaway") == "true":
        event["giveaway"] = {"provided": "true", "description": row.get("giveaway_description") or ""}
    return event


def _snapshot_source(kind, links):
    source = {"type": kind, "name": PUBLIC_SOURCE_NAMES[kind]}
    for link in links if isinstance(links, list) else []:
        if isinstance(link, dict) and link.get("type") == kind and kind in ("kaist_public", "manual", "instagram"):
            url = instagram_post_url(link.get("url")) if kind == "instagram" else public_url(link.get("url"))
            if url:
                source["url"] = url
                break
    return source


@dataclass
class PreparedFeed:
    generation: int
    payload: dict
    rows: list[dict]


def prepare_public_feed(repo, settings, now=None):
    """Read generation BEFORE canonical rows; prepare the whole set before writes."""
    from validate_content import validate_ggongbab_payload

    try:
        generation = repo.public_feed_generation()
        now = now or datetime.now(KST)
        payload = build_payload(repo.publishable_events(), settings, now, food_only=True)
        if validate_ggongbab_payload(payload, now):
            raise ValueError()
        links = repo.public_feed_has_links()
        rows = [public_row(event, links=links) for event in payload["events"]]
        return PreparedFeed(generation, payload, rows)
    except Exception:
        raise PublicFeedError("PUBLIC_FEED_PREPARATION_FAILED") from None


def commit_public_feed(repo, prepared):
    try:
        generation = repo.replace_public_feed(prepared.generation, prepared.rows)
        if type(generation) is not int or generation != prepared.generation + 1:
            raise ValueError()
    except Exception:
        raise PublicFeedError("PUBLIC_FEED_SYNC_FAILED") from None


def sync_public_feed(repo, settings, now=None):
    prepared = prepare_public_feed(repo, settings, now)
    commit_public_feed(repo, prepared)
    return prepared.payload
