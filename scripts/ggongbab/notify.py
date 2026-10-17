# -*- coding: utf-8 -*-
"""Operator push for collector alerts: Telegram (preferred) or authenticated ntfy, and a Windows
toast on the operations PC itself (no account or network; `WindowsToastNotifier`).

The message is built only from the fixed alert fields (component, severity, reason code,
last-success age, timestamp, recommended action) - never a subject, preview, identifier or
URL. Two senders use it:

* the local watchdog (fast, while this PC is on), with the bot token in Windows Credential
  Manager and the chat id in `.local/alert-push.json`;
* the cloud monitor step of the refresh workflow (`cloud_watch.py`), which runs on GitHub
  from the `ggongbab-production` environment and therefore still alerts when this PC is off.

Pushes happen on transitions only (a new or worse alert, and recovery), plus a reminder while
something stays critical, so a stuck collector cannot flood the phone. Provider tokens are
never written to logs, state files or the repository; a failed send returns a fixed code.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional

from .alerts import ACTIONS, SEVERITIES, Alert
from .ops_storage import atomic_json, read_json

KST = timezone(timedelta(hours=9))
TELEGRAM_API = "https://api.telegram.org"
TOKEN_TARGET = "babdoduk/alert-telegram"
CONNECTION_TEST_MESSAGE = "✅ Babdoduk monitoring connected\n\ncomponent: operations\nstatus: healthy"
NTFY_TOKEN_TARGET = "babdoduk/alert-ntfy"
REMIND_CRITICAL_SECONDS = 6 * 3600
RETRY_AFTER_FAILURE_SECONDS = 300
WARNING_DEBOUNCE_SECONDS = 600
TIMEOUT_SECONDS = 10
UA = "BabdodukOpsAlert/1.0 (+https://github.com/joshualikaist/Babdoduk)"

SENT = "PUSH_SENT"
NOT_CONFIGURED = "PUSH_NOT_CONFIGURED"
AUTH_FAILED = "PUSH_AUTH_FAILED"
REJECTED = "PUSH_REJECTED"
TRANSPORT_FAILED = "PUSH_TRANSPORT_FAILED"
NOTHING = "PUSH_NOTHING_NEW"
BACKOFF = "PUSH_BACKOFF"
FAILURES = frozenset({AUTH_FAILED, REJECTED, TRANSPORT_FAILED})

LABEL = {"healthy": "OK", "warning": "WARNING", "critical": "CRITICAL"}
COMPONENT = {"portal": "Portal LIST", "dooray_radar": "Dooray Radar", "dispatch": "Cloud trigger",
             "flash_candidate": "Flash candidate", "cloud_refresh": "Cloud refresh"}


def _age(seconds: Optional[int]) -> str:
    if seconds is None:
        return "no success recorded"
    if seconds < 120:
        return f"last success {seconds}s ago"
    if seconds < 7200:
        return f"last success {seconds // 60} min ago"
    return f"last success {seconds // 3600} h {seconds % 3600 // 60} min ago"


def format_message(changes: Iterable[Alert], *, source: str, recovered: Iterable[str] = ()) -> str:
    """Plain text from fixed fields only. `source` is "local PC" or "cloud monitor"."""
    lines = []
    for a in changes:
        lines.append(f"{LABEL.get(a.severity, a.severity.upper())} · {COMPONENT.get(a.component, a.component)} · "
                     f"{a.reason} · {_age(a.last_success_age_seconds)}")
        lines.append(f"  → {ACTIONS.get(a.action, a.action)}")
    for component in recovered:
        lines.append(f"RECOVERED · {COMPONENT.get(component, component)}")
    stamp = datetime.now(KST).strftime("%m-%d %H:%M KST")
    return "[Babdoduk ops] " + source + " · " + stamp + "\n" + "\n".join(lines)


class TelegramNotifier:
    """Bot API sendMessage. The token is part of the URL, so it never reaches an exception
    message, a log line or a returned value."""

    def __init__(self, token: str, chat_id: str, opener: Callable = urllib.request.urlopen):
        self._token, self.chat_id, self._opener = token, str(chat_id), opener

    def send(self, text: str) -> str:
        body = json.dumps({"chat_id": self.chat_id, "text": text[:4000], "disable_web_page_preview": True}).encode()
        request = urllib.request.Request(f"{TELEGRAM_API}/bot{self._token}/sendMessage", data=body, method="POST",
                                         headers={"Content-Type": "application/json", "User-Agent": UA})
        return _post(request, self._opener)


class NtfyNotifier:
    """Authenticated ntfy (access token), e.g. a reserved topic on ntfy.sh or a self-hosted server."""

    def __init__(self, server: str, topic: str, token: str, opener: Callable = urllib.request.urlopen):
        self.url, self._token, self._opener = server.rstrip("/") + "/" + topic, token, opener

    def send(self, text: str) -> str:
        critical = "CRITICAL" in text
        request = urllib.request.Request(self.url, data=text.encode("utf-8"), method="POST", headers={
            "Authorization": f"Bearer {self._token}", "Title": "Babdoduk ops", "User-Agent": UA,
            "Priority": "urgent" if critical else "default", "Tags": "rotating_light" if critical else "warning"})
        return _post(request, self._opener)


def _post(request, opener) -> str:
    try:
        with opener(request, timeout=TIMEOUT_SECONDS) as response:
            status = int(getattr(response, "status", 0) or response.getcode())
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
    except (urllib.error.URLError, TimeoutError, OSError):
        return TRANSPORT_FAILED
    finally:
        request.headers.pop("Authorization", None)
    if 200 <= status < 300:
        return SENT
    return AUTH_FAILED if status in (401, 403, 404) else REJECTED


class PushPolicy:
    """Which alerts deserve a push. Critical: at once, then a reminder every 6 hours while it
    lasts. Warning: only after it has persisted for 10 minutes, so a scan that is briefly late
    (for example right after sleep) never reaches the phone. Recovery: only for a component
    whose alert was actually pushed."""

    def __init__(self, state_path: Path, remind_seconds: int = REMIND_CRITICAL_SECONDS,
                 warning_after_seconds: int = WARNING_DEBOUNCE_SECONDS, critical_after_seconds: int = 0):
        self.path, self.remind, self.warning_after = Path(state_path), remind_seconds, warning_after_seconds
        self.critical_after = critical_after_seconds

    def select(self, alerts: list[Alert], now: float) -> tuple[list[Alert], list[str], dict]:
        state = read_json(self.path, {"open": {}})
        opened: dict = dict(state.get("open") or {})
        changes, next_open = [], {}
        for a in alerts:
            if a.severity == "healthy":
                continue
            key = f"{a.reason}:{a.severity}"
            before = opened.get(a.component) or {}
            same = before.get("key") == key
            first_seen = float(before.get("first_seen") or now) if same else now
            sent_at = before.get("sent_at") if same else None
            eligible = now - first_seen >= (self.critical_after if a.severity == "critical" else self.warning_after)
            due = sent_at is None or (a.severity == "critical" and now - float(sent_at) >= self.remind)
            if eligible and due:
                changes.append(a)
                sent_at = now
            next_open[a.component] = {"key": key, "severity": a.severity, "first_seen": first_seen,
                                      "sent_at": sent_at}
        recovered = [c for c, row in opened.items() if c not in next_open and row.get("sent_at") is not None]
        return changes, recovered, {"open": next_open}

    def commit(self, next_state: dict, result: str, now: float) -> None:
        next_state = dict(next_state, last_result=result, last_attempt=now)
        atomic_json(self.path, next_state)


def push(alerts: Iterable[Alert], notifier, policy: PushPolicy, *, source: str,
         now: Optional[float] = None) -> str:
    """Send what the policy selects. The state advances only after a successful send, so a
    failed push is retried on the next evaluation."""
    now = time.time() if now is None else now
    if notifier is None:
        return NOT_CONFIGURED
    last = read_json(policy.path, {})
    if last.get("last_result") in FAILURES and now - float(last.get("last_attempt") or 0) < RETRY_AFTER_FAILURE_SECONDS:
        return BACKOFF
    changes, recovered, next_state = policy.select(list(alerts), now)
    if not changes and not recovered:
        policy.commit(next_state, last.get("last_result") or NOTHING, float(last.get("last_attempt") or 0))
        return NOTHING
    render = getattr(notifier, "render", None)
    result = notifier.send(render(changes, recovered) if render else format_message(changes, source=source, recovered=recovered))
    if result == SENT:
        policy.commit(next_state, result, now)
    else:
        # Keep the previous open state so the same alerts are selected again after the backoff.
        policy.commit({"open": last.get("open") or {}}, result, now)
    return result


# --- local configuration (this PC) ------------------------------------------------------
def local_notifier(local: Path, *, read_credential: Optional[Callable[[str], Optional[str]]] = None):
    """Telegram (or ntfy) from `.local/alert-push.json` plus a Credential Manager token, or None."""
    config = read_json(Path(local) / "alert-push.json", {})
    if read_credential is None:
        from .dispatch import read_windows_credential as read_credential  # noqa: N813
    provider = config.get("provider")
    if provider == "telegram" and config.get("chat_id"):
        token = read_credential(TOKEN_TARGET)
        return TelegramNotifier(token, config["chat_id"]) if token else None
    if provider == "ntfy" and config.get("server") and config.get("topic"):
        token = read_credential(NTFY_TOKEN_TARGET)
        return NtfyNotifier(config["server"], config["topic"], token) if token else None
    return None


def push_local(local: Path, alerts: Iterable[Alert], *, now: Optional[float] = None,
               notifier=None, toast=None) -> str:
    """The external push (if configured) and, when the watchdog passes one, the Windows toast,
    each with its own state file. Returns the external push's result."""
    alerts = list(alerts)
    notifier = notifier if notifier is not None else local_notifier(local)
    result = push(alerts, notifier, PushPolicy(Path(local) / "alert-push-state.json"), source="local PC", now=now)
    if toast is not None:
        push(alerts, toast, PushPolicy(Path(local) / TOAST_STATE, critical_after_seconds=TOAST_CRITICAL_AFTER_SECONDS),
             source="local PC", now=now)
    return result


