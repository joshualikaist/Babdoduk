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


@pytest.mark.parametrize("code", ["PORTAL_CONTEXT_MISSING_OR_AMBIGUOUS", "PORTAL_SESSION_HANDOFF_FAILED"])
def test_a_portal_tab_without_a_usable_login_asks_for_a_login(code):
    """After the PC slept the Portal tab sat on the KAIST SSO page (2026-10-12): the alert asks
    for a login, not for a worker restart that cannot work without one."""
    portal = alerts.portal_alert({"last_success": NOW - 63564, "manual_reason": code}, running=False,
                                 enabled=True, now=NOW)
    assert (portal.severity, portal.reason, portal.action) == ("critical", "AUTH_EXPIRED", "login")
    from ggongbab.ops_policy import LOGIN
    assert set(alerts.PORTAL_HUMAN) & LOGIN == LOGIN    # every login latch is reported as a login


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


def test_the_alert_file_stays_readable_and_recovers_from_an_oversized_one(tmp_path):
    """2026-10-12: a 200-entry history reached 16,392 bytes, over the 16 KB that
    ops_storage.read_json accepts, so every later emit failed and no alert was written or pushed."""
    from ggongbab.ops_storage import read_json
    sink = alerts.FileSink(tmp_path)
    reasons = ["SCAN_DELAYED", "SCAN_STALE", "OK", "WORKER_NOT_RUNNING", "AUTH_EXPIRED"]
    for n in range(400):                         # many transitions: each emit changes the alert
        sink.emit([alerts.Alert.of("portal", reasons[n % len(reasons)], n, NOW + n)])
    assert (tmp_path / "ops-alerts.json").stat().st_size <= alerts.MAX_SINK_BYTES
    assert read_json(tmp_path / "ops-alerts.json", {})["history"]          # still readable, still kept
    (tmp_path / "ops-alerts.json").write_text('{"alerts": [], "history": [' + '{"x": 1},' * 3000 + '{}]}',
                                              encoding="utf-8")                # the oversized file of 10-12
    payload = sink.emit([alerts.Alert.of("portal", "AUTH_EXPIRED", 5, NOW)])
    assert payload["alerts"][0]["reason"] == "AUTH_EXPIRED" and len(payload["history"]) == 1
    assert read_json(tmp_path / "ops-alerts.json", {})["worst"] == "critical"


def test_unknown_reasons_cannot_carry_free_text():
    a = alerts.Alert.of("portal", "SOME PRIVATE TEXT", 5, NOW)
    assert a.reason == "NO_SUCCESS_RECORDED" and "PRIVATE" not in json.dumps(asdict(a))


def test_render_is_one_line_per_alert_with_an_action():
    lines = alerts.render([alerts.Alert.of("dooray_radar", "AUTH_EXPIRED", 30, NOW)])
    assert len(lines) == 1 and "complete SSO/MFA" in lines[0]


def test_a_closed_browser_escalates_to_critical_once_scans_are_stale():
    """2026-10-05..11: the Ops Chrome was closed for a week behind a single warning."""
    fresh = alerts.radar_alert({"last_success": NOW - 700, "reason": "DOORAY_BROWSER_ABSENT"}, running=True,
                               enabled=True, unread_disabled=False, now=NOW)
    stale = alerts.radar_alert({"last_success": NOW - 7 * 86400, "reason": "DOORAY_BROWSER_ABSENT"}, running=True,
                               enabled=True, unread_disabled=False, now=NOW)
    assert (fresh.reason, fresh.severity) == ("BROWSER_ABSENT", "warning")
    assert (stale.reason, stale.severity, stale.action) == ("BROWSER_ABSENT", "critical", "open_browser")


