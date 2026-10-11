# -*- coding: utf-8 -*-
"""Persistent candidate store: research/magazine/candidates.jsonl (one JSON object per line).

It is the research record, separate from the daily public edition. It holds public source
metadata only: title, canonical URL, a short verbatim source excerpt, image URL, discovery
method, query and lane, trend/habit evidence with verbatim detail, source trust, audience
relevance, hashes, scores and the selection/rejection decision. Never cookies, tokens, session
data or private URLs.

Bounded by prune(), after every network run. A row stays whole while it can still change a
decision: a qualifying story (the pool); a story that passed the hard rules while it can still
corroborate a new story or be corroborated by one (evidence.corroborate: dated, food, published
within TREND_MAX_DAYS) and was seen or selected within LIVE_DAYS; and the day's edition, for a
rebuild. Every other row is compact: FINGERPRINT only (who, where from, when, what was decided),
and for a published story also its dedup keys (ANCHOR), so a copy of it under another URL is still
a duplicate. A compact row keeps its decision and is not judged again until an adapter returns the
item again, which rebuilds it from the source.
- A published story is never dropped by the cap. Its compact row is kept ANCHOR_DAYS after its
  edition; after that the editions themselves keep it from running again (pipeline.recent_keys).
- An unpublished compact row is dropped FINGERPRINT_DAYS after it was last seen and a whole one
  RETAIN_DAYS after, and the unpublished rows never exceed MAX_CANDIDATES (oldest last-seen first).
Measured 2026-10-11 (scratch simulation of the next run on the committed store): 8.0 MB and 4,000
rows, 3,654 of them rejected, and the cap had already evicted 2 published stories. These rules
make it 2.6 MB and change no decision; a LIVE_DAYS of 7 would have cost 18 stories their
corroboration, 3 would have cost 28.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from .common import atomic_write, canonical_url, iso, parse_time, sha
from .evidence import TREND_MAX_DAYS, is_food

RETAIN_DAYS = 90
MAX_CANDIDATES = 4000
LIVE_DAYS = 14
FINGERPRINT_DAYS = 7                 # 92% of re-sightings came within a week (2026-10-11)
ANCHOR_DAYS = 30
FINGERPRINT = ("candidateId", "sourceId", "sourceUrl", "title", "discoveryMethod", "discoveryQuery", "discoveryLane",
               "discoveredAt", "discoveredSeq", "lastSeenAt", "rejectionReason", "duplicateOf")
ANCHOR = FINGERPRINT + ("canonicalUrl", "canonicalHash", "sourceItemId", "contentHash", "publishedAt",
                        "assignedCategory", "selected", "selectedAt", "selectedFor")
# What a compact row keeps when an adapter returns its item again and it is rebuilt.
HISTORY = ("discoveredAt", "discoveredSeq", "selected", "selectedAt", "selectedFor")
FIELDS = ("candidateId", "sourceId", "sourceName", "sourceType", "sourceUrl", "canonicalUrl", "title",
          "sourceExcerpt", "publishedAt", "discoveredAt", "lastSeenAt", "imageUrl", "imageSource",
          "imageValidated", "categoryHints", "assignedCategory", "discoveryQuery", "discoveryMethod",
          "contentHash", "canonicalHash", "sourceItemId", "duplicateOf", "qualityScore", "freshnessScore",
          "sourceScore", "relevanceScore", "score", "selected", "selectedAt", "rejectionReason", "medium",
          "trustTier", "seenVia", "textLength", "discoveredSeq", "selectedFor",
          # provenance and evidence (owner decision, 2026-09-29)
          "discoveryLane", "seenQueries", "searchRank", "sourceTrust", "contentKind", "publishedAtSource",
          "trendSignals", "trendEvidence", "trendEvidenceDetail", "corroboratedBy", "habitSignals",
          "audienceRelevance", "audienceScore", "laneDecisions", "viewCount", "likeCount", "requireFood",
          "commercePage", "sponsored", "howToMarkers", "trendEvidenceIndependent")
MAX_QUERIES = 8


def candidate_id(url: str) -> str:
    return "c_" + sha(canonical_url(url), 16)


def days_since(value, now: datetime) -> float:
    """Days from a stored timestamp to now; 0 when it is missing, so a row is never dropped or
    compacted for lack of a date."""
    when = parse_time(value)
    return (now - when).total_seconds() / 86400 if when else 0.0


def can_corroborate(row: dict, now: datetime) -> bool:
    """Whether evidence.corroborate can still pair this row with another story. Its age only
    grows, so once this is false it stays false until the item is seen again."""
    published = parse_time(row.get("publishedAt"))
    return bool(published) and (now - published).days <= TREND_MAX_DAYS and \
        is_food(row.get("title") or "", row.get("sourceExcerpt") or "")


def stays_whole(row: dict, now: datetime) -> bool:
    """Whether a row can still change a decision, so every field is kept (module docstring)."""
    if row.get("selected"):
        selected = row.get("selectedAt") or row.get("lastSeenAt")
        if days_since(selected, now) <= 1:
            return True                                # a rebuild of its edition needs it whole
        recent = min(days_since(row.get("lastSeenAt"), now), days_since(selected, now)) <= LIVE_DAYS
        return recent and can_corroborate(row, now)
    if row.get("duplicateOf"):
        return False
    reason = row.get("rejectionReason")
    if reason is None:
        return True                                    # qualifying: tomorrow's edition can still run it
    # Only the lane rules are left to pass, and a corroborating story can still make it a trend.
    return reason == "NO_QUALIFYING_LANE" and days_since(row.get("lastSeenAt"), now) <= LIVE_DAYS and \
        can_corroborate(row, now)


def compact(row: dict) -> dict:
    """The row as kept once it can no longer change: a new dict, so a run's rows stay whole."""
    fields = ANCHOR if row.get("selected") else FINGERPRINT
    out = {k: row[k] for k in fields if row.get(k) is not None}
    out["compact"] = True
    return out


