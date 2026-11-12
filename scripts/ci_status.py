"""The GitHub check results of one commit (the repository is public, so no login is needed).

    python scripts/ci_status.py <commit>          print each check once
    python scripts/ci_status.py <commit> --wait   wait (up to 20 minutes) until every check has finished

Exit 0 when every finished check passed, 1 when one failed, 2 when checks are still running or none exist
yet. `visual-guardian` fails while a shared-chrome change waits for the owner's baseline approval
(docs/VISUAL_BASELINES.md); it is reported like any other check, never hidden.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = "joshualikaist/Babdoduk"


def check_runs(sha):
    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/commits/{sha}/check-runs?per_page=100",
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": "babdoduk-ci-status"})
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.load(res).get("check_runs", [])


def summarize(runs):
    latest = {}
    for run in runs:   # the newest run of each check name
        if run["name"] not in latest or run["started_at"] > latest[run["name"]]["started_at"]:
            latest[run["name"]] = run
    return sorted((name, r["status"], r.get("conclusion")) for name, r in latest.items())


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("commit", nargs="?", default="HEAD")
    parser.add_argument("--wait", action="store_true")
    args = parser.parse_args(argv)
    sha = subprocess.run(["git", "rev-parse", args.commit], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    deadline = time.time() + 20 * 60
    while True:
        rows = summarize(check_runs(sha))
        pending = [r for r in rows if r[1] != "completed"]
        if not args.wait or (rows and not pending) or time.time() > deadline:
            break
        time.sleep(30)
    print(f"commit {sha[:7]}")
    for name, status, conclusion in rows:
        print(f"  {name:28s} {conclusion if status == 'completed' else status}")
    if not rows or pending:
        return 2
    return 1 if any(c not in ("success", "skipped", "neutral") for _, _, c in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
