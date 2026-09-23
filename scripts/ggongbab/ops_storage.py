"""Small atomic operational files and bounded allowlist-only logs under .local."""
from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import tempfile

from .ops_policy import REASONS, reason
from .portal_list_state import ListStateError, poller_lock


class OpsError(Exception):
    def __init__(self, code="OPS_STATE_UNAVAILABLE"):
        super().__init__(reason(code))


def read_json(path, default):
    try:
        if not path.exists():
            return default
        if path.stat().st_size > 16384:
            raise ValueError()
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError()
        return data
    except Exception:
        raise OpsError() from None


def atomic_json(path, data):
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".ops-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, allow_nan=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        raise OpsError() from None
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)  # only our newly created temporary operational file


def lock_held(path):
    try:
        with poller_lock(path):
            return False
    except ListStateError:
        return True


class _SafeRotatingHandler(RotatingFileHandler):
    def handleError(self, record):
        raise OpsError() from None  # no logging traceback/path/exception text


class SafeLog:
    """No free text is accepted. Each process owns a separate rotating file."""
    def __init__(self, path: Path, max_bytes=5 * 1024 * 1024, backups=3):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.handler = _SafeRotatingHandler(path, maxBytes=max_bytes, backupCount=backups, encoding="utf-8")
        self.handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        # Roll an existing oversized legacy file immediately, even before first log.
        if path.stat().st_size >= max_bytes:
            self.handler.doRollover()

    def __call__(self, code):
        if isinstance(code, str) and code in REASONS:
            self.handler.emit(logging.LogRecord("ops", logging.INFO, "", 0, code, (), None))

    def close(self):
        self.handler.close()