# --- Windows toast on this PC (owner decision 2026-10-12) ---------------------------------
# No account, token or network: PowerShell shows the toast through the Windows toast API under
# PowerShell's own app id, with no window and without taking focus. The text is fixed Korean
# wording keyed by component, reason and action - never a subject, title, id or URL.
TOAST_CONFIG = "alert-toast.json"        # {"enabled": false} turns the toast off
TOAST_STATE = "alert-toast-state.json"
TOAST_CRITICAL_AFTER_SECONDS = 180       # a scan that is only late right after the PC wakes stays quiet
TOAST_APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
TOAST_COMPONENT = {"portal": "Portal 공지 수집", "dooray_radar": "Dooray 메일 레이더", "dispatch": "클라우드 갱신 요청",
                   "flash_candidate": "새 꽁밥 후보", "cloud_refresh": "클라우드 갱신"}
TOAST_REASON = {
    "AUTH_EXPIRED": "로그인 만료", "WORKER_NOT_RUNNING": "작업 멈춤", "SCAN_STALE": "수집 멈춤",
    "SCAN_DELAYED": "수집 지연", "NO_SUCCESS_RECORDED": "성공 기록 없음", "BROWSER_ABSENT": "운영 Chrome 없음",
    "BROWSER_UNVERIFIED": "운영 Chrome 확인 불가", "RETRY_EXHAUSTED": "재시도 횟수 소진",
    "CONTRACT_CHANGED": "화면 구조 변경", "UNREAD_RADAR_DISABLED": "읽지 않은 메일 보호로 중지",
    "CONFIGURATION_REQUIRED": "설정 필요", "DISPATCH_FAILED": "갱신 요청 실패",
    "DISPATCH_AUTH_FAILED": "갱신 요청 인증 실패", "CANDIDATE_WAITING": "후보가 갱신을 기다림",
    "REFRESH_FAILED": "클라우드 갱신 실패",
}
TOAST_ACTION = {
    "login": "운영 Chrome에서 직접 로그인하세요. 로그인 화면이 닫히면 저절로 다시 시작합니다.",
    "wait": "잠시 뒤 저절로 다시 시도합니다.",
    "restart_worker": "상태를 확인한 뒤 start_ggongbab_workers.cmd를 실행하세요.",
    "open_browser": "start_ops_browser.cmd로 운영 Chrome을 여세요.",
    "review_contract": "화면 구조가 바뀌었습니다. 보정한 뒤 다시 시작하세요.",
    "investigate": "status_ggongbab_workers.cmd로 상태를 확인하세요.",
    "check_dispatch": "GitHub Actions와 갱신 요청 설정을 확인하세요.",
    "check_actions": "GitHub Actions에서 실패한 ggongbab-refresh 실행을 확인하세요.",
    "fix_config": "운영 사본 설정을 고친 뒤 다시 시작하세요.",
}
# The same actions in the Linux operations checkout's commands (scripts/linux/ops.sh).
LINUX_TOAST_ACTION = dict(TOAST_ACTION,
    restart_worker="상태를 확인한 뒤 scripts/linux/ops.sh start를 실행하세요.",
    open_browser="scripts/linux/ops.sh browser-start로 운영 Chrome을 여세요.",
    investigate="scripts/linux/ops.sh status로 상태를 확인하세요.",
)
TOAST_SCRIPT = r"""$ErrorActionPreference = 'Stop'
$enc = [Text.Encoding]::UTF8
$title = [Security.SecurityElement]::Escape($enc.GetString([Convert]::FromBase64String('@TITLE@')))
$body = [Security.SecurityElement]::Escape($enc.GetString([Convert]::FromBase64String('@BODY@')))
[void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
[void][Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml("<toast><visual><binding template='ToastGeneric'><text>$title</text><text>$body</text></binding></visual></toast>")
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('@APP@').Show($toast)
"""


