# -*- coding: utf-8 -*-
"""Dooray Radar: reads new mail in full, restores unread, fails closed. Fakes only - no browser,
mailbox or Dooray write."""
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from ggongbab import dooray_radar as radar
from ggongbab.config import KST
from ggongbab.web.exit_codes import AuthRequired, UiContractError
from ggongbab.web.mail_detail import MailUnavailable, OpenedMail, UnreadRestoreFailed
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


POSTER = ("image/jpeg", b"\xff\xd8\xff" + b"0" * 20000)


class Opener:
    """The mail reader, faked: a mail's full body is its preview unless `bodies` says otherwise.
    `mails` maps an id to OpenedMail fields; `fail` to an exception raised on open or restore."""

    def __init__(self, mails=None, fail=None):
        self.mails, self.fail = mails or {}, fail or {}
        self.opened, self.restored, self.image_loads = [], [], []

    @contextmanager
    def open(self, session, header):
        if self.fail.get(header.mail_id) == "unavailable":
            raise MailUnavailable("HTTP 404")
        spec = dict(self.mails.get(header.mail_id) or {})
        mail = OpenedMail(body=spec.pop("body", header.preview), **spec)
        self.opened.append(header.mail_id)
        try:
            yield mail
        finally:
            if header.unread:
                if self.fail.get(header.mail_id) == "restore":
                    raise UnreadRestoreFailed()
                self.restored.append(header.mail_id)

    def images(self, session, mail):
        self.image_loads.append(mail.image_count)
        return [POSTER][:mail.image_count]


def run(tmp_path, headers, *, requests=(), writer=None, dispatch=None, opener=None, **kw):
    files = radar.RadarFiles(tmp_path)
    files.set_enabled(True, T0)
    if kw.pop("dispatch_on", True):
        files.set_dispatch(True, T0)
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
    opener = opener if opener is not None else Opener()
    code = radar.run_radar(files, session_factory=session_factory, writer=writer, list_mails=list_mails,
                           mail_host=HOST, heartbeat=lambda *a: beats.append(a), dispatch=dispatch,
                           max_cycles=kw.pop("max_cycles", 1), clock=kw.pop("clock", lambda: T0),
                           sleep=lambda _: None, log=logs.append, opener=opener, **kw)
    return code, files, writer, beats, logs


def test_unread_mail_is_read_in_full_registered_and_marked_unread_again(tmp_path):
    headers = [hdr("m1", "커피차와 함께하는 캠퍼스 홍보 행사", "방문자 전원 커피 제공", unread=True),
               hdr("m2", "회의록 공유", "지난주 회의 내용", unread=True)]
    opener = Opener({"m1": {"body": "방문자 전원 커피 제공 (선착순, 소진 시 종료)\n장소: 학생회관 앞"}})
    dispatched = []
    code, files, writer, beats, logs = run(tmp_path, headers, opener=opener,
                                           dispatch=lambda new: dispatched.append(new) or "DISPATCH_NOT_CONFIGURED")
    assert code == 0 and len(writer.payloads) == 1
    task = writer.payloads[0]
    assert not task.preview_only and task.body == "방문자 전원 커피 제공 (선착순, 소진 시 종료)\n장소: 학생회관 앞"
    assert task.discovered_at and task.images == []
    assert opener.opened == ["m1", "m2"] and opener.restored == ["m1", "m2"]
    assert dispatched == [True] and beats[-1][0] == "healthy"
    counts = files.runtime_state()["counts"]
    assert counts["candidates"] == 1 and counts["unread"] == 2 and counts["opened"] == 2
    assert counts["unread_restored"] == 2
    flash = json.loads(files.flash.read_text(encoding="utf-8"))
    assert len(flash["pending"]) == 1 and flash["pending"][0]["dispatched"] is False
    state = AgentState.load(files.mail_state)
    assert state.seen("m1") and state.seen("m2")          # candidate registered, other filtered
    reasons = sorted(r.reason for r in state.mails.values())
    assert reasons == ["food provision wording + event", "no event wording"]


