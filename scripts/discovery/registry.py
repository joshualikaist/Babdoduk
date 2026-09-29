# -*- coding: utf-8 -*-
"""Canonical source registry: research/magazine/sources.json.

Each source is authored configuration (id, name, type, url or channel, enabled, trust tier,
categories, discovery method, queries) plus health that the pipeline maintains
(lastSuccessAt, lastFailureAt, failureCount, lastFailureCode, lastItemCount).

Trust tiers: A authoritative / original publisher, B established creator / food publication /
official brand, C discovery or community source. A Tier-C item is never published as factual
advice on its own (quality.py).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .common import atomic_write, dump_json, iso, read_json

TYPES = {"rss", "youtube_channel", "youtube_search", "web_search", "instagram"}
TIERS = {"A": 1.0, "B": 0.8, "C": 0.5}
HEALTH_FIELDS = ("lastAttemptAt", "lastSuccessAt", "lastFailureAt", "failureCount", "lastFailureCode", "lastItemCount")
LANES = ("tips", "trend", "health", "habit")


def load(path: Path) -> list[dict]:
    data = read_json(path, {"sources": []})
    sources = data.get("sources") if isinstance(data, dict) else None
    if not isinstance(sources, list):
        raise ValueError("source registry unreadable")
    return sources


def save(path: Path, sources: list[dict]) -> None:
    atomic_write(path, dump_json({"version": 1, "sources": sources}))


def enabled(sources: list[dict]) -> list[dict]:
    return [s for s in sources if s.get("enabled")]


def record(source: dict, *, ok: bool, now, code: Optional[str] = None, count: int = 0) -> None:
    source["lastAttemptAt"] = iso(now)
    source["lastItemCount"] = count
    if ok:
        source["lastSuccessAt"] = iso(now)
        source["failureCount"] = 0
        source["lastFailureCode"] = None
    else:
        source["lastFailureAt"] = iso(now)
        source["failureCount"] = int(source.get("failureCount") or 0) + 1
        source["lastFailureCode"] = code


def validate(sources: list[dict]) -> list[str]:
    errors, seen = [], set()
    for s in sources:
        sid = s.get("id")
        if not sid or sid in seen:
            errors.append(f"source id missing or duplicate: {sid!r}")
        seen.add(sid)
        if s.get("type") not in TYPES:
            errors.append(f"{sid}: unknown type {s.get('type')!r}")
        if s.get("trustTier") not in TIERS:
            errors.append(f"{sid}: trustTier must be A, B or C")
        if not set(s.get("categories") or []) <= set(LANES):
            errors.append(f"{sid}: unknown category")
        if not isinstance(s.get("enabled"), bool):
            errors.append(f"{sid}: enabled must be true/false")
        if s.get("type") in ("rss", "youtube_channel") and not (s.get("url") or s.get("channelId")):
            errors.append(f"{sid}: url or channelId required")
    return errors


def default_sources() -> list[dict]:
    """The sources the old hard-coded magazine used, plus the discovery routes of v1."""
    def src(**kw):
        base = {"enabled": True, "categories": [], "lastAttemptAt": None, "lastSuccessAt": None,
                "lastFailureAt": None, "failureCount": 0, "lastFailureCode": None, "lastItemCount": 0}
        base.update(kw)
        return base
    lane_queries = {
        "tips": ["요리 비법", "집밥 레시피", "자취 요리"],
        "trend": ["요즘 음식", "편의점 신상", "먹방 트렌드"],
        "health": ["건강한 한 끼"],
        "habit": ["식습관"],
    }
    return [
        src(id="blog-irisblossomlife", name="엄마표 집밥", type="rss", url="https://irisblossomlife.tistory.com/rss",
            trustTier="B", categories=["tips", "habit"], discoveryMethod="rss"),
        src(id="blog-koreanbapsang", name="Korean Bapsang", type="rss", url="https://www.koreanbapsang.com/feed/",
            trustTier="B", categories=["tips", "health"], discoveryMethod="rss"),
        src(id="blog-mykoreankitchen", name="My Korean Kitchen", type="rss", url="https://www.mykoreankitchen.com/feed/",
            trustTier="B", categories=["health", "habit"], discoveryMethod="rss"),
        src(id="blog-beyondkimchee", name="Beyond Kimchee", type="rss", url="https://www.beyondkimchee.com/feed/",
            trustTier="B", categories=["tips", "health"], discoveryMethod="rss"),
        src(id="blog-seonkyounglongest", name="Seonkyoung Longest", type="rss", url="https://seonkyounglongest.com/feed/",
            trustTier="B", categories=["tips", "trend"], discoveryMethod="rss"),
        src(id="blog-budgetbytes", name="Budget Bytes", type="rss", url="https://www.budgetbytes.com/feed/",
            trustTier="B", categories=["tips", "habit"], discoveryMethod="rss"),
        src(id="blog-justonecookbook", name="Just One Cookbook", type="rss", url="https://www.justonecookbook.com/feed/",
            trustTier="B", categories=["tips", "health"], discoveryMethod="rss"),
        src(id="yt-jachwiyorisin", name="자취요리신", type="youtube_channel", channelId="UCC9pQY_uaBSa0WOpMNJHbEQ",
            url="https://www.youtube.com/channel/UCC9pQY_uaBSa0WOpMNJHbEQ", trustTier="B", categories=["tips"],
            discoveryMethod="youtube_feed"),
        src(id="yt-cookingtree", name="쿠킹트리 Cooking tree", type="youtube_channel", channelId="UCtby6rJtBGgUm-2oD_E7bzw",
            url="https://www.youtube.com/channel/UCtby6rJtBGgUm-2oD_E7bzw", trustTier="B", categories=["tips"],
            discoveryMethod="youtube_feed"),
        src(id="yt-haruhankki", name="하루한끼", type="youtube_channel", channelId="UCPWFxcwPliEBMwJjmeFIDIg",
            url="https://www.youtube.com/channel/UCPWFxcwPliEBMwJjmeFIDIg", trustTier="B", categories=["health"],
            discoveryMethod="youtube_feed"),
        src(id="yt-hamzy", name="햄지 Hamzy", type="youtube_channel", channelId="UCPKNKldggioffXPkSmjs5lQ",
            url="https://www.youtube.com/channel/UCPKNKldggioffXPkSmjs5lQ", trustTier="B", categories=["trend"],
            discoveryMethod="youtube_feed"),
        src(id="yt-search", name="YouTube search", type="youtube_search", trustTier="C",
            categories=list(LANES), discoveryMethod="yt-dlp|youtube_api",
            queries=[q for qs in lane_queries.values() for q in qs]),
        src(id="web-exa", name="Web search (Exa)", type="web_search", trustTier="C", categories=list(LANES),
            discoveryMethod="exa", queries=[q for qs in lane_queries.values() for q in qs]),
        src(id="web-naver-blog", name="Naver Blog (via web search)", type="web_search", trustTier="C",
            categories=["tips", "trend"], discoveryMethod="exa",
            queries=["site:blog.naver.com 자취 요리 레시피", "site:blog.naver.com 편의점 신상"]),
        src(id="instagram-opencli", name="Instagram (OpenCLI, local only)", type="instagram", enabled=False,
            trustTier="C", categories=["trend"], discoveryMethod="opencli"),
    ]
