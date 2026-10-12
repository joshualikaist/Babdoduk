# -*- coding: utf-8 -*-
"""The labels the pipeline and the pages share: data/content/labels.json (docs/DATA.md).

The pages receive them through scripts/sync_site_chrome.py, which writes them into each page's
translation tables and into the scripts that need them; the pipeline reads them here. One
place, so a food type, a source, a cafeteria or a magazine lane is named the same everywhere.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

LABELS = Path(__file__).resolve().parents[1] / "data" / "content" / "labels.json"


@lru_cache(maxsize=None)
def labels() -> dict:
    return json.loads(LABELS.read_text(encoding="utf-8"))


def source_data_names() -> dict[str, str]:
    """The name a free-food event's source carries in the public data (sources[].name)."""
    return {kind: spec["dataName"] for kind, spec in labels()["sources"].items()}


def source_news_names() -> dict[str, str]:
    """The name a campus news item's source carries (data/ggongbab/news.json)."""
    return {kind: spec["newsName"] for kind, spec in labels()["sources"].items() if "newsName" in spec}


def restaurants() -> list[dict]:
    """The KAIST cafeterias, in the order the menu shows them."""
    return [dict(row) for row in labels()["restaurants"]]


def lane_leads() -> dict[str, str]:
    """The Korean lead line of each magazine lane, as an edition stores it."""
    return {lane: spec["lead"]["ko"] for lane, spec in labels()["magazineLanes"].items()}
