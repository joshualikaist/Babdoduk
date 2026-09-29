# -*- coding: utf-8 -*-
"""Build the daily magazine edition (data/magazine/{date}.json) from real, source-backed stories.

    python scripts/refresh_magazine.py                 # discover, then build today's edition
    python scripts/refresh_magazine.py --discover-only # discovery into the candidate store only
    python scripts/refresh_magazine.py --sanitize-only # clean stored editions, no network

Pipeline (scripts/discovery/, docs/MAGAZINE_DISCOVERY.md): source registry -> adapters ->
candidate store (research/magazine/) -> normalize -> dedup -> quality filter -> category ->
rank -> editorial selection -> public snapshot.

There is no fallback text. A story needs a real source, a real URL, the source's own title and
retrieved source text; its summary is a verbatim excerpt of that text. When sources are down or
thin, the edition is smaller. Every run also sanitizes stored editions, so fabricated items of
the old builder disappear from the archive the next time this runs.
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from discovery import pipeline, select  # noqa: E402
from discovery.common import atomic_write, dump_json, iso, now_kst, read_json  # noqa: E402

OUT = ROOT / "data" / "magazine"
EDITION_HOUR = 10


def edition_date(now: datetime) -> str:
    return (now if now.hour >= EDITION_HOUR else now - timedelta(days=1)).strftime("%Y-%m-%d")


def dated_files(out: Path) -> list[Path]:
    return sorted(p for p in out.glob("20*.json") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.stem))


def story_count(edition: dict) -> int:
    return int(bool(edition.get("featured"))) + sum(len(s.get("items") or []) for s in (edition.get("lanes") or {}).values())


def sanitize_all(out: Path, *, skip: str = "") -> int:
    removed = 0
    for path in dated_files(out):
        if path.stem == skip:
            continue
        edition = read_json(path, None)
        if not isinstance(edition, dict):
            continue
        had_desks = "desks" in edition
        cleaned, n = select.sanitize(edition)
        if n or had_desks:
            atomic_write(path, dump_json(cleaned))
        removed += n
    return removed


def write_index(out: Path) -> str:
    dates = sorted((p.stem for p in dated_files(out) if story_count(read_json(p, {})) > 0), reverse=True)
    latest = dates[0] if dates else ""
    atomic_write(out / "index.json", dump_json({"latest": latest, "dates": dates}))
    if latest:
        atomic_write(out / "latest.json", (out / f"{latest}.json").read_text(encoding="utf-8"))
    return latest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build the daily magazine from source-backed stories.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--discover-only", action="store_true")
    mode.add_argument("--sanitize-only", action="store_true")
    args = parser.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    if args.sanitize_only:
        print(f"magazine sanitized: removed {sanitize_all(OUT)} fabricated or link-less items")
        print(f"latest {write_index(OUT)}")
        return 0
    now = now_kst()
    paths = pipeline.Paths(ROOT)
    run = pipeline.discover(paths, now)
    edition, chosen = None, []
    if not args.discover_only:
        date = edition_date(now)
        edition, chosen = select.build(run["store"].all(), date=date, generated_at=iso(now),
                                       recent=pipeline.recent_keys(OUT, date))
        written = bool(story_count(edition))
        if written:
            atomic_write(OUT / f"{date}.json", dump_json(edition))
            print(f"magazine {date}: {story_count(edition)} source-backed stories "
                  f"(featured image: {'yes' if (edition.get('featured') or {}).get('image') else 'no'})")
        else:
            print(f"[warn] magazine {date}: no qualifying story; the previous edition stays latest")
            chosen = []
        removed = sanitize_all(OUT, skip=date if written else "")
        print(f"magazine archive: removed {removed} fabricated or link-less items")
        print(f"latest {write_index(OUT)}")
    report = pipeline.finish(paths, run, edition, chosen, now)
    summary = report["summary"]
    print(f"discovery: candidates={summary['candidates']} new={summary['new']} duplicates={summary['duplicates']} "
          f"rejected={summary['rejected']} selected={summary['selected']} failing={len(summary['failing'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
