"""Offline operational acceptance: no services, task registration or real browsers."""
from contextlib import contextmanager
from datetime import datetime, timedelta
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ggongbab.config import KST
from ggongbab.heartbeat import build_heartbeat
from ggongbab.ops_policy import (HUMAN, TRANSIENT, PORTAL_PORT, DOORAY_PORT,
                                 alert_state, restart_action)
from ggongbab.ops_storage import OpsError, SafeLog, atomic_json, lock_held
from ggongbab.portal_list_state import ListStateError, PortalListState, poller_lock
from ggongbab.portal_session import ListTransportError
from ggongbab.portal_list_poller import run_poller
from ggongbab.resident_ops import Files, Journal, Watchdog, run_worker, status_lines
from ggongbab.windows_portal_host import PortalHost, STOP_SCRIPT
import ggongbab.resident_ops as ops

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("LIVE_OPERATION_FORBIDDEN")
    monkeypatch.setattr("urllib.request.urlopen", forbidden)
    monkeypatch.setattr("requests.sessions.Session.send", forbidden)
    monkeypatch.setattr("subprocess.Popen", forbidden)
    monkeypatch.setattr("subprocess.run", forbidden)
    monkeypatch.setattr("ggongbab.portal_session.PortalSessionProvider.acquire", forbidden)


class Clock:
    def __init__(self):
        self.value = 1000
    def __call__(self):
        return self.value


@pytest.fixture
def files(tmp_path):
    files = Files(tmp_path)
    files.set_enabled(True, 1000)
    return files


def record(files, code, clock, **extra):
    row = files.runtime_state()
    row.update(started=1000, observed=clock(), reason=code, running=False,
               manual_reason=code if code in HUMAN else "", **extra)
    atomic_json(files.runtime, row)


def watchdog(files, clock):
    host = Mock()
    host.inspect.return_value = ("verified", None)
    launch = Mock(side_effect=lambda *args: Mock(poll=Mock(return_value=None)))
    return Watchdog(files, host=host, launch=launch, now=clock), launch


@pytest.mark.parametrize("code", sorted(TRANSIENT))
def test_transients_have_bounded_exponential_restarts(code):
    assert [restart_action(code, i) for i in range(6)] == [
        ("retry", 60), ("retry", 120), ("retry", 240), ("retry", 480), ("retry", 900), ("exhausted", None)]


@pytest.mark.parametrize("code", sorted(HUMAN))
def test_human_failures_never_retry(code):
    assert restart_action(code, 0) == ("manual", None)
    assert restart_action(code, 5) == ("manual", None)


@pytest.mark.parametrize("age,level", [(0, "healthy"), (180, "healthy"), (181, "warning"), (600, "warning"), (601, "critical")])
def test_heartbeat_success_thresholds(age, level):
    alert = alert_state("WORKER_RUNNING", 1000, 1000 + age)
    assert alert["severity"] == level and alert["last_success_age_seconds"] == age
    assert set(alert) == {"component", "severity", "action", "reason", "last_success_age_seconds"}


def test_duplicate_supervisors_and_existing_poller_lock(files):
    with poller_lock(files.watch_lock):
        with pytest.raises(ListStateError):
            with poller_lock(files.watch_lock):
                pytest.fail("duplicate supervisor")
    with poller_lock(files.worker_lock):
        assert lock_held(files.worker_lock)
        with pytest.raises(ListStateError):
            run_worker(files, settings=SimpleNamespace(has_supabase=False))
        assert not files.runtime.exists()  # must not overwrite running worker status
    assert not lock_held(files.worker_lock)
    assert files.worker_lock.exists()  # crash-safe lock does not rely on deleting files


def test_watchdog_does_not_launch_over_manual_or_orphan_worker(files):
    clock = Clock()
    dog, launch = watchdog(files, clock)
    try:
        with poller_lock(files.worker_lock):
            assert dog.tick()
            launch.assert_not_called()
    finally:
        dog.close()


def test_unexpected_exit_waits_and_budget_survives_watchdog_restart(files):
    clock = Clock()
    dog, launch = watchdog(files, clock)
    dog.tick()
    assert launch.call_count == 1
    dog.child.poll.return_value = 1
    clock.value += 1
    record(files, "WORKER_EXITED", clock)
    dog.tick()
    assert dog.state["retry_at"] == clock() + 60
    dog.close()
    restarted, again = watchdog(files, clock)
    try:
        restarted.tick()
        again.assert_not_called()
        clock.value += 60
        restarted.tick()
        assert again.call_count == 1 and restarted.state["launches"] == 2
    finally:
        restarted.close()