# --- false alarms of 2026-10-18 -------------------------------------------------------------
def test_a_just_started_worker_is_judged_from_its_start_not_from_an_old_success():
    """The owner logged in at 14:04; the watchdog resumed and restarted the Portal worker, whose last
    success was 5.6 hours old. The first scan took 3.5 minutes, and for those minutes the alert was a
    critical SCAN_STALE that popped a toast after the login had worked."""
    runtime = {"last_success": NOW - 20389, "started": NOW - 15, "manual_reason": "", "reason": "WORKER_STARTING"}
    a = alerts.portal_alert(runtime, running=True, enabled=True, now=NOW)
    assert (a.severity, a.reason) == ("healthy", "OK") and a.last_success_age_seconds == 20389   # true age shown
    late = alerts.portal_alert(dict(runtime, started=NOW - 250), running=True, enabled=True, now=NOW)
    assert (late.severity, late.reason) == ("warning", "SCAN_DELAYED")
    stuck = alerts.portal_alert(dict(runtime, started=NOW - 700), running=True, enabled=True, now=NOW)
    assert (stuck.severity, stuck.reason) == ("critical", "SCAN_STALE")        # still no success: a real alarm
    radar = alerts.radar_alert({"last_success": NOW - 9000, "started": NOW - 30, "reason": "DOORAY_RADAR_RUNNING"},
                               running=True, enabled=True, unread_disabled=False, now=NOW)
    assert radar.severity == "healthy"


def test_a_start_time_never_hides_a_worker_that_is_not_running():
    runtime = {"last_success": NOW - 700, "started": NOW - 10, "manual_reason": ""}
    a = alerts.portal_alert(runtime, running=False, enabled=True, now=NOW)
    assert (a.severity, a.reason) == ("critical", "WORKER_NOT_RUNNING")
    a = alerts.portal_alert({"last_success": None, "started": NOW - 5, "manual_reason": ""}, running=True,
                            enabled=True, now=NOW)
    assert (a.severity, a.reason) == ("healthy", "OK")        # first start: its first scan is not yet due
    a = alerts.portal_alert({"last_success": None, "started": NOW - 5, "manual_reason": ""}, running=False,
                            enabled=True, now=NOW)
    assert (a.severity, a.reason) == ("critical", "WORKER_NOT_RUNNING")      # a dead worker's start is no proof


@pytest.mark.parametrize("code", sorted(alerts.NETWORK_REASONS))
def test_a_network_outage_that_heals_by_itself_is_only_a_warning_for_thirty_minutes(code):
    """2026-10-18 01:38-01:57: Wi-Fi/Supabase errors left the Portal LIST 19 minutes without a success; the
    worker retried and recovered alone, but the alert was critical (and a toast) after 10 minutes."""
    runtime = {"last_success": NOW - 1200, "started": NOW - 5000, "manual_reason": "", "reason": code}
    a = alerts.portal_alert(runtime, running=True, enabled=True, now=NOW)
    assert (a.severity, a.reason, a.action) == ("warning", "NETWORK_UNSTABLE", "check_network")
    long = alerts.portal_alert(dict(runtime, last_success=NOW - 1801), running=True, enabled=True, now=NOW)
    assert (long.severity, long.reason) == ("critical", "SCAN_STALE")


def test_only_network_codes_get_the_network_grace_and_a_dead_worker_never_does():
    base = {"last_success": NOW - 1200, "started": NOW - 5000, "manual_reason": ""}
    for reason in ("WORKER_RUNNING", "WORKER_STARTING", "PORTAL_LIST_SESSION_REBUILT", ""):
        a = alerts.portal_alert(dict(base, reason=reason), running=True, enabled=True, now=NOW)
        assert (a.severity, a.reason) == ("critical", "SCAN_STALE"), reason
    dead = alerts.portal_alert(dict(base, reason="PORTAL_LIST_CONNECTION_ERROR"), running=False, enabled=True, now=NOW)
    assert dead.reason == "WORKER_NOT_RUNNING"
    login = alerts.portal_alert(dict(base, reason="PORTAL_LIST_CONNECTION_ERROR",
                                     manual_reason="PORTAL_LIST_AUTH_REQUIRED"), running=True, enabled=True, now=NOW)
    assert login.reason == "AUTH_EXPIRED"                    # a real expiry is never softened


def test_network_unstable_is_a_known_reason_with_text_in_every_channel():
    from ggongbab import notify
    assert alerts.REASONS["NETWORK_UNSTABLE"] == ("warning", "check_network")
    assert "check_network" in alerts.ACTIONS
    title, body = notify.format_toast([alerts.Alert.of("portal", "NETWORK_UNSTABLE", 1200, NOW)])
    assert "네트워크 불안정" in body and "Wi-Fi" in body and title == "밥도둑 운영: 확인이 필요합니다"
