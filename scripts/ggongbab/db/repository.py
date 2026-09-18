# -*- coding: utf-8 -*-
"""Repository layer: one interface, two implementations.

* SupabaseRepository - production, PostgREST over the private schema.
* MemoryRepository   - tests and --dry-run; same semantics without a database.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Optional, Protocol

from ..config import KST
from ..models import RawAttachment, RawItem
from .supabase_client import SupabaseClient

SOURCE_NAMES = {"dooray": "Dooray", "kaist_public": "KAIST 공지", "manual": "Manual", "portal": "KAIST Portal"}
SOURCE_PRIORITY = {"manual": 5, "dooray": 10, "kaist_public": 20, "portal": 30}


def _now() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


class Repository(Protocol):
    def source_id(self, source_type: str) -> str: ...
    def find_raw_item(self, source_type: str, external_id: str) -> Optional[dict[str, Any]]: ...
    def upsert_raw_item(self, item: RawItem) -> dict[str, Any]: ...
    def touch_raw_item(self, raw_item_id: str) -> None: ...
    def upsert_attachments(self, raw_item_id: str, attachments: list[RawAttachment]) -> None: ...
    def cached_parse(self, raw_item_id: str, content_hash: str) -> Optional[dict[str, Any]]: ...
    def insert_ai_run(self, row: dict[str, Any]) -> None: ...
    def events_linked_to(self, raw_item_id: str) -> list[str]: ...
    def candidate_events(self, around: Optional[datetime]) -> list[dict[str, Any]]: ...
    def insert_event(self, row: dict[str, Any]) -> str: ...
    def update_event(self, event_id: str, row: dict[str, Any]) -> None: ...
    def link_event_source(self, event_id: str, raw_item_id: str, score: float) -> None: ...
    def publishable_events(self) -> list[dict[str, Any]]: ...
    def review_events(self) -> list[dict[str, Any]]: ...
    def start_ingest_run(self, source_type: str) -> str: ...
    def finish_ingest_run(self, run_id: str, **fields: Any) -> None: ...


# ---------------------------------------------------------------------------
class SupabaseRepository:
    def __init__(self, client: SupabaseClient):
        self.client = client
        self._sources: dict[str, str] = {}

    def source_id(self, source_type: str) -> str:
        if source_type not in self._sources:
            rows = self.client.select("sources", {"type": f"eq.{source_type}", "select": "id,type", "limit": 1})
            if not rows:
                rows = self.client.insert("sources", {"type": source_type, "name": SOURCE_NAMES.get(source_type, source_type),
                                                      "priority": SOURCE_PRIORITY.get(source_type, 100)})
            self._sources[source_type] = rows[0]["id"]
        return self._sources[source_type]

    def find_raw_item(self, source_type: str, external_id: str) -> Optional[dict[str, Any]]:
        rows = self.client.select("raw_items", {
            "source_id": f"eq.{self.source_id(source_type)}",
            "external_id": f"eq.{external_id}",
            "select": "id,content_hash,source_updated_at,metadata",
            "limit": 1,
        })
        return rows[0] if rows else None

    def upsert_raw_item(self, item: RawItem) -> dict[str, Any]:
        row = {
            "source_id": self.source_id(item.source_type),
            "external_id": item.external_id,
            "subject": item.subject,
            "sender_name": item.sender_name,
            "sender_email": item.sender_email,
            "raw_text": item.raw_text,
            "raw_html": item.raw_html,
            "source_url": item.source_url,
            "source_created_at": item.source_created_at.isoformat() if item.source_created_at else None,
            "source_updated_at": item.source_updated_at.isoformat() if item.source_updated_at else None,
            "content_hash": item.content_hash,
            "metadata": item.metadata,
            "last_seen_at": _now(),
        }
        rows = self.client.upsert("raw_items", row, on_conflict="source_id,external_id")
        return rows[0]

    def touch_raw_item(self, raw_item_id: str) -> None:
        self.client.update("raw_items", {"id": raw_item_id}, {"last_seen_at": _now()})

    def upsert_attachments(self, raw_item_id: str, attachments: list[RawAttachment]) -> None:
        if not attachments:
            return
        rows = [{
            "raw_item_id": raw_item_id,
            "external_file_id": a.external_file_id,
            "filename": a.filename or None,
            "mime_type": a.mime_type or None,
            "size": a.size or None,
            "sha256": a.sha256 or None,
            "parse_status": a.parse_status,
            "metadata": {"inline": a.inline},
        } for a in attachments]
        self.client.upsert("attachments", rows, on_conflict="raw_item_id,external_file_id")

    def cached_parse(self, raw_item_id: str, content_hash: str) -> Optional[dict[str, Any]]:
        rows = self.client.select("ai_parse_runs", {
            "raw_item_id": f"eq.{raw_item_id}",
            "content_hash": f"eq.{content_hash}",
            "status": "eq.ok",
            "role": "eq.primary",
            "select": "parsed_json,model,confidence,created_at",
            "order": "created_at.desc",
            "limit": 1,
        })
        return rows[0] if rows and rows[0].get("parsed_json") else None

    def insert_ai_run(self, row: dict[str, Any]) -> None:
        self.client.insert("ai_parse_runs", row, returning=False)

    def events_linked_to(self, raw_item_id: str) -> list[str]:
        rows = self.client.select("event_sources", {"raw_item_id": f"eq.{raw_item_id}", "select": "event_id"})
        return [r["event_id"] for r in rows]

    def candidate_events(self, around: Optional[datetime]) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"status": "neq.rejected", "order": "event_start.asc", "limit": 500}
        if around:
            lo = (around - timedelta(days=3)).isoformat()
            hi = (around + timedelta(days=3)).isoformat()
            params["event_start"] = f"gte.{lo}"
            params["and"] = f"(event_start.lte.{hi})"
        else:
            params["event_start"] = "is.null"
        return self.client.select("events", params)

    def insert_event(self, row: dict[str, Any]) -> str:
        now = _now()
        rows = self.client.insert("events", {**row, "first_seen_at": now, "last_seen_at": now})
        return rows[0]["id"]

    def update_event(self, event_id: str, row: dict[str, Any]) -> None:
        payload = {k: v for k, v in row.items() if k not in {"id", "created_at", "updated_at", "first_seen_at"}}
        payload["last_seen_at"] = _now()
        self.client.update("events", {"id": event_id}, payload)

    def link_event_source(self, event_id: str, raw_item_id: str, score: float) -> None:
        self.client.upsert("event_sources", {"event_id": event_id, "raw_item_id": raw_item_id, "match_score": score},
                           on_conflict="event_id,raw_item_id", ignore_duplicates=True)

    def _with_sources(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not events:
            return events
        ids = ",".join(e["id"] for e in events)
        links = self.client.select("event_sources", {"event_id": f"in.({ids})", "select": "event_id,raw_item_id"})
        raw_ids = ",".join(sorted({l["raw_item_id"] for l in links})) if links else ""
        raw_rows = self.client.select("raw_items", {"id": f"in.({raw_ids})", "select": "id,source_id,source_url"}) if raw_ids else []
        sources = {s["id"]: s for s in self.client.select("sources", {"select": "id,type,name"})}
        raw_map = {r["id"]: r for r in raw_rows}
        by_event: dict[str, list[dict[str, Any]]] = {}
        for link in links:
            raw = raw_map.get(link["raw_item_id"]) or {}
            src = sources.get(raw.get("source_id"), {})
            by_event.setdefault(link["event_id"], []).append({
                "type": src.get("type", "unknown"),
                "name": src.get("name", ""),
                "url": raw.get("source_url") or "",
            })
        for event in events:
            event["_sources"] = by_event.get(event["id"], [])
        return events

    def publishable_events(self) -> list[dict[str, Any]]:
        since = (datetime.now(KST) - timedelta(days=2)).isoformat()
        rows = self.client.select("events", {
            "status": "eq.published", "needs_review": "eq.false",
            "event_start": f"gte.{since}", "order": "event_start.asc", "limit": 500,
        })
        return self._with_sources(rows)

    def review_events(self) -> list[dict[str, Any]]:
        rows = self.client.select("events", {"needs_review": "eq.true", "order": "event_start.asc.nullslast", "limit": 200})
        return self._with_sources(rows)

    def start_ingest_run(self, source_type: str) -> str:
        rows = self.client.insert("ingest_runs", {"source_type": source_type, "status": "running"})
        return rows[0]["id"]

    def finish_ingest_run(self, run_id: str, **fields: Any) -> None:
        self.client.update("ingest_runs", {"id": run_id}, {"finished_at": _now(), **fields})


# ---------------------------------------------------------------------------
class MemoryRepository:
    """In-memory stand-in with the same semantics (unique keys, upserts)."""

    def __init__(self) -> None:
        self.sources: dict[str, str] = {}
        self.raw_items: dict[str, dict[str, Any]] = {}
        self.attachments: dict[tuple[str, str], dict[str, Any]] = {}
        self.ai_runs: list[dict[str, Any]] = []
        self.events: dict[str, dict[str, Any]] = {}
        self.event_sources: dict[tuple[str, str], float] = {}
        self.ingest_runs: dict[str, dict[str, Any]] = {}

    def source_id(self, source_type: str) -> str:
        return self.sources.setdefault(source_type, str(uuid.uuid4()))

    def find_raw_item(self, source_type: str, external_id: str) -> Optional[dict[str, Any]]:
        sid = self.source_id(source_type)
        for row in self.raw_items.values():
            if row["source_id"] == sid and row["external_id"] == external_id:
                return dict(row)
        return None

    def upsert_raw_item(self, item: RawItem) -> dict[str, Any]:
        existing = self.find_raw_item(item.source_type, item.external_id)
        row = {
            "id": existing["id"] if existing else str(uuid.uuid4()),
            "source_id": self.source_id(item.source_type),
            "external_id": item.external_id,
            "subject": item.subject, "sender_name": item.sender_name, "sender_email": item.sender_email,
            "raw_text": item.raw_text, "raw_html": item.raw_html, "source_url": item.source_url,
            "source_created_at": item.source_created_at.isoformat() if item.source_created_at else None,
            "source_updated_at": item.source_updated_at.isoformat() if item.source_updated_at else None,
            "content_hash": item.content_hash, "metadata": item.metadata, "last_seen_at": _now(),
        }
        self.raw_items[row["id"]] = row
        return dict(row)

    def touch_raw_item(self, raw_item_id: str) -> None:
        if raw_item_id in self.raw_items:
            self.raw_items[raw_item_id]["last_seen_at"] = _now()

    def upsert_attachments(self, raw_item_id: str, attachments: list[RawAttachment]) -> None:
        for a in attachments:
            self.attachments[(raw_item_id, a.external_file_id)] = {
                "raw_item_id": raw_item_id, "external_file_id": a.external_file_id, "filename": a.filename,
                "mime_type": a.mime_type, "size": a.size, "sha256": a.sha256, "parse_status": a.parse_status,
            }

    def cached_parse(self, raw_item_id: str, content_hash: str) -> Optional[dict[str, Any]]:
        for run in reversed(self.ai_runs):
            if run["raw_item_id"] == raw_item_id and run.get("content_hash") == content_hash \
                    and run["status"] == "ok" and run.get("role", "primary") == "primary" and run.get("parsed_json"):
                return run
        return None

    def insert_ai_run(self, row: dict[str, Any]) -> None:
        self.ai_runs.append({"created_at": _now(), **row})

    def events_linked_to(self, raw_item_id: str) -> list[str]:
        return [e for (e, r) in self.event_sources if r == raw_item_id]

    def candidate_events(self, around: Optional[datetime]) -> list[dict[str, Any]]:
        out = []
        for row in self.events.values():
            if row.get("status") == "rejected":
                continue
            start = row.get("event_start")
            if around is None:
                if start is None:
                    out.append(dict(row))
                continue
            if start is None:
                continue
            dt = datetime.fromisoformat(start)
            if abs((dt - around).total_seconds()) <= 3 * 86400:
                out.append(dict(row))
        return out

    def insert_event(self, row: dict[str, Any]) -> str:
        event_id = str(uuid.uuid4())
        now = _now()
        self.events[event_id] = {"id": event_id, "first_seen_at": now, "last_seen_at": now, "created_at": now, **row}
        return event_id

    def update_event(self, event_id: str, row: dict[str, Any]) -> None:
        current = self.events[event_id]
        current.update({k: v for k, v in row.items() if k not in {"id", "created_at", "first_seen_at"}})
        current["last_seen_at"] = _now()
        current["updated_at"] = _now()

    def link_event_source(self, event_id: str, raw_item_id: str, score: float) -> None:
        self.event_sources.setdefault((event_id, raw_item_id), score)

    def _with_sources(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        type_by_source = {v: k for k, v in self.sources.items()}
        for event in events:
            srcs = []
            for (e, r), _score in self.event_sources.items():
                if e != event["id"]:
                    continue
                raw = self.raw_items.get(r, {})
                stype = type_by_source.get(raw.get("source_id"), "unknown")
                srcs.append({"type": stype, "name": SOURCE_NAMES.get(stype, stype), "url": raw.get("source_url") or ""})
            event["_sources"] = srcs
        return events

    def publishable_events(self) -> list[dict[str, Any]]:
        rows = [dict(r) for r in self.events.values() if r.get("status") == "published" and not r.get("needs_review")]
        rows.sort(key=lambda r: r.get("event_start") or "9999")
        return self._with_sources(rows)

    def review_events(self) -> list[dict[str, Any]]:
        rows = [dict(r) for r in self.events.values() if r.get("needs_review")]
        return self._with_sources(rows)

    def start_ingest_run(self, source_type: str) -> str:
        run_id = str(uuid.uuid4())
        self.ingest_runs[run_id] = {"id": run_id, "source_type": source_type, "status": "running", "started_at": _now()}
        return run_id

    def finish_ingest_run(self, run_id: str, **fields: Any) -> None:
        self.ingest_runs[run_id].update({"finished_at": _now(), **fields})
