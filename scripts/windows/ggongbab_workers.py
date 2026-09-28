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


def radar(files, *, once=False, dry_run=False, interval=None):
    """The Dooray Radar (list-level, unread-safe). Attaches to the already-open dedicated
    Dooray browser; never starts, restarts or closes it and never opens a mail body."""
    from contextlib import contextmanager
    from datetime import datetime
    from urllib.parse import urlparse
    from ggongbab.config import load_settings
    from ggongbab.dispatch import request_refresh
    from ggongbab.dooray_radar import INTERVAL_DEFAULT, RadarFiles, run_radar
    from ggongbab.heartbeat import HeartbeatWriter, build_heartbeat
    from ggongbab.portal_list_state import poller_lock
    from ggongbab.web.mail_reader import list_mails_paged
    from ggongbab.web.resident import is_running, resident_session
    from ggongbab.web.task_writer import TaskWriter
    from ggongbab.web.ui_contract import load_contract

    rf = RadarFiles(files.root)
    try:
        contract = load_contract(rf.contract)
        contract.require_ready()
        if not contract.read_state_key:
            raise OpsError("OPS_CONFIGURATION_REQUIRED")   # unread safety needs the verified read flag
        settings = load_settings()
        writer = None if dry_run else TaskWriter(settings)
        if writer is not None:
            writer.verify_project()
    except Exception:
        # A start that fails before the first scan (contract not verified, Dooray token or
        # project rejected) is recorded with a fixed code, so status and alerts say why.
        from ggongbab.dooray_radar import CONFIG_REQUIRED
        from ggongbab.ops_storage import atomic_json
        runtime = rf.runtime_state()
        runtime.update(running=False, reason=CONFIG_REQUIRED, observed=time.time())
        atomic_json(rf.runtime, runtime)
        log = SafeLog(files.local / "ops-radar.log")
        try:
            log(CONFIG_REQUIRED)
        finally:
            log.close()
        raise OpsError("OPS_CONFIGURATION_REQUIRED")
    beat_writer = None
    if settings.has_supabase and not dry_run:
        from ggongbab.db.supabase_client import SupabaseClient
        beat_writer = HeartbeatWriter(SupabaseClient(settings.supabase_url, settings.supabase_secret_key))

    def heartbeat(status, scanned, success, exit_class):
        if beat_writer is None:
            return
        try:
            beat_writer.write(build_heartbeat(agent_id="dooray-radar", version="dooray-radar-v1", status=status,
                exit_class=exit_class, auth_required=status == "auth_required",
                ui_contract_changed=status == "ui_changed", last_scan_at=scanned, last_success_at=success))
        except Exception:
            pass    # the local runtime file and alerts still record the state

    @contextmanager
    def session_factory():
        with resident_session(rf.profile, contract, start_url="", port=9222, attach_only=True,
                              log=lambda _: None) as session:
            yield session

    log = SafeLog(files.local / "ops-radar.log")
    try:
        with poller_lock(rf.lock):
            return run_radar(rf, session_factory=session_factory, writer=writer, list_mails=list_mails_paged,
                             mail_host=urlparse(contract.mail_url).netloc, heartbeat=heartbeat,
                             dispatch=lambda new: request_refresh(rf.dispatch, new_candidates=new),
                             interval=interval or INTERVAL_DEFAULT, dry_run=dry_run,
                             max_cycles=1 if once else None, browser_running=lambda: bool(is_running(9222)),
                             log=log)
    finally:
        log.close()


def alerts_command(files, emit=True):
    from ggongbab.alerts import FileSink, evaluate, render
    from ggongbab.dooray_radar import RadarFiles
    found = evaluate(files.local, portal_running=lock_held(files.worker_lock),
                     radar_running=lock_held(RadarFiles(files.root).lock))
    if emit:
        FileSink(files.local).emit(found)
    for line in render(found):
        print(line)
    return 0 if all(a.severity == "healthy" for a in found) else 2


class SafeLogContext:
    def __init__(self, path):
        self.log = SafeLog(path)
    def __enter__(self):
        return self.log
    def __exit__(self, *_):
        self.log.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Babdoduk Windows resident operations")
    parser.add_argument("action", choices=("watch", "worker", "enable", "stop", "status", "recover", "dooray-once", "check",
                                           "radar", "radar-once", "radar-enable", "radar-disable", "radar-allow-unread",
                                           "radar-dispatch-on", "radar-dispatch-off", "alerts"))
    parser.add_argument("--recover-stale", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="radar-once: detect only; no task, state or dispatch")
    parser.add_argument("--interval", type=int, help="radar: seconds between scans (120-300, default 180)")
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
        elif args.action in ("radar", "radar-once"):
            return radar(files, once=args.action == "radar-once", dry_run=args.dry_run, interval=args.interval)
        elif args.action in ("radar-enable", "radar-disable"):
            from ggongbab.dooray_radar import RadarFiles
            RadarFiles(ROOT).set_enabled(args.action == "radar-enable", time.time())
        elif args.action in ("radar-dispatch-on", "radar-dispatch-off"):
            # Owner step J: only after a stored token, one manual test dispatch and a verified cloud run.
            from ggongbab.dooray_radar import RadarFiles
            RadarFiles(ROOT).set_dispatch(args.action == "radar-dispatch-on", time.time())
        elif args.action == "radar-allow-unread":
            # Operator acknowledgement after reviewing why unread analysis was disabled.
            from ggongbab.dooray_radar import RadarFiles
            latch = RadarFiles(ROOT).unread_latch
            if latch.exists():
                latch.unlink()
            print("Unread list-level analysis re-enabled after operator review.")
        elif args.action == "alerts":
            return alerts_command(files)
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
