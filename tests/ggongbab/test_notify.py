# -*- coding: utf-8 -*-
"""External alert push: fixed fields only, transitions not ticks, tokens never leaked. Fakes only."""
from __future__ import annotations

import io
import json
import urllib.error

import pytest

from ggongbab import cloud_watch, notify
from ggongbab.alerts import Alert

NOW = 2_000_000_000.0
TOKEN = "123456789:SYNTHETIC_TOKEN_NOT_REAL_abcdefghijklmnop"
PRIVATE = "SYNTHETIC-PRIVATE-SUBJECT"


class Opener:
    def __init__(self, status=200, error=None):
        self.status, self.error, self.requests = status, error, []

    def __call__(self, request, timeout):
        self.requests.append({"url": request.full_url, "headers": dict(request.header_items()),
                              "body": request.data.decode("utf-8")})
        if self.error:
            raise self.error
        if self.status >= 400:
            raise urllib.error.HTTPError(request.full_url, self.status, "x", {}, io.BytesIO(b""))
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Recorder:
    def __init__(self, result=notify.SENT):
        self.result, self.messages = result, []

    def send(self, text):
        self.messages.append(text)
        return self.result


def crit(component="portal", reason="SCAN_STALE", age=900):
    return Alert.of(component, reason, age, NOW)


def warn(component="portal", age=200):
    return Alert.of(component, "SCAN_DELAYED", age, NOW)


def ok(component="portal"):
    return Alert.of(component, "OK", 10, NOW)


def test_telegram_sends_fixed_fields_and_never_returns_the_token():
    opener = Opener()
    result = notify.TelegramNotifier(TOKEN, "4242", opener).send(notify.format_message([crit()], source="local PC"))
    assert result == notify.SENT
    body = json.loads(opener.requests[0]["body"])
    assert body["chat_id"] == "4242" and "CRITICAL · Portal LIST · SCAN_STALE · last success 15 min ago" in body["text"]
    assert TOKEN not in body["text"] and TOKEN not in result


@pytest.mark.parametrize("status,error,expected", [(401, None, notify.AUTH_FAILED), (404, None, notify.AUTH_FAILED),
                                                   (429, None, notify.REJECTED),
                                                   (0, urllib.error.URLError("down"), notify.TRANSPORT_FAILED)])
def test_send_failures_are_fixed_codes(status, error, expected):
    assert notify.TelegramNotifier(TOKEN, "1", Opener(status, error)).send("x") == expected


def test_ntfy_is_authenticated_and_marks_critical_urgent():
    opener = Opener()
    notify.NtfyNotifier("https://ntfy.example.invalid/", "babdoduk-ops", "tk_SYNTHETIC", opener).send(
        notify.format_message([crit()], source="cloud monitor"))
    request = opener.requests[0]
    assert request["url"] == "https://ntfy.example.invalid/babdoduk-ops"
    assert request["headers"]["Priority"] == "urgent"


def test_message_has_no_room_for_private_text():
    a = Alert.of("dooray_radar", PRIVATE, 30, NOW)          # unknown reason collapses to a fixed code
    text = notify.format_message([a], source="local PC")
    assert PRIVATE not in text and "NO_SUCCESS_RECORDED" in text


def test_critical_pushes_once_then_reminds_after_six_hours_and_reports_recovery(tmp_path):
    policy, sink = notify.PushPolicy(tmp_path / "state.json"), Recorder()
    assert notify.push([crit()], sink, policy, source="local PC", now=NOW) == notify.SENT
    assert notify.push([crit()], sink, policy, source="local PC", now=NOW + 15) == notify.NOTHING
    assert notify.push([crit()], sink, policy, source="local PC", now=NOW + 6 * 3600 + 1) == notify.SENT
    assert notify.push([ok()], sink, policy, source="local PC", now=NOW + 7 * 3600) == notify.SENT
    assert "RECOVERED · Portal LIST" in sink.messages[-1] and len(sink.messages) == 3


