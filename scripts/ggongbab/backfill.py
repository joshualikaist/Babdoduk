# -*- coding: utf-8 -*-
"""Mailbox backfill driver: prefilter -> safety limit -> existing pipeline.

Deliberately thin. Everything after candidate selection reuses the pipeline that
is already in production: the same v2 prompt, the same sanitizer, the same
deterministic validator, the same dedup and the same exporter. No second AI path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from .config import KST, Settings
from .models import EventCandidate, RawItem
from .pipeline import Pipeline
from .prefilter import Decision, classify
from .prefilter import classify as classify_mail  # re-exported for tests
from .parsers.sanitizer import sanitize_for_ai


@dataclass
class CandidateReport:
    received: Optional[datetime]
    subject: str
    decision: Decision
    candidate: Optional[EventCandidate] = None
    skipped_cached: bool = False
    error: Optional[str] = None

    @property
    def verdict(self) -> str:
        if self.error:
            return "error"
        if self.candidate is None:
            return "cached" if self.skipped_cached else "no result"
        if not self.candidate.is_event:
            return "not event"
        if self.candidate.needs_review:
            return "review"
        if self.candidate.food_provided == "true":
            return "publishable"
        return "event, food unknown"


@dataclass
class BackfillReport:
    scanned: int = 0
    read_mails: int = 0
    unread_mails: int = 0
    unknown_state_mails: int = 0
    rule_candidates: int = 0
    ai_candidates: int = 0
    likely_events: int = 0
    food_provided: int = 0
    needs_review: int = 0
    not_event: int = 0
    in_window: int = 0
    past_events: int = 0
    ai_calls: int = 0
    ai_skipped: int = 0
    stopped_reason: Optional[str] = None
    rows: list[CandidateReport] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)   # (reason, subject)

    def render(self, event_until: Optional[date], dry_run: bool) -> str:
        head = "DRY RUN - nothing was written" if dry_run else "BACKFILL"
        lines = [
            f"=== {head} ===",
            f"Scanned mails: {self.scanned}",
            f"  Read: {self.read_mails} · Unread: {self.unread_mails} · State unknown: {self.unknown_state_mails}",
            f"Rule candidates: {self.rule_candidates}",
            f"AI candidates: {self.ai_candidates}   (AI calls: {self.ai_calls}, cached/skipped: {self.ai_skipped})",
            f"Likely events: {self.likely_events}",
            f"Explicit food provided: {self.food_provided}",
            f"Needs review: {self.needs_review}",
            f"Not event: {self.not_event}",
        ]
        if event_until:
            lines.append(f"Events up to {event_until.isoformat()} and still ahead: {self.in_window}"
                         f"   (already past: {self.past_events})")
        if self.stopped_reason:
            lines.append(f"STOPPED: {self.stopped_reason}")
        shown = [r for r in self.rows if r.candidate is not None or r.error]
        if shown:
            lines.append("")
            for index, row in enumerate(shown, 1):
                lines.extend(_render_row(index, row))
        if self.rejected:
            lines.append("")
            lines.append("Rejected by the local filter (no AI call):")
            from collections import Counter
            for reason, count in Counter(r for r, _s in self.rejected).most_common():
                lines.append(f"  {count:>4}  {reason}")
        return "\n".join(lines)


def _render_row(index: int, row: CandidateReport) -> list[str]:
    """One candidate, with no addresses, no body text and no ids."""
    out = [f"[{index}]"]
    if row.received:
        out.append(f"received: {row.received.astimezone(KST).date().isoformat()}")
    out.append(f"subject: {_clip(row.subject)}")
    cand = row.candidate
    if row.error:
        out.append(f"error: {row.error}")
    elif cand is None:
        out.append("result: already ingested (no AI call)")
    elif not cand.is_event:
        out.append("event: -")
        out.append("decision: not event")
    else:
        when = cand.event_start.astimezone(KST).strftime("%Y-%m-%d %H:%M") if cand.event_start else "unknown"
        out.append(f"event: {when}")
        place = " ".join(x for x in (cand.building, cand.room) if x) or (cand.location_name or "-")
        out.append(f"place: {place}")
        food = cand.food_provided
        out.append(f"food: {cand.food_type if food == 'true' else food}")
        out.append(f"registration: {cand.registration_required}")
        out.append(f"confidence: {cand.confidence}")
        out.append(f"decision: {row.verdict}")
        if cand.needs_review:
            out.append(f"review: {_clip(cand.review_reason or '', 110)}")
    return ["  " + line if i else line for i, line in enumerate(out)]


def _clip(text: str, n: int = 70) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def run_backfill(settings: Settings, repo, extractor, items: list[RawItem], *,
                 event_until: Optional[date] = None, max_ai_candidates: int = 50,
                 force: bool = False, use_ai: bool = True, now: Optional[datetime] = None) -> BackfillReport:
    """Filter locally, then hand survivors to the production pipeline."""
    report = BackfillReport()
    now = now or datetime.now(KST)
    pipeline = Pipeline(settings, repo, extractor if use_ai else None, [])

    candidates: list[tuple[RawItem, Decision]] = []
    for item in items:
        report.scanned += 1
        state = (item.metadata or {}).get("read_state", "unknown")
        if state == "read":
            report.read_mails += 1
        elif state == "unread":
            report.unread_mails += 1
        else:
            report.unknown_state_mails += 1
        # The filter reads the sanitized body, so the decision never depends on
        # addresses, phone numbers or signatures.
        decision = classify(item.subject, sanitize_for_ai(item.raw_text))
        if not decision.candidate:
            report.rejected.append((decision.reason, item.subject))
            continue
        report.rule_candidates += 1
        candidates.append((item, decision))

    if not force and len(candidates) > max_ai_candidates:
        report.stopped_reason = (
            f"{len(candidates)} rule candidates exceed --max-ai-candidates ({max_ai_candidates}). "
            f"Narrow --mail-from/--mail-to, or re-run with --force once the dry run looks right.")
        return report

    for item, decision in candidates:
        report.ai_candidates += 1
        row = CandidateReport(received=item.source_created_at, subject=item.subject, decision=decision)
        try:
            outcome = pipeline.process_item(item)
        except Exception as exc:  # noqa: BLE001 - one bad mail must not stop the backfill
            row.error = exc.__class__.__name__
            report.rows.append(row)
            continue
        if outcome is None:
            report.rows.append(row)
            continue
        row.skipped_cached = outcome.skipped_cached
        row.error = outcome.error
        row.candidate = outcome.candidate
        cand = outcome.candidate
        if cand is not None:
            if not cand.is_event:
                report.not_event += 1
            else:
                report.likely_events += 1
                if cand.food_provided == "true":
                    report.food_provided += 1
                if cand.needs_review:
                    report.needs_review += 1
                start = cand.event_start
                if start is not None:
                    if start < now:
                        report.past_events += 1
                    elif event_until is None or start.astimezone(KST).date() <= event_until:
                        report.in_window += 1
        report.rows.append(row)

    report.ai_calls = pipeline.stats.ai_calls
    report.ai_skipped = pipeline.stats.ai_skipped
    return report
