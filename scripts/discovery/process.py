# -*- coding: utf-8 -*-
"""Normalization, dedup, quality filter, lane rules and ranking.

Everything here is deterministic. Nothing writes prose: the only text that can reach a reader
is the source's own title and a verbatim excerpt of the source's own text.

Lanes are rules, not keyword routing (owner decision, 2026-09-29):
  trend   recent (<= 30 days), dated, food, retrieved text AND at least one trendEvidence kind
          found in the source text or platform metadata (discovery.evidence). A recipe needs a
          strong claim; a recent recipe alone is not a trend.
  habit   dated eating-behavior reporting or research from a Tier A/B source: two habit topic
          words plus a behavior/evidence sentence; news <= 90 days, research <= 2 years.
          Recipes and blogger opinion are not habit evidence.
  health  healthy-eating content from Tier A/B sources (a Tier C blog is never health advice)
  tips    how-to content: recipes, cooking posts and videos
A candidate that qualifies for no lane is rejected with NO_QUALIFYING_LANE, and laneDecisions
keeps the reason for each lane.
"""
from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Optional

from . import evidence
from .common import (canonical_url, clean_text, excerpt, is_public_url, iso, normalize_title, parse_time, sha,
                     title_similarity, youtube_id)
from .evidence import TREND_MAX_DAYS
from .registry import TIERS

TITLE_DUPLICATE = 0.82
EXCERPT_SUPPORT = 0.5
MAX_AGE_DAYS = 365          # evergreen lanes (tips, health) and news
RESEARCH_MAX_DAYS = evidence.HABIT_RESEARCH_MAX_DAYS
MIN_TEXT = {"youtube": 20, "blog": 60, "news": 60, "research": 120}   # news RSS descriptions are short
TIER_C_MIN_TEXT = 200

LANE_WORDS = {
    "tips": ("레시피", "만드는", "만들기", "볶음", "끓이", "양념", "손질", "조리", "식감", "비법", "꿀팁", "자취요리",
             "집밥", "반찬", "recipe", "how to", "make"),
    "trend": ("먹방", "신상", "편의점", "유행", "신메뉴", "요즘", "트렌드", "길거리", "야식", "asmr", "mukbang", "trend", "new"),
    "health": ("건강", "단백질", "샐러드", "저염", "저당", "채소", "영양", "두부", "다이어트", "균형", "healthy", "vegan",
               "protein", "salad", "vegetable"),
    "habit": ("아침", "습관", "천천히", "포만", "식사", "루틴", "식습관", "끼니", "habit", "breakfast", "routine"),
}
AD_WORDS = ("쿠팡파트너스", "파트너스 활동", "지원을 받아", "협찬", "유료광고", "광고 포함", "sponsored", "affiliate", "#ad ",
            "할인코드", "쿠폰 코드", "구매 링크")
PROMOTION_WORDS = ("cooking challenge", "giveaway", "contest", "enter to win", "sweepstakes", "경품", "이벤트 참여",
                   "챌린지 참여", "추첨", "공모전", "공모", "총상금", "응모", "참가자 모집", "체험단")
SEARCH_TYPES = ("web_search", "youtube_search")
# Board notices, personnel, obituaries, announcements and event recaps are not stories.
NOTICE_TAG = re.compile(r"^\s*\[[^\]]*(게시판|인사|부고|동정|알림|공지|모집|교육|행사|포토|사진|경조|화촉|신간|새 책|북)[^\]]*\]")
EVENT_TITLE = ("성료", "개최", "시상식", "기념식", "발대식", "협약식", "간담회", "세미나", "포럼", "박람회", "페스티벌",
               "축제", "설명회")
LANE_MIN_HITS = 2          # tips/health outside the source's own categories need two signals
OFF_TOPIC = ("맛집", "리조트", "호텔", "여행", "투어", "숙소", "호캉스", "노포", "출장", "브이로그 여행", "travel", "resort", "hotel")
BLOCKED = ("위장 학대", "경고:", "dangerous trend", "3x Speed", "위글위글", "주방템", "영수증만", "이벤트안내")
HOW_TO_KINDS = ("recipe", "video", "post")
LANE_ORDER = ("trend", "habit", "health", "tips")


