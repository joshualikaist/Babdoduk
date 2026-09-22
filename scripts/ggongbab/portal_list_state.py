"""Atomic LIST detection ledger/outbox: hashes, times and flags, never raw notices."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path

from .ingest_marker import portal_external_key
from .portal_discovery import notice_timestamp
from .prefilter import portal_list_warrants_detail


class ListStateError(Exception):
    def __init__(self, reason="PORTAL_LIST_STATE_UNAVAILABLE"):
        if reason not in {"PORTAL_LIST_STATE_UNAVAILABLE", "PORTAL_HEARTBEAT_WRITE_FAILED"}:
            reason = "PORTAL_LIST_STATE_UNAVAILABLE"
        super().__init__(reason)


def metadata(row):
    stamp = notice_timestamp(row["regDt"]).isoformat()
    public = row["publicYn"] == "Y"
    # This is a title-only Stage A signal, never a food-provided assertion.
    candidate = public and portal_list_warrants_detail(row["pstTtl"])
    fingerprint = hashlib.sha256(json.dumps(
        [stamp, row["pstTtl"], public], ensure_ascii=False).encode()).hexdigest()
    return portal_external_key(str(row["pstNo"])), {
        "reg_dt": stamp, "fingerprint": fingerprint, "public": public, "candidate": candidate,
    }


class PortalListState:
    def __init__(self, path):
        self.path = Path(path)
        self.data = {"version": 1, "initialized": False, "lower_bound": None,
                     "notices": {}, "pending": {}}
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                self._validate(loaded)
                self.data = loaded
            except Exception:
                # Corruption must not silently reset the baseline/dedup ledger.
                raise ListStateError() from None

    @staticmethod
    def _validate(data):
        if (not isinstance(data, dict)
                or set(data) != {"version", "initialized", "lower_bound", "notices", "pending"}
                or data["version"] != 1 or type(data["initialized"]) is not bool
                or (data["lower_bound"] is not None and not notice_timestamp(data["lower_bound"]))):
            raise ListStateError()
        for name in ("notices", "pending"):
            if not isinstance(data[name], dict):
                raise ListStateError()
            for key, row in data[name].items():
                if (not re.fullmatch(r"[a-f0-9]{64}", key)
                        or not isinstance(row, dict)
                        or set(row) != {"reg_dt", "fingerprint", "public", "candidate"}
                        or not notice_timestamp(row["reg_dt"])
                        or not re.fullmatch(r"[a-f0-9]{64}", row["fingerprint"])
                        or type(row["public"]) is not bool or type(row["candidate"]) is not bool):
                    raise ListStateError()
        if any(not row["public"] or not row["candidate"] for row in data["pending"].values()):
            raise ListStateError()

    def commit(self, data):
        self._validate(data)
        tmp = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".portal-list-", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
            self.data = deepcopy(data)
        except Exception:
            raise ListStateError() from None
        finally:
            if tmp and os.path.exists(tmp):
                os.unlink(tmp)


@contextmanager
def poller_lock(path):
    """OS lock releases on crashes; a stale filename never blocks recovery."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    locked = False
    try:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError:
            raise ListStateError() from None
        yield
    finally:
        if locked:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()
