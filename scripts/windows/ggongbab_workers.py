"""Operator entry point. Importing this module never probes or starts anything."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from ggongbab.ops_storage import OpsError, SafeLog, lock_held
from ggongbab.ops_policy import reason
from ggongbab.portal_list_state import ListStateError
from ggongbab.resident_ops import Files, run_worker, status_lines, watch
from ggongbab.windows_portal_host import PortalHost


def wait_stopped(files, timeout=60, *, sleep=time.sleep, monotonic=time.monotonic):
    deadline = monotonic() + timeout
    while lock_held(files.worker_lock) or lock_held(files.watch_lock):
        if monotonic() >= deadline:
            raise OpsError("OPS_WORKER_UNRESPONSIVE")
        sleep(1)


def recover(files, *, host=None, run=subprocess.run):
    # Operator-only, single attempt. Never enabled by Task Scheduler.
    files.set_enabled(False, time.time())
    wait_stopped(files)
    host = host or PortalHost(files.root)
    current, _ = host.inspect()
    runtime = files.runtime_state()
    stale = current == "stale" or runtime["reason"] == "PORTAL_CDP_ATTACH_TIMEOUT"
    host.ensure(recover_stale=stale)
    print("Dedicated Portal browser ready. Complete SSO manually only if prompted.", flush=True)
    result = run([sys.executable, str(files.root / "scripts/portal_web_agent.py"), "--setup", "--cdp"], cwd=files.root)
    print("After successful setup, run start_ggongbab_workers.cmd to resume polling.")
    return result.returncode


def dooray_once(files, *, run=subprocess.run):
    # Legacy operator/scheduler entry: the ops installer never schedules Dooray.
    with SafeLogContext(files.local / "agent.log") as log:
        result = run([sys.executable, str(files.root / "scripts/dooray_web_agent.py"),
            "--run", "--since-last-run", "--read-state", "read", "--run-pipeline", "--cdp"],
            cwd=files.root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log("DOORAY_RUN_OK" if result.returncode == 0 else "DOORAY_RUN_FAILED")
        return result.returncode


class SafeLogContext:
    def __init__(self, path):
        self.log = SafeLog(path)
    def __enter__(self):
        return self.log
    def __exit__(self, *_):
        self.log.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Babdoduk Windows resident operations")
    parser.add_argument("action", choices=("watch", "worker", "enable", "stop", "status", "recover", "dooray-once", "check"))
    parser.add_argument("--recover-stale", action="store_true")
    # Existing legacy launcher retains explicit safety switches, all fixed/validated.
    parser.add_argument("--since-last-run", action="store_true")
    parser.add_argument("--read-state", choices=("read",), default="read")
    parser.add_argument("--run-pipeline", action="store_true")
    parser.add_argument("--cdp", action="store_true")
    args = parser.parse_args(argv)
    files = Files(ROOT)
    try:
        if os.name != "nt":
            raise OpsError("OPS_CONFIGURATION_REQUIRED")
        if args.action == "check":
            import requests
            import playwright.sync_api
            from ggongbab.config import load_settings
            branch = subprocess.run(["git", "-C", str(ROOT), "branch", "--show-current"],
                capture_output=True, text=True, check=True, timeout=10)
            if branch.stdout.strip() != "lab":
                raise OpsError("OPS_CONFIGURATION_REQUIRED")
            if not load_settings().has_supabase:
                raise OpsError("OPS_CONFIGURATION_REQUIRED")
            print("Local Python dependencies and heartbeat configuration present; services not contacted.")
        elif args.action == "enable":
            files.set_enabled(True, time.time())
        elif args.action == "stop":
            files.set_enabled(False, time.time())
            wait_stopped(files)
            print("Workers stopped. Browser profile and Portal state retained.")
        elif args.action == "status":
            print("\n".join(status_lines(files)))
        elif args.action == "recover":
            return recover(files)
        elif args.action == "worker":
            return run_worker(files, recover_stale=args.recover_stale)
        elif args.action == "dooray-once":
            return dooray_once(files)
        else:
            watch(files)
        return 0
    except OpsError as exc:
        if sys.stdout:
            print(reason(str(exc)) + ": operator review required; no automatic reset performed.")
        return 1
    except ListStateError:
        if sys.stdout:
            print("PORTAL_LIST_STATE_UNAVAILABLE: worker lock or state unavailable; no reset performed.")
        return 1
    except Exception:
        if sys.stdout:
            print("OPS_OPERATION_FAILED: diagnostic values suppressed.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
