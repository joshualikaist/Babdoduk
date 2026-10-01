"""Operator control of the Babdoduk Ops Chrome: start, status, recover, mode switch, and the
closing/restarting of the two legacy browsers (cutover and rollback).

Every action inspects ownership first and fails closed: an unknown listener, an ambiguous owner
or unreadable process metadata is never started over, attached to or stopped. Nothing here
prints a URL, title, account, cookie or mail value, deletes a profile, clears cookies or touches
a ledger. Stopping a browser is limited to one positively verified dedicated Chrome.
"""
from __future__ import annotations

from pathlib import Path
import time

from .ops_browser import (MODES, dooray_host, dooray_start_url, ensure_tabs, legacy_slot, read_mode,
                          set_mode, unified_slot)
from .ops_storage import OpsError, lock_held
from .resident_ops import ops_browser_lines

ROLES = ("portal", "dooray")


def contract_path(files):
    return files.local / "dooray-ui.json"


def ops_host(files, **kwargs):
    from .windows_portal_host import ResidentHost
    return ResidentHost(files.root, slot=unified_slot(files.root), **kwargs)


def legacy_host(files, role, **kwargs):
    from .windows_portal_host import ResidentHost
    return ResidentHost(files.root, role=role, slot=legacy_slot(files.root, role), **kwargs)


def worker_locks(files):
    from .dooray_radar import RadarFiles
    return (files.worker_lock, files.watch_lock, RadarFiles(files.root).lock)


def wait_workers_stopped(files, timeout=60, *, sleep=time.sleep, monotonic=time.monotonic, held=lock_held):
    deadline = monotonic() + timeout
    while any(held(lock) for lock in worker_locks(files)):
        if monotonic() >= deadline:
            raise OpsError("OPS_WORKER_UNRESPONSIVE")
        sleep(1)


def status(files, *, host=None, targets=None):
    host = host or ops_host(files)
    state, _ = host.inspect()
    kwargs = {"targets": targets} if targets else {}
    mode = read_mode(files.local)
    return ["Babdoduk Ops Chrome",
            "Browser mode  : " + ("unified (workers use this browser)" if mode == "unified"
                                  else "separate (workers still use the legacy browsers)"),
            *ops_browser_lines(files.root, state, host.port, **kwargs)]


def _verified_or_absent(host):
    state, process = host.inspect()
    if state == "unverified":
        raise OpsError("OPS_BROWSER_UNVERIFIED")
    if state == "stale":
        raise OpsError("OPS_BROWSER_STALE")   # a dedicated process without a listener: use recover
    return state, process


def start(files, *, host=None, tabs=ensure_tabs, log=lambda _: None):
    """Reuse a healthy Ops Chrome, start it only if absent, open only a missing tab."""
    host = host or ops_host(files)
    _verified_or_absent(host)
    try:
        host.ensure(log=log)
    except OpsError as exc:
        raise OpsError("OPS_BROWSER_UNVERIFIED" if "UNVERIFIED" in str(exc) else str(exc)) from None
    except Exception:
        raise OpsError("OPS_BROWSER_UNVERIFIED") from None
    tabs(host.port, dooray_host(contract_path(files)), dooray_start_url(contract_path(files)), log=log)


def recover(files, *, host=None, tabs=ensure_tabs, now=time.time, wait=wait_workers_stopped):
    """Targeted, single-attempt recovery of the Ops Chrome.

    When the workers use it (unified mode) both are disabled first and their locks must be
    released. Only a verified dedicated process that is stale (no listener) or behind a recorded
    CDP attach timeout is stopped - rechecked by PID, creation time, command line and port.
    """
    from .dooray_radar import RadarFiles
    host = host or ops_host(files)
    unified = read_mode(files.local) == "unified"
    if unified:
        files.set_enabled(False, now())
        RadarFiles(files.root).set_enabled(False, now())
        wait(files)
    state, _ = host.inspect()
    if state == "unverified":
        raise OpsError("OPS_BROWSER_UNVERIFIED")
    restart = state == "stale" or (unified and state == "verified"
                                   and files.runtime_state()["reason"] == "PORTAL_CDP_ATTACH_TIMEOUT")
    try:
        host.ensure(recover_stale=restart)
    except OpsError as exc:
        raise OpsError("OPS_BROWSER_UNVERIFIED" if "UNVERIFIED" in str(exc) else str(exc)) from None
    except Exception:
        raise OpsError("OPS_BROWSER_UNVERIFIED") from None
    tabs(host.port, dooray_host(contract_path(files)), dooray_start_url(contract_path(files)))
    return unified