@pytest.mark.parametrize("code", ["PORTAL_LIST_AUTH_REQUIRED", "PORTAL_UI_CHANGED", "PORTAL_RESIDENT_OWNER_UNVERIFIED",
                                  "PORTAL_LIST_STATE_UNAVAILABLE", "PORTAL_SESSION_COOKIE_UNUSABLE"])
def test_terminal_latch_survives_logon_and_only_explicit_start_resumes(files, code):
    clock = Clock()
    dog, launch = watchdog(files, clock)
    dog.tick()
    dog.child.poll.return_value = 10
    clock.value += 1
    record(files, code, clock)
    dog.tick()
    assert dog.state["latched"] == code
    dog.close()
    dog, launch = watchdog(files, clock)
    try:
        clock.value += 3600
        for _ in range(3):
            dog.tick()
        launch.assert_not_called()
        files.set_enabled(True, clock())
        dog.tick()
        assert launch.call_count == 1 and not dog.state["latched"]
    finally:
        dog.close()


PORTAL_PAGE = "https://portal.kaist.ac.kr/main"
SSO_PAGE = "https://sso.kaist.ac.kr/auth/kaist/user/login/view"


def latched_dog(files, clock, code):
    dog, launch = watchdog(files, clock)
    dog.tick()
    dog.child.poll.return_value = 10
    clock.value += 1
    record(files, code, clock)
    dog.tick()
    assert dog.state["latched"] == code
    pages = {"urls": [PORTAL_PAGE]}
    dog.targets = lambda port: [{"id": f"t{i}", "url": url} for i, url in enumerate(pages["urls"])]
    return dog, launch, pages


def ticks(dog, clock, n=1):
    for _ in range(n):
        clock.value += 15
        dog.tick()


def test_a_login_latch_resumes_after_a_person_logged_in_again(files):
    """After the PC slept the Portal tab sat on the KAIST SSO page and the worker stopped with
    PORTAL_CONTEXT_MISSING_OR_AMBIGUOUS. The watchdog never logs in: it waits until a person has
    an SSO page open and closed again in the dedicated browser, then acknowledges the latch the
    same way an operator's start does."""
    clock = Clock()
    dog, launch, pages = latched_dog(files, clock, "PORTAL_CONTEXT_MISSING_OR_AMBIGUOUS")
    try:
        launches = launch.call_count
        ticks(dog, clock, 3)                                 # a Portal page alone: no login seen
        assert dog.state["latched"] and launch.call_count == launches
        pages["urls"] = [SSO_PAGE]                           # a person is logging in
        ticks(dog, clock)
        assert dog.state["latched"] and launch.call_count == launches
        pages["urls"] = [PORTAL_PAGE]                        # the login finished
        ticks(dog, clock)
        assert files.control_state() == {"enabled": True, "resume": clock()}
        assert "OPS_AUTO_RESUMED" in (files.local / "ops-watchdog.log").read_text(encoding="utf-8")
        ticks(dog, clock)
        assert not dog.state["latched"] and launch.call_count == launches + 1
    finally:
        dog.close()


def fail_again(dog, files, clock, code):
    dog.child.poll.return_value = 10
    clock.value += 1
    record(files, code, clock)
    ticks(dog, clock)
    assert dog.state["latched"] == code


def test_a_settled_browser_gets_one_quick_retry_and_a_broken_session_no_loop(files):
    """2026-10-12: two minutes after the PC woke the worker latched with
    PORTAL_CONTEXT_MISSING_OR_AMBIGUOUS, and the same login worked on a plain start 16 hours later.
    While the page list looks right (one Portal page, no SSO page) the watchdog retries such a
    latch once, two minutes after it; the retry is spent until a scan succeeds."""
    clock = Clock()
    code = "PORTAL_CONTEXT_MISSING_OR_AMBIGUOUS"
    dog, launch, pages = latched_dog(files, clock, code)
    try:
        launches = launch.call_count
        ticks(dog, clock, 6)                                 # 90 s after the latch was first seen: too soon
        assert dog.state["latched"] and launch.call_count == launches
        ticks(dog, clock, 4)                                 # 120 s: acknowledged; the next tick relaunches
        assert not dog.state["latched"] and launch.call_count == launches + 1
        fail_again(dog, files, clock, code)                  # still broken
        ticks(dog, clock, 20)                                # 5 minutes: no second quick retry
        assert dog.state["latched"] == code and launch.call_count == launches + 1
        pages["urls"] = [SSO_PAGE]                           # only a person's login resumes it now
        ticks(dog, clock)
        pages["urls"] = [PORTAL_PAGE]
        ticks(dog, clock, 2)
        assert not dog.state["latched"] and launch.call_count == launches + 2
    finally:
        dog.close()