def test_a_brief_warning_never_reaches_the_phone_but_a_lasting_one_does(tmp_path):
    policy, sink = notify.PushPolicy(tmp_path / "state.json"), Recorder()
    assert notify.push([warn()], sink, policy, source="local PC", now=NOW) == notify.NOTHING
    assert notify.push([ok()], sink, policy, source="local PC", now=NOW + 60) == notify.NOTHING   # no recovery spam
    assert notify.push([warn()], sink, policy, source="local PC", now=NOW + 120) == notify.NOTHING
    assert notify.push([warn()], sink, policy, source="local PC", now=NOW + 120 + 601) == notify.SENT
    assert sink.messages and "WARNING" in sink.messages[0]


def test_escalation_to_critical_pushes_immediately(tmp_path):
    policy, sink = notify.PushPolicy(tmp_path / "state.json"), Recorder()
    notify.push([warn()], sink, policy, source="local PC", now=NOW)
    assert notify.push([crit()], sink, policy, source="local PC", now=NOW + 30) == notify.SENT


def test_a_failed_push_backs_off_then_retries_the_same_alert(tmp_path):
    policy, failing = notify.PushPolicy(tmp_path / "state.json"), Recorder(notify.TRANSPORT_FAILED)
    assert notify.push([crit()], failing, policy, source="local PC", now=NOW) == notify.TRANSPORT_FAILED
    assert notify.push([crit()], failing, policy, source="local PC", now=NOW + 15) == notify.BACKOFF
    working = Recorder()
    assert notify.push([crit()], working, policy, source="local PC", now=NOW + 301) == notify.SENT


def test_not_configured_is_a_no_op(tmp_path):
    assert notify.push_local(tmp_path, [crit()], now=NOW, notifier=None) in (notify.NOT_CONFIGURED,)
    assert not (tmp_path / "alert-push-state.json").exists()


def test_local_notifier_needs_both_config_and_a_stored_token(tmp_path):
    assert notify.local_notifier(tmp_path, read_credential=lambda t: TOKEN) is None
    (tmp_path / "alert-push.json").write_text(json.dumps({"provider": "telegram", "chat_id": "42"}), encoding="utf-8")
    assert notify.local_notifier(tmp_path, read_credential=lambda t: None) is None
    assert isinstance(notify.local_notifier(tmp_path, read_credential=lambda t: TOKEN), notify.TelegramNotifier)
    assert TOKEN not in (tmp_path / "alert-push.json").read_text(encoding="utf-8")


# --- Windows toast on the operations PC --------------------------------------------------------
class Run:
    def __init__(self, code=0, error=None):
        self.code, self.error, self.commands = code, error, []

    def __call__(self, command, **kwargs):
        self.commands.append((command, kwargs))
        if self.error:
            raise self.error
        return type("Done", (), {"returncode": self.code})()


def test_the_toast_is_fixed_korean_wording_from_fixed_fields():
    title, body = notify.format_toast([Alert.of("portal", "AUTH_EXPIRED", 63564, NOW)])
    assert title == "밥도둑 운영: 조치가 필요합니다"
    assert body.splitlines() == ["Portal 공지 수집 · 로그인 만료",
                                 "운영 Chrome에서 직접 로그인하세요. 로그인 화면이 닫히면 저절로 다시 시작합니다."]
    assert notify.format_toast([], ["dooray_radar"]) == ("밥도둑 운영: 다시 정상입니다", "Dooray 메일 레이더 · 다시 정상")
    for reason in ("AUTH_EXPIRED", "SCAN_STALE", "BROWSER_ABSENT", "CONTRACT_CHANGED", "WORKER_NOT_RUNNING"):
        _, text = notify.format_toast([Alert.of("portal", reason, 900, NOW)])
        assert PRIVATE not in text and "http" not in text


