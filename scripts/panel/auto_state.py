"""Classify panel failures without leaking model output. A failure never counts as a completed day."""
import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
KST = timezone(timedelta(hours=9), name='Asia/Seoul')


def failure(result, now):
    text = str(result.get('result', ''))
    if result.get('api_error') == 'usage_limit_reached' or result.get('api_error_type') == 'rate_limit_error':
        reset = now + timedelta(hours=1)
        match = re.search(r'resets?\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b', text, re.I)
        if match:
            hour, minute = int(match[1]), int(match[2] or 0)
            if 1 <= hour <= 12 and 0 <= minute <= 59:
                reset = now.astimezone(KST).replace(hour=hour % 12 + (12 if match[3].lower() == 'pm' else 0),
                                                  minute=minute, second=0, microsecond=0)
                if reset <= now:
                    reset += timedelta(days=1)
        # Give the provider five minutes after its reported reset.
        return {'code': 'rate_limit', 'retryAt': (reset + timedelta(minutes=5)).isoformat()}
    if result.get('api_error_status') == 401:
        return {'code': 'auth_failed'}
    return {'code': 'failed'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--result', type=Path)
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--clear', action='store_true')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--retry-calendar', action='store_true')
    args = parser.parse_args(argv)
    target = args.state_dir / 'status.json'
    if args.retry_calendar:
        state = json.loads(target.read_text())
        retry = datetime.fromisoformat(state['retryAt']).astimezone(KST)
        print(retry.strftime('%Y-%m-%d %H:%M:%S Asia/Seoul'))
        return 0
    if args.check:
        try:
            state = json.loads(target.read_text())
            if state.get('code') == 'rate_limit' and datetime.fromisoformat(state['retryAt']) > datetime.now(KST):
                print('usage limit: waiting for the scheduled retry')
                return 75
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return 0
    if args.clear:
        state = {'code': 'working'}
    else:
        try:
            data = json.loads(args.result.read_text())
            state = failure(data, datetime.now(KST))
        except (OSError, ValueError, TypeError, AttributeError):
            state = {'code': 'failed'}
    args.state_dir.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(state) + '\n')
    temporary.chmod(0o600)
    temporary.replace(target)
    print(state['code'])
    return 75 if state['code'] == 'rate_limit' else 0


if __name__ == '__main__':
    raise SystemExit(main())
