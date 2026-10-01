"""Proof that one Ops Chrome serves the Portal worker and the Dooray Radar at the same time.

Run from the operations checkout against the unified Ops Chrome, before the workers are
switched to it (and again afterwards if wanted). It changes no worker state: no Portal ledger,
baseline, pending entry, heartbeat or announcement; no Dooray task, mail state, flash ledger,
dispatch, runtime file or unread latch. Its output is counts, booleans, one PID and one process
creation time (`.local/ops-browser-proof.json`); never a URL, title, subject, id or cookie.

Each cycle:
  1. snapshot: the verified owner (pid + creation time), page targets by role, window ids;
  2. Portal: the existing memory-only handoff (owner check, one Portal context, JSESSIONID) and
     ONE LIST GET of page 1; the in-memory client is then closed;
  3. Dooray (every k-th cycle): owner check, attach, the Dooray tab only, one dry-run
     list-level scan under the unread guard;
     2 and 3 are two CDP clients (two threads, two Playwright drivers). A barrier holds both
     attached at the same time before either does its work;
  4. snapshot again: same process, same tabs on the same roles, no new page or window.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
import threading
import time

from .config import KST
from .ops_browser import dooray_host, page_targets, role_of, unified_slot
from .ops_storage import OpsError, atomic_json

BARRIER_SECONDS = 60
JOB_SECONDS = 240
PROOF_FILE = "ops-browser-proof.json"
FATAL = frozenset({"OPS_BROWSER_CHANGED", "DOORAY_UNREAD_INVARIANT_BROKEN", "DOORAY_AUTH_REQUIRED",
                   "DOORAY_CONTRACT_CHANGED", "DOORAY_BROWSER_UNVERIFIED", "PORTAL_LIST_AUTH_REQUIRED",
                   "PORTAL_RESIDENT_OWNER_UNVERIFIED", "PORTAL_UI_CHANGED", "OPS_BROWSER_UNVERIFIED"})


def window_ids(port, *, cdp=None):
    """Distinct Chrome window ids of the page targets. Browser-level CDP only, so a discarded
    tab cannot block it (Target.getTargets + Browser.getWindowForTarget)."""
    from .cdp_lite import LoopbackCdp
    with (cdp or LoopbackCdp)(port) as client:
        targets = (client.call("Target.getTargets") or {}).get("targetInfos")
        if targets is None:
            raise OpsError("OPS_BROWSER_TARGETS_UNAVAILABLE")
        ids = set()
        for info in targets:
            if info.get("type") == "page":
                window = client.call("Browser.getWindowForTarget", {"targetId": info["targetId"]})
                if not window:
                    raise OpsError("OPS_BROWSER_TARGETS_UNAVAILABLE")
                ids.add(window["windowId"])
        return ids


def snapshot(host, port, mail_host, *, targets=page_targets, windows=window_ids):
    state, process = host.inspect()
    if state != "verified":
        raise OpsError("OPS_BROWSER_UNVERIFIED")
    roles = {page["id"]: role_of(page["url"], mail_host) for page in targets(port)}
    return {"pid": process["pid"], "created": str(process["created"]), "roles": roles,
            "windows": set(windows(port))}


def compare(before, after):
    """Changes between two snapshots, as counts: closures, cross-role navigation, additions."""
    role_tabs = {tid: role for tid, role in before["roles"].items() if role}
    return {
        "browser_changed": int(before["pid"] != after["pid"] or before["created"] != after["created"]),
        "tabs_closed": sum(1 for tid in role_tabs if tid not in after["roles"]),
        "cross_navigation": sum(1 for tid, role in role_tabs.items()
                                if tid in after["roles"] and after["roles"][tid] != role),
        "pages_added": len(set(after["roles"]) - set(before["roles"])),
        "windows_added": len(after["windows"] - before["windows"]),
    }


def portal_code(exc):
    from .portal_session import ListTransportError, safe_reason_code
    from .web.exit_codes import AuthRequired, UiContractError
    if isinstance(exc, AuthRequired):
        return safe_reason_code(exc)
    if isinstance(exc, UiContractError):
        return "PORTAL_UI_CHANGED"
    if isinstance(exc, ListTransportError):
        return exc.reason
    return "PORTAL_SESSION_HANDOFF_FAILED"


def dooray_code(exc):
    from . import dooray_radar as radar
    from .web.exit_codes import AuthRequired, UiContractError
    if isinstance(exc, radar.BrowserUnverified):
        return radar.UNVERIFIED
    if isinstance(exc, radar.UnreadInvariantBroken):
        return radar.INVARIANT
    if isinstance(exc, AuthRequired):
        return radar.AUTH
    if isinstance(exc, UiContractError):
        return radar.TRANSPORT if radar.transient_list_failure(exc) else radar.CONTRACT
    if str(exc) == radar.BROWSER:
        return radar.BROWSER
    return radar.TRANSPORT


def portal_job(slot, mail_host="", wake=None):
    """The worker's own handoff + one LIST GET, attached through a barrier-holding wrapper.
    Like the worker (ResidentHost.ensure), a discarded/frozen tab is restored first."""
    def job(barrier):
        from .ops_browser import wake_tabs
        from .portal_session import PortalSessionProvider
        from .web.resident import resident_session
        woke = (wake or wake_tabs)(slot.port, mail_host)
        marks = {"restored": woke["restored"]}

        @contextmanager
        def attach(*args, **kwargs):
            with resident_session(*args, **kwargs) as session:
                marks["attached"] = time.monotonic()
                barrier.wait()
                yield session
            marks["detached"] = time.monotonic()

        client = PortalSessionProvider(slot.profile, slot.port, attach=attach).acquire()
        client.close()   # memory only: no ledger, heartbeat or announcement exists here
        return {"ok": True, **marks}
    return job


def dooray_job(slot, root, contract, mail_host, now):
    """One dry-run Radar scan of the Dooray tab: no task, state, flash, dispatch or latch."""
    def job(barrier):
        from . import dooray_radar as radar
        from .portal_session import verify_resident_owner
        from .web.mail_reader import list_mails_paged
        from .web.resident import resident_session
        from .web.state import AgentState, digest
        files = radar.RadarFiles(root)
        try:
            verify_resident_owner(slot.profile, slot.port)
        except Exception:
            raise radar.BrowserUnverified() from None
        from .ops_browser import wake_tabs
        woke = wake_tabs(slot.port, mail_host)            # as the Radar does before attaching
        if "dooray" in woke["roles"]:
            time.sleep(15)                                # a restored inbox settles first
        headers = []

        def listing(session, **kwargs):
            rows = list_mails_paged(session, **kwargs)
            headers.extend(rows)
            return rows

        marks = {}
        with resident_session(slot.profile, contract, start_url="", port=slot.port, attach_only=True,
                              log=lambda _: None) as session:
            session.page = radar.dooray_page(session.context, mail_host)
            marks["attached"] = time.monotonic()
            barrier.wait()
            guard = radar.RequestGuard(session.context, mail_host)
            with guard.watching():
                result = radar.scan_once(session, AgentState.load(files.mail_state), None, list_mails=listing,
                                         now=now, since=now - timedelta(seconds=radar.FIRST_WINDOW_SECONDS),
                                         allow_unread=files.unread_allowed(), dry_run=True, guard=guard)
            violations = len(guard.violations)
        marks["detached"] = time.monotonic()
        return {"ok": True, "counts": result.counts(), "guard_violations": violations, **marks,
                "restored": woke["restored"],
                "unread": {digest(h.mail_id) for h in headers if h.unread},
                "read": {digest(h.mail_id) for h in headers if h.unread is False}}
    return job


def run_jobs(jobs):
    """Run each job in its own thread; a failing job aborts the barrier so the other never hangs."""
    barrier = threading.Barrier(len(jobs), timeout=BARRIER_SECONDS)
    results = {}

    def runner(name, job, code):
        try:
            results[name] = job(barrier)
        except BaseException as exc:  # noqa: BLE001 - reported as a fixed code only
            barrier.abort()
            results[name] = {"ok": False, "code": code(exc)}

    threads = [threading.Thread(target=runner, args=item, daemon=True) for item in jobs]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(JOB_SECONDS)
    for name, _, _ in jobs:
        results.setdefault(name, {"ok": False, "code": "OPS_PROOF_JOB_TIMEOUT"})
    return results


def overlapped(a, b):
    return all(k in r for r in (a, b) for k in ("attached", "detached")) and \
        a["attached"] < b["detached"] and b["attached"] < a["detached"]


def run_proof(root, *, cycles=10, interval=60, dooray_every=3, host=None, contract=None,
              snap=None, portal=None, dooray=None, sleep=time.sleep, clock=time.time, out=print):
    from .windows_portal_host import ResidentHost
    root = Path(root).resolve()
    slot = unified_slot(root)
    host = host or ResidentHost(root, slot=slot)
    contract_path = root / ".local" / "dooray-ui.json"
    mail_host = dooray_host(contract_path)
    if contract is None:
        from .web.ui_contract import load_contract
        contract = load_contract(contract_path)
        contract.require_ready()
        if not contract.read_state_key:
            raise OpsError("OPS_CONFIGURATION_REQUIRED")   # the unread guard needs the read flag
    snap = snap or (lambda: snapshot(host, slot.port, mail_host))
    portal = portal or portal_job(slot, mail_host)
    dooray = dooray or (lambda now: dooray_job(slot, root, contract, mail_host, now))
    report = {"started": round(clock(), 3), "cycles_planned": cycles, "cycles_run": 0, "port": slot.port,
              "portal_ok": 0, "portal_failed": 0, "dooray_ok": 0, "dooray_failed": 0, "overlaps": 0,
              "failures": [], "browser_changed": 0, "tabs_closed": 0, "cross_navigation": 0,
              "pages_added": 0, "windows_added": 0, "guard_violations": 0,
              "unread_still_unread": 0, "unread_became_read": 0, "tabs_restored": 0}
    first = None
    unread_seen = set()
    stop = False
    for cycle in range(cycles):
        if cycle:
            sleep(interval)
        before = snap()
        first = first or before
        jobs = [("portal", portal, portal_code)]
        with_dooray = cycle % dooray_every == 0
        if with_dooray:
            jobs.append(("dooray", dooray(datetime.fromtimestamp(clock(), KST)), dooray_code))
        results = run_jobs(jobs)
        after = snap()
        changes = compare(before, after)
        changes["browser_changed"] |= int(first["pid"] != after["pid"] or first["created"] != after["created"])
        for key, value in changes.items():
            report[key] += value
        if changes["browser_changed"]:
            report["failures"].append("OPS_BROWSER_CHANGED")
        portal_result = results["portal"]
        report["portal_ok" if portal_result["ok"] else "portal_failed"] += 1
        report["tabs_restored"] += sum(r.get("restored", 0) for r in results.values())
        if not portal_result["ok"]:
            report["failures"].append(portal_result["code"])
        if with_dooray:
            dooray_result = results["dooray"]
            report["dooray_ok" if dooray_result["ok"] else "dooray_failed"] += 1
            if dooray_result["ok"]:
                report["guard_violations"] += dooray_result["guard_violations"]
                report["dooray_counts"] = dooray_result["counts"]
                # Informational: a mail read on another device also moves unread -> read.
                report["unread_became_read"] += len(unread_seen & dooray_result["read"])
                unread_seen = (unread_seen - dooray_result["read"]) | dooray_result["unread"]
                report["unread_still_unread"] = len(unread_seen)
                report["overlaps"] += int(overlapped(portal_result, dooray_result))
            else:
                report["failures"].append(dooray_result["code"])
        report["cycles_run"] = cycle + 1
        report["chrome_pid"], report["chrome_created"] = after["pid"], after["created"]
        report["windows"] = len(after["windows"])
        report["tabs"] = {role: sum(1 for r in after["roles"].values() if r == role) for role in ("portal", "dooray")}
        out(f"cycle {cycle + 1}/{cycles}: portal={'ok' if portal_result['ok'] else portal_result['code']}"
            + (f" dooray={'ok' if results['dooray']['ok'] else results['dooray']['code']}" if with_dooray else "")
            + f" pid_stable={'no' if report['browser_changed'] else 'yes'} windows={report['windows']}"
            + f" tabs=portal:{report['tabs']['portal']},dooray:{report['tabs']['dooray']}")
        stop = bool(FATAL.intersection(report["failures"]) or report["guard_violations"]
                    or report["cross_navigation"] or report["tabs_closed"])
        if stop:
            break
    dooray_runs = report["dooray_ok"] + report["dooray_failed"]
    report["finished"] = round(clock(), 3)
    report["result"] = "PASS" if (not stop and report["cycles_run"] == cycles and not report["failures"]
                                  and report["portal_ok"] == cycles and report["dooray_ok"] == dooray_runs
                                  and report["overlaps"] == dooray_runs and report["windows"] == 1
                                  and not any(report[k] for k in ("browser_changed", "tabs_closed",
                                              "cross_navigation", "pages_added", "windows_added",
                                              "guard_violations"))) else "FAIL"
    report["failures"] = sorted(set(report["failures"]))
    atomic_json(root / ".local" / PROOF_FILE, report)
    return report
