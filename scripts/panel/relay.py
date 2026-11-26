#!/usr/bin/env python3
"""Publish a sanitized panel timeline for the lab page, without commits or deployments.

Uses a dedicated Storage bucket, provisioned once with --setup (owner approved 2026-11-26).
No SQL, collectors, authentication, Telegram or paid model runs are performed here.
Run with the ops .env: python scripts/panel/relay.py --env-file ~/Babdoduk-ops/.env
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import live
from panel_storage import PanelStorage, StorageError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ggongbab.config import _load_dotenv, load_settings

# Narration is public, but raw tool arguments and absolute source paths never are.
PRIVATE = re.compile(r"https?://\S+|(?:/[\w.~-]+){2,}[^\s]*|[A-Za-z]:[\\/][^\s]+|"
                     r"[\w.+-]+@[\w.-]+\.[a-z]{2,}|(?:sk-|sb_secret_|eyJ)[A-Za-z0-9_.-]+", re.I)
SECRET = re.compile(r"password|credential|authorization|bearer|api[_ -]?key|access[_ -]?token|"
                    r"secret|JSESSIONID|비밀번호|인증번호|암호", re.I)


def public_text(text: str) -> str:
    if SECRET.search(text):
        return "작업 내용을 확인하고 있어요."
    return PRIVATE.sub("[비공개]", text)[:400]


def snapshot(run: Path, state_dir: Path | None = None) -> dict:
    data = live.build(run, live=True)
    files = [run / 'journal.jsonl', *run.glob('agent-*.jsonl')]
    updated = max(p.stat().st_mtime for p in files if p.is_file())
    body = {
        'updatedAt': datetime.fromtimestamp(updated, timezone.utc).isoformat(timespec='milliseconds'),
        'timeline': {
            'run': hashlib.sha256(str(run.resolve()).encode()).hexdigest()[:16],
            'complete': bool(data.get('complete')),
            'end': data['end'],
            'panes': live.PANES,
            'phases': data['phases'],
            'events': [{**e, 'text': public_text(e['text'])} for e in data['events']],
        },
    }
    if state_dir:
        try:
            state = json.loads((state_dir / 'status.json').read_text())
            if state.get('code') == 'rate_limit':
                retry = datetime.fromisoformat(state['retryAt'])
                if retry.tzinfo is not None:
                    body['status'] = {'code': 'rate_limit', 'retryAt': retry.isoformat()}
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            pass
    return body


def publish(client, body: dict) -> None:
    if len(body['timeline']['events']) > 10000 or len(json.dumps(body).encode()) > 2_000_000:
        raise ValueError('panel snapshot exceeds publication limit')
    client.publish(body)


def main(argv=None) -> int:
    # The daemon is Linux-only; keep the pure snapshot helpers importable by Windows UI tests.
    import fcntl

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--run', type=Path)
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--setup', action='store_true')
    parser.add_argument('--state-dir', type=Path, default=Path.home() / 'Babdoduk-ops/.local/panel-auto')
    args = parser.parse_args(argv)
    if args.env_file:
        _load_dotenv(args.env_file)
    settings = load_settings()
    if not settings.has_supabase:
        print('Panel relay: backend configuration missing', file=sys.stderr)
        return 21
    client = PanelStorage(settings.supabase_url, settings.supabase_secret_key)
    if args.setup:
        client.setup()
        print('Panel storage configured')
        return 0
    args.state_dir.mkdir(parents=True, exist_ok=True)
    lock = (args.state_dir / 'relay.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print('Panel relay is already running', file=sys.stderr)
        return 2
    previous = None
    while True:
        try:
            run = args.run or live.newest_run()
            if run:
                body = snapshot(run, args.state_dir)
                digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
                if digest != previous:
                    publish(client, body)
                    previous = digest
                    print(f"Panel relay: published {len(body['timeline']['events'])} events", flush=True)
            elif args.once:
                print('Panel relay: no panel run found', file=sys.stderr)
                return 2
        except (OSError, ValueError, StorageError):
            # Backend error bodies can include private details. Never log them.
            print('Panel relay: publication unavailable; retrying', file=sys.stderr, flush=True)
            if args.once:
                return 23
        if args.once:
            return 0
        time.sleep(5)


if __name__ == '__main__':
    sys.exit(main())
