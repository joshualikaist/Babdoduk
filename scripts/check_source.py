# -*- coding: utf-8 -*-
"""Check a magazine source before it is registered (docs/MAGAZINE_SOURCES.md, CONTRIBUTING.md).

    python scripts/check_source.py news-hidoc-healthylife       # registered sources, by id
    python scripts/check_source.py --file proposal.json         # proposed entries: one object or a list

For each source: the registry rules (registry.validate: the fields and the publishing rules),
robots.txt for the feed address, then one read of the feed through the pipeline's own adapter,
with every item judged by the pipeline's own rules as of now. It prints the items read, the newest
date, how many qualify for each lane and the main reasons the others do not. Requests to one site
are two seconds apart. Nothing is written. Exit status 1 when a source breaks a rule, robots.txt
does not allow its feed, or the feed cannot be read.

Only rss sources are read here; a search or YouTube source is checked against the rules only.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from discovery import process, registry  # noqa: E402
from discovery.adapters import OK, rss  # noqa: E402
from discovery.common import HostPacer, fetch, iso, now_kst  # noqa: E402
from discovery.preview import Robots  # noqa: E402


def check(source: dict, *, fetcher, robots: Robots, now: datetime) -> tuple[bool, list[str]]:
    """(passes, report lines) for one source entry."""
    errors = registry.validate([source])
    lines = [f"{source.get('id')} ({source.get('name') or '-'})"] + [f"  rule: {e}" for e in errors]
    if source.get("type") != "rss" or not source.get("url"):
        return not errors, lines + ["  feed: not read here (only rss sources are)"]
    if not robots.allowed(source["url"]):
        return False, lines + ["  robots.txt: does not allow this feed, or could not be read"]
    result = rss.discover(source, fetcher=fetcher)
    if result.status != OK:
        return False, lines + [f"  feed: {result.status} {result.code or ''}".rstrip()]
    rows = []
    for n, item in enumerate(result.items, 1):
        row = process.normalize(item, source, now)
        if row:
            row.update(candidateId=f"{source.get('id')}_{n}", discoveredSeq=n, discoveredAt=iso(now))
            rows.append(row)
    process.process(rows, now)
    qualifying = collections.Counter(r["assignedCategory"] for r in rows
                                     if r.get("assignedCategory") and not r.get("rejectionReason"))
    reasons = collections.Counter(r.get("rejectionReason") or "DUPLICATE" for r in rows
                                  if r.get("rejectionReason") or r.get("duplicateOf"))
    dates = sorted((r.get("publishedAt") or "")[:10] for r in rows if r.get("publishedAt"))
    lines += [f"  robots.txt: allows the feed; feed: {len(rows)} items, newest {dates[-1] if dates else '-'}",
              "  qualifying: " + ", ".join(f"{lane} {qualifying.get(lane, 0)}" for lane in registry.LANES),
              "  not qualifying: " + (", ".join(f"{k} {v}" for k, v in reasons.most_common(4)) or "none")]
    return not errors, lines


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Check magazine sources against the rules and their feeds.")
    parser.add_argument("ids", nargs="*", help="registered source ids")
    parser.add_argument("--file", type=Path, help="a JSON file with one proposed entry or a list of them")
    args = parser.parse_args(argv)
    sources = []
    if args.file:
        data = json.loads(args.file.read_text(encoding="utf-8"))
        sources += data if isinstance(data, list) else [data]
    if args.ids:
        known = {s["id"]: s for s in registry.load()}
        missing = [sid for sid in args.ids if sid not in known]
        if missing:
            print(f"not in the registry: {', '.join(missing)}")
            return 1
        sources += [known[sid] for sid in args.ids]
    if not sources:
        parser.error("name registered source ids or --file")
    fetcher = HostPacer(fetch)
    robots, now, passed = Robots(fetcher), now_kst(), True
    for source in sources:
        ok, lines = check(source, fetcher=fetcher, robots=robots, now=now)
        passed = passed and ok
        print("\n".join(lines))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