def test_a_successful_scan_gives_the_quick_retry_back(files):
    clock = Clock()
    code = "PORTAL_CONTEXT_MISSING_OR_AMBIGUOUS"
    dog, launch, pages = latched_dog(files, clock, code)
    try:
        ticks(dog, clock, 10)                                # quick retry used, worker relaunched
        assert not dog.state["latched"]
        launches = launch.call_count
        clock.value += 30
        row = files.runtime_state()                          # the relaunched worker scans successfully
        row.update(observed=clock(), reason="WORKER_RUNNING", manual_reason="", last_success=clock(), running=True)
        atomic_json(files.runtime, row)
        ticks(dog, clock)
        assert launch.call_count == launches                 # nothing to do while it runs
        fail_again(dog, files, clock, code)                  # a later, separate latch
        ticks(dog, clock, 10)                                # gets its own quick retry
        assert not dog.state["latched"] and launch.call_count == launches + 1
    finally:
        dog.close()


@pytest.mark.parametrize("code", ["PORTAL_UI_CHANGED", "PORTAL_RESIDENT_OWNER_UNVERIFIED",
                                  "PORTAL_LIST_STATE_UNAVAILABLE"])
def test_only_login_latches_resume_on_their_own(files, code):
    clock = Clock()
    dog, launch, pages = latched_dog(files, clock, code)
    try:
        launches = launch.call_count
        pages["urls"] = [SSO_PAGE]
        ticks(dog, clock)
        pages["urls"] = [PORTAL_PAGE]
        ticks(dog, clock, 20)                                # neither a login nor a quick retry
        assert dog.state["latched"] == code and launch.call_count == launches
    finally:
        dog.close()


def test_an_unverified_browser_or_two_portal_pages_never_resume(files):
    clock = Clock()
    dog, launch, pages = latched_dog(files, clock, "PORTAL_CONTEXT_MISSING_OR_AMBIGUOUS")
    try:
        launches = launch.call_count
        pages["urls"] = [SSO_PAGE]
        ticks(dog, clock)
        pages["urls"] = [PORTAL_PAGE, PORTAL_PAGE]           # ambiguous: two Portal pages
        ticks(dog, clock, 12)
        dog.host.inspect.return_value = ("unverified", None)
        pages["urls"] = [PORTAL_PAGE]
        ticks(dog, clock, 12)
        assert dog.state["latched"] and launch.call_count == launches
    finally:
        dog.close()


def test_retry_after_is_kept_across_process_restart(files):
    clock = Clock()
    dog, launch = watchdog(files, clock)
    try:
        dog.tick()
        dog.child.poll.return_value = 1
        clock.value += 1
        record(files, "PORTAL_LIST_TRANSPORT_UNAVAILABLE", clock, retry_not_before=clock() + 3600)
        dog.tick()
        assert dog.state["retry_at"] == clock() + 3600
        clock.value += 900
        dog.tick()
        assert launch.call_count == 1
    finally:
        dog.close()


def test_cdp_timeout_gets_one_targeted_recovery_then_manual(files):
    clock = Clock()
    dog, launch = watchdog(files, clock)
    try:
        dog.tick()
        dog.child.poll.return_value = 10
        clock.value += 1
        record(files, "PORTAL_CDP_ATTACH_TIMEOUT", clock)
        dog.tick()
        clock.value += 60
        dog.tick()
        assert launch.call_args.args == (files, True)
        dog.child.poll.return_value = 10
        clock.value += 1
        record(files, "PORTAL_CDP_ATTACH_TIMEOUT", clock)
        dog.tick()
        assert dog.state["latched"] == "PORTAL_CDP_ATTACH_TIMEOUT"
    finally:
        dog.close()


def host_fixture(tmp_path, inventory):
    profile = tmp_path.resolve() / ".local/portal-browser-profile"
    tokens = {"dedicated": ["chrome.exe", f"--user-data-dir={profile}", "--remote-debugging-port=9223",
                              "--remote-debugging-address=127.0.0.1"],
              "other": ["chrome.exe", "--user-data-dir=OTHER", "--remote-debugging-port=9222"]}
    run = Mock(return_value=json.dumps(inventory))
    start, verify = Mock(), Mock()
    host = PortalHost(tmp_path, run=run, split=lambda value: tokens[value], start=start, verify=verify, sleep=lambda _: None,
                      wake=Mock(return_value={"pages": 1, "restored": 0, "roles": []}))
    return host, run, start, verify


def inventory(listening=False, processes=None, owners=None):
    return {"listening": listening, "loopback": listening, "processes": processes or [], "owners": owners or []}


