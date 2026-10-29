"""Outbound Portal worker + local watchdog. No web server or public publication."""
from __future__ import annotations

from datetime import datetime
import math
from pathlib import Path
from urllib.parse import urlsplit
import subprocess
import sys
import time

from .easy_login import page_kind
from .heartbeat import HeartbeatWriter
from .ops_browser import dooray_host, page_targets, read_mode, slot_for, tab_roles
from .ops_policy import HUMAN, LOGIN, REASONS, WARNING_SECONDS, alert_state, reason, restart_action
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
                        # A worker start is never the owner's: the browser opens minimized.
                        host.ensure(recover_stale=recover_stale, log=journal, minimized=True)
                    except OpsError as exc:
                        # A tab that cannot be restored blocks the attach exactly like the known
                        # CDP attach timeout: one verified-browser recovery, then manual.
                        code = str(exc)
                        if code in ("OPS_BROWSER_TAB_UNRESPONSIVE", "OPS_BROWSER_TARGETS_UNAVAILABLE",
                                    "OPS_BROWSER_CDP_ERROR"):
                            code = "PORTAL_CDP_ATTACH_TIMEOUT"
                        raise AuthRequired(code) from None
                    # The Ops Chrome (shared with the Radar) or, in separate mode, the Portal browser.
                    return PortalSessionProvider(host.profile, host.port).acquire()

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


RESUME_GAP_SECONDS = 120
RESUME_GRACE_SECONDS = 600
UNRESPONSIVE_GRACE_SECONDS = 120  # Watchdog.tick: time past the worker's own retry before it is unresponsive
QUICK_RETRY_SECONDS = 120     # Watchdog.may_resume: one retry of a login latch when the tabs look right
REOPEN_BROWSER_SECONDS = 1800  # Watchdog.reopen_browser: at most one automatic open per 30 minutes
EASY_LOGIN_CHECK_SECONDS = 300  # Watchdog.start_easy_login: how often a login wait is looked at again


def emit_alerts(files, now, *, portal_running, toast=None):
    """Combined operator alerts (Portal, Radar, dispatch, flash candidates) every watchdog tick,
    so a crashed or stale Radar is reported even when its own process is gone. `toast`: the
    Windows toast of this PC (notify.local_toast), passed by the running watchdog only."""
    try:
        from .alerts import FileSink, evaluate
        from .dooray_radar import RadarFiles
        found = evaluate(files.local, portal_running=portal_running,
                         radar_running=lock_held(RadarFiles(files.root).lock), now=now)
    except Exception:
        return    # alerting must never stop the watchdog
    try:
        FileSink(files.local).emit(found)
    except Exception:
        pass      # a local file problem must not silence the pushes below
    try:
        from .notify import push_local
        # The external push is a no-op until an operator configures a provider.
        push_local(files.local, found, now=now, toast=toast)
    except Exception:
        pass