def format_toast(changes: Iterable[Alert], recovered: Iterable[str] = (), *,
                 actions: Optional[dict] = None) -> tuple[str, str]:
    """(title, body) in Korean from fixed fields only."""
    actions = TOAST_ACTION if actions is None else actions
    changes = list(changes)
    if any(a.severity == "critical" for a in changes):
        title = "밥도둑 운영: 조치가 필요합니다"
    elif changes:
        title = "밥도둑 운영: 확인이 필요합니다"
    else:
        title = "밥도둑 운영: 다시 정상입니다"
    lines = []
    for a in changes:
        lines.append(f"{TOAST_COMPONENT.get(a.component, a.component)} · {TOAST_REASON.get(a.reason, a.reason)}")
        lines.append(actions.get(a.action, ACTIONS.get(a.action, a.action)))
    lines += [f"{TOAST_COMPONENT.get(c, c)} · 다시 정상" for c in recovered]
    return title, "\n".join(lines)


class WindowsToastNotifier:
    """A toast in the Windows notification centre of this PC."""

    def __init__(self, run: Optional[Callable] = None):
        self._run = run

    @staticmethod
    def render(changes, recovered) -> tuple[str, str]:
        return format_toast(changes, recovered)

    def send(self, message) -> str:
        import base64
        import subprocess
        title, body = message if isinstance(message, tuple) else ("밥도둑 운영", str(message))
        encode = lambda text: base64.b64encode(text.encode("utf-8")).decode("ascii")  # noqa: E731
        script = (TOAST_SCRIPT.replace("@TITLE@", encode(title[:120])).replace("@BODY@", encode(body[:600]))
                  .replace("@APP@", TOAST_APP_ID))
        command = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                   "-EncodedCommand", base64.b64encode(script.encode("utf-16-le")).decode("ascii")]
        try:
            done = (self._run or subprocess.run)(command, capture_output=True, timeout=30,
                                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError):
            return TRANSPORT_FAILED
        return SENT if done.returncode == 0 else TRANSPORT_FAILED