DEDICATED = {"pid": 123, "command": "dedicated", "created": "999"}
OTHER = {"pid": 456, "command": "other", "created": "888"}


def test_missing_browser_starts_only_dedicated_profile(tmp_path):
    host, run, start, verify = host_fixture(tmp_path, inventory(processes=[OTHER]))
    host.ensure()
    assert start.call_args.args == (tmp_path.resolve() / ".local/portal-browser-profile",)
    assert start.call_args.kwargs["port"] == 9223
    assert start.call_args.kwargs["start_url"] == "https://portal.kaist.ac.kr/"
    verify.assert_called_once_with(host.profile, 9223)
    assert all(call.args[0] != STOP_SCRIPT for call in run.call_args_list)


@pytest.mark.parametrize("data", [
    inventory(True, [OTHER], [456]), inventory(True, [DEDICATED, OTHER], [456]),
    inventory(True, [DEDICATED], [123, 456]), inventory(True, [], [456]),
])
def test_unverified_owner_never_stopped_or_started(tmp_path, data):
    host, run, start, verify = host_fixture(tmp_path, data)
    with pytest.raises(OpsError, match="PORTAL_RESIDENT_OWNER_UNVERIFIED"):
        host.ensure(recover_stale=True)
    start.assert_not_called()
    verify.assert_not_called()
    assert all(call.args[0] != STOP_SCRIPT for call in run.call_args_list)


def test_existing_verified_browser_is_reused(tmp_path):
    host, run, start, verify = host_fixture(tmp_path, inventory(True, [DEDICATED, OTHER], [123]))
    host.ensure()
    start.assert_not_called()
    verify.assert_called_once()


def test_stale_recovery_stops_exact_verified_process(tmp_path):
    host, run, start, verify = host_fixture(tmp_path, inventory(True, [DEDICATED, OTHER], [123]))
    run.side_effect = [json.dumps(inventory(True, [DEDICATED, OTHER], [123])), "", json.dumps(inventory(processes=[OTHER]))]
    host.ensure(recover_stale=True)
    # The exact verified identity plus the slot's port (stdin JSON, never interpolated).
    assert run.call_args_list[1].args == (STOP_SCRIPT, dict(DEDICATED, port=9223))
    start.assert_called_once()
    assert "CreationDate" in STOP_SCRIPT and "CommandLine -cne" in STOP_SCRIPT
    assert "Stop-Process -Id $proc.ProcessId" in STOP_SCRIPT
    assert "chrome.exe /" not in STOP_SCRIPT and "Remove-Item" not in STOP_SCRIPT


def test_non_listening_dedicated_process_requires_manual_recovery(tmp_path):
    host, run, start, _ = host_fixture(tmp_path, inventory(processes=[DEDICATED]))
    assert host.inspect()[0] == "stale"
    with pytest.raises(OpsError):
        host.ensure()
    start.assert_not_called()


def test_journal_uses_existing_heartbeat_and_never_claims_failed_write(files):
    clock = Clock()
    journal = Journal(files, now=clock)
    now = datetime(2026, 9, 23, tzinfo=KST)
    writer = Mock()
    row = build_heartbeat(agent_id="portal-list-poller", status="healthy", exit_class="0",
                          last_scan_at=now, last_success_at=now)
    journal.heartbeat(row, writer)
    writer.write.assert_called_once_with(row)
    confirmed = journal.row["last_success"]
    writer.write.side_effect = RuntimeError("SECRET_RESPONSE")
    row["last_success_at"] = (now + timedelta(minutes=1)).isoformat()
    with pytest.raises(RuntimeError):
        journal.heartbeat(row, writer)
    assert journal.row["last_success"] == confirmed
    journal("PORTAL_LIST_AUTH_REQUIRED")
    journal("PORTAL_HEARTBEAT_WRITE_FAILED")
    journal.close()
    assert files.runtime_state()["manual_reason"] == "PORTAL_LIST_AUTH_REQUIRED"
    assert "SECRET_RESPONSE" not in files.runtime.read_text()


def test_bounded_logs_accept_only_fixed_codes(tmp_path):
    path = tmp_path / "ops.log"
    sink = SafeLog(path, max_bytes=150, backups=3)
    for _ in range(100):
        sink("WORKER_RUNNING")
        sink("JSESSIONID=SECRET title=PRIVATE subject=PRIVATE id=9999")
        sink({"token": "SECRET"})
    sink.close()
    logs = list(tmp_path.glob("ops.log*"))
    assert len(logs) == 4
    assert all(p.stat().st_size <= 150 for p in logs)
    assert "SECRET" not in "".join(p.read_text() for p in logs)


