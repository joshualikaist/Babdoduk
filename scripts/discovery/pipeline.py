# -*- coding: utf-8 -*-
"""One discovery run: registry -> adapters -> candidate store -> process -> images -> selection,
plus the health report and the run log. A broken source means fewer stories and a health
warning, never filler."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from . import adapters, images, process, registry, select
from .common import atomic_write, dump_json, fetch, iso, read_json
from .store import CandidateStore

RUN_LOG_LINES = 400


class Paths:
    """research/magazine is the internal store: committed by the content bot so it persists across
    GitHub Actions runs, and excluded from the website by .vercelignore."""

    def __init__(self, root: Path, registry_path: Optional[Path] = None):
        self.registry = Path(registry_path) if registry_path else registry.REGISTRY
        self.research = Path(root) / "research" / "magazine"
        self.source_health = self.research / "source-health.json"
        self.candidates = self.research / "candidates.jsonl"
        self.health = self.research / "health.json"
        self.runs = self.research / "runs.jsonl"


def discover(paths: Paths, now: datetime, *, fetcher: Callable = fetch, env=os.environ,
             validate=images.image_ok, log=print, skip_types: tuple = ()) -> dict:
    """Collect from every enabled source into the candidate store, then process it.

    skip_types: source types not contacted in this run (an explicit operator choice, for example
    a cloud-parity build on a machine that can reach what GitHub's runners cannot). A skipped
    source is recorded as DEGRADED with SKIPPED_CLOUD_PARITY, never as a success."""
    sources = registry.load(paths.registry)
    source_health = registry.load_health(paths.source_health)
    store = CandidateStore(paths.candidates)
    health, queries, new = {}, [], 0
    for source in sources:
        entry = source_health.setdefault(source["id"], {})
        if not source.get("enabled"):
            health[source["id"]] = {"type": source["type"], "adapter": "DISABLED", "code": None, "items": 0}
            continue
        if source["type"] in skip_types:
            entry["lastAttemptAt"], entry["lastFailureCode"], entry["lastItemCount"] = iso(now), "SKIPPED_CLOUD_PARITY", 0
            health[source["id"]] = {"type": source["type"], "adapter": "SKIPPED", "code": "SKIPPED_CLOUD_PARITY", "items": 0}
            log(f"discovery {source['id']}: SKIPPED_CLOUD_PARITY")
            continue
        result = adapters.run(source, fetcher=fetcher, env=env)
        ok = result.status == adapters.OK
        if result.status != adapters.NOT_CONFIGURED:
            registry.record(entry, ok=ok, now=now, code=result.code or None, count=len(result.items))
        before = len(store.rows)
        for raw in result.items:
            row = process.normalize(raw, source, now)
            if row and row["sourceUrl"]:
                store.upsert(row, now)
        new += len(store.rows) - before
        for query in result.queries:
            queries.append({"sourceId": source["id"], "query": query})
        health[source["id"]] = {"type": source["type"], "adapter": result.status, "code": result.code or None,
                                "items": len(result.items)}
        log(f"discovery {source['id']}: {result.status}{' ' + result.code if result.code else ''} items={len(result.items)}")
    rows = store.all()
    newest: dict[str, str] = {}
    for row in rows:
        stamp = row.get("publishedAt") or ""
        if stamp > newest.get(row.get("sourceId"), ""):
            newest[row.get("sourceId")] = stamp
    for source in sources:
        entry = source_health[source["id"]]
        if newest.get(source["id"]):
            entry["newestItemAt"] = newest[source["id"]]
        entry["status"] = registry.status(source, entry, now)
        health[source["id"]].update({k: entry.get(k) for k in ("status", "lastSuccessAt", "lastFailureAt",
                                                                "failureCount", "newestItemAt")})
    for row in rows:                           # recompute decisions each run from the stored facts
        if not row.get("selected"):
            row["duplicateOf"] = None
            row["rejectionReason"] = None
    counts = process.process(rows, now)
    image_counts = images.enrich(rows, fetcher, validate=validate)
    for row in rows:
        if not row.get("duplicateOf") and not row.get("rejectionReason"):
            process.score(row, now)
    return {"sources": sources, "sourceHealth": source_health, "store": store, "health": health, "queries": queries,
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
        store.mark_selected(chosen, now, (edition or {}).get("date"))
    pruned = store.prune(now)
    store.save()
    registry.save_health(paths.source_health, run["sourceHealth"])
    enabled = [s for s in run["sources"] if s.get("enabled")]
    failing = sorted(sid for sid, h in run["health"].items() if h["adapter"] in (adapters.FETCH_FAILED, adapters.PARSE_FAILED))
    by_status = {name: sorted(sid for sid, h in run["health"].items() if h.get("status") == name) for name in registry.STATUSES}
    stale = by_status["STALE"]
    report = {
        "generatedAt": iso(now),
        "adapters": run["health"],
        "summary": {"enabledSources": len(enabled), "failing": failing,
                    "notConfigured": sorted(sid for sid, h in run["health"].items() if h["adapter"] == adapters.NOT_CONFIGURED),
                    "statusCounts": {name: len(ids) for name, ids in by_status.items()}, "byStatus": by_status,
                    **run["counts"], "pruned": pruned,
                    "selected": len(chosen), "fabricated": 0, "staleSources": stale},
        "warnings": [f"{sid}: {run['health'][sid]['code']}" for sid in failing]
                    + [f"{sid}: SOURCE_STALE (newest item older than {registry.STALE_DAYS} days)" for sid in stale]
                    + [f"{sid}: {run['health'][sid]['code']}" for sid in by_status["DEGRADED"] if sid not in failing],
    }
    atomic_write(paths.health, dump_json(report))
    line = json.dumps({"runAt": iso(now), "queries": run["queries"], "counts": report["summary"],
                       "edition": (edition or {}).get("date")}, ensure_ascii=False, sort_keys=True)
    lines = paths.runs.read_text(encoding="utf-8").splitlines() if paths.runs.exists() else []
    atomic_write(paths.runs, "\n".join((lines + [line])[-RUN_LOG_LINES:]) + "\n")
    return report
