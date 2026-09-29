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
        self.inbox = self.research / "inbox"          # written only by the local sidecar


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
    throttled: set[str] = set()                # a type that answered 429 is not asked again this run
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
        if source["type"] in throttled:
            result = adapters.AdapterResult(adapters.FETCH_FAILED, code="RATE_LIMITED_SKIPPED")
        else:
            result = adapters.run(source, fetcher=fetcher, env=env, inbox_dir=paths.inbox, now=now)
        if result.code == "HTTP_429":
            throttled.add(source["type"])
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
    reset_decisions(rows)                      # recompute decisions each run from the stored facts
    counts = process.process(rows, now)
    image_counts = images.enrich(rows, fetcher, validate=validate)
    for row in rows:
        if not row.get("duplicateOf") and not row.get("rejectionReason"):
            process.score(row, now)
    return {"sources": sources, "sourceHealth": source_health, "store": store, "health": health, "queries": queries,
            "counts": dict(counts, new=new, candidates=len(rows), **image_counts), "lanes": lane_report(rows)}


def pending_work(sources: list[dict]) -> list[str]:
    """Known post-launch work recorded in every health report."""
    local_youtube = any(s.get("enabled") and s.get("localOnly") and str(s.get("type", "")).startswith("youtube")
                        for s in sources)
    return ["YOUTUBE_AUTOMATION_PENDING"] if local_youtube else []


def reset_decisions(rows: list[dict]) -> None:
    for row in rows:
        if not row.get("selected"):
            row["duplicateOf"] = None
            row["rejectionReason"] = None
            row["assignedCategory"] = None


def reprocess(paths: Paths, now: datetime) -> dict:
    """Re-judge every stored candidate under the current rules, without the network: nothing is
    fetched, searched or deleted, so a rule change or an unreachable route never loses a
    candidate that was already discovered."""
    store = CandidateStore(paths.candidates)
    rows = store.all()
    reset_decisions(rows)
    counts = process.process(rows, now)
    return {"store": store, "counts": dict(counts, candidates=len(rows)), "lanes": lane_report(rows)}


def record_offline(paths: Paths, run: dict, edition: Optional[dict], chosen: list[str], now: datetime) -> dict:
    """An offline rebuild keeps the last network run's adapter health and records its own lane
    counts and a run-log line (mode "offline")."""
    store: CandidateStore = run["store"]
    store.mark_selected(chosen, now, (edition or {}).get("date"))
    store.save()
    report = read_json(paths.health, {}) or {}
    report.setdefault("summary", {}).update(run["counts"], selected=len(chosen), fabricated=0,
                                            offlineRebuildAt=iso(now))
    report["lanes"] = run["lanes"]
    report["pending"] = pending_work(registry.load(paths.registry))
    atomic_write(paths.health, dump_json(report))
    line = json.dumps({"runAt": iso(now), "mode": "offline", "queries": [], "counts": report["summary"],
                       "edition": (edition or {}).get("date")}, ensure_ascii=False, sort_keys=True)
    lines = paths.runs.read_text(encoding="utf-8").splitlines() if paths.runs.exists() else []
    atomic_write(paths.runs, "\n".join((lines + [line])[-RUN_LOG_LINES:]) + "\n")
    return report


def lane_report(rows: list[dict]) -> dict:
    """Per lane: qualifying unique candidates (not duplicates, not rejected, assigned there),
    and why the rows discovered for that lane did not qualify, so an empty lane is explained."""
    report = {}
    for lane in select.LANES:
        qualifying = [r for r in rows if r.get("assignedCategory") == lane and not r.get("duplicateOf")
                      and not r.get("rejectionReason")]
        asked = [r for r in rows if r.get("discoveryLane") == lane]
        reasons: dict[str, int] = {}
        for row in asked:
            if row.get("duplicateOf"):
                key = "DUPLICATE"
            elif row.get("rejectionReason") and row["rejectionReason"] != "NO_QUALIFYING_LANE":
                key = row["rejectionReason"]
            elif row.get("assignedCategory") == lane:
                continue
            else:
                other = (row.get("assignedCategory") or "").upper()
                key = (row.get("laneDecisions") or {}).get(lane) or f"ASSIGNED_{other}"
            reasons[key] = reasons.get(key, 0) + 1
        report[lane] = {"qualifying": len(qualifying), "discoveredForLane": len(asked),
                        "notQualifying": dict(sorted(reasons.items()))}
    return report


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
        "lanes": run.get("lanes") or {},
        "pending": pending_work(run["sources"]),
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
