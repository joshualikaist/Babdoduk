# -*- coding: utf-8 -*-
"""Copy generated data onto lab and main without merging feature code."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {
    "data/magazine": ROOT / "data" / "magazine",
    "data/kaist-menu": ROOT / "data" / "kaist-menu",
    "data/ggongbab": ROOT / "data" / "ggongbab",
}
# Files inside an allowed path that are hand-edited inputs, never generated output.
SKIP_NAMES = {"manual.json", ".staging"}


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd or ROOT, check=False, text=True, capture_output=True)


def must(cmd: list[str], cwd: Path | None = None) -> None:
    res = run(cmd, cwd)
    if res.returncode != 0:
        sys.stderr.write(res.stdout + res.stderr)
        raise SystemExit(res.returncode)


def copy_allowed(src_root: Path, dest_root: Path, paths: list[str]) -> None:
    """Mirror generated files; hand-edited inputs (SKIP_NAMES) on the target are left untouched."""
    for rel in paths:
        src = src_root / rel
        dest = dest_root / rel
        if not src.exists():
            continue
        dest.mkdir(parents=True, exist_ok=True)
        wanted = set()
        for file in src.rglob("*"):
            if any(part in SKIP_NAMES for part in file.relative_to(src).parts):
                continue
            target = dest / file.relative_to(src)
            wanted.add(target)
            if file.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file, target)
        for file in sorted(dest.rglob("*"), reverse=True):
            if file in wanted or any(part in SKIP_NAMES for part in file.relative_to(dest).parts):
                continue
            if file.is_dir():
                if not any(file.iterdir()):
                    file.rmdir()
            else:
                file.unlink()


def update_branch(branch: str, artifact: Path, paths: list[str], message: str) -> None:
    work = Path(tempfile.mkdtemp(prefix=f"bbd-{branch}-"))
    try:
        must(["git", "fetch", "origin", branch])
        must(["git", "worktree", "add", "--detach", str(work), f"origin/{branch}"])
        copy_allowed(artifact, work, paths)
        add_args = ["git", "add", "--"] + paths
        must(add_args, work)
        status = run(["git", "status", "--porcelain"], work)
        if not status.stdout.strip():
            print(f"{branch}: no generated-data changes")
            return
        must(["git", "config", "user.name", "babdoduk-content-bot"], work)
        must(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], work)
        must(["git", "commit", "-m", message], work)
        rebase = run(["git", "pull", "--rebase", "origin", branch], work)
        if rebase.returncode != 0:
            run(["git", "rebase", "--abort"], work)
            sys.stderr.write(rebase.stdout + rebase.stderr)
            raise SystemExit(f"rebase conflict on {branch}; leaving production data unchanged")
        push = run(["git", "push", "origin", f"HEAD:{branch}"], work)
        if push.returncode != 0:
            sys.stderr.write(push.stdout + push.stderr)
            raise SystemExit(f"push to {branch} failed")
        print(f"{branch}: pushed generated data")
    finally:
        run(["git", "worktree", "remove", "--force", str(work)])
        shutil.rmtree(work, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paths", nargs="+", default=["data/magazine"])
    parser.add_argument("--message", required=True)
    args = parser.parse_args()
    for rel in args.paths:
        if rel not in ALLOWED:
            raise SystemExit(f"refusing path {rel}")
    artifact = Path(tempfile.mkdtemp(prefix="bbd-artifact-"))
    copy_allowed(ROOT, artifact, args.paths)
    try:
        for branch in ("lab", "main"):
            update_branch(branch, artifact, args.paths, args.message)
    finally:
        shutil.rmtree(artifact, ignore_errors=True)


if __name__ == "__main__":
    main()
