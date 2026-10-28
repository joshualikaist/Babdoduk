# -*- coding: utf-8 -*-
"""The operator's secrets on this PC (2026-10-29), for example the alert bot token.

Windows keeps them in Credential Manager (dispatch.py). Linux has no such store on the operations
PC (no secret-tool), so each target is one file that only this user can read, outside every
checkout: `~/.config/babdoduk/credentials/` (directory 0700, files 0600). A file that others could
read is refused, as if nothing were stored. Values are never logged, echoed or written to state
files; the activation commands (scripts/alert_push.py) are the only writers.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

from . import dispatch


def store_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "babdoduk" / "credentials"


def where() -> str:
    """Where secrets live, for status lines (never a value)."""
    return "Windows Credential Manager" if os.name == "nt" else str(store_dir())


def _path(target: str, root: Optional[Path]) -> Path:
    return Path(root or store_dir()) / re.sub(r"[^A-Za-z0-9_.-]", "_", target)


def read_credential(target: str, *, root: Optional[Path] = None) -> Optional[str]:
    if os.name == "nt":
        return dispatch.read_windows_credential(target)
    path = _path(target, root)
    try:
        if path.stat().st_mode & 0o077:
            return None
        return path.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def write_credential(secret: str, target: str, *, comment: str = "", user: str = "",
                     root: Optional[Path] = None) -> bool:
    if os.name == "nt":
        return dispatch.write_windows_credential(secret, target, comment=comment, user=user)
    path = _path(target, root)
    temporary = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(secret)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        return True
    except OSError:
        return False


def delete_credential(target: str, *, root: Optional[Path] = None) -> bool:
    if os.name == "nt":
        return dispatch.delete_windows_credential(target)
    try:
        _path(target, root).unlink()
        return True
    except OSError:
        return False