def test_food_wording_only_in_the_body_or_an_attachment_is_found(tmp_path):
    """MISS 2026-10-14: the preview said nothing about food; the body or the attached notice did."""
    headers = [hdr("b1", "자연과학 토크 콘서트 안내", "자연과학대학에서 토크 콘서트를 엽니다.", unread=True),
               hdr("a1", "학과 세미나 안내", "첨부 파일을 확인해 주세요.")]
    opener = Opener({"b1": {"body": "10월 16일(목) 18:00, 창의학습관\n참석자 전원 저녁 도시락 제공"},
                     "a1": {"attachment_texts": [("첨부 1 · PDF 본문", "10월 20일 12:00 세미나, 점심 도시락 제공")]}})
    code, files, writer, *_ = run(tmp_path, headers, opener=opener)
    assert sorted(p.mail_id for p in writer.payloads) == ["a1", "b1"]
    attached = next(p for p in writer.payloads if p.mail_id == "a1")
    assert "[첨부 1 · PDF 본문]\n10월 20일 12:00 세미나, 점심 도시락 제공" in attached.body


def test_an_event_with_a_poster_is_a_candidate_and_the_poster_goes_with_the_task(tmp_path):
    headers = [hdr("p1", "자연과학 토크 콘서트", "많은 참여 바랍니다.", unread=True),
               hdr("p2", "사진 공유", "지난 주말 사진입니다.")]
    opener = Opener({"p1": {"image_refs": [("attachment", "https://x/parts/2", 300000)]},
                     "p2": {"image_refs": [("attachment", "https://x/parts/3", 300000)]}})
    code, files, writer, *_ = run(tmp_path, headers, opener=opener)
    assert [p.mail_id for p in writer.payloads] == ["p1"]                 # a photo without an event is not
    assert writer.payloads[0].images == [POSTER] and opener.image_loads == [1]
    assert files.runtime_state()["counts"]["images"] == 1
    reasons = {r.reason for r in AgentState.load(files.mail_state).mails.values()}
    assert "event + poster image" in reasons


def test_a_prize_draw_without_food_is_a_candidate(tmp_path):
    """MISS 2026-10-14 (INNOVATE KOREA): no food, a prize draw for visitors."""
    headers = [hdr("g1", "INNOVATE KOREA 2026 참가 안내", "행사장 방문 시 경품 추첨 이벤트에 참여할 수 있습니다.")]
    code, files, writer, *_ = run(tmp_path, headers)
    assert [p.mail_id for p in writer.payloads] == ["g1"]
    assert next(iter(AgentState.load(files.mail_state).mails.values())).reason.startswith("giveaway wording")


def test_a_transactional_subject_is_never_opened(tmp_path):
    opener = Opener()
    code, files, writer, *_ = run(tmp_path, [hdr("t1", "결제 완료 안내", "커피 쿠폰 증정 행사", unread=True)], opener=opener)
    assert opener.opened == [] and writer.payloads == []
    assert files.runtime_state()["counts"]["denied"] == 1
    assert AgentState.load(files.mail_state).seen("t1")


def test_a_mail_that_cannot_be_read_is_retried_next_time(tmp_path):
    headers = [hdr("gone", "커피차 홍보 행사", "커피 제공")]
    code, files, writer, *_ = run(tmp_path, headers, opener=Opener(fail={"gone": "unavailable"}))
    assert writer.payloads == [] and files.runtime_state()["counts"]["unavailable"] == 1
    assert not AgentState.load(files.mail_state).seen("gone")
    code, files, writer, *_ = run(tmp_path, headers)
    assert [p.mail_id for p in writer.payloads] == ["gone"]


def test_a_failed_unread_restore_stops_opening_unread_mail(tmp_path):
    headers = [hdr("u1", "커피차 홍보 행사", "커피 제공", unread=True)]
    code, files, writer, beats, logs = run(tmp_path, headers, opener=Opener(fail={"u1": "restore"}))
    assert not files.unread_allowed() and files.runtime_state()["reason"] == radar.RESTORE
    assert radar.RESTORE in logs and beats[-1][0] == "collector_error"
    assert not files.mail_state.exists()        # nothing of that scan is recorded; read mail is re-scanned
    opener = Opener()
    code, files, writer2, *_ = run(tmp_path, headers, opener=opener)
    assert opener.opened == [] and files.runtime_state()["counts"]["unread_skipped"] == 1


