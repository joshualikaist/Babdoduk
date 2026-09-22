# -*- coding: utf-8 -*-
"""Deterministic validator: the AI is an extraction engine, not the truth authority.

Every AI result is checked against RuleFacts computed from the same text.
Conflicts never get published silently; they become needs_review or a fallback call.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

from ..config import KST
from ..models import EventCandidate, EventExtraction, RuleFacts
from .rule_parser import explicit_food_evidence, food_type_hint, is_real_eligibility, registration_evidence

FALLBACK_REASONS = {
    "low_confidence",
    "date_conflict",
    "food_ambiguous",
    "missing_essential",
    "ai_flagged",
    "poster_conflict",
    "rule_conflict",
}


def parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        # tolerate "2026-09-25 12:00" and date-only values
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    return dt.astimezone(KST)


def _norm(text: Optional[str]) -> str:
    return re.sub(r"\s+", "", (text or "")).lower()


def _url_ok(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _url_in_source(url: str, facts: RuleFacts, source_text: str) -> bool:
    if url in facts.urls or url in source_text:
        return True
    stripped = url.rstrip("/")
    return any(u.rstrip("/") == stripped for u in facts.urls)


def _evidence_supported(quote: Optional[str], source_text: str) -> bool:
    """A quote counts only if a meaningful chunk of it appears in the source."""
    q = _norm(quote)
    if len(q) < 4:
        return False
    src = _norm(source_text)
    if q in src:
        return True
    # tolerate light paraphrase: at least 60% of 8-char shingles must appear
    shingles = [q[i:i + 8] for i in range(0, max(1, len(q) - 7), 4)]
    hits = sum(1 for s in shingles if s in src)
    return shingles and hits / len(shingles) >= 0.6


def fallback_reasons(ai: EventExtraction, facts: RuleFacts, source_text: str, threshold: float) -> list[str]:
    """Reasons that justify a second parse with the fallback model (never for every mail)."""
    reasons: list[str] = []
    if not ai.is_event:
        return reasons
    if ai.confidence < threshold:
        reasons.append("low_confidence")
    if ai.needs_review:
        reasons.append("ai_flagged")
    start = parse_iso(ai.event_start)
    if start and facts.dates and start.date().isoformat() not in facts.dates:
        reasons.append("date_conflict")
    if not ai.title or (not start and facts.dates and facts.times):
        reasons.append("missing_essential")
    if ai.food_provided == "true" and not (ai.evidence.food and explicit_food_evidence(ai.evidence.food)):
        reasons.append("food_ambiguous")
    if ai.food_provided != "true" and facts.explicit_food:
        reasons.append("rule_conflict")
    if ai.review_reason and re.search(r"poster|포스터|image|이미지", ai.review_reason, re.I):
        reasons.append("poster_conflict")
    return reasons


def validate(ai: EventExtraction, facts: RuleFacts, source_text: str, *, source_type: str = "manual",
             source_priority: int = 100, reference: Optional[datetime] = None) -> EventCandidate:
    """Turn an AI extraction into a validated candidate with review flags."""
    reasons: list[str] = []
    confidence = max(0.0, min(1.0, float(ai.confidence)))
    title = (ai.title or "").strip()
    cand = EventCandidate(title=title or "(제목 없음)", is_event=bool(ai.is_event),
                          source_type=source_type, source_priority=source_priority)  # type: ignore[arg-type]
    if not ai.is_event:
        cand.is_event = False
        cand.confidence = confidence
        return cand
    if not title:
        reasons.append("제목 누락")
        confidence = min(confidence, 0.4)

    # --- date / time --------------------------------------------------
    start = parse_iso(ai.event_start)
    end = parse_iso(ai.event_end)
    if start and facts.dates and start.date().isoformat() not in facts.dates:
        reasons.append(f"날짜 충돌: AI {start.date().isoformat()} vs 본문 {', '.join(facts.dates[:3])}")
        start = None
        end = None
    if start and facts.times and start.strftime("%H:%M") not in facts.times:
        reasons.append(f"시간 충돌: AI {start.strftime('%H:%M')} vs 본문 {', '.join(facts.times[:3])}")
    if start and not facts.dates and not _evidence_supported(ai.evidence.event_time, source_text):
        reasons.append("날짜 근거 없음")
        start = None
        end = None
    if end and start and end < start:
        end = None
    if start is None:
        reasons.append("행사 시작 시각 확정 불가")
    cand.event_start = start
    cand.event_end = end
    cand.date_text = (ai.date_text or "").strip() or None
    cand.time_text = (ai.time_text or "").strip() or None

    # --- location -----------------------------------------------------
    building = (ai.building or "").strip() or None
    if building:
        if facts.buildings and _norm(building) not in {_norm(b) for b in facts.buildings}:
            if not _evidence_supported(ai.evidence.location, source_text):
                reasons.append(f"장소 충돌: AI {building} vs 본문 {', '.join(facts.buildings[:3])}")
                building = None
    elif len(facts.buildings) == 1:
        building = facts.buildings[0]
    cand.building = building
    cand.room = (ai.room or "").strip() or None
    cand.location_name = (ai.location_name or "").strip() or None
    if cand.location_name and not facts.buildings and not _evidence_supported(ai.evidence.location, source_text) \
            and not _evidence_supported(cand.location_name, source_text):
        reasons.append("장소 근거 없음")
        cand.location_name = None

    # --- food ---------------------------------------------------------
    food_provided = ai.food_provided
    food_type = ai.food_type
    food_desc = (ai.food_description or "").strip() or None
    if food_provided == "true":
        quote = ai.evidence.food or ""
        ok = bool(explicit_food_evidence(quote)) and _evidence_supported(quote, source_text)
        if not ok and facts.explicit_food:
            ok = True  # the rules found explicit provision even if the AI quote is weak
            if not quote:
                food_desc = food_desc or facts.food_evidence[0]
        if not ok:
            reasons.append("식사 제공 근거 없음 (시간 표현만 있을 수 있음)")
            food_provided = "unknown"
            food_type = "unknown"
    elif facts.explicit_food:
        reasons.append(f"규칙은 식사 제공 감지({facts.food_evidence[0]}), AI는 {food_provided}")
    if food_provided == "true":
        hint = facts.food_type_hint if facts.explicit_food else food_type_hint(ai.evidence.food or "")
        if food_type == "unknown" and hint != "unknown":
            food_type = hint
        elif hint != "unknown" and food_type != hint and {food_type, hint} == {"meal", "lunchbox"}:
            food_type = "lunchbox"  # 도시락 is more specific than meal
    cand.food_provided = food_provided
    cand.food_type = food_type if food_provided == "true" else ("unknown" if food_provided == "unknown" else food_type)
    cand.food_description = food_desc

    # --- registration -------------------------------------------------
    url = (ai.registration_url or "").strip() or None
    if url:
        if not _url_ok(url):
            reasons.append("신청 URL 형식 오류")
            url = None
        elif not _url_in_source(url, facts, source_text):
            reasons.append("신청 URL이 본문에 없음")
            url = None
    cand.registration_url = url
    deadline = parse_iso(ai.registration_deadline)
    if deadline:
        known = set(facts.deadline_dates) | set(facts.dates)
        if known and deadline.date().isoformat() not in known:
            reasons.append("신청 마감일이 본문 날짜와 불일치")
            deadline = None
        elif not known and not _evidence_supported(ai.evidence.registration, source_text):
            reasons.append("신청 마감 근거 없음")
            deadline = None
    cand.registration_deadline = deadline
    # "not stated" is not "not required": only explicit wording (or a registration
    # link / deadline in the source) may decide either way.
    required = ai.registration_required
    rule_state = facts.registration_state or registration_evidence(source_text)
    quote_state = registration_evidence(ai.evidence.registration or "")
    if required == "true" and rule_state != "true" and quote_state != "true" and not url and not deadline:
        reasons.append("신청 필요 근거 없음")
        required = "unknown"
    elif required == "false" and rule_state != "false" and quote_state != "false":
        reasons.append("신청 불필요 근거 없음 (본문에 명시 없음)")
        required = "unknown"
    if required == "unknown" and (rule_state != "unknown" or url or deadline):
        required = rule_state if rule_state != "unknown" else "true"
    cand.registration_required = required

    # --- misc -----------------------------------------------------------
    cand.summary = (ai.summary or "").strip() or None
    cand.organizer = (ai.organizer or "").strip() or None
    # "참석자에게 점심 제공" describes recipients, not an admission restriction.
    eligibility = (ai.eligibility or "").strip() or None
    if eligibility and not is_real_eligibility(eligibility):
        eligibility = None
    if eligibility and not _evidence_supported(eligibility, source_text):
        eligibility = None
    cand.eligibility = eligibility
    if ai.needs_review:
        reasons.append(f"AI 검토 요청: {ai.review_reason or '사유 없음'}")

    if reasons:
        confidence = min(confidence, 0.6)
    cand.confidence = round(confidence, 3)
    cand.needs_review = bool(reasons)
    cand.review_reasons = reasons
    return cand


def pick_better(primary: EventCandidate, fallback: Optional[EventCandidate]) -> EventCandidate:
    """After a fallback parse, keep whichever candidate has fewer validator problems."""
    if fallback is None:
        return primary
    if not fallback.is_event and primary.is_event:
        primary.review_reasons.append("보조 모델은 행사 아님으로 판단")
        primary.needs_review = True
        return primary
    if len(fallback.review_reasons) < len(primary.review_reasons):
        return fallback
    if len(fallback.review_reasons) == len(primary.review_reasons) and fallback.confidence > primary.confidence:
        return fallback
    return primary
