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


def _parse_moment(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    moment = datetime.fromisoformat(str(value))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=KST)
    return moment.astimezone(KST)


def _later(old: Optional[str], new: Optional[str]) -> Optional[str]:
    """Keep the newer timestamp. A missing incoming value does not erase history."""
    old_at, new_at = _parse_moment(old), _parse_moment(new)
    if new_at is None:
        return old
    if old_at is None or new_at >= old_at:
        return new
    return old


def merge_heartbeat(existing: Optional[dict[str, Any]], incoming: dict[str, Any]) -> dict[str, Any]:
    """Apply one scan without moving timestamps backwards.

    A scan older than the stored last_scan_at still cannot erase a newer
    success or publish time, and it does not replace the newer status.
    """
    if set(incoming) != set(FIELDS):
        raise ValueError("heartbeat row left the allowlist")
    if existing is None:
        return dict(incoming)
    if set(existing) != set(FIELDS):
        raise ValueError("stored heartbeat left the allowlist")
    merged = dict(existing)
    merged["last_scan_at"] = _later(existing.get("last_scan_at"), incoming.get("last_scan_at"))
    merged["last_success_at"] = _later(existing.get("last_success_at"), incoming.get("last_success_at"))
    merged["last_publish_at"] = _later(existing.get("last_publish_at"), incoming.get("last_publish_at"))
    old_scan, new_scan = _parse_moment(existing.get("last_scan_at")), _parse_moment(incoming.get("last_scan_at"))
    stale = old_scan is not None and new_scan is not None and new_scan < old_scan
    if not stale:
        for key in ("status", "exit_class", "auth_required", "ui_contract_changed", "version"):
            merged[key] = incoming[key]
    return merged


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
    """One atomic record call. The database keeps older success and publish times."""

    def __init__(self, client: Any):
        self.client = client

    def write(self, row: dict[str, Any]) -> None:
        if set(row) != set(FIELDS):
            raise ValueError("refusing to store a heartbeat outside the allowlist")
        self.client.rpc("ggongbab_record_heartbeat", {
            "p_agent_id": row["agent_id"],
            "p_last_scan_at": row["last_scan_at"],
            "p_last_success_at": row["last_success_at"],
            "p_last_publish_at": row["last_publish_at"],
            "p_status": row["status"],
            "p_exit_class": row["exit_class"],
            "p_auth_required": row["auth_required"],
            "p_ui_contract_changed": row["ui_contract_changed"],
            "p_version": row["version"],
        })
