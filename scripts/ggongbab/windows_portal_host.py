"""Dedicated Chrome inspection/recovery (Windows; Linux through /proc). Values never leave memory.

One `ResidentHost` describes one dedicated browser (`ops_browser.BrowserSlot`): the unified
Ops Chrome shared by the Portal worker and the Dooray Radar, or - in `separate` mode, the
rollback - one of the two legacy browsers. The port reaches PowerShell as stdin JSON, never
by interpolation, and every check below is per slot: profile, port and loopback address.
On Linux the same two queries are answered from /proc (`linux_proc`), with argv from `cmdline`.
"""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from .ops_browser import (PORTAL_START, START_LOCK, dooray_host, dooray_start_url, slot_for,
                          start_dedicated, wake_tabs)
from .ops_storage import OpsError
from .portal_list_state import ListStateError, poller_lock
from .portal_session import verify_resident_owner
from .web.resident import start_chrome

INVENTORY_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
$expected = [Console]::In.ReadToEnd() | ConvertFrom-Json
$port = [int]$expected.port
$listeners = @([System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners() | Where-Object { $_.Port -eq $port })
$owners = @(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique)
$processes = @(Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" | ForEach-Object {
  @{ pid = [int]$_.ProcessId; command = $_.CommandLine; created = $_.CreationDate.ToUniversalTime().Ticks.ToString() }
})
@{ listening = ($listeners.Count -gt 0); loopback = ($listeners.Count -eq 1 -and $listeners[0].Address.ToString() -eq '127.0.0.1'); owners = $owners; processes = $processes } | ConvertTo-Json -Depth 4 -Compress
'''

# Data enters via stdin JSON, not shell interpolation. Recheck identity immediately
# before stopping exactly one verified process; PID reuse/changed ownership aborts.
STOP_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
$expected = [Console]::In.ReadToEnd() | ConvertFrom-Json
$port = [int]$expected.port
$proc = Get-CimInstance Win32_Process -Filter ('ProcessId=' + [int]$expected.pid)
if (-not $proc -or $proc.Name -ne 'chrome.exe' -or $proc.CommandLine -cne $expected.command -or $proc.CreationDate.ToUniversalTime().Ticks.ToString() -ne $expected.created) { exit 1 }
$listeners = @([System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners() | Where-Object { $_.Port -eq $port })
if ($listeners.Count -gt 0) {
  $owners = @(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction Stop)
  if ($owners.Count -ne 1 -or $owners[0].LocalAddress -ne '127.0.0.1' -or $owners[0].OwningProcess -ne $expected.pid) { exit 1 }
}
Stop-Process -Id $proc.ProcessId -ErrorAction Stop
'''

OWNER_CODES = {"portal": "PORTAL_RESIDENT_OWNER_UNVERIFIED", "dooray": "DOORAY_BROWSER_UNVERIFIED"}
# One process snapshot can catch a Chrome process mid-exit (no command line yet or any more) or a
# process query that is still slow after the PC wakes. Measured 2026-10-01 22:12: one such read
# right after a resume latched the Portal worker for 10 days. Re-read before failing closed: a real
# unknown or ambiguous owner stays unverified in every snapshot, so this only delays that verdict.
OWNER_RETRIES = 3
OWNER_RETRY_SECONDS = 5


def powershell(script, payload=None):
    if os.name != "nt":
        raise OpsError("PORTAL_RESIDENT_OWNER_UNVERIFIED")
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            input=json.dumps(payload) if payload is not None else None, capture_output=True,
            text=True, timeout=15, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
        return result.stdout
    except Exception:
        raise OpsError("PORTAL_RESIDENT_OWNER_UNVERIFIED") from None


def linux_run(script, payload=None):
    """The Linux answer to INVENTORY_SCRIPT / STOP_SCRIPT, with the same fail-closed code."""
    from . import linux_proc
    try:
        if script is INVENTORY_SCRIPT:
            return json.dumps(linux_proc.inventory(int(payload["port"])))
        if script is STOP_SCRIPT:
            linux_proc.stop_verified(payload)
            return ""
    except Exception:
        raise OpsError("PORTAL_RESIDENT_OWNER_UNVERIFIED") from None
    raise OpsError("PORTAL_RESIDENT_OWNER_UNVERIFIED")


def linux_split(command):
    """/proc argv is already split; anything else cannot be trusted."""
    if not isinstance(command, list) or not all(isinstance(a, str) for a in command):
        raise OpsError("PORTAL_RESIDENT_OWNER_UNVERIFIED")
    return list(command)


def platform_tools():
    """(run, split) for this OS. Any OS other than Windows or Linux fails closed in run()."""
    if os.name == "nt":
        return powershell, split_command
    if sys.platform.startswith("linux"):
        return linux_run, linux_split
    return powershell, split_command


def split_command(command):
    count = ctypes.c_int()
    split = ctypes.windll.shell32.CommandLineToArgvW
    split.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    split.restype = ctypes.POINTER(ctypes.c_wchar_p)
    argv = split(command, ctypes.byref(count))
    if not argv:
        raise OpsError("PORTAL_RESIDENT_OWNER_UNVERIFIED")
    try:
        return [argv[i] for i in range(count.value)]
    finally:
        free = ctypes.windll.kernel32.LocalFree
        free.argtypes = [ctypes.c_void_p]
        free(argv)


@contextmanager
def start_lock(path, *, timeout=60, sleep=time.sleep):
    """Serialise starts of one shared browser (operator START vs a worker bootstrap)."""
    waited = 0
    while True:
        lock = poller_lock(path)
        try:
            lock.__enter__()
            break
        except ListStateError:
            if waited >= timeout:
                raise OpsError("OPS_BROWSER_START_BUSY") from None
            sleep(1)
            waited += 1
    try:
        yield
    finally:
        lock.__exit__(None, None, None)


