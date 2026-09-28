# -*- coding: utf-8 -*-
"""Operator alerts: owner health targets, fixed fields, no content."""
from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from ggongbab import alerts
from ggongbab.ops_storage import atomic_json

NOW = 2_000_000_000.0
FIELDS = {"component", "severity", "reason", "last_success_age_seconds", "timestamp", "action"}


@pytest.mark.parametrize("age,severity,reason", [(59, "healthy", "OK"), (181, "warning", "SCAN_DELAYED"),
                                                 (601, "critical", "SCAN_STALE")])
def test_portal_targets(age, severity, reason):
    a = alerts.portal_alert({"last_success": NOW - age, "manual_reason": ""}, running=True, enabled=True, now=NOW)
    assert (a.severity, a.reason) == (severity, reason)


@pytest.mark.parametrize("age,severity", [(299, "healthy"), (601, "warning"), (1801, "critical")])
def test_radar_targets(age, severity):
    a = alerts.radar_alert({"last_success": NOW - age, "reason": "DOORAY_RADAR_RUNNING"}, running=True,
                           enabled=True, unread_disabled=False, now=NOW)
    assert a.severity == severity


def test_expired_logins_and_contract_changes_are_critical_with_an_operator_action():
    portal = alerts.portal_alert({"last_success": NOW - 30, "manual_reason": "PORTAL_LIST_AUTH_REQUIRED"},
                                 running=False, enabled=True, now=NOW)
    radar = alerts.radar_alert({"last_success": NOW - 30, "reason": "DOORAY_CONTRACT_CHANGED"}, running=False,
                               enabled=True, unread_disabled=False, now=NOW)
    assert (portal.severity, portal.reason, portal.action) == ("critical", "AUTH_EXPIRED", "login")
    assert (radar.severity, radar.reason) == ("critical", "CONTRACT_CHANGED")


def test_a_disabled_unread_radar_is_critical():
    a = alerts.radar_alert({"last_success": NOW - 30, "reason": "DOORAY_UNREAD_INVARIANT_BROKEN"}, running=True,
                           enabled=True, unread_disabled=True, now=NOW)
    assert (a.severity, a.reason) == ("critical", "UNREAD_RADAR_DISABLED")


def test_a_stale_enabled_worker_that_is_not_running_is_critical():
    a = alerts.portal_alert({"last_success": NOW - 400, "manual_reason": ""}, running=False, enabled=True, now=NOW)
    assert (a.severity, a.reason) == ("critical", "WORKER_NOT_RUNNING")


def test_flash_candidates_waiting_more_than_ten_minutes_alert_until_dispatched():
    waiting = {"pending": [{"id": "h1", "discovered_at": NOW - 700, "dispatched": False}]}
    done = {"pending": [{"id": "h1", "discovered_at": NOW - 700, "dispatched": True}]}
    fresh = {"pending": [{"id": "h2", "discovered_at": NOW - 60, "dispatched": False}]}
    [a] = alerts.flash_alerts(waiting, NOW)
    assert (a.component, a.reason, a.last_success_age_seconds) == ("flash_candidate", "CANDIDATE_WAITING", 700)
    assert alerts.flash_alerts(done, NOW) == [] and alerts.flash_alerts(fresh, NOW) == []


@pytest.mark.parametrize("result,reason", [("DISPATCH_AUTH_FAILED", "DISPATCH_AUTH_FAILED"),
                                           ("DISPATCH_TRANSPORT_FAILED", "DISPATCH_FAILED"), ("DISPATCH_DAILY_CAP", "DISPATCH_FAILED")])
def test_dispatch_failures_alert(result, reason):
    assert alerts.dispatch_alert({"last_result": result}, NOW).reason == reason
    assert alerts.dispatch_alert({"last_result": "DISPATCHED"}, NOW) is None


def test_evaluate_reads_only_operational_files_and_emits_only_the_fixed_fields(tmp_path):
    local = tmp_path / ".local"
    atomic_json(local / "ops-control.json", {"enabled": True, "resume": 1})
    atomic_json(local / "ops-portal.json", {"last_success": NOW - 30, "manual_reason": ""})
    atomic_json(local / "radar-control.json", {"enabled": True})
    atomic_json(local / "ops-radar.json", {"last_success": NOW - 900, "reason": "DOORAY_RADAR_RUNNING"})
    atomic_json(local / "radar-flash.json", {"pending": [{"id": "h", "discovered_at": NOW - 900, "dispatched": False}]})
    found = alerts.evaluate(local, portal_running=True, radar_running=True, now=NOW)
    assert [(a.component, a.severity) for a in found] == [("portal", "healthy"), ("dooray_radar", "warning"),
                                                           ("flash_candidate", "warning")]
    payload = alerts.FileSink(local).emit(found)
    assert payload["worst"] == "warning" and all(set(row) == FIELDS for row in payload["alerts"])
    again = alerts.FileSink(local).emit(found)
    assert len(again["history"]) == 3            # transitions only, not every tick
    assert all(set(row) == FIELDS for row in again["history"])


def test_unknown_reasons_cannot_carry_free_text():
    a = alerts.Alert.of("portal", "SOME PRIVATE TEXT", 5, NOW)
    assert a.reason == "NO_SUCCESS_RECORDED" and "PRIVATE" not in json.dumps(asdict(a))


def test_render_is_one_line_per_alert_with_an_action():
    lines = alerts.render([alerts.Alert.of("dooray_radar", "AUTH_EXPIRED", 30, NOW)])
    assert len(lines) == 1 and "complete SSO/MFA" in lines[0]
