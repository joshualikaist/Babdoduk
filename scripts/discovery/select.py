# -*- coding: utf-8 -*-
"""Editorial selection: the public daily edition from ranked, eligible candidates.

LANE_SIZE is a maximum, not a quota: a lane shows only what qualifies, possibly nothing. The
featured story is the best qualifying story with a validated image of its own; only when no
such story exists does the page show a text-only hero. Public items carry provenance (source,
URL, medium, dates, image and its origin, ids) but no internal scores.
"""
from __future__ import annotations

import re
from typing import Optional

from .common import excerpt

LANE_SIZE = 8
PER_SOURCE_PER_LANE = 2
LANES = ("trend", "tips", "health", "habit")
LANE_LEADS = {
    "tips": "밥이 더 맛있어지는 작은 조리 팁",
    "trend": "요즘 사람들이 뭘 먹고 있는지",
    "health": "맛도 포기하지 않는 건강식",
    "habit": "잘 먹는 법에 대한 작은 이야기",
}
SUMMARY_CHARS = 120        # a card-length excerpt, never a paragraph
MIN_SUMMARY = 20
URLS = re.compile(r"(https?://\S+|www\.\S+|\S+@\S+\.\w+|#[^\s#]+)")


BOILERPLATE = re.compile(r"^(watch how to make (this|these)\b|jump to recipe\b|print recipe\b)", re.I)


def card_summary(text: str, title: str = "") -> str:
    """A short verbatim excerpt without links, addresses, hashtags, embed boilerplate or a repeat
    of the title; empty when too thin (the card then shows title and source only)."""
    cleaned = re.sub(r"\s+", " ", URLS.sub(" ", text or "")).strip(" -|·")
    stripped = BOILERPLATE.sub("", cleaned).strip()
    if stripped != cleaned and title and stripped.lower().startswith(title.lower()):
        stripped = stripped[len(title):].strip(" -|·:")     # "Watch How to Make This <title>" heading
    cleaned = stripped
    words = cleaned.split()
    for n in range(min(12, len(words) // 2), 1, -1):       # an embed heading repeated as the first sentence
        if [w.lower() for w in words[:n]] == [w.lower() for w in words[n:2 * n]]:
            cleaned = " ".join(words[n:])
            break
    short = excerpt(cleaned, SUMMARY_CHARS)
    return short if len(short) >= MIN_SUMMARY else ""


def public_item(row: dict) -> dict:
    item = {
        "title": row["title"],
        "summary": card_summary(row.get("sourceExcerpt") or "", row.get("title") or ""),
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
    return item


def eligible(rows: list[dict], recent: set[str], date: str = "") -> list[dict]:
    """Qualifying stories not already published: a story runs in one edition only (its
    selectedFor), so an old source is never recycled as fresh content day after day."""
    return sorted((r for r in rows if not r.get("duplicateOf") and not r.get("rejectionReason")
                   and r.get("assignedCategory") and r["candidateId"] not in recent
                   and r.get("canonicalUrl") not in recent
                   and (not r.get("selectedFor") or r.get("selectedFor") == date)),
                  key=lambda r: (-(r.get("score") or 0), r["candidateId"]))


def build(rows: list[dict], *, date: str, generated_at: str, recent: set[str]) -> tuple[dict, list[str]]:
    pool = eligible(rows, recent, date)
    with_image = [r for r in pool if r.get("imageValidated") and r.get("imageUrl")]
    featured_row: Optional[dict] = (with_image or pool or [None])[0]
    lanes, chosen = {}, []
    if featured_row is not None:
        chosen.append(featured_row["candidateId"])
    for lane in LANES:
        picked, per_source = [], {}
        for row in pool:
            if len(picked) >= LANE_SIZE:
                break
            if row["assignedCategory"] != lane or row["candidateId"] in chosen:
                continue
            key = row.get("sourceName") or row.get("sourceId")
            if per_source.get(key, 0) >= PER_SOURCE_PER_LANE:
                continue
            per_source[key] = per_source.get(key, 0) + 1
            picked.append(row)
            chosen.append(row["candidateId"])
        lanes[lane] = {"lead": LANE_LEADS[lane], "items": [public_item(r) for r in picked]}
    featured = None
    if featured_row is not None:
        featured = dict(public_item(featured_row), category=featured_row["assignedCategory"])
    edition = {"date": date, "generatedAt": generated_at, "schedule": "Daily 10:00 KST",
               "featured": featured, "lanes": lanes}
    return edition, chosen


def truthful(item: dict) -> bool:
    """What every stored edition must satisfy: a real source, a real http(s) URL, no desk."""
    url = (item or {}).get("url") or ""
    return (bool(item) and url.startswith(("http://", "https://")) and item.get("medium") != "desk"
            and item.get("source") not in ("", None, "밥도둑 데스크") and bool(item.get("title")))


def sanitize(edition: dict) -> tuple[dict, int]:
    """Past editions: drop fabricated desk items and link-only idea desks, and drop generated
    summaries/tags (the old builder composed them; their source text was never kept)."""
    removed = 0

    def clean(item):
        keep = {k: item[k] for k in ("title", "source", "url", "medium", "image", "category", "publishedAt",
                                     "discoveredAt", "sourceId", "candidateId", "imageSource", "summary") if k in item}
        if "candidateId" not in item:        # built before provenance existed: its summary was generated
            keep.pop("summary", None)
        return keep

    featured = edition.get("featured")
    if featured and not truthful(featured):
        edition["featured"], removed = None, removed + 1
    elif featured:
        edition["featured"] = clean(featured)
    for spec in (edition.get("lanes") or {}).values():
        items = spec.get("items") or []
        good = [clean(i) for i in items if truthful(i)]
        removed += len(items) - len(good)
        spec["items"] = good
    if "desks" in edition:
        removed += sum(len(v or []) for v in edition["desks"].values())
        del edition["desks"]
    return edition, removed