def test_the_toast_runs_hidden_powershell_and_reports_fixed_codes():
    run = Run()
    toast = notify.WindowsToastNotifier(run=run)
    assert toast.send(("밥도둑 운영: 조치가 필요합니다", "Portal 공지 수집 · 로그인 만료")) == notify.SENT
    command, kwargs = run.commands[0]
    assert command[:5] == ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass"]
    assert command[5] == "-EncodedCommand" and kwargs["timeout"] == 30
    import base64
    import subprocess
    script = base64.b64decode(command[6]).decode("utf-16-le")
    assert "ToastNotificationManager" in script and notify.TOAST_APP_ID in script
    assert "로그인" not in script                      # the text travels base64-encoded, never spliced in
    assert kwargs["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)
    assert notify.WindowsToastNotifier(run=Run(code=1)).send(("t", "b")) == notify.TRANSPORT_FAILED
    assert notify.WindowsToastNotifier(run=Run(error=OSError("x"))).send(("t", "b")) == notify.TRANSPORT_FAILED


def test_the_toast_is_on_by_default_on_windows_and_can_be_turned_off(tmp_path):
    assert isinstance(notify.local_toast(tmp_path, windows=True), notify.WindowsToastNotifier)
    assert notify.local_toast(tmp_path, windows=False, linux=False) is None
    (tmp_path / notify.TOAST_CONFIG).write_text(json.dumps({"enabled": False}), encoding="utf-8")
    assert notify.local_toast(tmp_path, windows=True) is None
    assert notify.local_toast(tmp_path, windows=False, linux=True) is None


def test_linux_uses_notify_send_with_fixed_text_and_linux_commands(tmp_path):
    assert isinstance(notify.local_toast(tmp_path, windows=False, linux=True), notify.NotifySendNotifier)
    calls = []

    class Run:
        def __init__(self, code=0, error=None):
            self.code, self.error = code, error

        def __call__(self, command, **kwargs):
            calls.append((command, kwargs))
            if self.error:
                raise self.error
            return type("Done", (), {"returncode": self.code})()

    sender = notify.NotifySendNotifier(run=Run())
    alert = notify.Alert("portal", "critical", "WORKER_NOT_RUNNING", None, 0.0, "restart_worker")
    title, body = sender.render([alert], [])
    assert sender.send((title, body)) == notify.SENT
    command, kwargs = calls[-1]
    assert command[0] == "notify-send" and "--" in command and command[-2:] == [title, body]
    assert "--urgency=critical" in command and "shell" not in kwargs
    assert "scripts/linux/ops.sh start" in body and ".cmd" not in body
    assert notify.NotifySendNotifier(run=Run(code=1)).send(("t", "b")) == notify.TRANSPORT_FAILED
    assert notify.NotifySendNotifier(run=Run(error=OSError("x"))).send(("t", "b")) == notify.TRANSPORT_FAILED


def test_the_toast_waits_out_a_brief_critical_and_keeps_its_own_state(tmp_path):
    """Right after the PC wakes, a scan is late until the workers catch up; that should not pop a
    toast. A critical that lasts 3 minutes does, once, with its own state file."""
    toast = Recorder()
    assert notify.push_local(tmp_path, [crit()], now=NOW, notifier=None, toast=toast) == notify.NOT_CONFIGURED
    assert toast.messages == []
    notify.push_local(tmp_path, [ok()], now=NOW + 60, notifier=None, toast=toast)           # caught up: quiet
    notify.push_local(tmp_path, [crit()], now=NOW + 120, notifier=None, toast=toast)
    notify.push_local(tmp_path, [crit()], now=NOW + 120 + notify.TOAST_CRITICAL_AFTER_SECONDS, notifier=None,
                      toast=toast)
    assert len(toast.messages) == 1 and isinstance(toast.messages[0], str)               # Recorder has no render
    assert (tmp_path / notify.TOAST_STATE).exists() and not (tmp_path / "alert-push-state.json").exists()


def test_the_toast_renders_korean_through_its_own_render_hook(tmp_path):
    run = Run()
    toast = notify.WindowsToastNotifier(run=run)
    policy = notify.PushPolicy(tmp_path / "s.json")
    assert notify.push([Alert.of("portal", "AUTH_EXPIRED", 900, NOW)], toast, policy, source="local PC", now=NOW) == notify.SENT
    import base64
    script = base64.b64decode(run.commands[0][0][6]).decode("utf-16-le")
    encoded = [part.split("'")[0] for part in script.split("FromBase64String('")[1:]]
    title, body = (base64.b64decode(e).decode("utf-8") for e in encoded)
    assert title == "밥도둑 운영: 조치가 필요합니다" and body.startswith("Portal 공지 수집 · 로그인 만료")


# --- cloud monitor ------------------------------------------------------------------------
def iso(seconds_ago):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(NOW - seconds_ago, timezone.utc).isoformat()


def test_cloud_watch_alerts_on_stale_or_expired_collectors_even_with_the_pc_off():
    rows = [{"agent_id": "portal-list-poller", "status": "healthy", "last_success_at": iso(3 * 3600)},
            {"agent_id": "dooray-radar", "status": "auth_required", "last_success_at": iso(60)},
            {"agent_id": "dooray-resident", "status": "healthy", "last_success_at": iso(99 * 3600)}]
    sink, logs = Recorder(), []
    assert cloud_watch.run(rows=rows, outcome="success", notifier=sink, now=NOW, log=logs.append) == notify.SENT
    text = sink.messages[0]
    assert "cloud monitor" in text and "Portal LIST · SCAN_STALE" in text and "Dooray Radar · AUTH_EXPIRED" in text
    assert "dooray-resident" not in text


def test_cloud_watch_reports_a_failed_refresh_and_unreadable_heartbeats():
    sink = Recorder()
    cloud_watch.run(rows=None, outcome="failure", notifier=sink, now=NOW, log=lambda _: None)
    assert "Cloud refresh · REFRESH_FAILED" in sink.messages[0] and "NO_SUCCESS_RECORDED" in sink.messages[0]


def test_cloud_watch_is_quiet_when_healthy_paused_or_unconfigured():
    healthy = [{"agent_id": "portal-list-poller", "status": "healthy", "last_success_at": iso(30)}]
    stale = [{"agent_id": "portal-list-poller", "status": "healthy", "last_success_at": iso(7200)}]
    sink = Recorder()
    assert cloud_watch.run(rows=healthy, outcome="success", notifier=sink, now=NOW, log=lambda _: None) == "WATCH_OK"
    from datetime import datetime
    until = datetime.fromtimestamp(NOW).date().isoformat()
    assert cloud_watch.run(rows=stale, outcome="success", notifier=sink, now=NOW, paused_until=until,
                           log=lambda _: None) == "WATCH_PAUSED"
    assert cloud_watch.run(rows=stale, outcome="success", notifier=None, now=NOW,
                           log=lambda _: None) == notify.NOT_CONFIGURED
    assert sink.messages == []


def test_cloud_notifier_reads_only_the_environment_it_is_given():
    assert cloud_watch.cloud_notifier({}) is None
    assert isinstance(cloud_watch.cloud_notifier({"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": "1"}),
                      notify.TelegramNotifier)
    assert isinstance(cloud_watch.cloud_notifier({"NTFY_TOKEN": "tk_x", "NTFY_TOPIC": "t"}), notify.NtfyNotifier)


def test_owner_connection_test_uses_only_the_approved_safe_message(tmp_path, monkeypatch):
    import alert_push
    sink = Recorder()
    monkeypatch.setattr(alert_push, "CONFIG", tmp_path / "absent.json")
    monkeypatch.setattr(notify, "local_notifier", lambda _: sink)
    assert alert_push.main(["--test"]) == 0
    assert sink.messages == ["✅ Babdoduk monitoring connected\n\ncomponent: operations\nstatus: healthy"]
