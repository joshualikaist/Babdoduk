# -*- coding: utf-8 -*-
"""Dooray Radar: list-level, unread-safe, fail-closed. Fakes only - no browser, mailbox or Dooray write."""
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from ggongbab import dooray_radar as radar
from ggongbab.config import KST
from ggongbab.web.exit_codes import AuthRequired, UiContractError
from ggongbab.web.mail_reader import MailHeader
from ggongbab.web.state import AgentState

T0 = datetime(2026, 9, 28, 11, 50, tzinfo=KST).timestamp()
HOST = "mail.example.invalid"
PRIVATE = "SYNTHETIC-PRIVATE-SUBJECT"


def hdr(mail_id, subject, preview="", *, unread=False, minutes_ago=5):
    at = datetime.fromtimestamp(T0, KST) - timedelta(minutes=minutes_ago)
    return MailHeader(mail_id=mail_id, subject=subject, preview=preview, received=at.date(), unread=unread,
                      received_at=at.replace(second=0, microsecond=0))


class Context:
    def __init__(self, requests=()):
        self.handlers, self.requests = [], list(requests)

    def on(self, event, handler):
        self.handlers.append(handler)

    def remove_listener(self, event, handler):
        self.handlers.remove(handler)

    def fire(self):
        for method, path in self.requests:
            for handler in list(self.handlers):
                handler(SimpleNamespace(method=method, url=f"https://{HOST}{path}"))


class Writer:
    def __init__(self):
        self.payloads = []

    def create_task(self, payload, dry_run=False):
        self.payloads.append(payload)
        return f"post-{len(self.payloads)}"


def run(tmp_path, headers, *, requests=(), writer=None, dispatch=None, **kw):
    files = radar.RadarFiles(tmp_path)
    files.set_enabled(True, T0)
    context = Context(requests)
    beats, logs = [], []

    @contextmanager
    def session_factory():
        yield SimpleNamespace(context=context, page=None)

    def list_mails(session, **_):
        context.fire()          # the browser's own traffic while the Radar lists
        if isinstance(headers, Exception):
            raise headers
        return headers

    writer = writer if writer is not None else Writer()
    code = radar.run_radar(files, session_factory=session_factory, writer=writer, list_mails=list_mails,
                           mail_host=HOST, heartbeat=lambda *a: beats.append(a), dispatch=dispatch,
                           max_cycles=kw.pop("max_cycles", 1), clock=kw.pop("clock", lambda: T0),
                           sleep=lambda _: None, log=logs.append, **kw)
    return code, files, writer, beats, logs


def test_an_unread_flash_mail_is_registered_from_list_data_only(tmp_path):
    headers = [hdr("m1", "커피차와 함께하는 캠퍼스 홍보 행사", "방문자 전원 커피 제공 (선착순, 소진 시 종료)", unread=True),
               hdr("m2", "회의록 공유", "지난주 회의 내용", unread=True)]
    dispatched = []
    code, files, writer, beats, logs = run(tmp_path, headers, dispatch=lambda new: dispatched.append(new) or "DISPATCH_NOT_CONFIGURED")
    assert code == 0 and len(writer.payloads) == 1
    task = writer.payloads[0]
    assert task.preview_only and task.body == "방문자 전원 커피 제공 (선착순, 소진 시 종료)" and task.discovered_at
    assert dispatched == [True] and beats[-1][0] == "healthy"
    runtime = files.runtime_state()
    assert runtime["counts"]["candidates"] == 1 and runtime["counts"]["unread"] == 2
    flash = json.loads(files.flash.read_text(encoding="utf-8"))
    assert len(flash["pending"]) == 1 and flash["pending"][0]["dispatched"] is False
    state = AgentState.load(files.mail_state)
    assert state.seen("m1") and state.seen("m2")          # candidate registered, other filtered


@pytest.mark.parametrize("requests", [[("GET", "/v2/wapi/mails/1234567890")], [("POST", "/v2/wapi/mails/read")],
                                      [("PUT", "/v2/wapi/mails/flags")]])
def test_a_detail_or_write_request_during_a_scan_disables_unread_analysis_before_any_write(tmp_path, requests):
    code, files, writer, beats, logs = run(tmp_path, [hdr("m1", "커피차 홍보 행사", "커피 제공", unread=True)], requests=requests)
    assert writer.payloads == [] and not files.unread_allowed()
    assert files.runtime_state()["reason"] == radar.INVARIANT and radar.INVARIANT in logs


def test_the_apps_own_list_and_settings_gets_are_allowed(tmp_path):
    code, files, writer, *_ = run(tmp_path, [hdr("m1", "커피차 홍보 행사", "커피 제공", unread=True)],
                                  requests=[("GET", "/v2/wapi/mails"), ("GET", "/v2/wapi/mails/total-counts"),
                                            ("GET", "/v2/wapi/members/me")])
    assert files.unread_allowed() and len(writer.payloads) == 1


def test_a_missing_read_flag_fails_closed_and_stops(tmp_path):
    row = hdr("m1", "커피차 홍보 행사", "커피 제공")
    row.unread = None
    code, files, writer, beats, _ = run(tmp_path, [row])
    assert code == 20 and writer.payloads == [] and not files.unread_allowed()
    assert beats[-1][0] == "ui_changed"


def test_with_unread_disabled_unread_rows_are_skipped_and_read_rows_still_scanned(tmp_path):
    files = radar.RadarFiles(tmp_path)
    files.disable_unread(radar.INVARIANT, T0)
    headers = [hdr("u1", "커피차 홍보 행사", "커피 제공", unread=True), hdr("r1", "간식 나눔 행사", "간식 제공", unread=False)]
    code, files, writer, *_ = run(tmp_path, headers)
    assert [p.mail_id for p in writer.payloads] == ["r1"]
    assert files.runtime_state()["counts"]["unread_skipped"] == 1


