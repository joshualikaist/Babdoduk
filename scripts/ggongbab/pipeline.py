# -*- coding: utf-8 -*-
"""Orchestrates collect -> store -> sanitize -> rules -> AI -> validate -> dedup -> DB.

Idempotency: a raw item whose content_hash is unchanged and that already has an
event link is skipped without any AI call. A raw item whose last AI run failed
stays retryable on the next run.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from .collectors.base import Collector, CollectorError
from .config import KST, PROMPT_VERSION, Settings
from .db.repository import SOURCE_PRIORITY, Repository
from .dedup import find_match, merge_into
from .models import EventCandidate, EventExtraction, ParseOutcome, RawItem
from .parsers.ai_parser import AIResult, Extractor, build_user_text
from .parsers.rule_parser import analyze
from .parsers.sanitizer import sanitize_for_ai
from .parsers.validator import fallback_reasons, pick_better, validate


@dataclass
class RunStats:
    items_seen: int = 0
    items_new: int = 0
    ai_calls: int = 0
    ai_skipped: int = 0
    ai_fallback: int = 0
    ai_errors: int = 0
    events_created: int = 0
    events_updated: int = 0
    events_review: int = 0
    not_events: int = 0
    collector_errors: dict[str, str] = field(default_factory=dict)

    def summary(self) -> str:
        return (f"items: {self.items_seen} (new/changed {self.items_new}) | AI parsed: {self.ai_calls} | "
                f"AI skipped cached: {self.ai_skipped} | fallback calls: {self.ai_fallback} | AI errors: {self.ai_errors} | "
                f"events created: {self.events_created} | updated: {self.events_updated} | review: {self.events_review} | "
                f"not events: {self.not_events}")


class Pipeline:
    def __init__(self, settings: Settings, repo: Repository, extractor: Optional[Extractor],
                 collectors: list[Collector]):
        self.settings = settings
        self.repo = repo
        self.extractor = extractor
        self.collectors = collectors
        self.stats = RunStats()

    # ------------------------------------------------------------------
    def run(self) -> RunStats:
        for collector in self.collectors:
            if not collector.enabled():
                continue
            run_id = self.repo.start_ingest_run(collector.source_type)
            before = _snapshot(self.stats)
            try:
                items = collector.collect()
            except CollectorError as exc:
                self.stats.collector_errors[collector.source_type] = str(exc)
                self.repo.finish_ingest_run(run_id, status="failed", error_message=str(exc)[:500])
                print(f"[error] collector {collector.source_type}: {exc}")
                continue
            for item in items:
                try:
                    self.process_item(item)
                except Exception as exc:  # noqa: BLE001 - one bad item must not stop the run
                    self.stats.ai_errors += 1
                    print(f"[warn] item {item.source_type}:{item.external_id[:12]} failed: {exc.__class__.__name__}")
            delta = _delta(before, self.stats)
            status = "partial" if delta["ai_errors"] else "ok"
            self.repo.finish_ingest_run(run_id, status=status, **{k: v for k, v in delta.items() if k != "ai_errors"})
        return self.stats

    # ------------------------------------------------------------------
    def process_item(self, item: RawItem) -> Optional[ParseOutcome]:
        self.stats.items_seen += 1
        existing = self.repo.find_raw_item(item.source_type, item.external_id)
        content_hash = item.content_hash
        if existing and existing.get("content_hash") == content_hash:
            linked = self.repo.events_linked_to(existing["id"])
            cached = self.repo.cached_parse(existing["id"], content_hash)
            if linked or (cached and not _is_event(cached)):
                self.repo.touch_raw_item(existing["id"])
                self.stats.ai_skipped += 1
                return ParseOutcome(candidate=None, skipped_cached=True)
        row = self.repo.upsert_raw_item(item)
        raw_item_id = row["id"]
        if not existing or existing.get("content_hash") != content_hash:
            self.stats.items_new += 1
        self.repo.upsert_attachments(raw_item_id, item.attachments)

        outcome = self.parse_item(item, raw_item_id, content_hash)
        if outcome.error or outcome.candidate is None:
            return outcome
        cand = outcome.candidate
        if not cand.is_event:
            self.stats.not_events += 1
            return outcome
        self.store_candidate(cand, raw_item_id)
        return outcome

    # ------------------------------------------------------------------
    def parse_item(self, item: RawItem, raw_item_id: str, content_hash: str) -> ParseOutcome:
        reference = item.source_created_at or datetime.now(KST)
        clean_text = sanitize_for_ai(item.raw_text)
        facts = analyze(f"{item.subject}\n{clean_text}", reference)
        source_priority = SOURCE_PRIORITY.get(item.source_type, 100)

        cached = self.repo.cached_parse(raw_item_id, content_hash)
        if cached:
            self.stats.ai_skipped += 1
            try:
                extraction = EventExtraction.model_validate(cached["parsed_json"])
            except Exception:  # noqa: BLE001 - schema drift; re-parse
                extraction = None
            if extraction is not None:
                cand = validate(extraction, facts, clean_text, source_type=item.source_type,
                                source_priority=source_priority, reference=reference)
                return ParseOutcome(candidate=cand, skipped_cached=True)

        if self.extractor is None:
            return ParseOutcome(candidate=None, error="no extractor configured")

        images = _event_images(item, self.settings)
        note = f"POSTER_IMAGES_ATTACHED: {len(images)}" if images else ""
        user_text = build_user_text(
            subject=sanitize_for_ai(item.subject), body=clean_text,
            sent_at=reference.isoformat(timespec="minutes"), source_label=item.source_type, attachments_note=note)

        primary = self._call(self.extractor, user_text, images, self.settings.ai_model, raw_item_id, content_hash, "primary")
        if primary.extraction is None:
            self.stats.ai_errors += 1
            return ParseOutcome(candidate=None, ai_calls=1, error=primary.error)
        cand = validate(primary.extraction, facts, clean_text, source_type=item.source_type,
                        source_priority=source_priority, reference=reference)
        calls = 1
        used_fallback = False
        reasons = fallback_reasons(primary.extraction, facts, clean_text, self.settings.ai_confidence_threshold)
        if reasons and self.settings.ai_fallback_model and self.settings.ai_fallback_model != self.settings.ai_model:
            fb = self._call(self.extractor, user_text, images, self.settings.ai_fallback_model, raw_item_id, content_hash, "fallback")
            calls += 1
            used_fallback = True
            self.stats.ai_fallback += 1
            if fb.extraction is not None:
                fb_cand = validate(fb.extraction, facts, clean_text, source_type=item.source_type,
                                   source_priority=source_priority, reference=reference)
                cand = pick_better(cand, fb_cand)
                if cand.is_event and cand.needs_review and "fallback 결과와 비교됨" not in cand.review_reasons:
                    cand.review_reasons.append(f"fallback 사유: {', '.join(reasons)}")
        return ParseOutcome(candidate=cand, ai_calls=calls, fallback_used=used_fallback)

    def _call(self, extractor: Extractor, text: str, images: list[tuple[str, bytes]], model: str,
              raw_item_id: str, content_hash: str, role: str) -> AIResult:
        self.stats.ai_calls += 1
        result = extractor.extract(text, images, model)
        self.repo.insert_ai_run({
            "raw_item_id": raw_item_id,
            "content_hash": content_hash,
            "model": result.model,
            "prompt_version": result.prompt_version or PROMPT_VERSION,
            "input_kind": result.input_kind,
            "role": role,
            "parsed_json": json.loads(result.extraction.model_dump_json()) if result.extraction else None,
            "confidence": result.extraction.confidence if result.extraction else None,
            "needs_review": result.extraction.needs_review if result.extraction else None,
            "usage_input_tokens": result.usage.input_tokens,
            "usage_output_tokens": result.usage.output_tokens,
            "status": "ok" if result.extraction else "error",
            "error_message": result.error,
        })
        return result

    # ------------------------------------------------------------------
    def store_candidate(self, cand: EventCandidate, raw_item_id: str) -> str:
        existing = self.repo.candidate_events(cand.event_start)
        match = find_match(cand, existing, self.settings.dedup_threshold)
        if match:
            updated, _reasons = merge_into(match.event, cand)
            self.repo.update_event(match.event["id"], updated)
            self.repo.link_event_source(match.event["id"], raw_item_id, match.score)
            self.stats.events_updated += 1
            if updated.get("needs_review"):
                self.stats.events_review += 1
            return match.event["id"]
        row = cand.to_db_row()
        event_id = self.repo.insert_event(row)
        self.repo.link_event_source(event_id, raw_item_id, 1.0)
        self.stats.events_created += 1
        if cand.needs_review:
            self.stats.events_review += 1
        return event_id


def _is_event(cached: dict[str, Any]) -> bool:
    parsed = cached.get("parsed_json") or {}
    return bool(parsed.get("is_event", True))


def _event_images(item: RawItem, settings: Settings) -> list[tuple[str, bytes]]:
    images: list[tuple[str, bytes]] = []
    for att in item.attachments:
        if att.data and att.mime_type.startswith("image/") and att.parse_status == "downloaded":
            if len(att.data) <= settings.ai_max_image_bytes and len(att.data) >= 8 * 1024:  # skip tiny icons/signatures
                images.append((att.mime_type, att.data))
                att.parse_status = "used"
        if len(images) >= settings.ai_max_images:
            break
    return images


_COUNTERS = ("items_seen", "items_new", "ai_calls", "ai_skipped", "ai_fallback", "ai_errors",
             "events_created", "events_updated", "events_review")


def _snapshot(stats: RunStats) -> dict[str, int]:
    return {k: getattr(stats, k) for k in _COUNTERS}


def _delta(before: dict[str, int], stats: RunStats) -> dict[str, int]:
    return {k: getattr(stats, k) - before[k] for k in _COUNTERS}