def test_status_never_formats_unknown_content_or_account_data(files):
    clock = Clock()
    record(files, "WORKER_RUNNING", clock, last_success=958)
    host = Mock(inspect=Mock(return_value=("verified", {"command": "JSESSIONID=SECRET"})))
    lines = "\n".join(status_lines(files, host=host, now=1000))
    assert "42 sec ago" in lines and "9223" in lines and "9222" in lines
    assert "WORKER_EXITED" in lines  # lock absent, old healthy record is not a running worker
    assert "SECRET" not in lines and "not tested locally" in lines
    row = files.runtime_state()
    row["reason"] = "SECRET_SUBJECT"
    atomic_json(files.runtime, row)
    with pytest.raises(OpsError):
        status_lines(files, host=host)


def test_worker_preserves_baseline_pending_and_lock(files, monkeypatch):
    ledger = PortalListState(files.local / "portal-list-state.json")
    entry = {"reg_dt": "2026-09-23T09:00:00+09:00", "fingerprint": "a" * 64, "public": True, "candidate": True}
    ledger.commit({"version": 1, "initialized": True, "lower_bound": entry["reg_dt"],
                   "notices": {"b" * 64: entry}, "pending": {"b" * 64: entry}})
    before = ledger.path.read_bytes()
    monkeypatch.setattr("ggongbab.db.supabase_client.SupabaseClient", lambda *args: Mock())
    def fake_run(provider, state, **kwargs):
        assert lock_held(files.worker_lock)
        assert state.data["initialized"] and len(state.data["pending"]) == 1
        assert kwargs["interval"] == 60 and kwargs["max_failures"] == 5
        return 0
    monkeypatch.setattr(ops, "run_poller", fake_run)
    settings = SimpleNamespace(has_supabase=True, supabase_url="https://fake.invalid", supabase_secret_key="fake")
    for _ in range(2):
        assert run_worker(files, settings=settings, host=Mock()) == 0
        assert ledger.path.read_bytes() == before
    assert not lock_held(files.worker_lock)


def test_task_scheduler_configuration_and_no_dooray_autostart():
    script = (ROOT / "scripts/windows/install_ggongbab_tasks.ps1").read_text(encoding="utf-8")
    assert "-AtLogOn -User $operator" in script and "'PT30S'" in script
    assert "-LogonType Interactive -RunLevel Limited" in script
    assert "pythonw.exe" in script and "-MultipleInstances IgnoreNew" in script
    assert "-RestartCount 3" in script and "-Minutes 1" in script
    assert "-ExecutionTimeLimit ([TimeSpan]::Zero)" in script
    assert "-WakeToRun" not in script and "-Password" not in script and "-AtStartup" not in script
    assert "dooray_web_agent" not in script and "dooray-once" not in script
    assert "Start-ScheduledTask" not in script  # installation does not contact Portal


def test_ports_and_no_profile_or_state_removal_or_detail_endpoints():
    assert PORTAL_PORT == 9223 and DOORAY_PORT == 9222
    source = "\n".join((ROOT / name).read_text(encoding="utf-8") for name in (
        "scripts/ggongbab/resident_ops.py", "scripts/ggongbab/windows_portal_host.py",
        "scripts/windows/ggongbab_workers.py", "scripts/ggongbab/ops_browser.py",
        "scripts/ggongbab/ops_browser_control.py", "scripts/ggongbab/ops_browser_proof.py",
        "scripts/windows/ops_browser.ps1"))
    for forbidden in ("rmtree", "Remove-Item", "taskkill", "recents/{", "fetch_detail", "fill(", "otp", "password=",
                      "clear_cookies", "Network.clearBrowserCookies", "Storage.clearDataForOrigin",
                      "open_body", "detail_api"):
        assert forbidden not in source
    # The Ops Chrome modules delete nothing at all (profiles, state, latches stay as they are).
    new = "\n".join((ROOT / "scripts/ggongbab" / name).read_text(encoding="utf-8") for name in (
        "ops_browser.py", "ops_browser_control.py", "ops_browser_proof.py"))
    for forbidden in ("unlink(", "rmdir", "os.remove", "shutil", "Stop-Process", "kill("):
        assert forbidden not in new
    assert "portal-list-state.json" in source and "portal-list.lock" in source
    assert "ggongbab_public_events" not in source


