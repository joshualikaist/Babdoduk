#!/usr/bin/env python3
"""Publish a sanitized panel timeline for the lab page, without commits or deployments.

Requires the reviewed SQL proposal in docs/proposals/panel-live.sql to be applied first.
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ggongbab.config import _load_dotenv, load_settings
from ggongbab.db.supabase_client import SupabaseClient, SupabaseError

# Narration is public, but raw tool arguments and absolute source paths never are.
PRIVATE = re.compile(r"https?://\S+|(?:/[\w.~-]+){2,}[^\s]*|[A-Za-z]:[\\/][^\s]+|"
                     r"[\w.+-]+@[\w.-]+\.[a-z]{2,}|(?:sk-|sb_secret_|eyJ)[A-Za-z0-9_.-]+", re.I)
SECRET = re.compile(r"password|credential|authorization|bearer|api[_ -]?key|access[_ -]?token|"
                    r"secret|JSESSIONID|비밀번호|인증번호|암호", re.I)


def public_text(text: str) -> str:
    if SECRET.search(text):
        return "작업 내용을 확인하고 있어요."
    return PRIVATE.sub("[비공개]", text)[:400]


def snapshot(run: Path) -> dict:
    data = live.build(run, live=True)
    files = [run / 'journal.jsonl', *run.glob('agent-*.jsonl')]
    updated = max(p.stat().st_mtime for p in files if p.is_file())
    return {
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


def publish(client, body: dict) -> None:
    if len(body['timeline']['events']) > 10000 or len(json.dumps(body).encode()) > 2_000_000:
        raise ValueError('panel snapshot exceeds publication limit')
    client.rpc('panel_live_publish', {'p_timeline': body['timeline'], 'p_updated_at': body['updatedAt']})


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--run', type=Path)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args(argv)
    if args.env_file:
        _load_dotenv(args.env_file)
    settings = load_settings()
    if not settings.has_supabase:
        print('Panel relay: backend configuration missing', file=sys.stderr)
        return 21
    client = SupabaseClient(settings.supabase_url, settings.supabase_secret_key, timeout=10)
    previous = None
    while True:
        try:
            run = args.run or live.newest_run()
            if run:
                body = snapshot(run)
                digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
                if digest != previous:
                    publish(client, body)
                    previous = digest
                    print(f"Panel relay: published {len(body['timeline']['events'])} events", flush=True)
            elif args.once:
                print('Panel relay: no panel run found', file=sys.stderr)
                return 2
        except (OSError, ValueError, SupabaseError):
            # Backend error bodies can include private details. Never log them.
            print('Panel relay: publication unavailable; retrying', file=sys.stderr, flush=True)
            if args.once:
                return 23
        if args.once:
            return 0
        time.sleep(5)


if __name__ == '__main__':
    sys.exit(main())
