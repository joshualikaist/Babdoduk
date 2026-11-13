"""Babdoduk's checks in one command, as fast as they safely go (owner 2026-11-12: "뭐 하나 수정할때마다 코드
점검하는 시간이 너무 오래 걸리는 것 같아"; .claude/skills/verify-babdoduk/SKILL.md).

    python scripts/check_all.py --quick   before pushing to lab (about 1 to 2 minutes)
    python scripts/check_all.py           the five gates, before a production release (about 5 minutes)

Quick: shared chrome in sync, content valid, every test except the full site-UI run, on parallel workers.
After the push, GitHub's tests workflow runs the whole suite including the site-UI run
(scripts/ci_status.py reads its result). Full: the same, plus the site-UI run (its groups side by side,
scripts/check_site_ui.py) and the food-hub UI checker. Every stage runs even after a failure, and each
stage's first result is printed, never a rerun.

The chrome screenshot comparison is skipped unless --visual is given: its baselines exist for the pinned
CI container and the owner's Windows PC, not for this Linux PC, and ui-guardian compares them in CI
(docs/VISUAL_BASELINES.md). That is the same setting the tests workflow uses.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE_UI_TEST = "tests/test_site_ui.py::test_all_public_pages_windows_scrollbars_and_overflow"


def workers():
    if importlib.util.find_spec("xdist") is None:
        return []
    return ["-n", str(min(8, max(2, (os.cpu_count() or 4) - 2)))]


def stages(quick):
    py = sys.executable
    out = [
        ("chrome sync", [py, "scripts/sync_site_chrome.py", "--check"]),
        ("content", [py, "scripts/validate_content.py"]),
        ("tests", [py, "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider", *workers(), "--deselect", SITE_UI_TEST]),
    ]
    if not quick:
        out += [
            ("site UI", [py, "-m", "pytest", SITE_UI_TEST, "-q", "-p", "no:cacheprovider"]),
            ("food hub UI", [py, "scripts/check_ggongbab_ui.py"]),
        ]
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--quick", action="store_true", help="before a lab push: no site-UI or food-hub browser run")
    parser.add_argument("--visual", action="store_true", help="also compare the chrome screenshots (needs this platform's baselines)")
    args = parser.parse_args(argv)
    env = dict(os.environ)
    if not args.visual:
        env["BABDODUK_CHROME_VISUAL"] = "skip"
    results = []
    began = time.time()
    for name, cmd in stages(args.quick):
        start = time.time()
        proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
        took = time.time() - start
        tail = (proc.stdout + proc.stderr).strip().splitlines()
        results.append((name, proc.returncode, took))
        mark = "ok" if proc.returncode == 0 else f"FAILED (exit {proc.returncode})"
        print(f"{name:12s} {mark:18s} {took:5.0f}s", flush=True)
        if proc.returncode:
            print("\n".join("    " + line for line in tail[-25:]), flush=True)
    failed = [name for name, code, _ in results if code]
    print(f"{'total':12s} {'FAILED: ' + ', '.join(failed) if failed else 'all passed':18s} {time.time() - began:5.0f}s")
    if args.quick and not failed:
        print("the full suite with the site-UI run follows on GitHub after the push: python scripts/ci_status.py <commit>")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