def switch_mode(files, mode, *, held=lock_held):
    """Point both workers at the Ops Chrome (`unified`) or back at the legacy browsers
    (`separate`, the rollback). Only while every worker lock is free; no state is touched."""
    if mode not in MODES:
        raise OpsError("OPS_CONFIGURATION_REQUIRED")
    if any(held(lock) for lock in worker_locks(files)):
        raise OpsError("OPS_WORKERS_STILL_RUNNING")
    set_mode(files.local, mode)


def close_verified_browser(host, *, verify=None, connect=None, sleep=time.sleep):
    """Gracefully close ONE verified dedicated Chrome (CDP Browser.close, so its profile keeps
    its session for a rollback). The CDP endpoint must report the verified PID as its browser
    process before anything is sent. A non-listening (stale) or unverified browser is left alone."""
    state, process = host.inspect()
    if state == "absent":
        return "absent"
    if state != "verified":
        raise OpsError("OPS_BROWSER_UNVERIFIED")
    from .portal_session import verify_resident_owner
    try:
        (verify or verify_resident_owner)(host.profile, host.port)
    except Exception:
        raise OpsError("OPS_BROWSER_UNVERIFIED") from None
    (connect or _cdp_close)(host.port, process["pid"])
    for _ in range(40):
        sleep(0.5)
        state, _ = host.inspect()
        if state == "absent":
            return "closed"
    raise OpsError("OPS_BROWSER_CLOSE_FAILED")   # never escalated to a forced kill


def _cdp_close(port, expected_pid, *, cdp=None):
    """Browser-level only (no page attach), so a discarded tab cannot block the close."""
    from .cdp_lite import LoopbackCdp
    with (cdp or LoopbackCdp)(port) as client:
        info = client.call("SystemInfo.getProcessInfo", timeout=10)
        owners = [p.get("id") for p in (info or {}).get("processInfo", []) if p.get("type") == "browser"]
        if owners != [expected_pid]:
            raise OpsError("OPS_BROWSER_UNVERIFIED")
        client.call("Browser.close", timeout=5)


def close_legacy(files, role, *, host=None, **kwargs):
    """Cutover step: close an old dedicated browser once the workers use the Ops Chrome.
    Its profile directory stays untouched as the rollback asset."""
    if role not in ROLES:
        raise OpsError("OPS_CONFIGURATION_REQUIRED")
    if read_mode(files.local) != "unified":
        raise OpsError("OPS_CONFIGURATION_REQUIRED")   # it is still the workers' browser
    return close_verified_browser(host or legacy_host(files, role), **kwargs)


def start_legacy(files, role, *, host=None):
    """Rollback step: reopen an old dedicated browser from its preserved profile."""
    if role not in ROLES:
        raise OpsError("OPS_CONFIGURATION_REQUIRED")
    if read_mode(files.local) != "separate":
        raise OpsError("OPS_CONFIGURATION_REQUIRED")
    host = host or legacy_host(files, role)
    _verified_or_absent(host)
    try:
        host.ensure()
    except Exception:
        raise OpsError("OPS_BROWSER_UNVERIFIED") from None


def profile_inventory(files):
    """Which dedicated profile directories exist (cutover/rollback evidence). Names only."""
    local = Path(files.local)
    return {name: (local / name).is_dir() for name in
            ("ops-browser-profile", "portal-browser-profile", "dooray-browser-profile")}
