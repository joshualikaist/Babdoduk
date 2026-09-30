"""Campus food news: candidate recall and a separate, reviewed public projection.

LIST detection never calls this exporter. A reviewed source excerpt must support
every displayed fact; this module cannot fetch a body, infer a place, or turn a
news item into a free-food event.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from .config import KST
from .parsers.rule_parser import explicit_food_evidence
from .public_sanitizer import public_text

FOOD_SERVICE = re.compile(r"식당|매장|카페|버거|치킨|급식|학식|푸드|먹거리|음식|식사|커피|BBQ|\bNBB\b|restaurant|caf[eé]|burger|cafeteria|dining|food\s*service", re.I)
SERVICE_CHANGE = re.compile(r"오픈|개점|개업|입점|영업|운영\s*시간|폐점|이전|서비스|메뉴|출시|판매|휴무|휴업|재개|opening|opens?\b|closure|closing|relocat|operating\s*hours|service\s*launch|menu\s*change", re.I)
NON_SERVICE = re.compile(r"연구실|연구소|연구센터|실험실|논문|채용|설문|research\s*(?:lab|cent[er]+)|laboratory|job\s*opening", re.I)
PRIVATE = re.compile(r"portal\.kaist\.ac\.kr|sso\.kaist\.ac\.kr|/wz/|pstNo|boardNo|JSESSIONID|external[_ ]?id", re.I)
SOURCE_NAMES = {"portal": "KAIST 포탈", "kaist_public": "KAIST 공지"}
FIELDS = {"id", "contentType", "noticeDate", "title", "summary", "location", "sources", "hasFreeOffer"}


def is_news_candidate(title: str) -> bool:
    """Recall only. A brand name by itself is not a service change."""
    return bool(FOOD_SERVICE.search(title or "") and SERVICE_CHANGE.search(title or "")
                and not NON_SERVICE.search(title or ""))


def _clean(value, *, required=False, limit=240):
    if (not isinstance(value, str) or len(value) > limit or (required and not value.strip())
            or PRIVATE.search(value) or public_text(value) != value):
        raise ValueError("NEWS_UNSAFE_OR_UNVERIFIED_TEXT")
    return value.strip()


def extract_reviewed_news(record: dict) -> dict:
    """Extract exact source-backed facts after a separate review, never from a signal.

    An authenticated Portal LIST title remains Stage A. The review input must
    explicitly confirm campus scope and provide a supporting excerpt acquired
    under its own authorization (or supplied by the owner). No detail permission
    is implied here. Omitted free-offer evidence means UNKNOWN, never false.
    """
    if record.get("reviewed") is not True:
        raise ValueError("NEWS_REVIEW_REQUIRED")
    source = record.get("sourceType")
    if source not in SOURCE_NAMES:
        raise ValueError("NEWS_SOURCE_REQUIRED")
    evidence = _clean(record.get("evidence"), required=True, limit=2000)
    campus = _clean(record.get("campusEvidence"), required=True)
    title = _clean(record.get("title"), required=True)
    if campus not in evidence or not re.search(r"KAIST|카이스트|교내|학내|캠퍼스", campus, re.I):
        raise ValueError("NEWS_CAMPUS_EVIDENCE_REQUIRED")
    if title not in evidence or not is_news_candidate(title):
        raise ValueError("NEWS_SERVICE_CHANGE_NOT_CONFIRMED")
    stamp = record.get("noticeDate")
    if not isinstance(stamp, str) or date.fromisoformat(stamp).isoformat() != stamp:
        raise ValueError("NEWS_DATE_INVALID")
    if record.get("dateVerified") is not True:
        raise ValueError("NEWS_DATE_UNVERIFIED")
    item = {"id": "news-" + uuid.uuid5(uuid.NAMESPACE_URL, source + stamp + title).hex,
            "contentType": "campus_food_news", "noticeDate": stamp, "title": title,
            "sources": [{"type": source, "name": SOURCE_NAMES[source]}]}
    for key in ("summary", "location"):
        value = record.get(key)
        if value:
            value = _clean(value, limit=160)
            if value not in evidence:
                raise ValueError("NEWS_FACT_NOT_IN_SOURCE")
            item[key] = value
    positive, negative = record.get("freeOfferEvidence"), record.get("noFreeOfferEvidence")
    if positive and negative:
        raise ValueError("NEWS_CONFLICTING_FREE_OFFER")
    if positive:
        positive = _clean(positive, required=True)
        if (positive not in evidence or not explicit_food_evidence(positive)
                or not re.search(r"무료|공짜|증정|free|complimentary", positive, re.I)):
            raise ValueError("NEWS_FREE_OFFER_UNVERIFIED")
        item["hasFreeOffer"] = True
    elif negative:
        negative = _clean(negative, required=True)
        if negative not in evidence or not re.search(r"무료\s*(?:제공|증정|행사)\s*없|무료.*미제공|no\s+free\s+(?:food|offer|giveaway)", negative, re.I):
            raise ValueError("NEWS_NO_FREE_OFFER_UNVERIFIED")
        item["hasFreeOffer"] = False
    return item


def validate_news_payload(payload) -> list[str]:
    """Strict standalone schema. In particular there is no events array or source URL."""
    errors = []
    if not isinstance(payload, dict) or set(payload) != {"generatedAt", "timezone", "count", "items"}:
        return ["news top-level schema invalid"]
    try:
        stamp = datetime.fromisoformat(payload["generatedAt"])
        if stamp.utcoffset() != timedelta(hours=9):
            raise ValueError()
    except (ValueError, TypeError):
        errors.append("news generatedAt must have +09:00 offset")
    if payload["timezone"] != "Asia/Seoul":
        errors.append("news timezone invalid")
    items = payload["items"]
    if not isinstance(items, list):
        return errors + ["news items must be a list"]
    if type(payload["count"]) is not int or payload["count"] != len(items):
        errors.append("news count mismatch")
    seen = set()
    for item in items:
        try:
            if (not isinstance(item, dict) or set(item) - FIELDS
                    or not {"id", "contentType", "noticeDate", "title", "sources"} <= set(item)
                    or item["contentType"] != "campus_food_news"
                    or not re.fullmatch(r"news-[a-f0-9]{32}", item["id"])):
                raise ValueError()
            if item["id"] in seen:
                raise ValueError()
            seen.add(item["id"])
            if date.fromisoformat(item["noticeDate"]).isoformat() != item["noticeDate"]:
                raise ValueError()
            _clean(item["title"], required=True)
            for key in ("summary", "location"):
                if key in item:
                    _clean(item[key], required=True, limit=160)
            if "hasFreeOffer" in item and type(item["hasFreeOffer"]) is not bool:
                raise ValueError()
            if item["sources"] not in [[{"type": kind, "name": name}] for kind, name in SOURCE_NAMES.items()]:
                raise ValueError()
        except (KeyError, ValueError, TypeError):
            errors.append("news item failed schema/privacy validation (values suppressed)")
    return errors


def build_news(records: list[dict], now: datetime | None = None) -> dict:
    now = now or datetime.now(KST)
    items = [extract_reviewed_news(record) for record in records]
    # Dates describe the notice, never an inferred opening day.
    items = [item for item in items if now.date() - timedelta(days=30) <= date.fromisoformat(item["noticeDate"]) <= now.date()]
    items.sort(key=lambda item: (item["noticeDate"], item["id"]), reverse=True)
    payload = {"generatedAt": now.astimezone(KST).isoformat(timespec="seconds"), "timezone": "Asia/Seoul",
               "count": len(items), "items": items}
    if validate_news_payload(payload):
        raise ValueError("NEWS_EXPORT_INVALID")
    return payload


def load_news(reviewed: Path, now: datetime | None = None) -> dict:
    records = json.loads(reviewed.read_text(encoding="utf-8"))
    if not isinstance(records, dict) or set(records) != {"records"} or not isinstance(records["records"], list):
        raise ValueError("NEWS_REVIEW_INPUT_INVALID")
    return build_news(records["records"], now)


def write_news(payload: dict, destination: Path) -> None:
    if validate_news_payload(payload):
        raise ValueError("NEWS_EXPORT_INVALID")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(destination)


def export_news(reviewed: Path, destination: Path, now: datetime | None = None) -> dict:
    payload = load_news(reviewed, now)
    write_news(payload, destination)
    return payload