def expired(row: dict, now: datetime) -> bool:
    if row.get("selected"):
        return bool(row.get("compact")) and days_since(row.get("selectedAt") or row.get("lastSeenAt"), now) > ANCHOR_DAYS
    limit = FINGERPRINT_DAYS if row.get("compact") else RETAIN_DAYS
    return days_since(row.get("lastSeenAt"), now) > limit


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
        history = {k: row[k] for k in HISTORY if k in row} if row is not None and row.get("compact") else None
        if row is None or history is not None:
            row = {k: raw.get(k) for k in FIELDS if k in raw}
            seq = 1 + max((int(r.get("discoveredSeq") or 0) for r in self.rows.values()), default=0)
            row.update(candidateId=cid, discoveredAt=iso(now), lastSeenAt=iso(now), selected=False,
                       selectedAt=None, duplicateOf=None, rejectionReason=None, seenVia=[route],
                       discoveredSeq=seq, seenQueries=[raw["discoveryQuery"]] if raw.get("discoveryQuery") else [])
            # A compact row seen again is rebuilt whole from this sighting and judged again; it
            # keeps when it was first discovered and whether it already ran.
            row.update(history or {})
            self.rows[cid] = row
            return row
        row["lastSeenAt"] = iso(now)
        if route not in (row.get("seenVia") or []):
            row["seenVia"] = (row.get("seenVia") or []) + [route]
        query = raw.get("discoveryQuery")
        if query and query not in (row.get("seenQueries") or []):
            row["seenQueries"] = ((row.get("seenQueries") or []) + [query])[-MAX_QUERIES:]
        for key in ("title", "sourceExcerpt", "publishedAt", "publishedAtSource", "imageUrl", "imageSource",
                    "imageValidated", "contentHash", "discoveryLane", "discoveryQuery", "sourceTrust", "contentKind",
                    "requireFood"):
            if raw.get(key) and not row.get(key):
                row[key] = raw[key]
        # The first route re-reading the same text (or more) refreshes what is derived from it -
        # evidence, kind, tier, a cleaned title - so a rule change applies. Another route only adds
        # evidence and never rewrites the first discovery's title, source, tier or kind.
        first_route = (row.get("seenVia") or [route])[0] == route
        refresh = first_route and (raw.get("textLength") or 0) >= (row.get("textLength") or 0)
        if refresh:
            row["textLength"] = raw.get("textLength") or 0
            row["sourceExcerpt"] = raw.get("sourceExcerpt") or row.get("sourceExcerpt")
            for key in ("medium", "contentKind", "sourceTrust", "trustTier", "requireFood", "sponsored", "title",
                        "publishedAtSource", "trendSignals", "habitSignals", "audienceRelevance", "howToMarkers"):
                if raw.get(key) is not None:
                    row[key] = raw[key]
        else:
            signals = dict(row.get("trendSignals") or {})
            for kind, value in (raw.get("trendSignals") or {}).items():
                if kind not in signals or kind == "engagement":
                    signals[kind] = value
            row["trendSignals"] = signals
            new_score = (raw.get("audienceRelevance") or {}).get("score") or 0
            if new_score > ((row.get("audienceRelevance") or {}).get("score") or 0):
                row["audienceRelevance"] = raw["audienceRelevance"]
        for key in ("viewCount", "likeCount"):
            if isinstance(raw.get(key), int):
                row[key] = raw[key]
        return row

    def all(self) -> list[dict]:
        return list(self.rows.values())

    def prune(self, now) -> int:
        """Compact the rows that can no longer change a decision and drop the ones that can no
        longer matter (module docstring). Returns the number of rows dropped."""
        rows = [r if r.get("compact") or stays_whole(r, now) else compact(r) for r in self.rows.values()]
        rows = [r for r in rows if not expired(r, now)]
        published = [r for r in rows if r.get("selected")]
        others = sorted((r for r in rows if not r.get("selected")), key=lambda r: r.get("lastSeenAt") or "",
                        reverse=True)[:MAX_CANDIDATES]
        removed = len(self.rows) - len(published) - len(others)
        self.rows = {r["candidateId"]: r for r in published + others}
        return removed

    def save(self) -> None:
        ordered = sorted(self.rows.values(), key=lambda r: (int(r.get("discoveredSeq") or 0), r["candidateId"]))
        atomic_write(self.path, "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in ordered))

    def mark_selected(self, ids: Iterable[str], now, edition: Optional[str]) -> None:
        """A story is published once: selectedFor is the edition that first ran it. Rebuilding the
        same edition releases what an earlier build of that date chose but this one did not."""
        ids = list(ids)
        if edition:
            for row in self.rows.values():
                if row.get("selectedFor") == edition and row["candidateId"] not in ids:
                    row.update(selected=False, selectedAt=None, selectedFor=None)
        for cid in ids:
            if cid in self.rows:
                row = self.rows[cid]
                row["selected"] = True
                row["selectedAt"] = row.get("selectedAt") or iso(now)
                row["selectedFor"] = row.get("selectedFor") or edition
