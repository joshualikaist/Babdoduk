# -*- coding: utf-8 -*-
"""Build the daily magazine edition (data/magazine/{date}.json) from real, source-backed stories.

    python scripts/refresh_magazine.py                 # discover, then build today's edition
    python scripts/refresh_magazine.py --discover-only # discovery into the candidate store only
    python scripts/refresh_magazine.py --sanitize-only # clean stored editions, no network
    python scripts/refresh_magazine.py --if-missing    # a scheduled run: only if today's edition is missing

Pipeline (scripts/discovery/, docs/MAGAZINE_DISCOVERY.md): source registry -> adapters ->
candidate store (research/magazine/) -> normalize -> dedup -> quality filter -> category ->
rank -> editorial selection -> public snapshot.

There is no fallback text. A story needs a real source, a real URL, the source's own title and
retrieved source text; its card sentence is one verbatim sentence of the publisher's own preview
(discovery.preview reads it for a web search result). When sources are down or thin, a lane is
published with what it has and the run announces it (announce). Every run also sanitizes stored
editions, so fabricated items of the old builder and the stories of a withdrawn source disappear
from the archive the next time this runs.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import date as day, datetime, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from discovery import pipeline, preview, registry, select  # noqa: E402
from discovery.common import HostPacer, atomic_write, dump_json, fetch, iso, now_kst, read_json  # noqa: E402

OUT = ROOT / "data" / "magazine"
EDITION_HOUR = 10


def edition_date(now: datetime) -> str:
    return (now if now.hour >= EDITION_HOUR else now - timedelta(days=1)).strftime("%Y-%m-%d")


def dated_files(out: Path) -> list[Path]:
    return sorted(p for p in out.glob("20*.json") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.stem))


def story_count(edition: dict) -> int:
    return int(bool(edition.get("featured"))) + sum(len(s.get("items") or []) for s in (edition.get("lanes") or {}).values())


def archive_rules() -> dict:
    """The registry's publishing rules the archive follows too (select.sanitize): sources whose
    owners asked to leave, and sources shown by title, source, date and link only."""
    sources = registry.load()
    return {"withdrawn": frozenset(s["id"] for s in sources if s.get("withdrawn")),
            "quiet": frozenset(s["id"] for s in sources if s.get("excerpt") is False)}


def sanitize_all(out: Path, *, skip: str = "", rules: Optional[dict] = None, today: str = "") -> int:
    """Clean every stored edition but `skip`; a file is rewritten only when cleaning changed it. An
    edition more than select.YOUTUBE_ARCHIVE_DAYS before `today` loses its YouTube videos."""
    removed = 0
    for path in dated_files(out):
        if path.stem == skip:
            continue
        edition = read_json(path, None)
        if not isinstance(edition, dict):
            continue
        before = dump_json(edition)
        old = bool(today) and (day.fromisoformat(today) - day.fromisoformat(path.stem)).days > select.YOUTUBE_ARCHIVE_DAYS
        cleaned, n = select.sanitize(edition, youtube_expired=old, **(rules or {}))
        if dump_json(cleaned) != before:
            atomic_write(path, dump_json(cleaned))
        removed += n
    return removed


def write_index(out: Path) -> str:
    """index.json names the newest edition with stories; the pages read that edition directly.
    The old latest.json copy of it had no reader and is removed (the publisher then removes it
    from lab and main too)."""
    dates = sorted((p.stem for p in dated_files(out) if story_count(read_json(p, {})) > 0), reverse=True)
    latest = dates[0] if dates else ""
    atomic_write(out / "index.json", dump_json({"schemaVersion": 1, "latest": latest, "dates": dates}))
    (out / "latest.json").unlink(missing_ok=True)
    return latest


def announce(edition: Optional[dict], env=os.environ, out=print) -> list[str]:
    """A lane short of select.LANE_SIZE is published with what it has, never filled with anything
    made up, and announced (magazine sourcing plan, decision 9): a line in the run log, a warning
    on the GitHub Actions run page and a lane table in the job summary."""
    fill, short = pipeline.lane_fill(edition)
    lines = [f"lane {lane}: {fill[lane]} of {select.LANE_SIZE} stories" for lane in short]
    actions = env.get("GITHUB_ACTIONS") == "true"
    for line in lines:
        out(f"::warning title=Magazine lane short::{edition['date']} {line}" if actions
            else f"[warn] magazine {edition['date']} {line}")
    if actions and env.get("GITHUB_STEP_SUMMARY") and fill:
        table = "".join(f"| {lane} | {n} of {select.LANE_SIZE} |\n" for lane, n in fill.items())
        with open(env["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as handle:
            handle.write(f"### Magazine {edition['date']}\n\n| Lane | Stories |\n| --- | --- |\n{table}\n")
    return lines


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build the daily magazine from source-backed stories.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--discover-only", action="store_true")
    mode.add_argument("--sanitize-only", action="store_true")
    mode.add_argument("--select-only", action="store_true",
                      help="rebuild today's edition from the stored candidates, without the network")
    parser.add_argument("--if-missing", action="store_true",
                        help="do nothing when today's edition is already built: the scheduled runs, so the first "
                             "one that starts publishes the edition and the later ones are backups")
    parser.add_argument("--skip-type", action="append", default=[], metavar="TYPE",
                        help="do not contact sources of this type in this run (recorded as SKIPPED_CLOUD_PARITY), "
                             "e.g. youtube_channel for a build that matches what GitHub's runners can reach")
    args = parser.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    if args.if_missing:
        date = edition_date(now_kst())
        built = read_json(OUT / f"{date}.json", None)
        if isinstance(built, dict) and story_count(built):
            print(f"magazine {date}: already built; nothing to do")
            return 0
    rules = archive_rules()
    if args.sanitize_only:
        removed = sanitize_all(OUT, rules=rules, today=edition_date(now_kst()))
        print(f"magazine sanitized: removed {removed} fabricated, link-less "
              f"or withdrawn items")
        print(f"latest {write_index(OUT)}")
        return 0
    now = now_kst()
    paths = pipeline.Paths(ROOT)
    if args.select_only:
        # Offline: re-judge the stored candidates under the current rules and rebuild today's
        # edition. Nothing is fetched or searched, and no stored candidate is dropped.
        run = pipeline.reprocess(paths, now)
        date = edition_date(now)
        rows = pipeline.runnable(run["store"].all(), registry.load(paths.registry))
        edition, chosen = select.build(rows, date=date, generated_at=iso(now),
                                       recent=pipeline.recent_keys(OUT, date))
        if not story_count(edition):
            print(f"[warn] magazine {date}: no qualifying story in the store")
            return 0
        atomic_write(OUT / f"{date}.json", dump_json(edition))
        pipeline.record_offline(paths, run, edition, chosen, now)
        print(f"magazine {date}: {story_count(edition)} stories selected from the store (no network)")
        print(f"magazine archive: removed {sanitize_all(OUT, skip=date, rules=rules, today=date)} fabricated, "
              f"link-less or withdrawn items")
        print(f"latest {write_index(OUT)}")
        announce(edition)
        return 0
    run = pipeline.discover(paths, now, skip_types=tuple(args.skip_type))
    edition, chosen = None, []
    if not args.discover_only:
        date = edition_date(now)
        rows = pipeline.runnable(run["store"].all(), run["sources"])
        edition, chosen = select.build(rows, date=date, generated_at=iso(now),
                                       recent=pipeline.recent_keys(OUT, date))
        preview.fill(edition, {r["candidateId"]: r for r in rows}, HostPacer(fetch))
        written = bool(story_count(edition))
        if written:
            atomic_write(OUT / f"{date}.json", dump_json(edition))
            print(f"magazine {date}: {story_count(edition)} source-backed stories "
                  f"(featured image: {'yes' if (edition.get('featured') or {}).get('image') else 'no'})")
        else:
            print(f"[warn] magazine {date}: no qualifying story; the previous edition stays latest")
            chosen = []
        removed = sanitize_all(OUT, skip=date if written else "", rules=rules, today=date)
        print(f"magazine archive: removed {removed} fabricated, link-less or withdrawn items")
        print(f"latest {write_index(OUT)}")
    report = pipeline.finish(paths, run, edition, chosen, now)
    summary = report["summary"]
    print(f"discovery: candidates={summary['candidates']} new={summary['new']} duplicates={summary['duplicates']} "
          f"rejected={summary['rejected']} selected={summary['selected']} failing={len(summary['failing'])}")
    if edition and story_count(edition):
        announce(edition)
    return 0


if __name__ == "__main__":
    sys.exit(main())
