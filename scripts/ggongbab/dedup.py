# -*- coding: utf-8 -*-
"""Cross-source duplicate detection and merge.

The same event can arrive from Dooray mail, the KAIST notice board and the
manual file. Matching combines normalized title similarity, event date,
organizer and building; external ids are never enough on their own.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlsplit
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Optional

from .models import EventCandidate
from .parsers.validator import parse_iso

_STOP = re.compile(r"\[[^\]]*\]|\([^)]*\)|안내|공지|알림|재공지|re:|fw:|fwd:|전달|모집|참가|참여|신청|설명회|세미나|행사|개최|the|of|and|for|a", re.I)
_PUNCT = re.compile(r"[^\w가-힣]+")


def normalize_title(title: str) -> str:
    text = _STOP.sub(" ", title or "")
    text = _PUNCT.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ratio = SequenceMatcher(None, a, b).ratio()
    tokens_a, tokens_b = set(a.split()), set(b.split())
    jaccard = len(tokens_a & tokens_b) / len(tokens_a | tokens_b) if tokens_a and tokens_b else 0.0
    return max(ratio, jaccard)


def _date_of(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        return value.date().isoformat()
    dt = parse_iso(value) if isinstance(value, str) else None
    return dt.date().isoformat() if dt else None


def _norm(value: Optional[str]) -> str:
    return re.sub(r"\s+", "", (value or "")).lower()


@dataclass
class Match:
    event: dict[str, Any]
    score: float


def score_pair(cand: EventCandidate, row: dict[str, Any]) -> float:
    title_sim = similarity(normalize_title(cand.title), normalize_title(row.get("title") or ""))
    score = 0.55 * title_sim
    d1 = _date_of(cand.event_start)
    d2 = _date_of(row.get("event_start"))
    if d1 and d2:
        score += 0.30 if d1 == d2 else -0.35
    elif not d1 and not d2:
        score += 0.05
    else:
        score -= 0.05
    org1, org2 = _norm(cand.organizer), _norm(row.get("organizer"))
    if org1 and org2:
        score += 0.10 if similarity(org1, org2) >= 0.8 else -0.05
    b1, b2 = _norm(cand.building), _norm(row.get("building"))
    if b1 and b2:
        score += 0.10 if b1 == b2 else -0.10
    if title_sim >= 0.92 and d1 == d2:
        score = max(score, 0.9)
    return round(score, 3)


def find_match(cand: EventCandidate, existing: list[dict[str, Any]], threshold: float) -> Optional[Match]:
    best: Optional[Match] = None
    for row in existing:
        score = score_pair(cand, row)
        if score >= threshold and (best is None or score > best.score):
            best = Match(event=row, score=score)
    return best


ESSENTIAL_CONFLICT_FIELDS = ("event_start", "building", "food_provided", "registration_url", "registration_deadline")
FILLABLE_FIELDS = (
    "summary", "event_start", "event_end", "registration_deadline", "date_text", "time_text",
    "location_name", "building", "room", "food_type", "food_description", "organizer",
    "eligibility", "registration_required", "registration_url",
    "giveaway", "giveaway_description", "food_evidence_source",
)


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, datetime) or isinstance(b, datetime) or (isinstance(a, str) and "T" in str(a) and str(a)[:4].isdigit()):
        return _date_of(a) == _date_of(b) and (parse_iso(str(a)) if not isinstance(a, datetime) else a) == (
            parse_iso(str(b)) if not isinstance(b, datetime) else b)
    return _norm(str(a)) == _norm(str(b))


def _place(value: Optional[str]) -> str:
    return _PUNCT.sub("", (value or "")).lower()


_BUILDING_CODE = re.compile(r"\b([A-Z]{1,2}\d{1,2}(?:-\d)?)\b", re.I)
_TRACKING = re.compile(r"^(utm_\w+|pk|fbclid|gclid|igsh|igshid|si|ref|ref_src|mc_cid|mc_eid)$", re.I)


def same_building(a: Any, b: Any) -> bool:
    """One building written two ways: "KI빌딩" and "KI빌딩(E4)", "E11" and "창의학습관(E11)".
    Two building codes must be the same code ("E1" is not "E11"); otherwise the names without
    their codes and brackets must be equal (2026-11-02: 업비트 특강 was held over KI빌딩 vs KI빌딩(E4))."""
    text_a, text_b = str(a or ""), str(b or "")
    codes_a = {c.upper() for c in _BUILDING_CODE.findall(text_a)}
    codes_b = {c.upper() for c in _BUILDING_CODE.findall(text_b)}
    if codes_a and codes_b:
        return codes_a == codes_b
    name_a = _place(_BUILDING_CODE.sub("", re.sub(r"[()（）]", " ", text_a)))
    name_b = _place(_BUILDING_CODE.sub("", re.sub(r"[()（）]", " ", text_b)))
    return bool(name_a) and name_a == name_b


def same_url(a: Any, b: Any) -> bool:
    """One link written two ways: the same address whose query differs only by tracking or referral
    keys (?pk=, utm_*), or by a trailing slash or the host's case (2026-11-02: NAVER D2SF 토크 was held
    over https://luma.com/viqcul3g?pk=g vs https://luma.com/viqcul3g). Any other query difference stays
    a conflict: on a board link the query is often the post id."""
    try:
        one, two = urlsplit(str(a or "").strip()), urlsplit(str(b or "").strip())
    except ValueError:
        return False
    if not one.netloc or not two.netloc:
        return _norm(str(a)) == _norm(str(b))
    def kept(parts):
        return sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _TRACKING.match(k))
    return (one.scheme.lower() in ("http", "https") and two.scheme.lower() in ("http", "https")
            and one.netloc.lower().removeprefix("www.") == two.netloc.lower().removeprefix("www.")
            and one.path.rstrip("/") == two.path.rstrip("/") and kept(one) == kept(two))


def same_field(key: str, a: Any, b: Any) -> bool:
    if key == "building":
        return _same(a, b) or same_building(a, b)
    if key == "registration_url":
        return _same(a, b) or same_url(a, b)
    return _same(a, b)


def merge_into(existing: dict[str, Any], cand: EventCandidate) -> tuple[dict[str, Any], list[str]]:
    """Return (updated_row, review_reasons). Conflicting facts are flagged, never overwritten."""
    new = cand.to_db_row()
    updated = dict(existing)
    reasons: list[str] = []
    for key in FILLABLE_FIELDS:
        old_val = existing.get(key)
        new_val = new.get(key)
        empty_old = old_val in (None, "", "unknown")
        empty_new = new_val in (None, "", "unknown")
        if empty_old and not empty_new:
            updated[key] = new_val
        elif not empty_old and not empty_new and key in ESSENTIAL_CONFLICT_FIELDS and not same_field(key, old_val, new_val):
            reasons.append(f"병합 충돌 {key}: {str(old_val)[:30]} vs {str(new_val)[:30]}")
        elif (key == "building" and not empty_old and not empty_new and not _BUILDING_CODE.search(str(old_val))
              and _BUILDING_CODE.search(str(new_val))):
            updated[key] = new_val                     # the same building, now with its code
    old_food = existing.get("food_provided") or "unknown"
    new_food = new.get("food_provided") or "unknown"
    if old_food == "unknown" and new_food != "unknown":
        updated["food_provided"] = new_food
        updated["food_type"] = new.get("food_type") or "unknown"
        updated["food_evidence_source"] = new.get("food_evidence_source")
    elif old_food != "unknown" and new_food != "unknown" and old_food != new_food:
        reasons.append(f"병합 충돌 food_provided: {old_food} vs {new_food}")
    updated["confidence"] = round(max(float(existing.get("confidence") or 0), float(new.get("confidence") or 0)), 3)
    if len((new.get("summary") or "")) > len((existing.get("summary") or "")) * 1.5 and new.get("summary"):
        updated["summary"] = new["summary"]
    prev_reasons = [r for r in (existing.get("review_reason") or "").split("; ") if r]
    all_reasons = prev_reasons + [r for r in cand.review_reasons if r not in prev_reasons] + [r for r in reasons if r not in prev_reasons]
    updated["review_reason"] = "; ".join(all_reasons) or None
    updated["needs_review"] = bool(all_reasons) or bool(existing.get("needs_review")) or cand.needs_review
    if existing.get("status") in ("rejected", "archived"):
        updated["status"] = existing["status"]
    else:
        updated["status"] = "review" if updated["needs_review"] else "published"
    return updated, reasons