def test_bounded_in_process_retries_and_cooperative_stop(tmp_path):
    provider = Mock(acquire=Mock(return_value=Mock()))
    state = PortalListState(tmp_path / "ledger")
    import ggongbab.portal_list_poller as poller
    errors = [ListTransportError(reason="PORTAL_LIST_CONNECT_TIMEOUT") for _ in range(3)]
    calls, delays = [], []
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(poller.PortalListPoller, "poll_once", Mock(side_effect=errors))
        code = run_poller(provider, state, emit_heartbeat=lambda row: None, max_failures=3,
            on_retry=delays.append, sleep=calls.append, monotonic=lambda: 0, log=lambda _: None)
        # Backoff after the first failure; from the second, the stale transport is rebuilt
        # after a short bounded wait (Phase 2). The failure budget still stops the worker.
        assert code == 1 and delays == [120, 30, 30] and sum(calls) == 150
        assert provider.acquire.call_count == 2
    provider.reset_mock()
    assert run_poller(provider, state, emit_heartbeat=lambda row: None, stop_requested=lambda: True) == 0
    provider.acquire.assert_not_called()


@pytest.mark.parametrize("code,status", [("PORTAL_CDP_ATTACH_TIMEOUT", "collector_error"),
    ("PORTAL_RESIDENT_OWNER_UNVERIFIED", "collector_error"), ("PORTAL_LIST_AUTH_REQUIRED", "auth_required")])
def test_browser_failures_are_not_mislabeled_as_expired_auth(tmp_path, code, status):
    from ggongbab.web.exit_codes import AuthRequired
    beats = []
    provider = Mock(acquire=Mock(side_effect=AuthRequired(code)))
    assert run_poller(provider, PortalListState(tmp_path / "ledger"), emit_heartbeat=beats.append, log=lambda _: None) == 10
    assert beats[-1]["status"] == status
    assert beats[-1]["auth_required"] is (status == "auth_required")


def test_disabled_watchdog_never_launches(files):
    clock = Clock()
    files.set_enabled(False, clock())
    dog, launch = watchdog(files, clock)
    try:
        assert dog.tick() is False
        launch.assert_not_called()
    finally:
        dog.close()


def test_retry_exhaustion_persists(files):
    clock = Clock()
    dog, launch = watchdog(files, clock)
    try:
        dog.state.update(launches=6, launched_at=1000, resume=1000)
        record(files, "WORKER_EXITED", clock)
        dog.save()
        dog.tick()
        assert dog.state["latched"] == "OPS_RETRY_EXHAUSTED"
        launch.assert_not_called()
    finally:
        dog.close()


def test_stale_live_worker_is_reported_without_kill(files):
    clock = Clock()
    dog, _ = watchdog(files, clock)
    try:
        dog.tick()
        child = dog.child
        for _ in range(41):                      # the watchdog keeps its 15 s cadence; the worker is silent
            clock.value += 15
            dog.tick()
        assert dog.state["latched"] == "OPS_WORKER_UNRESPONSIVE"
        child.terminate.assert_not_called()
        child.kill.assert_not_called()
    finally:
        dog.close()


def test_a_sleep_gives_the_worker_a_grace_window_before_it_is_called_unresponsive(files):
    clock = Clock()
    dog, _ = watchdog(files, clock)
    try:
        dog.tick()
        clock.value += 7200                      # the PC slept for two hours: no tick ran
        dog.tick()
        assert dog.state["latched"] == ""
        for _ in range(38):                      # still inside the 600 s grace after waking
            clock.value += 15
            dog.tick()
        assert dog.state["latched"] == ""
    finally:
        dog.close()


def test_an_unresponsive_latch_clears_itself_once_the_worker_scans_again(files, monkeypatch):
    import ggongbab.resident_ops as ops
    clock = Clock()
    dog, _ = watchdog(files, clock)
    try:
        dog.state["latched"] = "OPS_WORKER_UNRESPONSIVE"
        monkeypatch.setattr(ops, "lock_held", lambda path: path == files.worker_lock)
        row = files.runtime_state()
        row.update(last_success=clock.value - 30, observed=clock.value, reason="WORKER_RUNNING", running=True)
        atomic_json(files.runtime, row)
        dog.tick()
        assert dog.state["latched"] == ""
    finally:
        dog.close()


def test_a_worker_waking_from_its_own_backoff_is_not_called_unresponsive(files):
    """2026-10-29: the worker slept its 900 s backoff and was latched in the seconds it took to
    rebuild its session after waking."""
    clock = Clock()
    dog, _ = watchdog(files, clock)
    try:
        dog.tick()
        record(files, "PORTAL_LIST_CONNECTION_ERROR", clock, retry_not_before=clock.value + 900)
        for _ in range(61):                      # 915 s: the backoff is over, the worker is rebuilding
            clock.value += 15
            dog.tick()
        assert dog.state["latched"] == ""
    finally:
        dog.close()


