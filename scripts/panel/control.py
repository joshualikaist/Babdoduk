#!/usr/bin/env python3
"""Owner-authenticated, on-demand panel requests. No shell/code comes from a request.

The only ingress is one bounded JSON object in a PRIVATE Storage bucket. A signed upload
capability allows replacing that object, never reading it. Both the lab API and this worker
verify the current Auth user and the server-owned app_metadata.panel_operator flag.
The backend key stays on the ops PC. Opening a page or polling never starts a model run.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from panel_storage import PanelStorage, StorageError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ggongbab.config import _load_dotenv, load_settings

INBOX = 'panel-requests'
OBJECT = 'pending.json'
PUBLIC = 'panel-live'
LIMIT = 16_384
UNIT = 'babdoduk-panel.service'


def stamp(now):
    return datetime.fromtimestamp(now, timezone.utc).isoformat()


def read_json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def save(path, body):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(body) + '\n')
    temporary.chmod(0o600)
    temporary.replace(path)


def auth_request(client, path, *, token=None, body=None, method='GET'):
    headers = {'apikey': client.key, 'Authorization': 'Bearer ' + (token or client.key),
               'Content-Type': 'application/json'}
    raw = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(client.base.removesuffix('/storage/v1') + '/auth/v1/' + path,
                                     headers=headers, data=raw, method=method)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise StorageError(exc.code) from None
    except (OSError, ValueError):
        raise StorageError('transport') from None


def operator(client, token):
    user = auth_request(client, 'user', token=token)
    return bool(user.get('id') and user.get('app_metadata', {}).get('panel_operator') is True)


def valid_request(body, now):
    if not isinstance(body, dict) or set(body) != {'requestId', 'createdAt', 'accessToken'}:
        return False
    try:
        if str(UUID(body['requestId'])) != body['requestId']:
            return False
        created = datetime.fromisoformat(body['createdAt'])
        return (created.tzinfo is not None and -10 <= now - created.timestamp() <= 120
                and isinstance(body['accessToken'], str) and 32 <= len(body['accessToken']) <= 8192)
    except (ValueError, TypeError, KeyError, AttributeError):
        return False


def public_state(status, busy, record, now):
    result = {'updatedAt': stamp(now), 'state': 'idle'}
    if record.get('requestId'):
        result['requestId'] = record['requestId']
    try:
        retry = datetime.fromisoformat(status['retryAt'])
        if status.get('code') == 'rate_limit' and retry.timestamp() > now:
            return {**result, 'state': 'rate_limit', 'retryAt': retry.isoformat()}
    except (ValueError, TypeError, KeyError):
        pass
    if busy:
        result['state'] = 'publishing' if status.get('code') == 'publishing' else 'running'
    elif record:
        # Allow systemd to acquire the runner lock before interpreting its final state.
        if now - record.get('requestedAt', 0) < 15:
            result['state'] = 'starting'
        elif status.get('code') in ('complete', 'failed', 'auth_failed'):
            result['state'] = status['code']
        else:
            result['state'] = 'failed'
    return result


def service_busy():
    res = subprocess.run(['systemctl', '--user', 'show', UNIT, '--property=ActiveState', '--value'],
                         capture_output=True, text=True, check=True, timeout=5)
    return res.stdout.strip() in ('active', 'activating', 'deactivating', 'reloading')


def start_service():
    subprocess.run(['systemctl', '--user', 'start', '--no-block', UNIT],
                   check=True, capture_output=True, timeout=5)


class Controller:
    def __init__(self, client, state_dir, *, verify=None, busy=None, start=None):
        self.client, self.state_dir = client, state_dir
        self.verify = verify or (lambda token: operator(client, token))
        self.busy, self.start = busy or service_busy, start or start_service
        self.upload = None
        self.expires = 0

    def tick(self, now):
        record_path = self.state_dir / 'control-state.json'
        record = read_json(record_path)
        status = read_json(self.state_dir / 'status.json')
        state = public_state(status, self.busy(), record, now)
        try:
            request = self.client.request('GET', '/object/authenticated/' + INBOX + '/' + OBJECT + '?v=' + str(int(now)))
        except StorageError as exc:
            if exc.code not in (400, 404):
                raise
            request = None
        if request and valid_request(request, now) and request['requestId'] not in record.get('seen', []):
            try:
                allowed = self.verify(request['accessToken'])
            except StorageError as exc:
                if exc.code not in (401, 403):
                    raise
                allowed = False
            if allowed:
                # Persist before launching: a restart must never repeat an accepted request.
                seen = (record.get('seen', []) + [request['requestId']])[-100:]
                if state['state'] not in ('starting', 'running', 'publishing', 'rate_limit'):
                    record = {'requestId': request['requestId'], 'requestedAt': now, 'seen': seen}
                    save(record_path, record)
                    save(self.state_dir / 'status.json', {'code': 'starting', 'updatedAt': stamp(now)})
                    try:
                        self.start()
                    except (OSError, subprocess.SubprocessError):
                        save(self.state_dir / 'status.json', {'code': 'failed', 'updatedAt': stamp(now)})
                        state = {'updatedAt': stamp(now), 'state': 'failed', 'requestId': request['requestId']}
                    else:
                        state = {'updatedAt': stamp(now), 'state': 'starting', 'requestId': request['requestId']}
                else:
                    record['seen'] = seen
                    save(record_path, record)
            # The private inbox contains a short-lived access token. Remove it after checking.
            self.client.request('DELETE', '/object/' + INBOX, {'prefixes': [OBJECT]})
        elif request:
            self.client.request('DELETE', '/object/' + INBOX, {'prefixes': [OBJECT]})
        if now >= self.expires - 3600:
            signed = self.client.request('POST', '/object/upload/sign/' + INBOX + '/' + OBJECT, {}, upload=True)
            self.upload = signed['url']
            self.expires = now + 7200
        self.client.request('POST', '/object/' + PUBLIC + '/control.json',
                            {**state, 'upload': self.upload, 'uploadExpiresAt': stamp(self.expires)}, upload=True)
        return state


def grant(client, email):
    matches = []
    for page in range(1, 101):
        users = auth_request(client, f'admin/users?page={page}&per_page=100').get('users', [])
        matches.extend(u for u in users if u.get('email', '').casefold() == email.casefold())
        if len(users) < 100:
            break
    if len(matches) != 1:
        raise ValueError('exactly one existing signed-in account is required')
    user = matches[0]
    if not user.get('email_confirmed_at'):
        raise ValueError('the account email must already be confirmed')
    auth_request(client, 'admin/users/' + user['id'], method='PUT',
                 body={'app_metadata': {**user.get('app_metadata', {}), 'panel_operator': True}})


def main():
    import fcntl
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, required=True)
    parser.add_argument('--state-dir', type=Path, default=Path.home() / 'Babdoduk-ops/.local/panel-auto')
    parser.add_argument('--setup', action='store_true')
    parser.add_argument('--grant-email')
    args = parser.parse_args()
    _load_dotenv(args.env_file)
    settings = load_settings()
    if not settings.has_supabase:
        return 21
    client = PanelStorage(settings.supabase_url, settings.supabase_secret_key)
    if args.setup:
        client.setup_bucket(INBOX, public=False, limit=LIMIT)
        print('Private panel request inbox configured')
        return 0
    if args.grant_email:
        grant(client, args.grant_email)
        print('Panel operator enabled for the requested account')
        return 0
    args.state_dir.mkdir(parents=True, exist_ok=True)
    lock = (args.state_dir / 'control.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return 2
    controller = Controller(client, args.state_dir)
    while True:
        try:
            controller.tick(time.time())
        except (StorageError, OSError, ValueError, KeyError, subprocess.SubprocessError):
            print('Panel control unavailable; retrying', file=sys.stderr, flush=True)
        time.sleep(5)


if __name__ == '__main__':
    raise SystemExit(main())
