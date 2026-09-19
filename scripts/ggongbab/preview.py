"""Local mailbox preview using the production parser and an in-memory repository.

No project writer, persistent repository, or public export writer is used here.
Only the final public-shaped payload and numeric diagnostics leave memory.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, time
from pathlib import Path

from .config import KST
from .db.repository import MemoryRepository
from .exporter import build_payload
from .models import RawItem
from .parsers.ai_parser import OpenAIExtractor
from .parsers.ai_errors import UNKNOWN, classify_message, is_retryable, summary_lines
from .pipeline import Pipeline
from .prefilter import classify
from .web.exit_codes import PipelineFailed, UiContractError
from .web.mail_reader import list_mails, open_body

PREVIEW_FILE = Path(__file__).resolve().parents[2] / ".local" / "ggongbab-preview.json"
COUNTERS = ("loadedRows", "dateMatched", "readEligible", "prefilterCandidates",
            "previewsAvailable", "bodyAttempted", "bodyFetched", "aiCalls",
            "fallbackCalls", "aiErrorAttempts", "aiRecovered", "aiErrors",
            "likelyEvents", "explicitFood",
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


MAX_ERROR_RETRIES = 2
# Long enough for a per-minute rate-limit window to reset.
RETRY_BACKOFF_SECONDS = 70


def _tally(metrics, candidate) -> None:
    metrics["likelyEvents"] += int(candidate.is_event)
    metrics["explicitFood"] += int(candidate.is_event and candidate.food_provided == "true")
    metrics["needsReview"] += int(candidate.is_event and candidate.needs_review)
    metrics["notEvent"] += int(not candidate.is_event)


def _run_pass(pipeline, items, metrics, log, label):
    """Process items once. Returns (item, category) for each outright failure.

    Only an extraction failure comes back. A result that is merely uncertain -
    needs_review, food unknown, low confidence, not an event - is a real answer,
    so retrying it would just buy the same answer again. The category travels
    with the item so the caller can tell a waitable failure from a spent quota.
    """
    failed = []
    for index, item in enumerate(items):
        try:
            result = pipeline.process_item(item)
        except Exception as exc:  # noqa: BLE001 - one item must not end the pass
            pipeline.stats.ai_errors += 1
            category = classify_message(exc.__class__.__name__)
            pipeline.stats.ai_error_categories[category] = \
                pipeline.stats.ai_error_categories.get(category, 0) + 1
            failed.append((item, category))
            continue
        candidate = result.candidate if result else None
        if candidate is not None:
            _tally(metrics, candidate)
        elif result is not None and result.error:
            failed.append((item, result.error_category or UNKNOWN))
        log(f"{label}: {index + 1}/{len(items)}")
    return failed


def generate_preview(items, counts, settings, *, max_ai_candidates=50, force=False,
                     error_retries=1, backoff_seconds=None,
                     extractor_factory=OpenAIExtractor, log=print):
    """Check the whole candidate set BEFORE constructing/calling the extractor."""
    if max_ai_candidates < 1:
        raise UiContractError("--max-ai-candidates must be positive")
    if not 0 <= error_retries <= MAX_ERROR_RETRIES:
        raise UiContractError(
            f"--ai-error-retries must be 0..{MAX_ERROR_RETRIES}; a larger value would let one "
            f"bad run multiply into hundreds of API calls")
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

    failed = _run_pass(pipeline, items, metrics, log, "AI candidates processed")
    attempts = len(failed)
    recovered = 0
    for attempt in range(error_retries):
        retryable = [item for item, category in failed if is_retryable(category)]
        if not retryable:
            if failed:
                log(f"{len(failed)} failure(s) are not retryable; not re-sending")
            break
        stuck = [pair for pair in failed if not is_retryable(pair[1])]
        # Throttling is the common transient failure, and re-firing immediately
        # is what turns 39 calls into 78 rejected ones. Wait out the window first.
        base = RETRY_BACKOFF_SECONDS if backoff_seconds is None else backoff_seconds
        pause = base * (attempt + 1)
        log(f"retrying {len(retryable)} failed extraction(s) after {pause}s, "
            f"pass {attempt + 1}/{error_retries}")
        if pause:
            time.sleep(pause)
        before = len(failed)
        # A failed parse is not a cached success, so the same RawItem re-enters
        # the production pipeline; items that already succeeded are never re-sent.
        failed = stuck + _run_pass(pipeline, retryable, metrics, log, "retry")
        recovered += before - len(failed)
    metrics["aiCalls"] = pipeline.stats.ai_calls
    metrics["fallbackCalls"] = pipeline.stats.ai_fallback
    metrics["aiErrorAttempts"] = attempts
    metrics["aiRecovered"] = recovered
    # What remains unresolved after every attempt - not the running total.
    metrics["aiErrors"] = len(failed)
    for line in summary_lines(pipeline.stats.ai_error_categories):
        log(line)
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