class NotifySendNotifier:
    """A desktop notification on this Linux PC (`notify-send`, the freedesktop notification service)."""

    def __init__(self, run: Optional[Callable] = None, executable: str = "notify-send"):
        self._run = run
        self._executable = executable

    @staticmethod
    def render(changes, recovered) -> tuple[str, str]:
        return format_toast(changes, recovered, actions=LINUX_TOAST_ACTION)

    def send(self, message) -> str:
        import subprocess
        title, body = message if isinstance(message, tuple) else ("밥도둑 운영", str(message))
        urgency = "critical" if "조치가 필요합니다" in title else "normal"
        command = [self._executable, "--app-name=밥도둑 운영", f"--urgency={urgency}", "--",
                   title[:120], body[:600]]
        try:
            done = (self._run or subprocess.run)(command, capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return TRANSPORT_FAILED
        return SENT if done.returncode == 0 else TRANSPORT_FAILED


def local_toast(local: Path, *, windows: Optional[bool] = None, linux: Optional[bool] = None):
    """The desktop notification of this PC (Windows toast, or `notify-send` on Linux) unless
    `.local/alert-toast.json` says {"enabled": false}."""
    import os
    import shutil
    import sys
    windows = os.name == "nt" if windows is None else windows
    if linux is None:
        linux = sys.platform.startswith("linux") and shutil.which("notify-send") is not None
    if read_json(Path(local) / TOAST_CONFIG, {}).get("enabled", True) is False:
        return None
    if windows:
        return WindowsToastNotifier()
    if linux:
        return NotifySendNotifier()
    return None
