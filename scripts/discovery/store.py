# -*- coding: utf-8 -*-
"""Persistent candidate store: research/magazine/candidates.jsonl (one JSON object per line).

It is the research record, separate from the daily public edition. It holds public source
metadata only: title, canonical URL, a short verbatim source excerpt, image URL, discovery
method and query, hashes, scores and the selection/rejection decision. Never cookies, tokens,
session data or private URLs. Bounded: a candidate not seen for RETAIN_DAYS is dropped, and the
file never exceeds MAX_CANDIDATES (oldest last-seen first).
"""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Iterable, Optional

from .common import atomic_write, canonical_url, iso, parse_time, sha

RETAIN_DAYS = 90
MAX_CANDIDATES = 4000
FIELDS = ("candidateId", "sourceId", "sourceName", "sourceType", "sourceUrl", "canonicalUrl", "title",
          "sourceExcerpt", "publishedAt", "discoveredAt", "lastSeenAt", "imageUrl", "imageSource",
          "imageValidated", "categoryHints", "assignedCategory", "discoveryQuery", "discoveryMethod",
          "contentHash", "canonicalHash", "sourceItemId", "duplicateOf", "qualityScore", "freshnessScore",
          "sourceScore", "relevanceScore", "score", "selected", "selectedAt", "rejectionReason", "medium",
          "trustTier", "seenVia", "textLength", "discoveredSeq")


def candidate_id(url: str) -> str:
    return "c_" + sha(canonical_url(url), 16)


class CandidateStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.rows: dict[str, dict] = {}
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and row.get("candidateId"):
                    self.rows[row["candidateId"]] = row

    def upsert(self, raw: dict, now) -> dict:
        """Insert a normalized discovery or refresh last-seen on a known one. First discovery
        wins for discoveredAt/discoveryQuery; every route that saw it is kept in seenVia."""
        cid = candidate_id(raw["sourceUrl"])
        row = self.rows.get(cid)
        route = f"{raw.get('discoveryMethod')}:{raw.get('sourceId')}"
        if row is None:
            row = {k: raw.get(k) for k in FIELDS if k in raw}
            seq = 1 + max((int(r.get("discoveredSeq") or 0) for r in self.rows.values()), default=0)
            row.update(candidateId=cid, discoveredAt=iso(now), lastSeenAt=iso(now), selected=False,
                       selectedAt=None, duplicateOf=None, rejectionReason=None, seenVia=[route],
                       discoveredSeq=seq)
            self.rows[cid] = row
            return row
        row["lastSeenAt"] = iso(now)
        if route not in (row.get("seenVia") or []):
            row["seenVia"] = (row.get("seenVia") or []) + [route]
        for key in ("title", "sourceExcerpt", "publishedAt", "imageUrl", "imageSource", "imageValidated", "contentHash",
                    "textLength"):
            if raw.get(key) and not row.get(key):
                row[key] = raw[key]
        return row

    def all(self) -> list[dict]:
        return list(self.rows.values())

    def prune(self, now) -> int:
        cutoff = now - timedelta(days=RETAIN_DAYS)
        keep = {cid: r for cid, r in self.rows.items()
                if (parse_time(r.get("lastSeenAt")) or now) >= cutoff or r.get("selected")}
        ordered = sorted(keep.values(), key=lambda r: r.get("lastSeenAt") or "", reverse=True)[:MAX_CANDIDATES]
        removed = len(self.rows) - len(ordered)
        self.rows = {r["candidateId"]: r for r in ordered}
        return removed

    def save(self) -> None:
        ordered = sorted(self.rows.values(), key=lambda r: (int(r.get("discoveredSeq") or 0), r["candidateId"]))
        atomic_write(self.path, "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in ordered))

    def mark_selected(self, ids: Iterable[str], now) -> None:
        for cid in ids:
            if cid in self.rows:
                self.rows[cid]["selected"] = True
                self.rows[cid]["selectedAt"] = self.rows[cid].get("selectedAt") or iso(now)

    def get(self, cid: str) -> Optional[dict]:
        return self.rows.get(cid)
