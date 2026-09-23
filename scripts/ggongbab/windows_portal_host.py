"""Windows-only dedicated Chrome inspection/recovery. Values never leave memory."""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import subprocess
import time

from .ops_policy import PORTAL_PORT
from .ops_storage import OpsError
from .portal_session import verify_resident_owner
from .web.resident import start_chrome

INVENTORY_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
$listeners = @([System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners() | Where-Object { $_.Port -eq 9223 })
$owners = @(Get-NetTCPConnection -State Listen -LocalPort 9223 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique)
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
$proc = Get-CimInstance Win32_Process -Filter ('ProcessId=' + [int]$expected.pid)
if (-not $proc -or $proc.Name -ne 'chrome.exe' -or $proc.CommandLine -cne $expected.command -or $proc.CreationDate.ToUniversalTime().Ticks.ToString() -ne $expected.created) { exit 1 }
$listeners = @([System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners() | Where-Object { $_.Port -eq 9223 })
if ($listeners.Count -gt 0) {
  $owners = @(Get-NetTCPConnection -State Listen -LocalPort 9223 -ErrorAction Stop)
  if ($owners.Count -ne 1 -or $owners[0].LocalAddress -ne '127.0.0.1' -or $owners[0].OwningProcess -ne $expected.pid) { exit 1 }
}
Stop-Process -Id $proc.ProcessId -ErrorAction Stop
'''


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


class PortalHost:
    def __init__(self, root, *, run=powershell, split=split_command, start=start_chrome,
                 verify=verify_resident_owner, sleep=time.sleep):
        self.profile = Path(root).resolve() / ".local" / "portal-browser-profile"
        self.run, self.split, self.start, self.verify, self.sleep = run, split, start, verify, sleep

    def inspect(self):
        try:
            inventory = json.loads(self.run(INVENTORY_SCRIPT))
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
                    if len(profiles) != 1 or ports != ["--remote-debugging-port=9223"] or binds != ["--remote-debugging-address=127.0.0.1"]:
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

    def ensure(self, *, recover_stale=False, log=lambda _: None):
        state, process = self.inspect()
        if state == "unverified" or (state == "stale" and not recover_stale):
            raise OpsError("PORTAL_RESIDENT_OWNER_UNVERIFIED")
        if recover_stale and process is not None:
            self.run(STOP_SCRIPT, process)
            for _ in range(20):
                self.sleep(0.5)
                state, _ = self.inspect()
                if state == "absent":
                    break
            if state != "absent":
                raise OpsError("PORTAL_RESIDENT_OWNER_UNVERIFIED")
            log("PORTAL_BROWSER_RECOVERED")
        if state == "absent":
            # Existing helper retains profile/session restore; no credentials, no cleanup.
            log("PORTAL_BROWSER_ABSENT")
            try:
                self.start(self.profile, port=PORTAL_PORT, start_url="https://portal.kaist.ac.kr/", log=lambda _: None)
            except Exception:
                raise OpsError("PORTAL_RESIDENT_OWNER_UNVERIFIED") from None
            log("PORTAL_BROWSER_STARTED")
        self.verify(self.profile, PORTAL_PORT)
