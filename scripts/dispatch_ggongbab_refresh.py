#!/usr/bin/env python3
"""Operator commands for the low-latency refresh trigger (Option A, docs/GGONGBAB_TRIGGER.md).

    python scripts/dispatch_ggongbab_refresh.py --status        # never prints the token
    python scripts/dispatch_ggongbab_refresh.py --store-token   # activation: prompts, no echo
    python scripts/dispatch_ggongbab_refresh.py --remove-token
    python scripts/dispatch_ggongbab_refresh.py --request       # one manual dispatch (debounced)

--store-token and --request are activation steps and need the owner's approval first.
"""
from __future__ import annotations

import argparse
import getpass
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ggongbab import dispatch  # noqa: E402

STATE_FILE = ROOT / ".local" / "dispatch-state.json"
TOKEN_SHAPE = re.compile(r"^(?:github_pat_[A-Za-z0-9_]{40,}|ghp_[A-Za-z0-9]{30,})$")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--status", action="store_true")
    mode.add_argument("--store-token", action="store_true")
    mode.add_argument("--remove-token", action="store_true")
    mode.add_argument("--request", action="store_true")
    args = parser.parse_args(argv)
    if args.status:
        state = dispatch.DispatchState.load(STATE_FILE)
        configured = bool(dispatch.read_windows_credential())
        age = f"{int(time.time() - state.last_dispatch_at)} s ago" if state.last_dispatch_at else "never"
        print(f"token stored     : {'yes' if configured else 'no'} ({dispatch.CREDENTIAL_TARGET})")
        print(f"target           : {dispatch.REPOSITORY} {dispatch.WORKFLOW} on {dispatch.REF}")
        print(f"last dispatch    : {age}; today {state.count}/{dispatch.DAILY_CAP}; pending {state.pending}")
        print(f"last result      : {state.last_result or '-'}")
        return 0
    if args.store_token:
        token = getpass.getpass("Fine-grained token (Babdoduk only, Actions: read and write): ").strip()
        if not TOKEN_SHAPE.match(token):
            print("That does not look like a GitHub token; nothing was stored.")
            return 1
        ok = dispatch.write_windows_credential(token)
        del token
        print("stored in Windows Credential Manager" if ok else "could not store the token")
        return 0 if ok else 1
    if args.remove_token:
        print("removed" if dispatch.delete_windows_credential() else "no stored token")
        return 0
    code = dispatch.request_refresh(STATE_FILE, new_candidates=True, source="manual")
    print(code)
    return 0 if code in (dispatch.DISPATCHED, dispatch.DEBOUNCED) else 1


if __name__ == "__main__":
    sys.exit(main())