class ResidentHost:
    def __init__(self, root, *, role="portal", slot=None, run=None, split=None,
                 start=start_chrome, verify=verify_resident_owner, sleep=time.sleep, wake=wake_tabs):
        self.root = Path(root).resolve()
        self.role = role
        slot = slot or slot_for(self.root, role)
        self.profile, self.port, self.unified = slot.profile, slot.port, slot.unified
        self.owner_code = OWNER_CODES[role]
        default_run, default_split = platform_tools()
        run, split = run or default_run, split or default_split
        self.run, self.split, self.start, self.verify, self.sleep = run, split, start, verify, sleep
        self.wake = wake

    @property
    def contract_path(self):
        return self.root / ".local" / "dooray-ui.json"

    def inspect(self):
        try:
            inventory = json.loads(self.run(INVENTORY_SCRIPT, {"port": self.port}))
            if (type(inventory["listening"]) is not bool or type(inventory["loopback"]) is not bool
                    or not isinstance(inventory["owners"], list) or not isinstance(inventory["processes"], list)):
                raise ValueError()
            dedicated = []
            for process in inventory["processes"]:
                if not process.get("command"):
                    # Inaccessible Chrome metadata cannot prove the profile is absent.
                    raise ValueError()
                args = self.split(process["command"])
                profiles = [a.split("=", 1)[1] for a in args if a.startswith("--user-data-dir=")]
                if any(Path(p).resolve() == self.profile for p in profiles):
                    ports = [a for a in args if a.startswith("--remote-debugging-port=")]
                    binds = [a for a in args if a.startswith("--remote-debugging-address=")]
                    if (len(profiles) != 1 or ports != [f"--remote-debugging-port={self.port}"]
                            or binds != ["--remote-debugging-address=127.0.0.1"]):
                        # Renderers with profile flags aren't independent browser owners.
                        if any(a.startswith("--type=") for a in args):
                            continue
                        raise ValueError()
                    if type(process["pid"]) is not int or process["pid"] <= 0 or not str(process["created"]).isdigit():
                        raise ValueError()
                    dedicated.append(process)
            if len(dedicated) > 1:
                raise ValueError()
            if inventory["listening"]:
                if not inventory["loopback"] or len(dedicated) != 1 or inventory["owners"] != [dedicated[0]["pid"]]:
                    raise ValueError()
                return "verified", dedicated[0]
            return ("stale", dedicated[0]) if dedicated else ("absent", None)
        except Exception:
            return "unverified", None

    def _start(self, log, minimized=False):
        if self.unified:
            # The Ops Chrome opens (or restores) both tabs, whichever worker starts it.
            start_dedicated(self.profile, port=self.port, roles=("portal", "dooray"),
                            dooray_url=dooray_start_url(self.contract_path),
                            mail_host=dooray_host(self.contract_path), start=self.start, log=log,
                            minimized=minimized)
        elif self.role == "portal":
            # Legacy Portal browser: unchanged behaviour (landing page + session restore).
            self.start(self.profile, port=self.port, start_url=PORTAL_START, log=lambda _: None,
                       minimized=minimized)
        else:
            start_dedicated(self.profile, port=self.port, roles=("dooray",),
                            dooray_url=dooray_start_url(self.contract_path),
                            mail_host=dooray_host(self.contract_path), start=self.start, log=log,
                            minimized=minimized)

    def stop_verified(self, process):
        """Stop exactly one process that inspect() just verified, rechecked by STOP_SCRIPT."""
        self.run(STOP_SCRIPT, dict(process, port=self.port))
        state = "unverified"
        for _ in range(20):
            self.sleep(0.5)
            state, _ = self.inspect()
            if state == "absent":
                return
        raise OpsError(self.owner_code)

    def _inspect_settled(self):
        state, process = self.inspect()
        for _ in range(OWNER_RETRIES):
            if state != "unverified":
                break
            self.sleep(OWNER_RETRY_SECONDS)
            state, process = self.inspect()
        return state, process

    def _verify_settled(self):
        for attempt in range(OWNER_RETRIES + 1):
            try:
                return self.verify(self.profile, self.port)
            except Exception:
                if attempt == OWNER_RETRIES:
                    raise
                self.sleep(OWNER_RETRY_SECONDS)

    def ensure(self, *, recover_stale=False, log=lambda _: None, minimized=False):
        """`minimized`: a start that no person asked for (worker, watchdog) opens minimized and
        in the background; an operator's start stays a normal window for a manual login."""
        lock = start_lock(self.root / ".local" / START_LOCK, sleep=self.sleep) if self.unified else _nothing()
        with lock:
            state, process = self._inspect_settled()
            if state == "unverified" or (state == "stale" and not recover_stale):
                raise OpsError(self.owner_code)
            if recover_stale and process is not None:
                self.stop_verified(process)
                state = "absent"
                log("PORTAL_BROWSER_RECOVERED")
            if state == "absent":
                # Existing helper retains profile/session restore; no credentials, no cleanup.
                log("PORTAL_BROWSER_ABSENT")
                try:
                    self._start(log, minimized)
                except Exception:
                    raise OpsError(self.owner_code) from None
                log("PORTAL_BROWSER_STARTED")
        self._verify_settled()
        # Only after the owner is verified: restore a tab Chrome discarded or froze, so it
        # cannot block a Playwright attach (OPS_BROWSER_TAB_UNRESPONSIVE when it stays dead).
        woke = self.wake(self.port, dooray_host(self.contract_path))
        if woke["restored"]:
            log("OPS_BROWSER_TAB_RESTORED")
        return woke


class PortalHost(ResidentHost):
    """The Portal worker's dedicated browser under the current mode."""


@contextmanager
def _nothing():
    yield