def test_a_recheck_reads_older_mail_the_previous_rules_dismissed(tmp_path):
    state = AgentState.load(radar.RadarFiles(tmp_path).mail_state)
    old = hdr("old", "자연과학 토크 콘서트", "많은 참여 바랍니다.", minutes_ago=3 * 1440)
    record = state.record("old", old.subject, old.received, registered=False, outcome="filtered")
    record.rules = "2026-09-28.flash-1"
    state.save()
    opener = Opener({"old": {"body": "10월 16일 18:00 창의학습관, 저녁 도시락 제공"}})
    code, files, writer, *_ = run(tmp_path, [old], opener=opener)
    assert writer.payloads == []                                    # outside the normal window
    code, files, writer, *_ = run(tmp_path, [old], opener=opener, recheck_days=7)
    assert [p.mail_id for p in writer.payloads] == ["old"]
    with pytest.raises(ValueError):
        run(tmp_path, [], recheck_days=15)


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
    opener = Opener()
    code, files, writer, *_ = run(tmp_path, headers, opener=opener)
    assert [p.mail_id for p in writer.payloads] == ["r1"] and opener.opened == ["r1"]
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


def test_an_expired_login_is_reported_and_never_ends_the_radar(tmp_path):
    code, files, _, beats, logs = run(tmp_path, AuthRequired("expired"))
    assert code == 0 and beats[-1][0] == "auth_required" and files.unread_allowed()
    assert files.runtime_state()["reason"] == radar.AUTH and logs[-1] == radar.AUTH


def test_an_expired_login_waits_for_a_person_and_resumes_by_itself(tmp_path, monkeypatch):
    """Nothing restarts an exited Radar (its task runs at logon), so an expired Dooray login is
    retried with backoff, at most AUTH_RETRY_MAX apart, and the Radar resumes on the first scan
    after a person logs in again in the Ops Chrome."""
    files = radar.RadarFiles(tmp_path)
    files.set_enabled(True, T0)
    attempts, beats, waits = [], [], []

    @contextmanager
    def session_factory():
        yield SimpleNamespace(context=Context(), page=None)

    def list_mails(session, **_):
        attempts.append(1)
        if len(attempts) <= 4:
            raise AuthRequired("expired")
        return []

    monkeypatch.setattr(radar, "_wait", lambda _files, seconds, _sleep, _dry: waits.append(seconds) or True)
    code = radar.run_radar(files, session_factory=session_factory, writer=Writer(), list_mails=list_mails,
                           mail_host=HOST, heartbeat=lambda *a: beats.append(a[0]), max_cycles=5,
                           clock=lambda: T0, sleep=lambda _: None)
    assert code == 0 and len(attempts) == 5
    assert waits == [180, 360, radar.AUTH_RETRY_MAX, radar.AUTH_RETRY_MAX]
    assert beats == ["auth_required"] * 4 + ["healthy"]
    assert files.runtime_state()["reason"] == radar.RUNNING and files.unread_allowed()


def test_a_closed_browser_is_reported_and_never_started(tmp_path):
    code, files, *_ = run(tmp_path, [], browser_running=lambda: False)
    assert files.runtime_state()["reason"] == radar.BROWSER


def test_interval_is_bounded_to_two_to_five_minutes(tmp_path):
    for bad in (60, 301):
        with pytest.raises(ValueError):
            run(tmp_path, [], interval=bad)


def test_no_private_text_in_state_runtime_flash_or_latch_files(tmp_path):
    run(tmp_path, [hdr("m1", PRIVATE + " 커피차 행사", PRIVATE + " 커피 제공", unread=True),
                   hdr("m2", PRIVATE + " 공지", PRIVATE + " 본문")])
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
    assert not files.dispatch_enabled()
    assert workers.main(["radar-dispatch-on"]) == 0 and files.dispatch_enabled()
    assert workers.main(["radar-dispatch-off"]) == 0 and not files.dispatch_enabled()
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