@pytest.mark.parametrize("restarted", [False, True])
def test_an_unresponsive_latch_is_released_once_the_worker_has_exited(files, restarted):
    """Nothing can be writing once the child is gone and the lock is free: the restart budget
    decides again (after a watchdog restart there is no child handle at all)."""
    clock = Clock()
    dog, launch = watchdog(files, clock)
    try:
        dog.tick()
        record(files, "PORTAL_LIST_CONNECTION_ERROR", clock)
        dog.state["latched"] = "OPS_WORKER_UNRESPONSIVE"
        if restarted:
            dog.child = None
        else:
            dog.child.poll.return_value = 1
        dog.tick()
        assert dog.state["latched"] == "" and dog.state["retry_at"] == clock.value + 60
        clock.value += 60
        dog.tick()
        assert launch.call_count == 2
    finally:
        dog.close()


def test_an_unresponsive_latch_holds_while_the_worker_is_alive(files):
    clock = Clock()
    dog, launch = watchdog(files, clock)
    try:
        dog.tick()
        dog.state["latched"] = "OPS_WORKER_UNRESPONSIVE"
        clock.value += 3600
        dog.tick()
        assert dog.state["latched"] == "OPS_WORKER_UNRESPONSIVE" and launch.call_count == 1
    finally:
        dog.close()


def test_the_watchdog_writes_combined_alerts_every_tick(files):
    clock = Clock()
    dog, _ = watchdog(files, clock)
    try:
        dog.tick()
        payload = json.loads((files.local / "ops-alerts.json").read_text(encoding="utf-8"))
        assert [a["component"] for a in payload["alerts"]] == ["portal"]
        assert set(payload["alerts"][0]) == {"component", "severity", "reason", "last_success_age_seconds",
                                             "timestamp", "action"}
    finally:
        dog.close()


def test_corrupt_control_fails_without_touching_ledger(files):
    ledger = PortalListState(files.local / "portal-list-state.json")
    ledger.commit(ledger.data)
    before = ledger.path.read_bytes()
    atomic_json(files.control, {"enabled": "SECRET", "resume": 1000})
    with pytest.raises(OpsError):
        files.control_state()
    assert ledger.path.read_bytes() == before


def test_browser_start_failure_stops_instead_of_becoming_network_retry(tmp_path):
    host, _, start, verify = host_fixture(tmp_path, inventory())
    start.side_effect = RuntimeError("PRIVATE_COMMAND_LINE")
    with pytest.raises(OpsError, match="^PORTAL_RESIDENT_OWNER_UNVERIFIED$"):
        host.ensure()
    verify.assert_not_called()


@pytest.mark.parametrize("extra", ["--remote-debugging-port=9222", "--remote-debugging-address=0.0.0.0"])
def test_duplicate_or_wrong_port_flags_never_allow_stop(tmp_path, extra):
    host, run, start, _ = host_fixture(tmp_path, inventory(True, [DEDICATED], [123]))
    original = host.split
    host.split = lambda command: original(command) + [extra]
    with pytest.raises(OpsError):
        host.ensure(recover_stale=True)
    assert all(call.args[0] != STOP_SCRIPT for call in run.call_args_list)
    start.assert_not_called()


def retry_host(tmp_path, snapshots, verify=None):
    profile = tmp_path.resolve() / ".local/portal-browser-profile"
    tokens = {"dedicated": ["chrome.exe", f"--user-data-dir={profile}", "--remote-debugging-port=9223",
                            "--remote-debugging-address=127.0.0.1"], "other": ["chrome.exe"]}
    run = Mock(side_effect=[json.dumps(s) for s in snapshots])
    start, slept = Mock(), []
    host = PortalHost(tmp_path, run=run, split=lambda value: tokens[value], start=start,
                      verify=verify or Mock(), sleep=slept.append,
                      wake=Mock(return_value={"pages": 1, "restored": 0, "roles": []}))
    return host, run, start, slept


MID_EXIT = {"pid": 77, "command": "", "created": "5"}   # a renderer gone mid-snapshot: no command line


def test_one_unreadable_snapshot_after_a_resume_is_read_again_not_latched(tmp_path):
    host, run, start, slept = retry_host(tmp_path, [inventory(True, [DEDICATED, MID_EXIT], [123]),
                                                    inventory(True, [DEDICATED, OTHER], [123])])
    host.ensure()
    assert slept == [5] and run.call_count == 2
    start.assert_not_called()
    assert all(call.args[0] != STOP_SCRIPT for call in run.call_args_list)


