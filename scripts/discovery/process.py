# -*- coding: utf-8 -*-
"""Normalization, dedup, quality filter, category classification and ranking.

Everything here is deterministic. Nothing writes prose: the only text that can reach a reader
is the source's own title and a verbatim excerpt of the source's own text.
"""
from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Optional

from .common import (canonical_url, clean_text, excerpt, is_public_url, iso, normalize_title, parse_time, sha,
                     title_similarity, youtube_id)
from .registry import TIERS

TITLE_DUPLICATE = 0.82
MAX_AGE_DAYS = 120
MIN_TEXT = {"youtube": 20, "blog": 60}
TIER_C_MIN_TEXT = 200

LANE_WORDS = {
    "tips": ("레시피", "만드는", "만들기", "볶음", "끓이", "양념", "손질", "조리", "식감", "비법", "꿀팁", "자취요리",
             "집밥", "반찬", "recipe", "how to", "make"),
    "trend": ("먹방", "신상", "편의점", "유행", "신메뉴", "요즘", "트렌드", "길거리", "야식", "asmr", "mukbang", "trend", "new"),
    "health": ("건강", "단백질", "샐러드", "저염", "저당", "채소", "영양", "두부", "다이어트", "균형", "healthy", "vegan",
               "protein", "salad", "vegetable"),
    "habit": ("아침", "습관", "천천히", "포만", "식사", "루틴", "식습관", "끼니", "habit", "breakfast", "routine"),
}
FOOD_WORDS = ("레시피", "요리", "음식", "먹", "밥", "반찬", "국", "찌개", "볶음", "김치", "면", "고기", "채소", "간식",
              "디저트", "빵", "떡", "라면", "편의점", "맛", "recipe", "food", "cook", "kimchi", "rice", "soup",
              "noodle", "dish", "banchan", "mukbang", "snack", "meal", "porridge", "pancake", "chicken", "pork",
              "beef", "meat", "egg", "tofu", "stew", "bread", "cake", "sauce", "kitchen", "bake", "dessert")
AD_WORDS = ("쿠팡파트너스", "파트너스 활동", "지원을 받아", "협찬", "유료광고", "광고 포함", "sponsored", "affiliate", "#ad ",
            "할인코드", "쿠폰 코드", "구매 링크")
OFF_TOPIC = ("맛집", "리조트", "호텔", "여행", "투어", "숙소", "호캉스", "노포", "출장", "브이로그 여행", "travel", "resort", "hotel")
BLOCKED = ("위장 학대", "경고:", "dangerous trend", "3x Speed", "위글위글", "주방템", "영수증만", "이벤트안내")


def normalize(raw: dict, source: dict, now: datetime) -> Optional[dict]:
    url = (raw.get("sourceUrl") or "").strip()
    if url.startswith("//"):
        url = "https:" + url
    text = clean_text(raw.get("text") or "")
    medium = raw.get("medium") or "blog"
    name = source.get("name") or ""
    if source.get("type") in ("youtube_search", "web_search"):
        name = raw.get("channelTitle") or raw.get("siteName") or name
    published = raw.get("publishedAt")
    published = published if isinstance(published, datetime) else parse_time(published)
    item_id = raw.get("sourceItemId") or ""
    vid = youtube_id(url)
    return {
        "sourceId": source.get("id"), "sourceName": name, "sourceType": source.get("type"), "sourceUrl": url,
        "canonicalUrl": canonical_url(url), "title": clean_text(raw.get("title") or "")[:200],
        "sourceExcerpt": excerpt(text, 280), "textLength": len(text), "publishedAt": iso(published),
        "imageUrl": raw.get("imageUrl") or "", "imageSource": raw.get("imageSource") or "",
        "imageValidated": False,          # only images.enrich sets it, after a real image response
        "categoryHints": list(source.get("categories") or []), "discoveryQuery": raw.get("discoveryQuery"),
        "discoveryMethod": source.get("discoveryMethod"), "medium": medium, "trustTier": source.get("trustTier"),
        "sourceItemId": f"yt:{vid}" if vid else (item_id or canonical_url(url)),
        # Title plus the start of the text: the same post republished under another URL, not two
        # videos that merely share a channel's boilerplate description.
        "contentHash": sha(normalize_title(raw.get("title") or "") + re.sub(r"\s+", "", text)[:300]) if len(text) >= 40 else None,
        "canonicalHash": sha(canonical_url(url)),
    }


