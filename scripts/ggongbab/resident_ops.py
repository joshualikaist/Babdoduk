"""Outbound Portal worker + local watchdog. No web server or public publication."""
from __future__ import annotations

from datetime import datetime
import math
from pathlib import Path
from urllib.parse import urlsplit
import subprocess
import sys
import time

from .heartbeat import HeartbeatWriter
from .ops_policy import (HUMAN, REASONS, PORTAL_PORT, DOORAY_PORT, alert_state,
                         reason, restart_action)
from .ops_storage import OpsError, SafeLog, atomic_json, lock_held, read_json
from .portal_list_state import ListStateError, PortalListState, poller_lock
from .portal_list_poller import run_poller
from .portal_session import PortalSessionProvider
from .windows_portal_host import PortalHost


def number(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise OpsError()
    return value


class Files:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.local = self.root / ".local"
        self.control = self.local / "ops-control.json"
        self.runtime = self.local / "ops-portal.json"
        self.watch = self.local / "ops-watchdog.json"
        self.alert = self.local / "ops-alert.json"
        self.worker_lock = self.local / "portal-list.lock"
        self.watch_lock = self.local / "ops-watchdog.lock"

    def control_state(self):
        state = read_json(self.control, {"enabled": False, "resume": 0})
        if set(state) != {"enabled", "resume"} or type(state["enabled"]) is not bool:
            raise OpsError()
        number(state["resume"])
        return state

    def set_enabled(self, enabled, now):
        atomic_json(self.control, {"enabled": bool(enabled), "resume": number(now)})

    def runtime_state(self):
        row = read_json(self.runtime, {
            "started": 0, "observed": 0, "last_success": None, "retry_not_before": 0,
            "reason": "WORKER_STOPPED", "manual_reason": "", "running": False,
        })
        if set(row) != {"started", "observed", "last_success", "retry_not_before", "reason", "manual_reason", "running"}:
            raise OpsError()
        for name in ("started", "observed", "retry_not_before"):
            number(row[name])
        if row["last_success"] is not None:
            number(row["last_success"])
        if (row["reason"] not in REASONS or row["manual_reason"] not in HUMAN | {""}
                or type(row["running"]) is not bool):
            raise OpsError()
        return row


class Journal:
    def __init__(self, files, *, now=time.time):
        self.files, self.now = files, now
        self.row = files.runtime_state()
        self.row.update(started=now(), observed=now(), reason="WORKER_STARTING", manual_reason="",
                        retry_not_before=0, running=True)
        self.log = SafeLog(files.local / "ops-portal.log")
        self.save()

    def save(self):
        self.row["observed"] = self.now()
        atomic_json(self.files.runtime, self.row)

    def __call__(self, message):
        # Ignore upstream prose/counts; persist only explicit known operational codes.
        if message not in REASONS:
            return
        self.row["reason"] = message
        if message in HUMAN:
            self.row["manual_reason"] = message
        self.log(message)
        self.save()

    def heartbeat(self, row, writer):
        # Capture required manual action even if the remote heartbeat write fails.
        if row["status"] == "ui_changed":
            self("PORTAL_UI_CHANGED")
        elif row["status"] == "auth_required" and self.row["reason"] not in REASONS:
            self("PORTAL_LIST_AUTH_REQUIRED")
        writer.write(row)  # existing agent_heartbeats RPC; success is not assumed
        if row["status"] == "healthy":
            self.row["last_success"] = datetime.fromisoformat(row["last_success_at"]).timestamp()
            self.row["reason"] = "WORKER_RUNNING"
            self.row["retry_not_before"] = 0
            self.log("WORKER_RUNNING")
        self.save()

    def retry(self, delay):
        self.row["retry_not_before"] = self.now() + number(delay)
        self.save()

    def close(self):
        self.row["running"] = False
        try:
            self.save()
        finally:
            self.log.close()


def run_worker(files, *, recover_stale=False, host=None, settings=None, now=time.time):
    from .config import load_settings
    from .db.supabase_client import SupabaseClient
    settings = settings or load_settings()
    journal = None
    writer = None
    # Same OS lock as manual --poll-list. Never remove it or the ledger/profile.
    with poller_lock(files.worker_lock):
        try:
            journal = Journal(files, now=now)
            if not settings.has_supabase or urlsplit(settings.supabase_url).scheme != "https":
                raise OpsError("OPS_CONFIGURATION_REQUIRED")
            writer = HeartbeatWriter(SupabaseClient(settings.supabase_url, settings.supabase_secret_key))
            state = PortalListState(files.local / "portal-list-state.json")
            host = host or PortalHost(files.root)

            class Provider:
                def acquire(self):
                    from .web.exit_codes import AuthRequired
                    try:
                        host.ensure(recover_stale=recover_stale, log=journal)
                    except OpsError as exc:
                        raise AuthRequired(str(exc)) from None
                    return PortalSessionProvider(host.profile, PORTAL_PORT).acquire()

            return run_poller(Provider(), state, emit_heartbeat=lambda row: journal.heartbeat(row, writer),
                log=journal, interval=60, max_failures=5, on_retry=journal.retry,
                stop_requested=lambda: not files.control_state()["enabled"])
        except (OpsError, ListStateError) as exc:
            if journal:
                journal(reason(str(exc)))
                if writer is not None:
                    from .heartbeat import build_heartbeat
                    from .config import KST
                    try:
                        journal.heartbeat(build_heartbeat(agent_id="portal-list-poller", status="collector_error",
                            exit_class=reason(str(exc)), last_scan_at=datetime.now(KST)), writer)
                    except Exception:
                        journal("PORTAL_HEARTBEAT_WRITE_FAILED")
            return 1
        except Exception:
            if journal:
                journal("WORKER_EXITED")
            return 1
        finally:
            if journal:
                journal.close()


def launch_worker(files, recover_stale):
    command = [sys.executable, str(files.root / "scripts/windows/ggongbab_workers.py"), "worker"]
    if recover_stale:
        command.append("--recover-stale")
    return subprocess.Popen(command, cwd=files.root, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)


class Watchdog:
    """Persistent bounded restart budget. Only a held child handle may be terminated."""
    def __init__(self, files, *, launch=launch_worker, host=None, now=time.time):
        self.files, self.launch, self.host, self.now = files, launch, host or PortalHost(files.root), now
        self.child = None
        self.state = read_json(files.watch, {"launches": 0, "recoveries": 0, "retry_at": 0,
                                            "latched": "", "resume": 0, "launched_at": 0})
        if set(self.state) != {"launches", "recoveries", "retry_at", "latched", "resume", "launched_at"}:
            raise OpsError()
        for key in ("launches", "recoveries", "retry_at", "resume", "launched_at"):
            number(self.state[key])
        if self.state["latched"] not in REASONS | {""}:
            raise OpsError()
        self.log = SafeLog(files.local / "ops-watchdog.log")

    def save(self):
        atomic_json(self.files.watch, self.state)

    def tick(self):
        now = self.now()
        control = self.files.control_state()
        runtime = self.files.runtime_state()
        held = lock_held(self.files.worker_lock)
        if not control["enabled"]:
            return False  # worker also checks this control every <=5s between requests
        if control["resume"] > self.state["resume"]:
            self.state.update(launches=0, recoveries=0, retry_at=0, latched="", resume=control["resume"], launched_at=0)
            self.save()
        code = self.state["latched"] or runtime["manual_reason"] or runtime["reason"]
        # An explicit operator resume acknowledges an older terminal observation.
        if runtime["observed"] < control["resume"] and not self.state["latched"]:
            code = "WORKER_STARTING"
        browser_state, _ = self.host.inspect()
        alert_code = code
        if not held and code in {"WORKER_RUNNING", "WORKER_STARTING"} and self.state["launched_at"]:
            alert_code = "WORKER_EXITED"
        if browser_state == "absent" and code == "WORKER_RUNNING":
            alert_code = "PORTAL_BROWSER_ABSENT"
        if browser_state == "unverified":
            alert_code = "PORTAL_RESIDENT_OWNER_UNVERIFIED"
        alert = alert_state(alert_code, runtime["last_success"], now)
        alert["worker_running"] = held
        alert["observed_at"] = now
        atomic_json(self.files.alert, alert)
        if self.state["latched"]:
            return True
        if self.child is not None and self.child.poll() is None:
            # Missing Chrome does not invalidate an already usable HTTP session.
            # Never kill it based solely on a stale remote heartbeat/backoff.
            if runtime["last_success"] and now - runtime["started"] >= 600 and now - runtime["last_success"] <= 180:
                self.state.update(launches=1, recoveries=0)
                self.save()
            if now - max(runtime["observed"], self.state["launched_at"]) > 600 and now > runtime["retry_not_before"]:
                self.state["latched"] = "OPS_WORKER_UNRESPONSIVE"
                self.save()  # require human review; do not kill a maybe-writing poller
            return True
        if held:
            # Orphan/manual poller: monitor it, never launch or terminate a duplicate.
            if code in HUMAN:
                self.state["latched"] = code
                self.save()
            return True
        if self.child is not None or self.state["launched_at"]:
            self.child = None
            if not self.state["retry_at"]:
                if code in {"WORKER_STARTING", "WORKER_RUNNING", "WORKER_STOPPED"}:
                    code = "WORKER_EXITED"
                action, delay = restart_action(code, max(0, self.state["launches"] - 1), self.state["recoveries"])
                if action in {"manual", "exhausted"}:
                    self.state["latched"] = "OPS_RETRY_EXHAUSTED" if action == "exhausted" else code
                else:
                    self.state["retry_at"] = max(now + delay, runtime["retry_not_before"])
                self.save()
                return True
            if now < self.state["retry_at"]:
                return True
        elif code in HUMAN and runtime["observed"] >= control["resume"]:
            self.state["latched"] = code
            self.save()
            return True
        recover = code == "PORTAL_CDP_ATTACH_TIMEOUT"
        self.state["launches"] += 1
        self.state["recoveries"] += int(recover)
        self.state.update(retry_at=0, launched_at=now)
        self.save()  # budget survives supervisor crash, even during launch
        self.child = self.launch(self.files, recover)
        self.log("WORKER_STARTING")
        return True

    def close(self):
        self.log.close()


def watch(files):
    with poller_lock(files.watch_lock):
        watchdog = Watchdog(files)
        try:
            while watchdog.tick():
                time.sleep(15)
        finally:
            watchdog.close()


def status_lines(files, host=None, now=None):
    now = time.time() if now is None else now
    row = files.runtime_state()
    control = files.control_state()
    watch_state = read_json(files.watch, {})
    code = reason(watch_state.get("latched") or row["manual_reason"] or row["reason"])
    alert = alert_state(code, row["last_success"], now)
    state, _ = (host or PortalHost(files.root)).inspect()
    running = lock_held(files.worker_lock)
    if not running and code == "WORKER_RUNNING":
        code = "WORKER_EXITED"
        alert = alert_state(code, row["last_success"], now)
    if state == "absent" and running:
        alert = alert_state("PORTAL_BROWSER_ABSENT", row["last_success"], now)
    elif state == "unverified":
        alert = alert_state("PORTAL_RESIDENT_OWNER_UNVERIFIED", row["last_success"], now)
    age = alert["last_success_age_seconds"]
    return ["Babdoduk Worker Status",
        "Portal worker : " + ("RUNNING (lock held)" if running else "STOPPED"),
        "Portal CDP    : " + {"verified": "OK", "absent": "ABSENT", "stale": "STALE", "unverified": "OWNER UNVERIFIED"}[state] + " (9223)",
        "Portal status : " + (alert["severity"] if control["enabled"] else "disabled") + " / " + code,
        "Last success  : " + (f"{age} sec ago (confirmed heartbeat write)" if age is not None else "not observed"),
        "Dooray worker : NOT MANAGED (operator-triggered; audit existing tasks)",
        "Dooray CDP    : not probed (9222)", "Cloud:", "Supabase      : not tested locally by status",
        "Vercel        : independent", "GitHub cron   : independent"]
