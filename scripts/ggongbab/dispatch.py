# -*- coding: utf-8 -*-
"""Low-latency trigger (Option A): ask GitHub to run the existing cloud refresh now.

The local mailbox radar registers a candidate task, then calls `request_refresh`. That
sends one workflow_dispatch for `ggongbab-refresh.yml` on main; the cloud job stays the
single writer (collection -> AI -> validation -> Supabase -> latest.json), and the
30-minute schedule remains the safety net. See docs/GGONGBAB_TRIGGER.md.

Safety properties, each covered by tests:
  * the ref is always main (not a parameter), and the workflow itself refuses any other ref;
  * the token is read from Windows Credential Manager at call time and never logged,
    returned or written to disk; without a stored token nothing is sent (NOT_CONFIGURED);
  * debounce: at most one dispatch per MIN_INTERVAL_SECONDS. A candidate that arrives
    inside the window sets `pending`, and the next radar cycle dispatches it, so nothing
    waits for the schedule; at most DAILY_CAP dispatches per KST day;
  * results are fixed codes only.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from .config import KST

REPOSITORY = "joshualikaist/Babdoduk"
WORKFLOW = "ggongbab-refresh.yml"
REF = "main"
DISPATCH_URL = f"https://api.github.com/repos/{REPOSITORY}/actions/workflows/{WORKFLOW}/dispatches"
CREDENTIAL_TARGET = "babdoduk/ggongbab-refresh-dispatch"
MIN_INTERVAL_SECONDS = 300
DAILY_CAP = 60
SOURCES = ("radar", "manual")
UA = "BabdodukGgongbabRadar/1.0 (+https://github.com/joshualikaist/Babdoduk)"

NOT_CONFIGURED = "DISPATCH_NOT_CONFIGURED"
NOTHING_NEW = "DISPATCH_NOTHING_NEW"
DEBOUNCED = "DISPATCH_DEBOUNCED"
DAILY_LIMIT = "DISPATCH_DAILY_CAP"
DISPATCHED = "DISPATCHED"
AUTH_FAILED = "DISPATCH_AUTH_FAILED"
REJECTED = "DISPATCH_REJECTED"
TRANSPORT_FAILED = "DISPATCH_TRANSPORT_FAILED"


@dataclass
class DispatchState:
    day: str = ""
    count: int = 0
    last_dispatch_at: float = 0.0
    pending: bool = False
    last_result: str = ""

    @classmethod
    def load(cls, path: Path) -> "DispatchState":
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        return cls(day=str(data.get("day") or ""), count=int(data.get("count") or 0),
                   last_dispatch_at=float(data.get("last_dispatch_at") or 0.0),
                   pending=bool(data.get("pending")), last_result=str(data.get("last_result") or ""))

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".dispatch-", suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as fh:
                json.dump(asdict(self), fh)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


# --- Windows Credential Manager (generic credential, UTF-16LE blob) -----------------
def read_windows_credential(target: str = CREDENTIAL_TARGET) -> Optional[str]:
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                    ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME),
                    ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                    ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                    ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]

    advapi = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    advapi.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                 ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]
    advapi.CredReadW.restype = wintypes.BOOL
    advapi.CredFree.argtypes = [ctypes.c_void_p]
    pointer = ctypes.POINTER(CREDENTIAL)()
    if not advapi.CredReadW(target, 1, 0, ctypes.byref(pointer)):
        return None
    try:
        blob = ctypes.string_at(pointer.contents.CredentialBlob, pointer.contents.CredentialBlobSize)
        return blob.decode("utf-16-le") or None
    finally:
        advapi.CredFree(pointer)


def write_windows_credential(secret: str, target: str = CREDENTIAL_TARGET) -> bool:
    """Operator activation step only (docs/GGONGBAB_TRIGGER.md); never called by the radar."""
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                    ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME),
                    ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.c_char_p),
                    ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                    ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]

    blob = secret.encode("utf-16-le")
    credential = CREDENTIAL(Flags=0, Type=1, TargetName=target, Comment="Babdoduk refresh dispatch (Actions: write)",
                            CredentialBlobSize=len(blob), CredentialBlob=blob, Persist=2,
                            AttributeCount=0, Attributes=None, TargetAlias=None, UserName="github-dispatch")
    advapi = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    advapi.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIAL), wintypes.DWORD]
    advapi.CredWriteW.restype = wintypes.BOOL
    return bool(advapi.CredWriteW(ctypes.byref(credential), 0))


def delete_windows_credential(target: str = CREDENTIAL_TARGET) -> bool:
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes

    advapi = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    advapi.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    advapi.CredDeleteW.restype = wintypes.BOOL
    return bool(advapi.CredDeleteW(target, 1, 0))


# --- request ----------------------------------------------------------------------
def request_refresh(state_path: Path, *, new_candidates: bool, source: str = "radar",
                    now: Optional[float] = None,
                    token_provider: Callable[[], Optional[str]] = read_windows_credential,
                    opener: Callable = urllib.request.urlopen) -> str:
    """Dispatch the cloud refresh when something new is waiting. Returns a fixed code."""
    if source not in SOURCES:
        raise ValueError("unknown dispatch source")
    now = time.time() if now is None else now
    state = DispatchState.load(state_path)
    today = datetime.fromtimestamp(now, KST).date().isoformat()
    if state.day != today:
        state.day, state.count = today, 0
    if new_candidates:
        state.pending = True
    if not state.pending:
        return NOTHING_NEW
    if state.last_dispatch_at and now - state.last_dispatch_at < MIN_INTERVAL_SECONDS:
        state.last_result = DEBOUNCED
        state.save(state_path)
        return DEBOUNCED
    if state.count >= DAILY_CAP:
        state.last_result = DAILY_LIMIT
        state.save(state_path)
        return DAILY_LIMIT
    token = token_provider()
    if not token:
        state.last_result = NOT_CONFIGURED
        state.save(state_path)
        return NOT_CONFIGURED
    body = json.dumps({"ref": REF, "inputs": {"mode": "full", "source": source}}).encode("utf-8")
    request = urllib.request.Request(DISPATCH_URL, data=body, method="POST", headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json", "User-Agent": UA})
    del token
    try:
        with opener(request, timeout=15) as response:
            status = int(getattr(response, "status", 0) or response.getcode())
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
    except (urllib.error.URLError, TimeoutError, OSError):
        state.last_result = TRANSPORT_FAILED      # still pending: the next cycle retries
        state.save(state_path)
        return TRANSPORT_FAILED
    finally:
        request.headers.pop("Authorization", None)
    if status in (200, 204):
        state.last_dispatch_at, state.count, state.pending = now, state.count + 1, False
        state.last_result = DISPATCHED
    else:
        state.last_result = AUTH_FAILED if status in (401, 403) else REJECTED
    state.save(state_path)
    return state.last_result
