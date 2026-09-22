# -*- coding: utf-8 -*-
"""Privacy-safe heartbeat for the resident Dooray agent.

The row is operational metadata only. Mail subject, sender, body, preview,
cookies, tokens, browser profiles, and identifier-bearing URLs are not fields
and are rejected if a caller tries to attach them.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from .config import KST

AGENT_ID = "dooray-resident"
STATUSES = ("healthy", "auth_required", "ui_changed", "collector_error", "pipeline_error")
FIELDS = (
    "agent_id",
    "last_scan_at",
    "last_success_at",
    "last_publish_at",
    "status",
    "exit_class",
    "auth_required",
    "ui_contract_changed",
    "version",
)


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=KST)
    return value.astimezone(KST).isoformat(timespec="seconds")


def build_heartbeat(*, status: str, exit_class: str, auth_required: bool = False,
                    ui_contract_changed: bool = False, last_scan_at: Optional[datetime] = None,
                    last_success_at: Optional[datetime] = None, last_publish_at: Optional[datetime] = None,
                    version: str = "dooray-resident", agent_id: str = AGENT_ID) -> dict[str, Any]:
    if status not in STATUSES:
        raise ValueError("unknown heartbeat status")
    if any(sep in agent_id for sep in (" ", "/", "?", "@")):
        raise ValueError("agent_id must be a fixed source name")
    row = {
        "agent_id": agent_id,
        "last_scan_at": _iso(last_scan_at),
        "last_success_at": _iso(last_success_at),
        "last_publish_at": _iso(last_publish_at),
        "status": status,
        "exit_class": exit_class,
        "auth_required": bool(auth_required),
        "ui_contract_changed": bool(ui_contract_changed),
        "version": version,
    }
    if set(row) != set(FIELDS):
        raise ValueError("heartbeat row left the allowlist")
    return row


def heartbeat_alert(row: dict[str, Any], now: datetime, max_age: timedelta) -> Optional[str]:
    """Return a status name when an operator should look, else None.

    auth_required, ui_changed, and error statuses alert immediately.
    A healthy row alerts when last_scan_at is older than max_age.
    """
    status = str(row.get("status") or "")
    if status != "healthy":
        return status or "missing"
    scanned = row.get("last_scan_at")
    if not scanned:
        return "stale"
    try:
        moment = datetime.fromisoformat(str(scanned))
    except ValueError:
        return "stale"
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=KST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=KST)
    if moment.astimezone(KST) < now.astimezone(KST) - max_age:
        return "stale"
    return None


def write_resident_heartbeat(settings, code: int, *, published: bool, now: Optional[datetime] = None) -> bool:
    """Write one allowlisted row. Returns False when Supabase is not configured."""
    if settings is None or not getattr(settings, "has_supabase", False):
        return False
    from .db.supabase_client import SupabaseClient

    moment = now or datetime.now(KST)
    if code == 10:
        status, auth, ui = "auth_required", True, False
    elif code == 20:
        status, auth, ui = "ui_changed", False, True
    elif code == 40:
        status, auth, ui = "pipeline_error", False, False
    elif code == 30:
        status, auth, ui = "collector_error", False, False
    elif code == 0:
        status, auth, ui = "healthy", False, False
    else:
        status, auth, ui = "collector_error", False, False
    row = build_heartbeat(
        status=status,
        exit_class=str(code),
        auth_required=auth,
        ui_contract_changed=ui,
        last_scan_at=moment,
        last_success_at=moment if code == 0 else None,
        last_publish_at=moment if code == 0 and published else None,
    )
    HeartbeatWriter(SupabaseClient(settings.supabase_url, settings.supabase_secret_key)).write(row)
    return True


class HeartbeatWriter:
    """Upsert one row. The client is injected so tests never open a socket."""

    def __init__(self, client: Any):
        self.client = client

    def write(self, row: dict[str, Any]) -> None:
        if set(row) != set(FIELDS):
            raise ValueError("refusing to store a heartbeat outside the allowlist")
        self.client.upsert("agent_heartbeats", row, on_conflict="agent_id")
