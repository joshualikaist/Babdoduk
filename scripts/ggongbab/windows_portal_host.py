"""Windows-only dedicated Chrome inspection/recovery. Values never leave memory.

One `ResidentHost` describes one dedicated browser (`ops_browser.BrowserSlot`): the unified
Ops Chrome shared by the Portal worker and the Dooray Radar, or - in `separate` mode, the
rollback - one of the two legacy browsers. The port reaches PowerShell as stdin JSON, never
by interpolation, and every check below is per slot: profile, port and loopback address.
"""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
import json
import os
from pathlib import Path
import subprocess
import time

from .ops_browser import (PORTAL_START, START_LOCK, dooray_host, dooray_start_url, slot_for,
                          start_dedicated)
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
    def __init__(self, root, *, role="portal", slot=None, run=powershell, split=split_command,
                 start=start_chrome, verify=verify_resident_owner, sleep=time.sleep):
        self.root = Path(root).resolve()
        self.role = role
        slot = slot or slot_for(self.root, role)
        self.profile, self.port, self.unified = slot.profile, slot.port, slot.unified
        self.owner_code = OWNER_CODES[role]
        self.run, self.split, self.start, self.verify, self.sleep = run, split, start, verify, sleep

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

    def _start(self, log):
        if self.unified:
            # The Ops Chrome opens (or restores) both tabs, whichever worker starts it.
            start_dedicated(self.profile, port=self.port, roles=("portal", "dooray"),
                            dooray_url=dooray_start_url(self.contract_path),
                            mail_host=dooray_host(self.contract_path), start=self.start, log=log)
        elif self.role == "portal":
            # Legacy Portal browser: unchanged behaviour (landing page + session restore).
            self.start(self.profile, port=self.port, start_url=PORTAL_START, log=lambda _: None)
        else:
            start_dedicated(self.profile, port=self.port, roles=("dooray",),
                            dooray_url=dooray_start_url(self.contract_path),
                            mail_host=dooray_host(self.contract_path), start=self.start, log=log)

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

    def ensure(self, *, recover_stale=False, log=lambda _: None):
        lock = start_lock(self.root / ".local" / START_LOCK, sleep=self.sleep) if self.unified else _nothing()
        with lock:
            state, process = self.inspect()
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
                    self._start(log)
                except Exception:
                    raise OpsError(self.owner_code) from None
                log("PORTAL_BROWSER_STARTED")
        self.verify(self.profile, self.port)


class PortalHost(ResidentHost):
    """The Portal worker's dedicated browser under the current mode."""


@contextmanager
def _nothing():
    yield
