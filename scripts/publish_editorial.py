#!/usr/bin/env python3
"""Publish only authenticated, scheduled editorial entries. Never promote lab source code.

prepare creates isolated main/lab candidates and writes their paths to GITHUB_OUTPUT. The workflow
checks both candidates, then finish verifies the exact checked SHAs and pushes both refs atomically.
No force, reset, rebase, generated-data copying, live collectors or browser credentials.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
QUEUE = "inputs/editorial/schedule.json"
RECEIPTS = "inputs/editorial/published.json"
EVENTS = "data/content/events.json"
ALLOWED = {EVENTS, RECEIPTS, "event.html"}


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def validate_queue(data: dict, root: Path = ROOT) -> None:
    # The same validator the web API uses. stdin is data, never executable code or a shell argument.
    check = subprocess.run(["node", "-e", "const fs=require('node:fs');require('./lib/editorial.cjs').validateQueue(JSON.parse(fs.readFileSync(0,'utf8')));"],
                           input=json.dumps(data), text=True, cwd=root, capture_output=True)
    if check.returncode:
        raise ValueError("Invalid editorial queue (values suppressed)")


def decode_queue(data: dict) -> dict:
    result = subprocess.run(["node", "-e", "const fs=require('node:fs');const d=require('./lib/editorial.cjs').decodeQueue(JSON.parse(fs.readFileSync(0,'utf8')),process.env.EDITORIAL_QUEUE_KEY);process.stdout.write(JSON.stringify(d));"],
                            input=json.dumps(data), text=True, cwd=ROOT, capture_output=True)
    if result.returncode:
        raise ValueError("Queue decryption failed (values suppressed); check EDITORIAL_QUEUE_KEY")
    return json.loads(result.stdout)


def plan(queue: dict, receipts: dict, events: dict, now: datetime) -> tuple[dict, dict, list[str]]:
    if now.tzinfo is None:
        raise ValueError("Publication clock needs a timezone")
    if receipts.get("schemaVersion") != 1 or not isinstance(receipts.get("items"), list):
        raise ValueError("Invalid publication receipts")
    known = {}
    for entry in receipts["items"]:
        if set(entry) != {"id", "digest", "publishedAt"} or entry["id"] in known:
            raise ValueError("Invalid publication receipt")
        known[entry["id"]] = entry["digest"]
    result = json.loads(json.dumps(events))
    history = json.loads(json.dumps(receipts))
    due = []
    for item in queue["items"]:
        fingerprint = digest(item)
        if item["id"] in known:
            if known[item["id"]] != fingerprint:
                raise ValueError("A published entry was changed; review required")
            continue
        if item["status"] != "scheduled" or datetime.fromisoformat(item["publishAt"]) > now:
            continue
        bucket = "notices" if item["kind"] == "notice" else "activities"
        if item["content"] not in result[bucket]:
            result[bucket].append(item["content"])
        history["items"].append({"id": item["id"], "digest": fingerprint,
                                  "publishedAt": now.astimezone(timezone.utc).isoformat()})
        due.append(item["id"])
    return result, history, due


def git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def load_ref(ref: str, path: str, fallback=None):
    result = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=ROOT, text=True, capture_output=True)
    if result.returncode:
        if fallback is not None:
            return fallback
        raise ValueError(f"Missing {path} on {ref}")
    return json.loads(result.stdout)


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prepare(now: datetime, state: Path) -> dict:
    git("fetch", "origin", "main", "lab")
    base_main, base_lab = git("rev-parse", "origin/main"), git("rev-parse", "origin/lab")
    queue = decode_queue(load_ref(base_lab, QUEUE))
    validate_queue(queue)
    events, receipts, due = plan(queue, load_ref(base_main, RECEIPTS, {"schemaVersion": 1, "items": []}),
                                 load_ref(base_main, EVENTS), now)
    if not due:
        return {"due": "false"}
    # Always isolated from the runner checkout. These worktrees belong to this run only.
    directory = Path(tempfile.mkdtemp(prefix="editorial-", dir=state.parent))
    main, lab = directory / "main", directory / "lab"
    git("worktree", "add", "--detach", str(main), base_main)
    write_json(main / EVENTS, events)
    write_json(main / RECEIPTS, receipts)
    subprocess.run([sys.executable, "scripts/validate_content.py", "--only", "authored"], cwd=main, check=True)
    subprocess.run([sys.executable, "scripts/sync_site_chrome.py"], cwd=main, check=True)
    changed = set(git("diff", "--name-only", cwd=main).splitlines())
    # Include the new receipt file if this is the first publication.
    changed |= set(git("ls-files", "--others", "--exclude-standard", cwd=main).splitlines())
    if not changed <= ALLOWED:
        raise ValueError("Editorial publication touched a path outside its allowlist")
    git("diff", "--check", cwd=main)
    git("add", "--", *sorted(changed), cwd=main)
    git("-c", "user.name=babdoduk-editorial-bot", "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com",
        "commit", "-m", "content(editorial): publish scheduled news and events", "-m",
        "Approved by the owner in the authenticated lab publication queue.\n\nAgent: Editorial publisher", cwd=main)
    main_sha = git("rev-parse", "HEAD", cwd=main)
    git("worktree", "add", "--detach", str(lab), base_lab)
    # A normal back-sync preserves experiments. A conflict fails before either remote changes.
    git("-c", "user.name=babdoduk-editorial-bot", "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com",
        "merge", "--no-ff", main_sha, "-m", "Merge published editorial content back into lab\n\nAgent: Editorial publisher", cwd=lab)
    result = {"due": "true", "main_dir": str(main), "lab_dir": str(lab), "base_main": base_main,
              "base_lab": base_lab, "main_sha": main_sha, "lab_sha": git("rev-parse", "HEAD", cwd=lab),
              "queue_sha": git("rev-parse", f"{base_lab}:{QUEUE}"), "count": len(due)}
    write_json(state, result)
    return result


def probe(now: datetime) -> dict:
    """Cheap read-only check before installing browser/test dependencies on every cron tick."""
    git("fetch", "origin", "main", "lab")
    queue = decode_queue(load_ref("origin/lab", QUEUE))
    _, _, due = plan(queue, load_ref("origin/main", RECEIPTS, {"schemaVersion": 1, "items": []}),
                     load_ref("origin/main", EVENTS), now)
    return {"due": "true" if due else "false"}


def finish(state: Path) -> None:
    data = json.loads(state.read_text())
    for name in ("main", "lab"):
        tree = Path(data[f"{name}_dir"])
        if git("rev-parse", "HEAD", cwd=tree) != data[f"{name}_sha"] or git("status", "--porcelain", cwd=tree):
            raise ValueError("Checked candidate changed")
    git("fetch", "origin", "main", "lab")
    for name in ("main", "lab"):
        if git("rev-parse", f"origin/{name}") != data[f"base_{name}"]:
            raise ValueError("Remote moved; no push. The next scheduled run rebuilds from latest refs.")
    # Atomic CAS for both refs. Includes main and lab baselines, so deletion/cancellation in the
    # queue and bot/source pushes during validation cannot be silently overwritten.
    git("push", "--atomic", "origin", f"{data['main_sha']}:refs/heads/main", f"{data['lab_sha']}:refs/heads/lab")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("probe", "prepare", "finish"))
    parser.add_argument("--state", type=Path, default=ROOT / ".local" / "editorial-state.json")
    args = parser.parse_args()
    args.state.parent.mkdir(parents=True, exist_ok=True)
    if args.mode == "finish":
        finish(args.state)
    else:
        result = probe(datetime.now(timezone.utc)) if args.mode == "probe" else prepare(datetime.now(timezone.utc), args.state.resolve())
        print(json.dumps(result))
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
                for key, value in result.items():
                    output.write(f"{key}={value}\n")


if __name__ == "__main__":
    main()
