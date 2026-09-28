# -*- coding: utf-8 -*-
"""Operator alerts for the resident collectors: fixed codes and numbers, never content.

An alert carries only: component, severity, reason code, last-success age, timestamp and a
recommended operator action. Mail subjects, event text, ids, URLs and account data never
enter it. `evaluate` reads the local operational files; `FileSink` is the local, provider-free
sink (`.local/ops-alerts.json`). An external notifier (toast, mail, messenger) is an owner
decision and plugs in behind the same `emit` interface.

Health targets (owner, 2026-09-28):
  Portal LIST       expected ~60 s   warning > 3 min    critical > 10 min without a success
  Dooray Radar      expected 2-5 min warning > 10 min   critical > 30 min without a success
  Flash candidate   discovered but no cloud dispatch progress for > 10 min -> warning
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Optional

from .ops_storage import atomic_json, read_json

SLO = {
    "portal": {"expected": 60, "warning": 180, "critical": 600},
    "dooray_radar": {"expected": 180, "warning": 600, "critical": 1800},
    "flash_candidate": {"warning": 600},
}
SEVERITIES = ("healthy", "warning", "critical")
ACTIONS = {
    "none": "no action",
    "wait": "transient; the collector retries on its own",
    "restart_worker": "run start_ggongbab_workers.cmd after checking the status",
    "login": "complete SSO/MFA in the dedicated browser window, then start the worker",
    "review_contract": "the list/UI contract changed; re-run calibration before resuming",
    "open_browser": "open the dedicated browser for this collector (keep it minimized)",
    "check_dispatch": "check the dispatch token and GitHub Actions; the schedule still runs",
    "investigate": "check the collector status and logs (codes only)",
}
# Reason codes this module may put in an alert, with the severity floor and the action.
REASONS = {
    "OK": ("healthy", "none"),
    "SCAN_DELAYED": ("warning", "wait"),
    "SCAN_STALE": ("critical", "restart_worker"),
    "NO_SUCCESS_RECORDED": ("critical", "investigate"),
    "WORKER_NOT_RUNNING": ("critical", "restart_worker"),
    "AUTH_EXPIRED": ("critical", "login"),
    "CONTRACT_CHANGED": ("critical", "review_contract"),
    "UNREAD_RADAR_DISABLED": ("critical", "review_contract"),
    "BROWSER_ABSENT": ("warning", "open_browser"),
    "RETRY_EXHAUSTED": ("critical", "restart_worker"),
    "DISPATCH_FAILED": ("warning", "check_dispatch"),
    "DISPATCH_AUTH_FAILED": ("critical", "check_dispatch"),
    "CANDIDATE_WAITING": ("warning", "check_dispatch"),
}


@dataclass(frozen=True)
class Alert:
    component: str
    severity: str
    reason: str
    last_success_age_seconds: Optional[int]
    timestamp: float
    action: str

    @classmethod
    def of(cls, component: str, reason: str, age: Optional[int], now: float, severity: Optional[str] = None):
        if reason not in REASONS:
            reason = "NO_SUCCESS_RECORDED"
        floor, action = REASONS[reason]
        return cls(component, severity or floor, reason, age, round(now, 3), action)


def _age(last_success, now) -> Optional[int]:
    return max(0, int(now - last_success)) if isinstance(last_success, (int, float)) and last_success else None


def staleness(component: str, age: Optional[int]) -> tuple[str, str]:
    slo = SLO[component]
    if age is None:
        return "critical", "NO_SUCCESS_RECORDED"
    if age > slo["critical"]:
        return "critical", "SCAN_STALE"
    if age > slo["warning"]:
        return "warning", "SCAN_DELAYED"
    return "healthy", "OK"


PORTAL_HUMAN = {"PORTAL_LIST_AUTH_REQUIRED": "AUTH_EXPIRED", "PORTAL_LIST_REDIRECT_REQUIRES_MANUAL_REVIEW": "AUTH_EXPIRED",
                "PORTAL_SESSION_COOKIE_MISSING_OR_AMBIGUOUS": "AUTH_EXPIRED", "PORTAL_SESSION_COOKIE_UNUSABLE": "AUTH_EXPIRED",
                "PORTAL_UI_CHANGED": "CONTRACT_CHANGED", "OPS_RETRY_EXHAUSTED": "RETRY_EXHAUSTED"}


def portal_alert(runtime: dict, *, running: bool, enabled: bool, now: float) -> Alert:
    age = _age(runtime.get("last_success"), now)
    severity, code = staleness("portal", age)
    human = PORTAL_HUMAN.get(runtime.get("manual_reason") or "")
    if human:
        return Alert.of("portal", human, age, now)
    if enabled and not running and severity != "healthy":
        return Alert.of("portal", "WORKER_NOT_RUNNING", age, now)
    return Alert.of("portal", code, age, now, severity)


RADAR_HUMAN = {"DOORAY_AUTH_REQUIRED": "AUTH_EXPIRED", "DOORAY_CONTRACT_CHANGED": "CONTRACT_CHANGED",
               "DOORAY_BROWSER_ABSENT": "BROWSER_ABSENT"}


def radar_alert(runtime: dict, *, running: bool, enabled: bool, unread_disabled: bool, now: float) -> Alert:
    age = _age(runtime.get("last_success"), now)
    severity, code = staleness("dooray_radar", age)
    if unread_disabled:
        return Alert.of("dooray_radar", "UNREAD_RADAR_DISABLED", age, now)
    human = RADAR_HUMAN.get(runtime.get("reason") or "")
    if human in {"AUTH_EXPIRED", "CONTRACT_CHANGED"} or (human and severity != "healthy"):
        return Alert.of("dooray_radar", human, age, now)
    if enabled and not running and severity != "healthy":
        return Alert.of("dooray_radar", "WORKER_NOT_RUNNING", age, now)
    return Alert.of("dooray_radar", code, age, now, severity)


def dispatch_alert(state: dict, now: float) -> Optional[Alert]:
    result = state.get("last_result") or ""
    if result == "DISPATCH_AUTH_FAILED":
        return Alert.of("dispatch", "DISPATCH_AUTH_FAILED", None, now)
    if result in {"DISPATCH_REJECTED", "DISPATCH_TRANSPORT_FAILED", "DISPATCH_DAILY_CAP"}:
        return Alert.of("dispatch", "DISPATCH_FAILED", None, now)
    return None


def flash_alerts(ledger: dict, now: float) -> list[Alert]:
    """A same-day/flash candidate that no cloud dispatch has picked up within 10 minutes."""
    waiting = [e for e in (ledger.get("pending") or []) if not e.get("dispatched")
               and isinstance(e.get("discovered_at"), (int, float))
               and now - e["discovered_at"] > SLO["flash_candidate"]["warning"]]
    if not waiting:
        return []
    oldest = min(e["discovered_at"] for e in waiting)
    return [Alert.of("flash_candidate", "CANDIDATE_WAITING", int(now - oldest), now)]


def evaluate(local: Path, *, portal_running: bool, radar_running: bool, now: Optional[float] = None) -> list[Alert]:
    """All current alerts from the operational files under .local (read-only)."""
    now = time.time() if now is None else now
    control = read_json(local / "ops-control.json", {"enabled": False, "resume": 0})
    portal = read_json(local / "ops-portal.json", {"last_success": None, "manual_reason": ""})
    alerts = [portal_alert(portal, running=portal_running, enabled=bool(control.get("enabled")), now=now)]
    radar_control = read_json(local / "radar-control.json", {"enabled": False})
    if radar_control.get("enabled") or (local / "ops-radar.json").exists():
        radar = read_json(local / "ops-radar.json", {"last_success": None, "reason": ""})
        alerts.append(radar_alert(radar, running=radar_running, enabled=bool(radar_control.get("enabled")),
                                  unread_disabled=(local / "radar-unread-disabled.json").exists(), now=now))
    dispatch = dispatch_alert(read_json(local / "dispatch-state.json", {}), now)
    if dispatch:
        alerts.append(dispatch)
    alerts += flash_alerts(read_json(local / "radar-flash.json", {"pending": []}), now)
    return alerts


class FileSink:
    """Local, provider-free sink: the current alerts plus a bounded transition history."""
    def __init__(self, local: Path, history: int = 200):
        self.path, self.history = Path(local) / "ops-alerts.json", history

    def emit(self, alerts: Iterable[Alert]) -> dict:
        alerts = list(alerts)
        previous = read_json(self.path, {"alerts": [], "history": []})
        before = {(a["component"], a["reason"], a["severity"]) for a in previous.get("alerts", [])}
        now_rows = [asdict(a) for a in alerts]
        changes = [r for r in now_rows if (r["component"], r["reason"], r["severity"]) not in before]
        history = (previous.get("history", []) + changes)[-self.history:]
        payload = {"observed_at": max((a.timestamp for a in alerts), default=time.time()),
                   "worst": max((SEVERITIES.index(a.severity) for a in alerts), default=0),
                   "alerts": now_rows, "history": history}
        payload["worst"] = SEVERITIES[payload["worst"]]
        atomic_json(self.path, payload)
        return payload


def render(alerts: Iterable[Alert]) -> list[str]:
    lines = []
    for a in alerts:
        age = "never" if a.last_success_age_seconds is None else f"{a.last_success_age_seconds}s"
        lines.append(f"{a.severity.upper():8s} {a.component:15s} {a.reason:22s} age={age:>7s}  -> {ACTIONS[a.action]}")
    return lines


def to_json(alerts: Iterable[Alert]) -> str:
    return json.dumps([asdict(a) for a in alerts], ensure_ascii=False)