def test_an_owner_that_stays_unverified_still_fails_closed_after_the_rereads(tmp_path):
    unknown = inventory(True, [OTHER], [456])            # a listener that is not the dedicated Chrome
    host, run, start, slept = retry_host(tmp_path, [unknown] * 4)
    with pytest.raises(OpsError, match="^PORTAL_RESIDENT_OWNER_UNVERIFIED$"):
        host.ensure(recover_stale=True)
    assert slept == [5, 5, 5] and run.call_count == 4
    start.assert_not_called()
    assert all(call.args[0] != STOP_SCRIPT for call in run.call_args_list)


def test_the_final_owner_check_is_also_reread_before_it_fails(tmp_path):
    from ggongbab.web.exit_codes import AuthRequired
    flaky = Mock(side_effect=[AuthRequired("PORTAL_RESIDENT_OWNER_UNVERIFIED"), None])
    host, _, _, slept = retry_host(tmp_path, [inventory(True, [DEDICATED], [123])], verify=flaky)
    host.ensure()
    assert flaky.call_count == 2 and slept == [5]
    always = Mock(side_effect=AuthRequired("PORTAL_RESIDENT_OWNER_UNVERIFIED"))
    host, _, _, slept = retry_host(tmp_path, [inventory(True, [DEDICATED], [123])], verify=always)
    with pytest.raises(AuthRequired):
        host.ensure()
    assert always.call_count == 4 and slept == [5, 5, 5]


# --- the watchdog opens a missing Ops Chrome (owner request, 2026-10-28) ------------------------------
def test_a_missing_browser_is_opened_for_a_login_and_at_most_every_thirty_minutes(files):
    """10-19 to 10-28: a login latch never starts a browser, and after a reboot nothing opened one, so
    both collectors stood still for days behind a toast. The watchdog now opens it, for a person to log in."""
    clock = Clock()
    wd, launch = watchdog(files, clock)
    wd.state.update(latched="PORTAL_LIST_AUTH_REQUIRED", resume=1000)   # latched after the last operator start
    wd.save()
    wd.host.inspect.return_value = ("absent", None)
    assert wd.tick() is True
    wd.host.ensure.assert_called_once()
    assert wd.host.ensure.call_args.kwargs["minimized"] is False      # a person must see the login page
    clock.value += 15
    wd.tick()
    assert wd.host.ensure.call_count == 1                             # not on every 15 s tick
    clock.value += ops.REOPEN_BROWSER_SECONDS
    wd.tick()
    assert wd.host.ensure.call_count == 2
    assert "OPS_BROWSER_AUTO_OPENED" in (files.local / "ops-watchdog.log").read_text(encoding="utf-8")
    launch.assert_not_called()                                        # the latch still launches no worker
    assert wd.state["latched"] == "PORTAL_LIST_AUTH_REQUIRED"          # opening is not a login


def test_without_a_login_latch_the_browser_opens_as_an_unattended_start(files):
    clock = Clock()
    wd, _ = watchdog(files, clock)
    wd.host.inspect.side_effect = [("absent", None), ("verified", None)] + [("verified", None)] * 10
    wd.tick()
    wd.host.ensure.assert_called_once()
    assert wd.host.ensure.call_args.kwargs["minimized"] is True


def test_a_failed_open_is_logged_and_waits_for_the_next_attempt(files):
    clock = Clock()
    wd, _ = watchdog(files, clock)
    wd.state.update(latched="PORTAL_LIST_AUTH_REQUIRED", resume=1000)   # latched after the last operator start
    wd.host.inspect.return_value = ("absent", None)
    wd.host.ensure.side_effect = OpsError("PORTAL_RESIDENT_OWNER_UNVERIFIED")
    assert wd.tick() is True
    assert "OPS_BROWSER_AUTO_OPEN_FAILED" in (files.local / "ops-watchdog.log").read_text(encoding="utf-8")
    clock.value += 60
    wd.tick()
    assert wd.host.ensure.call_count == 1


@pytest.mark.parametrize("state", ["verified", "stale", "unverified"])
def test_only_an_absent_browser_is_opened(files, state):
    clock = Clock()
    wd, _ = watchdog(files, clock)
    wd.state.update(latched="PORTAL_LIST_AUTH_REQUIRED", resume=1000)   # latched after the last operator start
    wd.host.inspect.return_value = (state, None)
    wd.tick()
    wd.host.ensure.assert_not_called()                                # a stale or unknown process is never touched


def test_stopped_workers_never_open_the_browser(files):
    clock = Clock()
    files.set_enabled(False, 1001)
    wd, _ = watchdog(files, clock)
    wd.host.inspect.return_value = ("absent", None)
    assert wd.tick() is False
    wd.host.ensure.assert_not_called()