def test_the_radar_code_path_reads_and_only_restores_unread():
    """The Radar's own requests go through the API request context, which the browser request guard
    does not see. So its code may read (GET) and send exactly one write - marking a mail unread again
    - and nothing that clicks, navigates, moves, deletes or marks mail read."""
    from pathlib import Path as _P
    root = _P(__file__).resolve().parents[2] / "scripts"
    source = (root / "ggongbab/dooray_radar.py").read_text(encoding="utf-8")
    detail = (root / "ggongbab/web/mail_detail.py").read_text(encoding="utf-8")
    workers = (root / "windows/ggongbab_workers.py").read_text(encoding="utf-8")
    radar_fn = workers[workers.index("def radar("):workers.index("def mail_lookup(")]
    for forbidden in ("open_body", ".click(", ".fill(", ".goto(", ".evaluate(", "request.put", "request.patch",
                      "request.delete", "request.fetch", "mark_read", "set_read", "/read", "/move", "/delete"):
        for name, text in (("radar", source), ("mail_detail", detail), ("worker", radar_fn)):
            assert forbidden not in text, (name, forbidden)
    assert "request.post" not in source and "request.post" not in radar_fn
    assert detail.count("request.post(") == 1 and '/unread"' in detail and '"mailIdList": [mail_id]' in detail
    assert "list_mails=list_mails_paged" in radar_fn and "attach_only=True" in radar_fn


def test_mail_lookup_explains_a_mail_without_printing_it(tmp_path, monkeypatch, capsys):
    workers = _workers(tmp_path, monkeypatch)
    files = radar.RadarFiles(tmp_path)
    state = AgentState.load(files.mail_state)
    state.record("m1", PRIVATE + " 토크 콘서트", date(2026, 10, 13), registered=False, outcome="filtered",
                 reason="event wording but no date")
    state.save()
    assert workers.mail_lookup(workers.Files(tmp_path), PRIVATE + " 토크 콘서트") == 0
    out = capsys.readouterr().out
    assert "filtered" in out and "event wording but no date" in out and "2026-10-13" in out and PRIVATE not in out
    workers.mail_lookup(workers.Files(tmp_path), "다른 제목")
    assert "No ledger entry" in capsys.readouterr().out


def test_the_cloud_trigger_stays_off_until_the_operator_turns_it_on(tmp_path):
    dispatched = []
    code, files, writer, *_ = run(tmp_path, [hdr("m1", "커피차 홍보 행사", "커피 제공", unread=True)],
                                  dispatch=lambda new: dispatched.append(new) or "DISPATCHED", dispatch_on=False)
    assert len(writer.payloads) == 1 and dispatched == []
    assert files.runtime_state()["dispatch"] == radar.DISPATCH_OFF
    assert json.loads(files.flash.read_text(encoding="utf-8"))["pending"][0]["dispatched"] is False


def test_enable_and_dispatch_switches_do_not_overwrite_each_other(tmp_path):
    files = radar.RadarFiles(tmp_path)
    files.set_dispatch(True, T0)
    files.set_enabled(True, T0)
    assert files.enabled() and files.dispatch_enabled()
    files.set_enabled(False, T0)
    assert files.dispatch_enabled() and not files.enabled()
    files.set_dispatch(False, T0)
    assert not files.dispatch_enabled() and not files.enabled()


@pytest.mark.skipif(__import__("os").name != "nt", reason="the operator entry point is Windows-only")
def test_a_start_that_fails_before_the_first_scan_is_recorded_for_status_and_alerts(tmp_path, monkeypatch):
    from ggongbab import alerts
    workers = _workers(tmp_path, monkeypatch)
    files = radar.RadarFiles(tmp_path)
    files.set_enabled(True, T0)
    assert workers.main(["radar-once"]) == 1                    # no calibrated contract here
    runtime = files.runtime_state()
    assert runtime["reason"] == radar.CONFIG_REQUIRED and runtime["running"] is False
    assert radar.CONFIG_REQUIRED in (tmp_path / ".local/ops-radar.log").read_text(encoding="utf-8")
    a = alerts.radar_alert(runtime, running=False, enabled=True, unread_disabled=False, now=T0)
    assert (a.severity, a.reason, a.action) == ("critical", "CONFIGURATION_REQUIRED", "fix_config")
