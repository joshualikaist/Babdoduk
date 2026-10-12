# -*- coding: utf-8 -*-
"""Editorial selection: the public daily edition from ranked, eligible candidates.

Every lane carries LANE_SIZE stories (owner decision, 2026-10-12: five per lane in every
edition). A lane is filled best-first in tiers until it is full: fresh stories, at most
PER_SOURCE_PER_LANE from one source; then fresh stories from any source; then older tips and health
stories (past EVERGREEN_FRESH_DAYS, still within the evergreen window). Only qualifying stories
count, and a story runs once: a lane that still has fewer is published with what it has and the
run report names it (pipeline.finish), never filled with anything made up.

Hero (owner decision, 2026-09-29), heroKind in the edition:
  "trend"  a qualified trend story with INDEPENDENT evidence - measured demand, strong engagement,
           independent reporting of stockouts/popularity, or corroboration by another source that
           is not the same launch - never the seller's own words; two kinds preferred. It also
           needs a validated image of its own, a Tier A/B source and Korean/audience relevance >=
           HERO_AUDIENCE; published within HERO_IDEAL_DAYS preferred, 30 at most.
  "pick"   otherwise the best recent story with its own validated image, labelled
           "오늘의 추천 글" on the page: never wording that implies today's trend. With no image
           anywhere, a text-only hero.
Public items carry provenance (source, URL, medium, dates, image and its origin, ids, the
trend evidence kinds) but no internal scores or evidence text.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

import content_labels

from .common import KST, excerpt, parse_time
from .process import age_days

LANE_SIZE = 5              # stories per lane, every edition (owner decision, 2026-10-12)
EVERGREEN_FRESH_DAYS = 90  # an older tips/health story fills its lane only after every fresh one
PER_SOURCE_PER_LANE = 2    # variety first; relaxed only when the lane cannot be filled otherwise
HERO_IDEAL_DAYS = 7
HERO_MAX_DAYS = 30
HERO_AUDIENCE = 0.5
RULES = "lanes-v1"          # editions built under the evidence rules; older ones are legacy
LANES = ("trend", "tips", "health", "habit")
LANE_LEADS = content_labels.lane_leads()          # data/content/labels.json, the page shows its own copy
SUMMARY_CHARS = 120        # a card-length excerpt, never a paragraph
MIN_SUMMARY = 20
URLS = re.compile(r"(https?://\S+|www\.\S+|\S+@\S+\.\w+|#[^\s#]+)")


BOILERPLATE = re.compile(r"^(watch how to make (this|these)\b|jump to recipe\b|print recipe\b)", re.I)
# News leads open with a dateline or byline ("[서울=뉴시스] 김상윤 기자 =", "【 청년일보 】",
# "[대한급식신문=김보희 기자]") and carry photo captions ("사진=… 캡처"): not part of the story.
DATELINE = re.compile(r"^\s*(\[[^\]]{1,30}\]|【[^】]{1,30}】|\([^)]{1,20}=[^)]{0,20}\))\s*([가-힣]{2,4}\s*기자\s*=\s*)?")
CAPTION = re.compile(r"(/?\s*사진\s*=\s*[^.]{0,60}?(캡처|제공|갈무리|뉴시스|연합뉴스|DB)\s*)")
# A video description that opens with the channel's own notices has no description to excerpt.
CHANNEL_BOILERPLATE = re.compile(r"(멤버십\s*가입|구독과\s*좋아요|구독\s*부탁|알림\s*설정|CC\s*버튼|press cc|자막이\s*필요|"
                                 r"협업\s*(문의|제안)|business inquir|subscribe)", re.I)


def card_summary(text: str, title: str = "") -> str:
    """A short verbatim excerpt without links, addresses, hashtags, embed boilerplate or a repeat
    of the title; empty when too thin (the card then shows title and source only)."""
    cleaned = re.sub(r"\s+", " ", URLS.sub(" ", text or "")).strip(" -|·")
    cleaned = CAPTION.sub(" ", DATELINE.sub("", cleaned)).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\.\s*\.(?!\.)", ".", cleaned)          # "제작됐다. ." once a photo credit is gone
    head = re.sub(r"^\s*\[[^\]]{1,12}\]\s*", "", title or "")   # "[자료] 제목" as printed in the text
    if head and cleaned.startswith(head) and re.match(r"\s*(\d+\.|[-•▶\[])", cleaned[len(head):]):
        cleaned = cleaned[len(head):].strip()       # a data release repeating its headline before a list
    stripped = BOILERPLATE.sub("", cleaned).strip()
    if stripped != cleaned and title and stripped.lower().startswith(title.lower()):
        stripped = stripped[len(title):].strip(" -|·:")     # "Watch How to Make This <title>" heading
    cleaned = stripped
    words = cleaned.split()
    for n in range(min(12, len(words) // 2), 1, -1):       # an embed heading repeated as the first sentence
        if [w.lower() for w in words[:n]] == [w.lower() for w in words[n:2 * n]]:
            cleaned = " ".join(words[n:])
            break
    cleaned = re.sub(r"[ㅡ\-=_~*]{4,}", " ", cleaned).strip()
    if cleaned.count("▶") >= 2 or cleaned.count("•") >= 3 or CHANNEL_BOILERPLATE.search(cleaned[:80]):
        return ""                                  # a video's link list or channel notice, not a description
    short = excerpt(cleaned, SUMMARY_CHARS)
    return short if len(short) >= MIN_SUMMARY else ""


def public_item(row: dict) -> dict:
    item = {
        "title": row["title"],
        # A source registered with "excerpt": false is shown by title, source, date and link only.
        "summary": card_summary(row.get("sourceExcerpt") or "", row.get("title") or "")
        if row.get("excerptAllowed", True) else "",
        "source": row.get("sourceName") or "",
        "sourceId": row.get("sourceId"),
        "candidateId": row["candidateId"],
        "url": row["sourceUrl"],
        "medium": row.get("medium") or "blog",
        "discoveredAt": row.get("discoveredAt"),
    }
    if row.get("publishedAt"):
        item["publishedAt"] = row["publishedAt"]
    if row.get("imageUrl") and row.get("imageValidated"):
        item["image"] = row["imageUrl"]
        item["imageSource"] = row.get("imageSource")
    if row.get("assignedCategory") == "trend" and row.get("trendEvidence"):
        item["trendEvidence"] = list(row["trendEvidence"])
    return item


def independent_evidence(row: dict) -> list[str]:
    if row.get("trendEvidenceIndependent") is not None:
        return list(row["trendEvidenceIndependent"])
    from .process import trend_evidence          # rows built outside the pipeline (tests)
    return trend_evidence(row)[2]


def strong_evidence(row: dict) -> bool:
    """Evidence that does not speak for the seller: enough for a Trending-now hero."""
    return bool(independent_evidence(row))


def choose_hero(pool: list[dict], now: datetime) -> tuple[Optional[dict], str]:
    """(row, heroKind). A trend hero only on strong evidence; never a recipe standing in for a trend."""
    def trend_ok(row):
        age = age_days(row, now)
        audience = float((row.get("audienceRelevance") or {}).get("score") or 0)
        trusted = row.get("sourceTrust") in ("A", "B")        # high source trust: never a Tier C lead
        return (row.get("assignedCategory") == "trend" and strong_evidence(row) and row.get("imageValidated")
                and row.get("imageUrl") and trusted and audience >= HERO_AUDIENCE
                and age is not None and age <= HERO_MAX_DAYS)
    trends = sorted((r for r in pool if trend_ok(r)),
                    key=lambda r: (len(independent_evidence(r)) < 2, age_days(r, now) > HERO_IDEAL_DAYS,
                                   -(r.get("score") or 0), r["candidateId"]))
    if trends:
        return trends[0], "trend"
    with_image = [r for r in pool if r.get("imageValidated") and r.get("imageUrl")]
    recent_first = sorted(with_image, key=lambda r: ((age_days(r, now) is None) or age_days(r, now) > HERO_MAX_DAYS,
                                                    -(r.get("score") or 0), r["candidateId"]))
    if recent_first:
        return recent_first[0], "pick"
    return (pool[0], "pick") if pool else (None, "pick")


def eligible(rows: list[dict], recent: set[str], date: str = "") -> list[dict]:
    """Qualifying stories not already published: a story runs in one edition only (its
    selectedFor), so an old source is never recycled as fresh content day after day. A compact
    row (store.compact) is never a story: it no longer has the facts to show or judge."""
    return sorted((r for r in rows if not r.get("compact") and not r.get("duplicateOf") and not r.get("rejectionReason")
                   and r.get("assignedCategory") and r["candidateId"] not in recent
                   and r.get("canonicalUrl") not in recent
                   and (not r.get("selectedFor") or r.get("selectedFor") == date)),
                  key=lambda r: (-(r.get("score") or 0), r["candidateId"]))


def build(rows: list[dict], *, date: str, generated_at: str, recent: set[str]) -> tuple[dict, list[str]]:
    pool = eligible(rows, recent, date)
    now = parse_time(generated_at) or datetime.fromisoformat(date).replace(hour=10, tzinfo=KST)
    featured_row, hero_kind = choose_hero(pool, now)
    lanes, chosen = {}, []
    if featured_row is not None:
        chosen.append(featured_row["candidateId"])

    def old(row):
        age = age_days(row, now)
        return row["assignedCategory"] in ("tips", "health") and age is not None and age > EVERGREEN_FRESH_DAYS

    # Tiers, in order, until the lane holds LANE_SIZE: (may this row run, given how many its
    # source already has in the lane?)
    tiers = (lambda row, used: not old(row) and used < PER_SOURCE_PER_LANE,
             lambda row, used: not old(row),
             lambda row, used: True)
    for lane in LANES:
        picked, per_source = [], {}
        for allowed in tiers:
            for row in pool:
                if len(picked) >= LANE_SIZE:
                    break
                if row["assignedCategory"] != lane or row["candidateId"] in chosen:
                    continue
                if set(row.get("corroboratedBy") or []) & set(chosen):
                    continue                      # the same story told by another outlet: one slot per topic
                key = row.get("sourceName") or row.get("sourceId")
                if not allowed(row, per_source.get(key, 0)):
                    continue
                per_source[key] = per_source.get(key, 0) + 1
                picked.append(row)
                chosen.append(row["candidateId"])
        lanes[lane] = {"lead": LANE_LEADS[lane], "items": [public_item(r) for r in picked]}
    featured = None
    if featured_row is not None:
        featured = dict(public_item(featured_row), category=featured_row["assignedCategory"], heroKind=hero_kind)
    # The nominal "Daily 10:00 KST" schedule is no longer written: the scheduled run starts hours
    # late, and the page shows generatedAt (schemas/magazine-edition.schema.json).
    edition = {"schemaVersion": 1, "date": date, "generatedAt": generated_at, "rules": RULES,
               "featured": featured, "lanes": lanes}
    return edition, chosen


def truthful(item: dict) -> bool:
    """What every stored edition must satisfy: a real source, a real http(s) URL, no desk."""
    url = (item or {}).get("url") or ""
    return (bool(item) and url.startswith(("http://", "https://")) and item.get("medium") != "desk"
            and item.get("source") not in ("", None, "밥도둑 데스크") and bool(item.get("title")))


def sanitize(edition: dict) -> tuple[dict, int]:
    """Past editions: drop fabricated desk items and link-only idea desks, and drop generated
    summaries/tags (the old builder composed them; their source text was never kept). A trend
    item without trend evidence is not shown as a trend, and an edition built before the lane
    rules (no "rules" marker) keeps no habit items: the old builder put recipes there by keyword."""
    removed = 0
    legacy = edition.get("rules") != RULES

    def clean(item):
        keep = {k: item[k] for k in ("title", "source", "url", "medium", "image", "category", "publishedAt",
                                     "discoveredAt", "sourceId", "candidateId", "imageSource", "summary",
                                     "heroKind", "trendEvidence") if k in item}
        if "candidateId" not in item:        # built before provenance existed: its summary was generated
            keep.pop("summary", None)
        return keep

    def allowed(item, lane):
        if lane == "trend" and not item.get("trendEvidence"):
            return False
        return not (lane == "habit" and legacy)

    featured = edition.get("featured")
    if featured and (not truthful(featured) or not allowed(featured, featured.get("category"))):
        edition["featured"], removed = None, removed + 1
    elif featured:
        edition["featured"] = clean(featured)
    for lane, spec in (edition.get("lanes") or {}).items():
        items = spec.get("items") or []
        good = [clean(i) for i in items if truthful(i) and allowed(i, lane)]
        removed += len(items) - len(good)
        spec["items"] = good
    if "desks" in edition:
        removed += sum(len(v or []) for v in edition["desks"].values())
        del edition["desks"]
    return edition, removed