def test_overlap_window_and_ledger_prevent_replays(tmp_path):
    files = radar.RadarFiles(tmp_path)
    runtime = files.runtime_state()
    runtime["last_success"] = T0 - 600
    from ggongbab.ops_storage import atomic_json
    atomic_json(files.runtime, runtime)
    headers = [hdr("new", "커피차 홍보 행사", "커피 제공", minutes_ago=5),
               hdr("old", "커피차 홍보 행사", "커피 제공", minutes_ago=60)]   # before last success - 30 min
    code, files, writer, *_ = run(tmp_path, headers)
    assert [p.mail_id for p in writer.payloads] == ["new"]
    code, files, writer2, *_ = run(tmp_path, headers)                        # next cycle: nothing again
    assert writer2.payloads == []


def test_dry_run_detects_without_writing_state_tasks_or_dispatch(tmp_path):
    dispatched = []
    code, files, writer, *_ = run(tmp_path, [hdr("m1", "커피차 홍보 행사", "커피 제공", unread=True)],
                                  dry_run=True, dispatch=lambda new: dispatched.append(new))
    assert writer.payloads == [] and dispatched == [] and not files.mail_state.exists()
    runtime = files.runtime_state()
    assert runtime["counts"]["candidates"] == 1 and runtime["last_success"] is None and runtime["last_dry_run"] == T0


def test_a_dispatched_refresh_marks_flash_candidates_as_picked_up(tmp_path):
    code, files, *_ = run(tmp_path, [hdr("m1", "커피차 홍보 행사", "커피 제공", unread=True)], dispatch=lambda new: "DISPATCHED")
    assert json.loads(files.flash.read_text(encoding="utf-8"))["pending"][0]["dispatched"] is True


@pytest.mark.parametrize("error,latched", [(UiContractError("list endpoint failed: TimeoutError"), False),
                                          (UiContractError("list endpoint returned HTTP 503"), False),
                                          (UiContractError("list endpoint did not return JSON"), True)])
def test_transient_list_failures_back_off_but_a_contract_change_fails_closed(tmp_path, error, latched):
    code, files, *_ = run(tmp_path, error)
    assert files.unread_allowed() is (not latched)
    assert files.runtime_state()["reason"] == (radar.CONTRACT if latched else radar.TRANSPORT)


def test_an_expired_login_stops_for_a_human(tmp_path):
    code, files, _, beats, _ = run(tmp_path, AuthRequired("expired"))
    assert code == 10 and beats[-1][0] == "auth_required" and files.unread_allowed()


def test_a_closed_browser_is_reported_and_never_started(tmp_path):
    code, files, *_ = run(tmp_path, [], browser_running=lambda: False)
    assert files.runtime_state()["reason"] == radar.BROWSER


def test_interval_is_bounded_to_two_to_five_minutes(tmp_path):
    for bad in (60, 301):
        with pytest.raises(ValueError):
            run(tmp_path, [], interval=bad)


def test_no_private_text_in_state_runtime_flash_or_latch_files(tmp_path):
    run(tmp_path, [hdr("m1", PRIVATE + " 커피차 행사", PRIVATE + " 커피 제공", unread=True)])
    files = radar.RadarFiles(tmp_path)
    files.disable_unread(radar.INVARIANT, T0)
    for path in (files.runtime, files.flash, files.mail_state, files.unread_latch):
        assert PRIVATE not in path.read_text(encoding="utf-8"), path.name


# --- operator commands and the scheduled task scripts ------------------------------------
def _workers(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path as _P
    root = _P(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("ggongbab_workers_under_test", root / "scripts/windows/ggongbab_workers.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    return module


@pytest.mark.skipif(__import__("os").name != "nt", reason="the operator entry point is Windows-only")
def test_enable_disable_allow_unread_and_alerts_commands(tmp_path, monkeypatch, capsys):
    workers = _workers(tmp_path, monkeypatch)
    files = radar.RadarFiles(tmp_path)
    assert workers.main(["radar-enable"]) == 0 and files.enabled()
    files.disable_unread(radar.INVARIANT, T0)
    assert workers.main(["radar-allow-unread"]) == 0 and files.unread_allowed()
    assert workers.main(["radar-disable"]) == 0 and not files.enabled()
    code = workers.main(["alerts"])
    out = capsys.readouterr().out
    assert code in (0, 2) and "portal" in out
    assert (tmp_path / ".local/ops-alerts.json").exists()


def test_the_radar_task_scripts_match_the_portal_worker_model():
    from pathlib import Path as _P
    root = _P(__file__).resolve().parents[2] / "scripts/windows"
    install = (root / "install_dooray_radar_task.ps1").read_text(encoding="utf-8")
    control = (root / "radar_tasks.ps1").read_text(encoding="utf-8")
    assert "-LogonType Interactive -RunLevel Limited" in install and "-AtLogOn" in install
    assert "'\" radar')" in install
    assert "-MultipleInstances IgnoreNew" in install and "-WakeToRun" not in install and "-Password" not in install
    assert "Start-ScheduledTask" not in install
    assert "TASK_OWNER_UNVERIFIED" in control and "radar-enable" in control and "radar-disable" in control
    for forbidden in ("Remove-Item", "taskkill", "Stop-Process", "rmtree"):
        assert forbidden not in install + control
