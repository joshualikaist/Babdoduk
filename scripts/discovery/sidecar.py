# -*- coding: utf-8 -*-
"""Local discovery sidecar (operator PC only): discovery, never publication.

Runs the registry's enabled localOnly sources - YouTube channel feeds and YouTube search through
yt-dlp (metadata only, --skip-download) - and writes each source's findings to
research/magazine/inbox/<sourceId>.json. That is all it writes. It does not touch the
candidate store, source health, data/magazine or git: the normal pipeline
(scripts/refresh_magazine.py) reads the inbox as one more source and applies the same rules to
every candidate, and only that pipeline produces the public edition.

    python scripts/magazine_local_discovery.py

yt-dlp is found through BABDODUK_YTDLP_BIN or PATH (pinned: yt-dlp 2026.8.19). No cookies,
browser profiles or accounts are used; a sign-in or bot check simply ends that query.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime

from . import registry
from .adapters import NOT_CONFIGURED, AdapterResult, inbox, youtube
from .adapters.web import expand
from .common import fetch

YTDLP_PIN = "2026.8.19"


def run(paths, now: datetime, *, fetcher=fetch, runner=subprocess.run, env=os.environ, which=shutil.which,
        log=print) -> dict:
    report = {}
    for source in registry.load(paths.registry):
        if not (source.get("enabled") and source.get("localOnly")):
            continue
        binary = env.get("BABDODUK_YTDLP_BIN") or which("yt-dlp")
        if source["type"] == "youtube_channel":
            result, tool = youtube.discover_channel(source, fetcher=fetcher), "youtube_feed"
            if result.status != "OK" and binary:          # the Atom feed answers 404 (2026-09-29)
                result, tool = youtube.ytdlp_channel(source, runner, binary), f"yt-dlp {YTDLP_PIN}"
        elif source["type"] == "youtube_search":
            queries = [expand(q, now) for q in source.get("queries") or []]
            result = (youtube.ytdlp_search(queries, runner, binary, lane=source.get("lane")) if binary
                      else AdapterResult(NOT_CONFIGURED, code="YTDLP_NOT_INSTALLED"))
            tool = f"yt-dlp {YTDLP_PIN}"
        else:
            result, tool = AdapterResult(NOT_CONFIGURED, code="LOCAL_TYPE_UNSUPPORTED"), ""
        if result.items or result.status != NOT_CONFIGURED:
            inbox.write(paths.inbox, source, result, now, tool)
        report[source["id"]] = {"status": result.status, "code": result.code or None, "items": len(result.items),
                                "queries": len(result.queries)}
        log(f"local discovery {source['id']}: {result.status}{' ' + result.code if result.code else ''} "
            f"items={len(result.items)}")
    return report
