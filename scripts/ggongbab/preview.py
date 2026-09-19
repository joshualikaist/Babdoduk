"""Local mailbox preview using the production parser and an in-memory repository.

No project writer, persistent repository, or public export writer is used here.
Only the final public-shaped payload and numeric diagnostics leave memory.
"""
from __future__ import annotations

import json
from datetime import datetime, time
from pathlib import Path

from .config import KST
from .db.repository import MemoryRepository
from .exporter import build_payload
from .models import RawItem
from .parsers.ai_parser import OpenAIExtractor
from .pipeline import Pipeline
from .prefilter import classify
from .web.exit_codes import PipelineFailed, UiContractError
from .web.mail_reader import list_mails, open_body

PREVIEW_FILE = Path(__file__).resolve().parents[2] / ".local" / "ggongbab-preview.json"
COUNTERS = ("loadedRows", "dateMatched", "readEligible", "prefilterCandidates",
            "previewsAvailable", "bodyAttempted", "bodyFetched", "aiCalls",
            "fallbackCalls", "aiErrors", "likelyEvents", "explicitFood",
            "needsReview", "notEvent", "publicCount")


def collect_candidates(session, start, end, *, limit, target=None, read_state="read",
                       fetch_body=True, log=print):
    """Use the existing mailbox pager, filter and verified detail API."""
    if read_state != "read":
        raise UiContractError("preview-feed requires --read-state read")
    if not session.contract.read_state_key:
        raise UiContractError("preview-feed requires a calibrated read-state field")
    headers = list_mails(session, limit=limit, target=target, since=start)
    if any(h.unread is None for h in headers):
        raise UiContractError("read-state is missing or invalid; preview stopped before body fetch")
    counts = dict.fromkeys(COUNTERS, 0)
    counts["loadedRows"] = len(headers)
    items = []
    for index, header in enumerate(headers):
        if not header.received or not start <= header.received <= end:
            continue
        counts["dateMatched"] += 1
        counts["previewsAvailable"] += bool(header.preview)
        if header.unread is not False:
            continue
        counts["readEligible"] += 1
        decision = classify(header.subject, header.preview)
        if fetch_body and (decision.candidate or decision.has_event_word or decision.has_meal_time):
            counts["bodyAttempted"] += 1
            open_body(session, header, target=target)
            counts["bodyFetched"] += bool(header.body_opened)
            # Preserve the browser agent's candidate policy: enrich an existing
            # candidate; reclassify a near miss after fetching its body.
            if not decision.candidate:
                decision = classify(header.subject, header.text_for_filter)
        if decision.candidate:
            items.append(RawItem(
                source_type="dooray", external_id=header.mail_id, subject=header.subject,
                raw_text=header.body or header.preview,
                source_created_at=datetime.combine(header.received, time.min, tzinfo=KST),
                metadata={"preview_mode": True, "read_state": "read"}))
        if (index + 1) % 25 == 0:
            log(f"mail rows scanned: {index + 1}; body fetched: {counts['bodyFetched']}")
    counts["prefilterCandidates"] = len(items)
    return items, counts


def generate_preview(items, counts, settings, *, max_ai_candidates=50, force=False,
                     extractor_factory=OpenAIExtractor, log=print):
    """Check the whole candidate set BEFORE constructing/calling the extractor."""
    if max_ai_candidates < 1:
        raise UiContractError("--max-ai-candidates must be positive")
    log(f"{len(items)} rule candidates")
    log(f"AI safety limit: {max_ai_candidates}")
    if len(items) > max_ai_candidates and not force:
        raise UiContractError(
            f"STOPPED: {len(items)} candidates exceed preview AI safety limit {max_ai_candidates}.")
    if items and not settings.has_openai:
        raise PipelineFailed("preview requires an OpenAI API key")
    log("continuing")
    repo = MemoryRepository()
    extractor = extractor_factory(settings.openai_api_key) if items else None
    pipeline = Pipeline(settings, repo, extractor, [])
    metrics = {key: int(counts.get(key, 0)) for key in COUNTERS}
    for index, item in enumerate(items):
        try:
            result = pipeline.process_item(item)
        except Exception:
            pipeline.stats.ai_errors += 1
            result = None
        candidate = result.candidate if result else None
        if candidate:
            metrics["likelyEvents"] += int(candidate.is_event)
            metrics["explicitFood"] += int(candidate.is_event and candidate.food_provided == "true")
            metrics["needsReview"] += int(candidate.is_event and candidate.needs_review)
            metrics["notEvent"] += int(not candidate.is_event)
        log(f"AI candidates processed: {index + 1}/{len(items)}")
    metrics["aiCalls"] = pipeline.stats.ai_calls
    metrics["fallbackCalls"] = pipeline.stats.ai_fallback
    metrics["aiErrors"] = pipeline.stats.ai_errors
    payload = build_payload(repo.publishable_events(), settings, food_only=True)
    metrics["publicCount"] = payload["count"]
    payload["_preview"] = metrics
    from validate_content import validate_ggongbab_payload

    if validate_ggongbab_payload(payload):
        raise PipelineFailed("preview export validation failed; no payload written")
    PREVIEW_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PREVIEW_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(PREVIEW_FILE)
    for key, value in metrics.items():
        log(f"{key}: {value}")
    if metrics["aiErrors"]:
        raise PipelineFailed("preview saved with AI errors; inspect count-only diagnostics")
    return payload
