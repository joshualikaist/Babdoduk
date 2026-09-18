# -*- coding: utf-8 -*-
"""Manual input collector: data/ggongbab/manual.json.

Entries are written by hand when automatic collection misses something. They
go through the same parser -> validator -> dedup -> exporter path as mail.

Format (list under "items"):
{
  "items": [
    {
      "id": "2026-09-25-samsung-lunch-talk",     # stable id; changing text re-parses
      "title": "삼성전자 Tech Lunch Talk",
      "text": "9월 25일 12시 N1 101호에서 ... 참석자에게 점심 도시락을 제공합니다.",
      "url": "https://...",                       # optional public link
      "date": "2026-09-19"                        # optional: when the notice was posted
    }
  ]
}
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..config import KST, Settings
from ..models import RawItem
from .base import Collector, CollectorError


class ManualCollector(Collector):
    source_type = "manual"
    name = "Manual"

    def __init__(self, settings: Settings, path: Optional[Path] = None):
        self.path = path or settings.manual_path

    def enabled(self) -> bool:
        return self.path.exists()

    def collect(self) -> list[RawItem]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CollectorError(f"manual.json unreadable: {exc}") from exc
        items: list[RawItem] = []
        for entry in data.get("items") or []:
            ext_id = str(entry.get("id") or "").strip()
            text = str(entry.get("text") or "").strip()
            if not ext_id or not text:
                continue
            posted = None
            if entry.get("date"):
                try:
                    posted = datetime.fromisoformat(str(entry["date"])).replace(tzinfo=KST)
                except ValueError:
                    posted = None
            items.append(RawItem(
                source_type="manual",
                external_id=ext_id,
                subject=str(entry.get("title") or "").strip(),
                raw_text=text,
                source_url=str(entry.get("url") or "").strip(),
                source_created_at=posted or datetime.now(KST),
                metadata={"manual": True},
            ))
        return items
