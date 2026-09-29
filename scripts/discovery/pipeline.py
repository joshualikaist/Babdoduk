# -*- coding: utf-8 -*-
"""One discovery run: registry -> adapters -> candidate store -> process -> images -> selection,
plus the health report and the run log. A broken source means fewer stories and a health
warning, never filler."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from . import adapters, images, process, registry, select
from .common import atomic_write, dump_json, fetch, iso, read_json
from .store import CandidateStore

RUN_LOG_LINES = 400
STALE_SOURCE_DAYS = 120


class Paths:
    def __init__(self, root: Path):
        self.research = Path(root) / "research" / "magazine"
        self.sources = self.research / "sources.json"
        self.candidates = self.research / "candidates.jsonl"
        self.health = self.research / "health.json"
        self.runs = self.research / "runs.jsonl"


def discover(paths: Paths, now: datetime, *, fetcher: Callable = fetch, env=os.environ,
             validate=images.image_ok, log=print) -> dict:
    """Collect from every enabled source into the candidate store, then process it."""
    sources = registry.load(paths.sources) if paths.sources.exists() else registry.default_sources()
    store = CandidateStore(paths.candidates)
    health, queries, new = {}, [], 0
    for source in sources:
        if not source.get("enabled"):
            health[source["id"]] = {"type": source["type"], "status": "DISABLED", "code": None,
                                    "items": 0, "lastSuccessAt": source.get("lastSuccessAt")}
            continue
        result = adapters.run(source, fetcher=fetcher, env=env)
        ok = result.status == adapters.OK
        if result.status != adapters.NOT_CONFIGURED:
            registry.record(source, ok=ok, now=now, code=result.code or None, count=len(result.items))
        before = len(store.rows)
        for raw in result.items:
            row = process.normalize(raw, source, now)
            if row and row["sourceUrl"]:
                store.upsert(row, now)
        new += len(store.rows) - before
        for query in result.queries:
            queries.append({"sourceId": source["id"], "query": query})
        health[source["id"]] = {"type": source["type"], "status": result.status, "code": result.code or None,
                                "items": len(result.items), "lastSuccessAt": source.get("lastSuccessAt"),
                                "failureCount": source.get("failureCount", 0)}
        log(f"discovery {source['id']}: {result.status}{' ' + result.code if result.code else ''} items={len(result.items)}")
    rows = store.all()
    newest: dict[str, str] = {}
    for row in rows:
        stamp = row.get("publishedAt") or ""
        if stamp > newest.get(row.get("sourceId"), ""):
            newest[row.get("sourceId")] = stamp
    for sid, entry in health.items():
        entry["newestItemAt"] = newest.get(sid)
    for row in rows:                           # recompute decisions each run from the stored facts
        if not row.get("selected"):
            row["duplicateOf"] = None
            row["rejectionReason"] = None
    counts = process.process(rows, now)
    image_counts = images.enrich(rows, fetcher, validate=validate)
    for row in rows:
        if not row.get("duplicateOf") and not row.get("rejectionReason"):
            process.score(row, now)
    return {"sources": sources, "store": store, "health": health, "queries": queries,
            "counts": dict(counts, new=new, candidates=len(rows), **image_counts)}


def recent_keys(out: Path, before: str, days: int = 7) -> set[str]:
    """Candidates and URLs already published in the last editions, so the same story does not
    run again the next morning."""
    keys: set[str] = set()
    for path in sorted(out.glob("20*.json"), reverse=True):
        if path.stem >= before:
            continue
        edition = read_json(path, {})
        items = [edition.get("featured") or {}] + [i for s in (edition.get("lanes") or {}).values() for i in s.get("items") or []]
        for item in items:
            for key in (item.get("candidateId"), item.get("url")):
                if key:
                    keys.add(key)
        days -= 1
        if days <= 0:
            break
    from .common import canonical_url
    return keys | {canonical_url(k) for k in keys if k.startswith("http")}


def finish(paths: Paths, run: dict, edition: Optional[dict], chosen: list[str], now: datetime) -> dict:
    """Persist registry health, the candidate store, the health report and the run log."""
    store: CandidateStore = run["store"]
    if chosen:
        store.mark_selected(chosen, now)
    pruned = store.prune(now)
    store.save()
    registry.save(paths.sources, run["sources"])
    enabled = [s for s in run["sources"] if s.get("enabled")]
    failing = [sid for sid, h in run["health"].items() if h["status"] in (adapters.FETCH_FAILED, adapters.PARSE_FAILED)]
    stale_before = iso(now - timedelta(days=STALE_SOURCE_DAYS))
    stale = sorted(sid for sid, h in run["health"].items()
                   if h["status"] == adapters.OK and (h.get("newestItemAt") or "") < stale_before)
    report = {
        "generatedAt": iso(now),
        "adapters": run["health"],
        "summary": {"enabledSources": len(enabled), "failing": failing,
                    "notConfigured": sorted(sid for sid, h in run["health"].items() if h["status"] == adapters.NOT_CONFIGURED),
                    **run["counts"], "pruned": pruned,
                    "selected": len(chosen), "fabricated": 0, "staleSources": stale},
        "warnings": [f"{sid}: {run['health'][sid]['code']}" for sid in failing]
                    + [f"{sid}: SOURCE_STALE (newest item older than {STALE_SOURCE_DAYS} days)" for sid in stale],
    }
    atomic_write(paths.health, dump_json(report))
    line = json.dumps({"runAt": iso(now), "queries": run["queries"], "counts": report["summary"],
                       "edition": (edition or {}).get("date")}, ensure_ascii=False, sort_keys=True)
    lines = paths.runs.read_text(encoding="utf-8").splitlines() if paths.runs.exists() else []
    atomic_write(paths.runs, "\n".join((lines + [line])[-RUN_LOG_LINES:]) + "\n")
    return report
