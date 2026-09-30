# -*- coding: utf-8 -*-
"""External operator push for collector alerts: Telegram (preferred) or authenticated ntfy.

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
                 warning_after_seconds: int = WARNING_DEBOUNCE_SECONDS):
        self.path, self.remind, self.warning_after = Path(state_path), remind_seconds, warning_after_seconds

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
            eligible = a.severity == "critical" or now - first_seen >= self.warning_after
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
    result = notifier.send(format_message(changes, source=source, recovered=recovered))
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
               notifier=None) -> str:
    notifier = notifier if notifier is not None else local_notifier(local)
    return push(alerts, notifier, PushPolicy(Path(local) / "alert-push-state.json"), source="local PC", now=now)