def normalize(raw: dict, source: dict, now: datetime) -> Optional[dict]:
    url = (raw.get("sourceUrl") or "").strip()
    if url.startswith("//"):
        url = "https:" + url
    text = clean_text(raw.get("text") or "")
    lead = clean_text(raw.get("excerptText") or "")
    medium = raw.get("medium") or "blog"
    name = source.get("name") or ""
    if source.get("type") in ("youtube_search", "web_search"):
        name = raw.get("channelTitle") or raw.get("siteName") or name
    published = raw.get("publishedAt")
    published = published if isinstance(published, datetime) else parse_time(published)
    item_id = raw.get("sourceItemId") or ""
    vid = youtube_id(url)
    title = clean_text(raw.get("title") or "")[:200]
    tier = raw.get("trustTier") or source.get("trustTier")
    evidence_text = (text + " " + clean_text(raw.get("evidenceText") or "")).strip()
    meta = {"viewCount": raw.get("viewCount"), "likeCount": raw.get("likeCount")}
    return {
        "sourceId": source.get("id"), "sourceName": name, "sourceType": source.get("type"), "sourceUrl": url,
        "canonicalUrl": canonical_url(url), "title": title,
        "sourceExcerpt": excerpt(lead if len(lead) >= 40 else text, 280), "textLength": len(text),
        "publishedAt": iso(published),
        "publishedAtSource": raw.get("publishedAtSource") or ("feed" if published else ""),
        "imageUrl": raw.get("imageUrl") or "", "imageSource": raw.get("imageSource") or "",
        "imageValidated": False,          # only images.enrich sets it, after a real image response
        "categoryHints": list(source.get("categories") or []), "discoveryQuery": raw.get("discoveryQuery"),
        "discoveryMethod": raw.get("discoveryMethod") or source.get("discoveryMethod"),
        "discoveryLane": raw.get("discoveryLane") or source.get("lane"),
        "medium": medium, "trustTier": tier, "sourceTrust": tier,
        "contentKind": evidence.content_kind(title, text, medium, source.get("kind") or ""),
        "requireFood": bool(source.get("requireFood")), "commercePage": bool(raw.get("commerce")),
        "sponsored": evidence.sponsored(text),
        "searchRank": raw.get("searchRank"), "viewCount": meta["viewCount"], "likeCount": meta["likeCount"],
        "trendSignals": evidence.trend_signals(evidence_text, title=title, meta=meta, now=now, published=published),
        "habitSignals": evidence.habit_signals(title, evidence_text),
        "audienceRelevance": evidence.audience(title, text),
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
        # Only real values are evidence: an absent id must never match another absent id.
        keys = [f"{kind}:{row[field]}" for kind, field in (("url", "canonicalHash"), ("item", "sourceItemId"),
                                                           ("content", "contentHash")) if row.get(field)]
        original = next((by_key[k] for k in keys if k in by_key), None)
        if original is None:
            # Title similarity is supporting evidence only: it needs the same site, or a matching
            # excerpt, before two different URLs count as one story.
            for other in kept:
                if title_similarity(row.get("title") or "", other.get("title") or "") < TITLE_DUPLICATE:
                    continue
                same_site = _host(row) and _host(row) == _host(other)
                same_text = title_similarity(row.get("sourceExcerpt") or "", other.get("sourceExcerpt") or "") >= EXCERPT_SUPPORT
                if same_site or same_text:
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


def _host(row: dict) -> str:
    url = row.get("canonicalUrl") or ""
    return url.split("/")[2] if url.count("/") >= 2 else ""


def age_days(row: dict, now: datetime) -> Optional[float]:
    published = parse_time(row.get("publishedAt"))
    return (now - published).total_seconds() / 86400 if published else None


def _blob(row: dict) -> str:
    return ((row.get("title") or "") + " " + (row.get("sourceExcerpt") or "")).lower()


def rejection(row: dict, now: datetime) -> Optional[str]:
    """A fixed reason when the candidate may not be published at all, else None."""
    url = row.get("sourceUrl") or ""
    title = row.get("title") or ""
    blob = _blob(row)
    if not is_public_url(url):
        return "BAD_URL"
    if len(title) < 4:
        return "NO_TITLE"
    minimum = MIN_TEXT.get(row.get("medium"), MIN_TEXT["blog"])
    if (row.get("textLength") or 0) < minimum:
        return "NO_SOURCE_TEXT"
    if row.get("commercePage"):
        return "COMMERCE_PAGE"
    disclosed = evidence.NOT_SPONSORED.sub(" ", blob)          # "협찬 없이", "내돈내산" is not an ad
    if row.get("sponsored") or any(word.lower() in disclosed for word in AD_WORDS):
        return "AD_OR_SPONSORED"
    if any(word in blob for word in PROMOTION_WORDS):
        return "PROMOTION"
    if NOTICE_TAG.search(title) or any(word in title for word in EVENT_TITLE):
        return "NOTICE_OR_EVENT"
    if any(word.lower() in title.lower() for word in BLOCKED):
        return "BLOCKED_TOPIC"
    if any(word.lower() in title.lower() for word in OFF_TOPIC):
        return "OFF_TOPIC_RESTAURANT_TRAVEL"
    # A registered food blog or channel is food by definition; open discovery (Tier C) and broad
    # news feeds (requireFood) must show it.
    if (row.get("trustTier") == "C" or row.get("requireFood")) and not evidence.is_food(title, row.get("sourceExcerpt") or ""):
        return "NOT_FOOD"
    # A search result without a date cannot show when it was true; feeds always carry one.
    if row.get("sourceType") in SEARCH_TYPES and not row.get("publishedAt"):
        return "NO_DATE"
    if row.get("trustTier") == "C" and (row.get("textLength") or 0) < TIER_C_MIN_TEXT and row.get("medium") != "youtube":
        return "WEAK_TIER_C"
    age = age_days(row, now)
    if age is not None and age > (RESEARCH_MAX_DAYS if evidence.is_research(row) else MAX_AGE_DAYS):
        return "TOO_OLD"
    return None


def trend_evidence(row: dict) -> tuple[list[str], dict]:
    """(kinds, detail) that count for this row. A recipe's weak claim ("인기", "popular") does
    not count: a recipe is not a trend without a strong claim, figures, engagement or another
    source."""
    signals = row.get("trendSignals") or {}
    kinds, detail = [], {}
    for kind in ("explicit_source_claim", "sales_data", "engagement"):
        signal = signals.get(kind)
        if not signal:
            continue
        if kind == "explicit_source_claim" and row.get("contentKind") == "recipe" and not signal.get("strong"):
            continue
        kinds.append(kind)
        detail[kind] = signal.get("text") or ""
    if row.get("corroboratedBy"):
        kinds.append("corroborated")
        detail["corroborated"] = list(row["corroboratedBy"])[:3]
    return kinds, detail


def lane_decisions(row: dict, now: Optional[datetime]) -> dict:
    """lane -> None when the row qualifies, else the reason it does not."""
    out = {}
    age = age_days(row, now) if now else None
    kind = row.get("contentKind") or evidence.content_kind(row.get("title") or "", row.get("sourceExcerpt") or "",
                                                           row.get("medium") or "")
    tier = row.get("sourceTrust") or row.get("trustTier")
    food = evidence.is_food(row.get("title") or "", row.get("sourceExcerpt") or "")
    hints = row.get("categoryHints") or []
    blob = _blob(row)
    hits = {lane: sum(1 for w in words if w.lower() in blob) for lane, words in LANE_WORDS.items()}

    kinds, _ = trend_evidence(row)
    business = evidence.business_title(row.get("title") or "")
    if business:
        out["trend"] = "BUSINESS_NEWS"
    elif age is None:
        out["trend"] = "NO_DATE"
    elif age > TREND_MAX_DAYS:
        out["trend"] = "TOO_OLD_FOR_TREND"
    elif not food:
        out["trend"] = "NOT_FOOD"
    elif not kinds:
        weak = (row.get("trendSignals") or {}).get("explicit_source_claim")
        out["trend"] = "RECIPE_WITHOUT_TREND_EVIDENCE" if kind == "recipe" and weak else "NO_TREND_EVIDENCE"
    else:
        out["trend"] = None

    habit = row.get("habitSignals") or {}
    research = evidence.is_research(row)
    limit = evidence.HABIT_RESEARCH_MAX_DAYS if research else evidence.HABIT_NEWS_MAX_DAYS
    if kind == "recipe":
        out["habit"] = "RECIPE_NOT_HABIT"
    elif business:
        out["habit"] = "BUSINESS_NEWS"
    elif tier not in ("A", "B") or kind == "video":
        out["habit"] = "NOT_BEHAVIOR_SOURCE"
    elif age is None:
        out["habit"] = "NO_DATE"
    elif age > limit:
        out["habit"] = "TOO_OLD_FOR_HABIT"
    elif len(habit.get("words") or []) < 2:
        out["habit"] = "NOT_HABIT_TOPIC"
    elif not habit.get("behavior") and not research:
        out["habit"] = "NO_BEHAVIOR_EVIDENCE"
    elif not food:
        out["habit"] = "NOT_FOOD"
    else:
        out["habit"] = None

    if tier not in ("A", "B"):
        out["health"] = "TIER_C_NOT_HEALTH_ADVICE"
    elif business:
        out["health"] = "BUSINESS_NEWS"
    elif hits["health"] >= LANE_MIN_HITS or ("health" in hints and kind in HOW_TO_KINDS):
        # a news feed's category is not enough: the story itself must be about eating well
        out["health"] = None
    else:
        out["health"] = "NOT_HEALTH_TOPIC"

    if kind in HOW_TO_KINDS and ("tips" in hints or hits["tips"] >= LANE_MIN_HITS or kind == "recipe"):
        out["tips"] = None
    else:
        out["tips"] = "NOT_A_HOW_TO"
    return out


def classify(row: dict, now: Optional[datetime] = None) -> Optional[str]:
    """The lane this row is published in, or None. The lane the discovery query asked for
    wins when the row qualifies for it; otherwise trend/habit (rule-qualified) before the
    evergreen lanes, and among tips/health the source's own category and word signals."""
    decisions = lane_decisions(row, now)
    row["laneDecisions"] = decisions
    ok = [lane for lane in LANE_ORDER if decisions.get(lane) is None]
    if not ok:
        return None
    wanted = row.get("discoveryLane")
    if wanted in ok:
        return wanted
    if "trend" in ok and "habit" in ok:
        return "habit" if len((row.get("habitSignals") or {}).get("words") or []) >= 3 else "trend"
    for lane in ("trend", "habit"):
        if lane in ok:
            return lane
    hints = row.get("categoryHints") or []
    blob = _blob(row)
    hits = {lane: sum(1 for w in LANE_WORDS[lane] if w.lower() in blob) for lane in ok}
    return max(ok, key=lambda lane: (hits[lane] + (0.5 if lane in hints else 0), -ok.index(lane)))


def score(row: dict, now: datetime) -> None:
    """0.25 source trust + 0.20 freshness + 0.15 lane relevance + 0.15 quality + 0.25 audience
    relevance, plus up to 0.10 for trend evidence in the trend lane. Deterministic."""
    lane = row.get("assignedCategory") or "tips"
    blob = _blob(row)
    when = parse_time(row.get("publishedAt")) or parse_time(row.get("discoveredAt")) or now
    days = max(0.0, (now - when).total_seconds() / 86400)
    row["sourceScore"] = TIERS.get(row.get("sourceTrust") or row.get("trustTier"), 0.5)
    row["freshnessScore"] = round(math.exp(-days / 21), 3)
    if lane == "habit":
        relevance = len((row.get("habitSignals") or {}).get("words") or []) / 4
    elif lane == "trend":
        relevance = len(row.get("trendEvidence") or []) / 2
    else:
        relevance = sum(1 for w in LANE_WORDS[lane] if w.lower() in blob) / 3
    row["relevanceScore"] = round(min(1.0, relevance), 3)
    text_part = min(1.0, (row.get("textLength") or 0) / 400)
    row["qualityScore"] = round(0.6 * text_part + 0.4 * (1.0 if row.get("imageValidated") else 0.0), 3)
    row["audienceScore"] = float((row.get("audienceRelevance") or {}).get("score") or 0.0)
    bonus = 0.1 * min(1.0, len(row.get("trendEvidence") or []) / 2) if lane == "trend" else 0.0
    row["score"] = round(0.25 * row["sourceScore"] + 0.2 * row["freshnessScore"] + 0.15 * row["relevanceScore"]
                         + 0.15 * row["qualityScore"] + 0.25 * row["audienceScore"] + bonus, 4)


def process(rows: list[dict], now: datetime) -> dict:
    """Dedup, filter, corroborate, lane rules and ranking in place. Returns counts for the run
    report."""
    duplicates = mark_duplicates(rows)
    for row in rows:
        if not row.get("duplicateOf"):
            row["rejectionReason"] = rejection(row, now)
    corroborated = evidence.corroborate(rows, now)
    for row in rows:
        if row.get("duplicateOf") or row.get("rejectionReason"):
            continue
        row["corroboratedBy"] = corroborated.get(row["candidateId"]) or []
        row["trendEvidence"], row["trendEvidenceDetail"] = trend_evidence(row)
        lane = classify(row, now)
        row["assignedCategory"] = lane
        if lane is None:
            row["rejectionReason"] = "NO_QUALIFYING_LANE"
            continue
        score(row, now)
    rejected = sum(1 for row in rows if row.get("rejectionReason"))
    return {"duplicates": duplicates, "rejected": rejected}