def mark_duplicates(rows: list[dict]) -> int:
    """Deterministic: the earliest-discovered row of a group is canonical; later rows point at it
    with duplicateOf. Signals: canonical URL, source item id (YouTube video id), content hash and
    normalized-title similarity. Provenance of every duplicate stays in the store."""
    # Discovery order is persistent (discoveredSeq), so the same row stays the original run after run.
    ordered = sorted(rows, key=lambda r: (int(r.get("discoveredSeq") or 0), r["candidateId"]))
    by_key: dict[str, str] = {}
    kept: list[dict] = []
    marked = 0
    for row in ordered:
        if row.get("duplicateOf"):
            continue
        keys = [f"url:{row.get('canonicalHash')}", f"item:{row.get('sourceItemId')}"]
        if row.get("contentHash"):
            keys.append(f"content:{row['contentHash']}")
        original = next((by_key[k] for k in keys if k in by_key), None)
        if original is None:
            for other in kept:
                if title_similarity(row.get("title") or "", other.get("title") or "") >= TITLE_DUPLICATE:
                    original = other["candidateId"]
                    break
        if original and original != row["candidateId"]:
            row["duplicateOf"] = original
            marked += 1
            continue
        kept.append(row)
        for k in keys:
            by_key.setdefault(k, row["candidateId"])
    return marked


def rejection(row: dict, now: datetime) -> Optional[str]:
    """A fixed reason when the candidate may not be published, else None."""
    url = row.get("sourceUrl") or ""
    title = row.get("title") or ""
    blob = (title + " " + (row.get("sourceExcerpt") or "")).lower()
    if not is_public_url(url):
        return "BAD_URL"
    if len(title) < 4:
        return "NO_TITLE"
    minimum = MIN_TEXT.get(row.get("medium"), MIN_TEXT["blog"])
    if (row.get("textLength") or 0) < minimum:
        return "NO_SOURCE_TEXT"
    if any(word.lower() in blob for word in AD_WORDS):
        return "AD_OR_SPONSORED"
    if any(word.lower() in title.lower() for word in BLOCKED):
        return "BLOCKED_TOPIC"
    if any(word.lower() in title.lower() for word in OFF_TOPIC):
        return "OFF_TOPIC_RESTAURANT_TRAVEL"
    # A registered food blog or channel is food by definition; open discovery (Tier C) must show it.
    if row.get("trustTier") == "C" and not any(word.lower() in blob for word in FOOD_WORDS):
        return "NOT_FOOD"
    if row.get("trustTier") == "C" and (row.get("textLength") or 0) < TIER_C_MIN_TEXT:
        return "WEAK_TIER_C"
    published = parse_time(row.get("publishedAt"))
    if published and (now - published).days > MAX_AGE_DAYS:
        return "TOO_OLD"
    return None


def classify(row: dict) -> str:
    blob = ((row.get("title") or "") + " " + (row.get("sourceExcerpt") or "")).lower()
    hints = row.get("categoryHints") or []
    scores = {lane: sum(1 for w in words if w.lower() in blob) + (0.5 if lane in hints else 0)
              for lane, words in LANE_WORDS.items()}
    order = list(hints) + [lane for lane in LANE_WORDS if lane not in hints]
    return max(order, key=lambda lane: (scores[lane], -order.index(lane)))


def score(row: dict, now: datetime) -> None:
    lane = row.get("assignedCategory") or "tips"
    blob = ((row.get("title") or "") + " " + (row.get("sourceExcerpt") or "")).lower()
    when = parse_time(row.get("publishedAt")) or parse_time(row.get("discoveredAt")) or now
    days = max(0.0, (now - when).total_seconds() / 86400)
    row["sourceScore"] = TIERS.get(row.get("trustTier"), 0.5)
    row["freshnessScore"] = round(math.exp(-days / 21), 3)
    row["relevanceScore"] = round(min(1.0, sum(1 for w in LANE_WORDS[lane] if w.lower() in blob) / 3), 3)
    text_part = min(1.0, (row.get("textLength") or 0) / 400)
    row["qualityScore"] = round(0.6 * text_part + 0.4 * (1.0 if row.get("imageValidated") else 0.0), 3)
    row["score"] = round(0.35 * row["sourceScore"] + 0.25 * row["freshnessScore"] + 0.2 * row["relevanceScore"]
                         + 0.2 * row["qualityScore"], 4)


def process(rows: list[dict], now: datetime) -> dict:
    """Dedup, filter, classify and rank in place. Returns counts for the run report."""
    duplicates = mark_duplicates(rows)
    rejected = 0
    for row in rows:
        if row.get("duplicateOf"):
            continue
        row["rejectionReason"] = rejection(row, now)
        if row["rejectionReason"]:
            rejected += 1
            continue
        row["assignedCategory"] = classify(row)
        score(row, now)
    return {"duplicates": duplicates, "rejected": rejected}