def launch_worker(files, recover_stale):
    command = [sys.executable, str(files.root / "scripts/windows/ggongbab_workers.py"), "worker"]
    if recover_stale:
        command.append("--recover-stale")
    return subprocess.Popen(command, cwd=files.root, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def launch_easy_login(files):
    """One Easy Login attempt in its own process (easy_login.run_assist), so the watchdog never
    waits on a page."""
    return subprocess.Popen([sys.executable, str(files.root / "scripts/windows/ggongbab_workers.py"), "easy-login"],
        cwd=files.root, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


class Watchdog:
    """Persistent bounded restart budget. Only a held child handle may be terminated."""
    def __init__(self, files, *, launch=launch_worker, host=None, now=time.time, targets=page_targets, toast=None,
                 launch_easy=launch_easy_login):
        self.files, self.launch, self.host, self.now = files, launch, host or PortalHost(files.root), now
        self.targets, self.toast, self.launch_easy = targets, toast, launch_easy
        # In memory only: whether a KAIST SSO page was seen open since the current login latch,
        # when this process first saw that latch, and whether its one quick retry is spent.
        self.sso_for, self.sso_seen, self.latch_seen_at, self.quick_retry_used = "", False, 0.0, False
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
        # In memory only: a tick gap far beyond the 15 s cadence means the PC slept. The worker
        # then gets a grace window to report before it can be judged unresponsive.
        self.last_tick = None
        self.resumed_at = 0.0
        # In memory only: when this process last opened a missing Ops Chrome by itself.
        self.browser_opened_at = -float(REOPEN_BROWSER_SECONDS)
        # In memory only: the running Easy Login attempt and when a login wait was last looked at.
        self.easy_child, self.easy_checked_at = None, -float(EASY_LOGIN_CHECK_SECONDS)

    def save(self):
        atomic_json(self.files.watch, self.state)

    def reopen_browser(self, now):
        """Open the Ops Chrome when it is missing, so a person sees it and can log in (owner request,
        2026-10-28). From 10-19 the Portal worker waited at a login latch, which never starts a
        browser; after a reboot on 10-23 nothing opened one, so the Radar (which never starts Chrome)
        had none either, and both collectors stood still for days behind a toast.

        Only the dedicated profile on its loopback port is started (host.ensure: a stale or
        unverified process is never touched). While a login latch holds it opens as a normal window,
        because a person must log in; otherwise it is the usual unattended start. Nothing is typed,
        clicked or logged in. At most once per REOPEN_BROWSER_SECONDS; a failure only waits for the
        next attempt. Workers that are stopped (control disabled) never get here."""
        if now - self.browser_opened_at < REOPEN_BROWSER_SECONDS:
            return False
        self.browser_opened_at = now
        try:
            self.host.ensure(log=self.log, minimized=self.state["latched"] not in LOGIN)
        except Exception:  # noqa: BLE001 - the next attempt is the recovery
            self.log("OPS_BROWSER_AUTO_OPEN_FAILED")
            return False
        self.log("OPS_BROWSER_AUTO_OPENED")
        return True

    def login_needed(self, now):
        """A collector waits for a KAIST login: the Portal worker at a login latch (after its one
        quick retry has had its chance), or the Dooray Radar reporting DOORAY_AUTH_REQUIRED."""
        if self.state["latched"] in LOGIN and now - self.latch_seen_at >= QUICK_RETRY_SECONDS + 30:
            return True
        return read_json(self.files.local / "ops-radar.json", {}).get("reason") == "DOORAY_AUTH_REQUIRED"

    def start_easy_login(self, now):
        """Launch one Easy Login attempt (owner decision 2026-10-29, docs/PORTAL_EASY_LOGIN_ASSIST.md):
        it clicks the portal's login and Easy Login's Login, and sends the verification code to the
        owner's Telegram; the owner approves on their phone. Off unless `.local/easy-login.json`
        enables it. The attempt's own limits (30 minutes, 4 a day, a pause after 2 unanswered
        codes) are checked here before a process starts and again inside it."""
        if self.easy_child is not None and self.easy_child.poll() is None:
            return False
        if now - self.easy_checked_at < EASY_LOGIN_CHECK_SECONDS:
            return False
        self.easy_checked_at = now
        try:
            from .easy_login import may_start
            if not may_start(self.files.local, now):
                return False
            self.easy_child = self.launch_easy(self.files)
        except Exception:  # noqa: BLE001 - the next check is the recovery
            return False
        self.log("EASY_LOGIN_STARTED")
        return True

    def may_resume(self, browser_state, now):
        """Whether a login latch may be acknowledged now: "login", "retry" or None. Never a login.

        Read from the verified browser's loopback page list only (scheme and host of each page,
        in memory); nothing is attached, typed, sent or stored. Either way exactly one Portal page
        must be open and no KAIST SSO page:
          * "login" - since the latch a KAIST SSO page was open and has now closed: a person has
            logged in again. Each such resume needs a new SSO page.
          * "retry" - once, QUICK_RETRY_SECONDS after the latch, while the page list looks right.
            On 2026-10-12 the worker latched with PORTAL_CONTEXT_MISSING_OR_AMBIGUOUS two
            minutes after the PC woke, and the same login then worked 16 hours later on a plain
            start: the browser had not settled. The quick retry is spent until a scan succeeds,
            so a session that is really broken cannot resume itself in a loop.
        """
        if self.sso_for != self.state["latched"]:
            self.sso_for, self.sso_seen, self.latch_seen_at = self.state["latched"], False, now
        if browser_state != "verified":
            return None
        try:
            pages = self.targets(self.host.port)
            counts = tab_roles(pages, dooray_host(self.files.local / "dooray-ui.json"))
        except Exception:
            return None     # an unreadable page list never resumes anything
        if counts["sso"]:
            self.sso_seen = True
            return None
        if counts["portal"] != 1:
            return None
        if self.sso_seen:
            self.sso_seen = False
            return "login"
        if (not self.quick_retry_used and now - self.latch_seen_at >= QUICK_RETRY_SECONDS
                and not any(page_kind(t["url"]) == "portal_login" for t in pages)):
            self.quick_retry_used = True
            return "retry"
        return None

    def portal_login_open(self):
        """Whether the verified browser shows the Portal's own login page, where the Portal sends
        its tab once the session is gone. Host and path of each page, in memory only."""
        try:
            return any(page_kind(t["url"]) == "portal_login" for t in self.targets(self.host.port))
        except Exception:
            return False

    def tick(self):
        now = self.now()
        if self.last_tick is not None and now - self.last_tick > RESUME_GAP_SECONDS:
            self.resumed_at = now
        self.last_tick = now
        control = self.files.control_state()
        runtime = self.files.runtime_state()
        held = lock_held(self.files.worker_lock)
        if not control["enabled"]:
            return False  # worker also checks this control every <=5s between requests
        if control["resume"] > self.state["resume"]:
            self.state.update(launches=0, recoveries=0, retry_at=0, latched="", resume=control["resume"], launched_at=0)
            self.save()
        if (self.state["latched"] == "OPS_WORKER_UNRESPONSIVE" and held and runtime["last_success"]
                and now - runtime["last_success"] <= WARNING_SECONDS):
            # The worker is scanning again, so the stall was not real (e.g. judged across a sleep).
            self.state["latched"] = ""
            self.save()
            self.log("WORKER_RUNNING")
        if (self.state["latched"] == "OPS_WORKER_UNRESPONSIVE" and not held
                and (self.child is None or self.child.poll() is not None)):
            # The latch protects a live poller that might still be writing. Once the worker has
            # exited and released its lock nothing can be writing, so the ordinary restart budget
            # decides again. On 2026-10-29 a worker exited by itself 16 s after the latch and
            # collection stood still for 3.5 hours behind it.
            self.state["latched"] = ""
            self.save()
            self.log("WORKER_EXITED")
        code = self.state["latched"] or runtime["manual_reason"] or runtime["reason"]
        # An explicit operator resume acknowledges an older terminal observation.
        if runtime["observed"] < control["resume"] and not self.state["latched"]:
            code = "WORKER_STARTING"
        browser_state, _ = self.host.inspect()
        if browser_state == "absent" and self.reopen_browser(now):
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
        emit_alerts(self.files, now, portal_running=held, toast=self.toast)
        if self.quick_retry_used and runtime["last_success"] and runtime["last_success"] > self.state["resume"]:
            self.quick_retry_used = False     # a scan succeeded since the last resume
        if (not self.state["latched"] and browser_state == "verified" and not held
                and (self.child is None or self.child.poll() is not None)
                and not (runtime["last_success"] and now - runtime["last_success"] <= WARNING_SECONDS)
                and self.portal_login_open()):
            # The session is gone whatever the LIST answered: on 2026-10-29, after the Portal's
            # dawn outage, it answered a 5xx and the worker was restarted in vain. Wait for a login
            # like any login latch, so Easy Login and the automatic resume apply.
            self.state["latched"] = "PORTAL_LIST_AUTH_REQUIRED"
            self.save()
            self.log("PORTAL_LIST_AUTH_REQUIRED")
        if self.state["latched"] in LOGIN and self.may_resume(browser_state, now):
            # The same acknowledgement an operator's start writes; the next tick clears the
            # latch and launches the worker against the browser's current login.
            self.files.set_enabled(True, now)
            self.log("OPS_AUTO_RESUMED")
            return True
        if browser_state == "verified" and self.login_needed(now):
            self.start_easy_login(now)
        if self.state["latched"]:
            return True
        if self.child is not None and self.child.poll() is None:
            # Missing Chrome does not invalidate an already usable HTTP session.
            # Never kill it based solely on a stale remote heartbeat/backoff.
            if runtime["last_success"] and now - runtime["started"] >= 600 and now - runtime["last_success"] <= 180:
                self.state.update(launches=1, recoveries=0)
                self.save()
            # A worker waking from its own backoff needs a moment to rebuild its session and report.
            if (now - max(runtime["observed"], self.state["launched_at"]) > 600
                    and now > runtime["retry_not_before"] + UNRESPONSIVE_GRACE_SECONDS
                    and now - self.resumed_at > RESUME_GRACE_SECONDS):
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
        from .notify import local_toast
        watchdog = Watchdog(files, toast=local_toast(files.local))
        try:
            while watchdog.tick():
                time.sleep(15)
        finally:
            watchdog.close()


BROWSER_STATES = {"verified": "running", "absent": "missing", "stale": "stale", "unverified": "unverified"}


def ops_browser_lines(root, state, port, *, targets=page_targets):
    """Ops Chrome + tab presence. A tab is looked up only on a verified owner; never a URL/title."""
    tabs = {"portal": "unknown", "dooray": "unknown"}
    if state == "verified":
        try:
            counts = tab_roles(targets(port), dooray_host(Path(root) / ".local" / "dooray-ui.json"))
            login = " / KAIST SSO login page open" if counts["sso"] else ""
            tabs = {"portal": "present" if counts["portal"] else
                              ("SSO login page (log in there)" if counts["sso"] else "absent"),
                    "dooray": ("present (inbox)" if counts["inbox"] else
                               "present (login or not on the inbox)" + login if counts["dooray"] else
                               "absent" + login)}
        except OpsError:
            pass
    elif state in ("absent", "stale"):
        tabs = {"portal": "absent", "dooray": "absent"}
    return [f"Ops browser   : {BROWSER_STATES[state]} (127.0.0.1:{port})",
            f"Portal tab    : {tabs['portal']}", f"Dooray tab    : {tabs['dooray']}"]


def radar_status_lines(files, now):
    from .dooray_radar import RadarFiles
    radar = RadarFiles(files.root)
    try:
        row = radar.runtime_state()
    except Exception:
        return ["Dooray radar  : STATE UNREADABLE"]
    age = int(now - row["last_success"]) if isinstance(row.get("last_success"), (int, float)) and row["last_success"] else None
    code = row.get("reason") if row.get("reason") in REASONS else "DOORAY_RADAR_STOPPED"
    port = slot_for(files.root, "dooray").port
    return ["Dooray radar  : " + ("RUNNING (lock held)" if lock_held(radar.lock) else "STOPPED")
            + (" / enabled" if radar.enabled() else " / disabled") + " / " + code + f" (browser {port})",
            "Radar success : " + (f"{age} sec ago" if age is not None else "not observed"),
            "Unread radar  : " + ("allowed (list level only)" if radar.unread_allowed()
                                  else "DISABLED (fail-closed; review, then radar-allow-unread)"),
            "Cloud trigger : " + ("on (dispatch after new candidates)" if radar.dispatch_enabled()
                                  else "off (the 30-minute schedule still runs)")]


def status_lines(files, host=None, now=None, targets=page_targets):
    now = time.time() if now is None else now
    row = files.runtime_state()
    control = files.control_state()
    watch_state = read_json(files.watch, {})
    code = reason(watch_state.get("latched") or row["manual_reason"] or row["reason"])
    alert = alert_state(code, row["last_success"], now)
    unified = read_mode(files.local) == "unified"
    port = slot_for(files.root, "portal").port
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
        "Browser mode  : " + ("unified (one Babdoduk Ops Chrome)" if unified else "separate (legacy Portal + Dooray browsers)"),
        *(ops_browser_lines(files.root, state, port, targets=targets) if unified else []),
        "Portal worker : " + ("RUNNING (lock held)" if running else "STOPPED"),
        "Portal CDP    : " + {"verified": "OK", "absent": "ABSENT", "stale": "STALE", "unverified": "OWNER UNVERIFIED"}[state] + f" ({port})",
        "Portal status : " + (alert["severity"] if control["enabled"] else "disabled") + " / " + code,
        "Last success  : " + (f"{age} sec ago (confirmed heartbeat write)" if age is not None else "not observed"),
        *radar_status_lines(files, now),
        "Cloud:", "Supabase      : not tested locally by status",
        "Vercel        : independent", "GitHub cron   : independent"]
