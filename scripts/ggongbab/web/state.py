# -*- coding: utf-8 -*-
"""Incremental scan state, stored without personal information.

`.local/ggongbab-mail-state.json` records only what is needed to avoid touching a
mail twice: a stable identifier hash, a subject hash, the received date, when it
was processed and whether it became a task.

Never stored: message bodies, subjects in clear text, e-mail addresses, sender
names, cookies, tokens.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from ..config import KST

STATE_VERSION = 1


def digest(value: str) -> str:
    """Short, stable, one-way. Enough to recognise a mail, useless as content."""
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()[:32]


@dataclass
class MailRecord:
    id_hash: str
    subject_hash: str
    received: Optional[str] = None      # YYYY-MM-DD only, no clock time
    processed_at: str = ""
    registered: bool = False
    outcome: str = ""                   # candidate / filtered / error - never mail text

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentState:
    path: Path
    version: int = STATE_VERSION
    last_run_at: Optional[str] = None
    last_scanned_to: Optional[str] = None
    mails: dict[str, MailRecord] = field(default_factory=dict)

    # -- persistence ---------------------------------------------------
    @classmethod
    def load(cls, path: Path) -> "AgentState":
        state = cls(path=path)
        if not path.exists():
            return state
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return state            # a corrupt state file must not stop the agent
        state.version = int(data.get("version") or STATE_VERSION)
        state.last_run_at = data.get("lastRunAt")
        state.last_scanned_to = data.get("lastScannedTo")
        for row in data.get("mails") or []:
            if not isinstance(row, dict) or not row.get("id_hash"):
                continue
            record = MailRecord(
                id_hash=str(row["id_hash"]),
                subject_hash=str(row.get("subject_hash") or ""),
                received=row.get("received"),
                processed_at=str(row.get("processed_at") or ""),
                registered=bool(row.get("registered")),
                outcome=str(row.get("outcome") or ""),
            )
            state.mails[record.id_hash] = record
        return state

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": STATE_VERSION,
            "note": "hashes only - no subjects, bodies, addresses or cookies",
            "lastRunAt": self.last_run_at,
            "lastScannedTo": self.last_scanned_to,
            "mails": [m.to_json() for m in sorted(self.mails.values(), key=lambda m: m.processed_at)],
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        # Atomic replace so a killed run cannot leave a half-written state file.
        handle, tmp_name = tempfile.mkstemp(dir=str(self.path.parent), prefix=".state-", suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.replace(tmp_name, self.path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    # -- queries -------------------------------------------------------
    def seen(self, mail_id: str) -> bool:
        """True only after a confirmed filter or a confirmed task write.

        A failed write stays absent, or is stored as write-failed, and both are
        retried. An unconfirmed candidate (no post id) is not terminal either.
        """
        record = self.mails.get(digest(mail_id))
        if record is None:
            return False
        if record.outcome == "write-failed":
            return False
        if record.outcome == "candidate" and not record.registered:
            return False
        return True

    def forget(self, mail_id: str) -> None:
        """Drop a non-terminal row so the next run can try the write again."""
        self.mails.pop(digest(mail_id), None)

    def record(self, mail_id: str, subject: str, received: Optional[date], *,
               registered: bool, outcome: str) -> MailRecord:
        record = MailRecord(
            id_hash=digest(mail_id),
            subject_hash=digest(subject),
            received=received.isoformat() if received else None,
            processed_at=datetime.now(KST).isoformat(timespec="seconds"),
            registered=registered,
            outcome=outcome,
        )
        self.mails[record.id_hash] = record
        return record

    def since_last_run(self, default_days: int = 3) -> date:
        """Window start for --since-last-run, with a day of overlap for safety."""
        if self.last_run_at:
            try:
                last = datetime.fromisoformat(self.last_run_at)
                return (last.astimezone(KST) - timedelta(days=1)).date()
            except ValueError:
                pass
        return (datetime.now(KST) - timedelta(days=default_days)).date()

    def mark_run(self, scanned_to: Optional[date] = None) -> None:
        self.last_run_at = datetime.now(KST).isoformat(timespec="seconds")
        if scanned_to:
            self.last_scanned_to = scanned_to.isoformat()

    def prune(self, keep_days: int = 400) -> int:
        """Drop very old records so the file cannot grow without bound."""
        cutoff = (datetime.now(KST) - timedelta(days=keep_days)).date().isoformat()
        stale = [k for k, m in self.mails.items() if (m.received or m.processed_at[:10]) < cutoff]
        for key in stale:
            del self.mails[key]
        return len(stale)
