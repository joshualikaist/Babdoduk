# -*- coding: utf-8 -*-
"""Cloud-side collector watch: alerts even when the operator's PC is off.

Runs as the last step of the ggongbab-refresh job on GitHub. It reads the collectors'
heartbeat rows (status and timestamps only) and the refresh step's own outcome, and pushes to
Telegram (or authenticated ntfy) when something is not healthy. GitHub runs this schedule a
few times a day, so the cloud path is the "eventually" alarm; the local watchdog is the fast
one. There is no state between runs: while a problem persists, each monitor run repeats it.
Set the repository variable GGONGBAB_WATCH_PAUSED_UNTIL (YYYY-MM-DD) to silence it, for
example while the PC is deliberately off for a trip. It always exits 0 so a monitoring
problem never fails the refresh job.
"""
from __future__ import annotations

import os
import time
from datetime import date, datetime
from typing import Optional

from .alerts import Alert, render, staleness
from .notify import NOT_CONFIGURED, NtfyNotifier, TelegramNotifier, format_message

# Heartbeat agent ids and the alert component they map to. The legacy "dooray-resident"
# mail bridge is retired and not watched.
WATCHED = {"portal-list-poller": "portal", "dooray-radar": "dooray_radar"}
HUMAN = {"auth_required": "AUTH_EXPIRED", "ui_changed": "CONTRACT_CHANGED"}


def _epoch(value) -> Optional[float]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def heartbeat_alerts(rows: list[dict], now: float) -> list[Alert]:
    by_agent = {row.get("agent_id"): row for row in rows or []}
    found = []
    for agent, component in WATCHED.items():
        row = by_agent.get(agent)
        if row is None:
            continue                     # never deployed: nothing to watch yet
        last = _epoch(row.get("last_success_at"))
        age = None if last is None else max(0, int(now - last))
        human = HUMAN.get(str(row.get("status") or ""))
        if human:
            found.append(Alert.of(component, human, age, now))
            continue
        severity, code = staleness(component, age)
        found.append(Alert.of(component, code, age, now, severity))
    return found


def refresh_alert(outcome: str, now: float) -> Optional[Alert]:
    return Alert.of("cloud_refresh", "REFRESH_FAILED", None, now) if outcome == "failure" else None


def paused(value: str, today: date) -> bool:
    try:
        return bool(value) and today <= date.fromisoformat(value.strip())
    except ValueError:
        return False


def cloud_notifier(env=os.environ):
    if env.get("TELEGRAM_BOT_TOKEN") and env.get("TELEGRAM_CHAT_ID"):
        return TelegramNotifier(env["TELEGRAM_BOT_TOKEN"], env["TELEGRAM_CHAT_ID"])
    if env.get("NTFY_TOKEN") and env.get("NTFY_TOPIC"):
        return NtfyNotifier(env.get("NTFY_SERVER") or "https://ntfy.sh", env["NTFY_TOPIC"], env["NTFY_TOKEN"])
    return None


def run(*, rows: Optional[list[dict]], outcome: str, notifier, now: Optional[float] = None,
        paused_until: str = "", log=print) -> str:
    now = time.time() if now is None else now
    found = [] if rows is None else heartbeat_alerts(rows, now)
    extra = refresh_alert(outcome, now)
    if extra:
        found.append(extra)
    if rows is None:
        found.append(Alert.of("portal", "NO_SUCCESS_RECORDED", None, now))   # heartbeats unreadable
    for line in render(found):
        log(line)
    bad = [a for a in found if a.severity != "healthy"]
    if not bad:
        log("cloud watch: all watched collectors healthy")
        return "WATCH_OK"
    if paused(paused_until, datetime.fromtimestamp(now).date()):
        log("cloud watch: paused by GGONGBAB_WATCH_PAUSED_UNTIL")
        return "WATCH_PAUSED"
    if notifier is None:
        log(f"cloud watch: {NOT_CONFIGURED}")
        return NOT_CONFIGURED
    result = notifier.send(format_message(bad, source="cloud monitor"))
    log(f"cloud watch: {result}")
    return result


def main() -> int:
    from .config import load_settings
    from .db.supabase_client import SupabaseClient

    rows = None
    settings = load_settings()
    if settings.has_supabase:
        try:
            client = SupabaseClient(settings.supabase_url, settings.supabase_secret_key)
            rows = client.select("agent_heartbeats", {"select": "agent_id,status,last_success_at,last_scan_at"})
        except Exception as exc:  # noqa: BLE001 - class name only in public logs
            print(f"cloud watch: heartbeats unreadable ({exc.__class__.__name__})")
    run(rows=rows, outcome=os.environ.get("REFRESH_OUTCOME", ""), notifier=cloud_notifier(),
        paused_until=os.environ.get("GGONGBAB_WATCH_PAUSED_UNTIL", ""))
    return 0

