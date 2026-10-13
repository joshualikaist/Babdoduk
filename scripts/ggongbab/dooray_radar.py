# -*- coding: utf-8 -*-
"""Dooray mailbox Radar: reads every new mail in full and registers candidates, fail-closed.

Every 2-5 minutes the Radar lists the inbox through the calibrated LIST endpoint, from the Dooray
tab of the already-open dedicated browser (the Ops Chrome, whose Portal tab it never uses, or the
legacy Dooray browser after a rollback). Each mail it has not handled yet is opened (owner decision
2026-10-14, after two events were missed because their food or prize wording was only in a poster
or the body): the body, the text of its attachments (PDF, HWP, HWPX, DOCX, PPTX, XLSX) and the
count of its poster images go to the prefilter, and a candidate becomes a collection task holding
that text, with its poster images attached as task files for the cloud AI. A mail whose subject is
plainly transactional (receipts, password resets) is never opened.

Opening a mail marks it read, so an unread mail is marked unread again right after
(web/mail_detail.py). The processed-mail ledger (`ggongbab-mail-state.json`) prevents replays and
records the prefilter's reason for each mail.

Fail closed: if the read flag is missing or the LIST contract changes, if the dedicated browser
itself sends a mail-detail request or any non-GET request to the mail host during a scan, or if an
opened unread mail cannot be marked unread again, unread mail is no longer opened
(`radar-unread-disabled.json`, cleared only by an operator) and a critical alert is raised. The
Radar never starts, restarts or closes Chrome and never asks for SSO by itself.
"""
from __future__ import annotations

import re
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

from .config import KST
from .ops_storage import atomic_json, read_json
from .prefilter import DENY, classify
from .web.exit_codes import AgentError, AuthRequired, UiContractError
from .web.mail_detail import MailOpener, MailUnavailable, UnreadRestoreFailed
from .web.state import AgentState, digest
from .web.task_writer import MailPayload

INTERVAL_DEFAULT = 180
INTERVAL_MIN, INTERVAL_MAX = 120, 300
AUTH_RETRY_MAX = 600       # while the login is expired: at most one LIST attempt every 10 minutes
OVERLAP_SECONDS = 1800
FIRST_WINDOW_SECONDS = 86400
MAX_ROWS = 200
RECHECK_MAX_DAYS = 14
RECHECK_MAX_ROWS = 1000
FLASH_KEEP_SECONDS = 6 * 3600
DETAIL_PATH = re.compile(r"/v\d+/wapi/mails/\d{6,}")

RUNNING = "DOORAY_RADAR_RUNNING"
STOPPED = "DOORAY_RADAR_STOPPED"
AUTH = "DOORAY_AUTH_REQUIRED"
CONTRACT = "DOORAY_CONTRACT_CHANGED"
BROWSER = "DOORAY_BROWSER_ABSENT"
INVARIANT = "DOORAY_UNREAD_INVARIANT_BROKEN"
TRANSPORT = "DOORAY_TRANSPORT_FAILED"
WRITE = "DOORAY_WRITE_FAILED"
CONFIG_REQUIRED = "DOORAY_CONFIGURATION_REQUIRED"
UNVERIFIED = "DOORAY_BROWSER_UNVERIFIED"
RESTORE = "DOORAY_UNREAD_RESTORE_FAILED"
REASONS = frozenset({RUNNING, STOPPED, AUTH, CONTRACT, BROWSER, INVARIANT, TRANSPORT, WRITE, CONFIG_REQUIRED,
                     UNVERIFIED, RESTORE})
DISPATCH_OFF = "DISPATCH_OFF"
MAIL_PATH = re.compile(r"^/mail(/|$)", re.I)


class UnreadInvariantBroken(Exception):
    """The dedicated browser itself sent a detail/body or write request while the Radar was scanning.
    The Radar's own requests go through the API request context, which this guard does not see."""


class BrowserUnverified(Exception):
    """The loopback listener is not positively the expected dedicated Chrome. Never attach."""


def dooray_page(context, mail_host: str):
    """The Dooray tab of a (possibly shared) browser: a top-level https page on the mail host,
    the inbox preferred. Any other site's tab - the Portal tab of the Ops Chrome - is never used."""
    fallback = None
    for page in list(context.pages):
        try:
            if page.is_closed():
                continue
            url = urlparse(page.url or "")
        except Exception:  # noqa: BLE001 - a tab closing while we look
            continue
        if url.scheme != "https" or url.netloc.lower() != mail_host.lower():
            continue
        if MAIL_PATH.match(url.path or "/"):
            return page
        fallback = fallback or page
    if fallback is None:
        raise ConnectionError(BROWSER)
    return fallback


class RadarFiles:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.local = self.root / ".local"
        self.control = self.local / "radar-control.json"
        self.runtime = self.local / "ops-radar.json"
        self.lock = self.local / "dooray-radar.lock"
        self.unread_latch = self.local / "radar-unread-disabled.json"
        self.flash = self.local / "radar-flash.json"
        self.dispatch = self.local / "dispatch-state.json"
        self.mail_state = self.local / "ggongbab-mail-state.json"
        self.contract = self.local / "dooray-ui.json"
        self.profile = self.local / "dooray-browser-profile"

    def enabled(self) -> bool:
        return bool(read_json(self.control, {"enabled": False}).get("enabled"))

    def set_enabled(self, enabled: bool, now: float) -> None:
        control = read_json(self.control, {})
        control.update(enabled=bool(enabled), changed_at=now)
        atomic_json(self.control, control)

    def dispatch_enabled(self) -> bool:
        """The cloud trigger is a separate operator switch (owner order: store the token, send
        one test dispatch, verify the cloud run, and only then let the Radar dispatch)."""
        return read_json(self.control, {}).get("dispatch") is True

    def set_dispatch(self, enabled: bool, now: float) -> None:
        control = read_json(self.control, {"enabled": False})
        control.update(dispatch=bool(enabled), dispatch_changed_at=now)
        atomic_json(self.control, control)

    def unread_allowed(self) -> bool:
        return not self.unread_latch.exists()

    def disable_unread(self, code: str, now: float) -> None:
        atomic_json(self.unread_latch, {"reason": code if code in REASONS else INVARIANT, "at": now})

    def runtime_state(self) -> dict:
        return read_json(self.runtime, {"started": 0, "observed": 0, "last_scan": None, "last_success": None,
                                        "reason": STOPPED, "running": False, "counts": {}})


class RequestGuard:
    """Records any mail-detail request or non-GET request the browser sends to the mail host."""

    def __init__(self, context, mail_host: str):
        self.context, self.mail_host, self.violations = context, mail_host, []

    def _on(self, request) -> None:
        try:
            url = urlparse(request.url)
        except Exception:  # noqa: BLE001
            return
        if url.netloc == self.mail_host and (request.method != "GET" or DETAIL_PATH.search(url.path)):
            self.violations.append((request.method, DETAIL_PATH.sub("/mails/<id>", url.path)))

    @contextmanager
    def watching(self):
        self.context.on("request", self._on)
        try:
            yield self
        finally:
            try:
                self.context.remove_listener("request", self._on)
            except Exception:  # noqa: BLE001
                pass


@dataclass
class ScanResult:
    rows: int = 0
    in_window: int = 0
    seen: int = 0
    unread: int = 0
    unread_skipped: int = 0
    candidates: int = 0
    registered: int = 0
    opened: int = 0             # mails read in full
    unread_restored: int = 0    # unread mails marked unread again after reading
    unavailable: int = 0        # detail not readable (deleted or moved since the listing); retried
    denied: int = 0             # transactional subjects, never opened
    images: int = 0             # poster images attached to new tasks
    flash: list = field(default_factory=list)

    def counts(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if k != "flash"} | {"flash": len(self.flash)}


def scan_once(session, state: AgentState, writer, *, list_mails, now: datetime, since: datetime,
              allow_unread: bool, dry_run: bool, guard: RequestGuard, opener,
              limit: int = MAX_ROWS, recheck: bool = False) -> ScanResult:
    """One pass. Raises UiContractError / UnreadInvariantBroken / UnreadRestoreFailed to fail closed."""
    result = ScanResult()
    headers = list_mails(session, limit=limit, target=None, since=since.date())
    result.rows = len(headers)
    if any(h.unread is None for h in headers):
        raise UiContractError(CONTRACT)
    if guard.violations:
        raise UnreadInvariantBroken()
    for header in headers:
        stamp = header.received_at
        if (stamp is not None and stamp < since) or (stamp is None and header.received and header.received < since.date()):
            continue
        result.in_window += 1
        result.unread += bool(header.unread)
        if state.seen(header.mail_id, recheck=recheck):
            result.seen += 1
            continue
        if header.unread and not allow_unread:
            result.unread_skipped += 1
            continue
        if DENY.search(header.subject or ""):
            result.denied += 1
            if not dry_run:
                state.record(header.mail_id, header.subject, header.received, registered=False, outcome="filtered",
                             reason="denylist: transactional subject (not opened)")
            continue
        try:
            with opener.open(session, header) as mail:
                result.opened += 1
                # Marked unread again when this block ends; a failed restore raises instead.
                result.unread_restored += bool(header.unread)
                decision = classify(header.subject, mail.filter_text() or header.preview, now, images=mail.image_count)
                if not decision.candidate:
                    if not dry_run:
                        state.record(header.mail_id, header.subject, header.received, registered=False,
                                     outcome="filtered", reason=decision.reason)
                    continue
                result.candidates += 1
                if decision.urgency == "high":
                    result.flash.append(digest(header.mail_id))
                if dry_run:
                    continue
                images = opener.images(session, mail) if mail.image_count else []
                post_id = writer.create_task(MailPayload(
                    mail_id=header.mail_id, subject=header.subject, body=mail.task_body() or header.preview,
                    received=header.received, preview_only=False, received_at=header.received_at,
                    discovered_at=now, images=images))
                if post_id:
                    state.record(header.mail_id, header.subject, header.received, registered=True,
                                 outcome="candidate", reason=decision.reason)
                    result.registered += 1
                    result.images += len(images)
        except MailUnavailable:
            result.unavailable += 1     # not recorded: the next scan tries again
    if guard.violations:
        raise UnreadInvariantBroken()
    return result


def update_flash(files: RadarFiles, flash_ids: list, dispatched: bool, now: float) -> dict:
    ledger = read_json(files.flash, {"pending": []})
    pending = [e for e in ledger.get("pending", []) if now - e.get("discovered_at", now) < FLASH_KEEP_SECONDS]
    known = {e["id"] for e in pending}
    pending += [{"id": i, "discovered_at": now, "dispatched": False} for i in flash_ids if i not in known]
    if dispatched:
        for entry in pending:
            entry["dispatched"] = True
    ledger = {"pending": pending}
    atomic_json(files.flash, ledger)
    return ledger


def run_radar(files: RadarFiles, *, session_factory: Callable, writer, list_mails, mail_host: str,
              heartbeat: Callable[[str, Optional[datetime], Optional[datetime], str], None],
              dispatch: Optional[Callable[[bool], str]] = None, interval: int = INTERVAL_DEFAULT,
              dry_run: bool = False, max_cycles: Optional[int] = None,
              clock: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep,
              browser_running: Callable[[], bool] = lambda: True, log: Callable[[str], None] = lambda _: None,
              opener=None, recheck_days: int = 0) -> int:
    """The Radar loop. Returns 0 when stopped and 20 on a contract change. An expired login is
    retried with backoff (at most AUTH_RETRY_MAX seconds apart) until a person logs in again.

    `recheck_days` (an operator's one-off run, with max_cycles=1) widens the window to that many
    days, so mail an older prefilter dismissed is read again under the current rules."""
    if not INTERVAL_MIN <= interval <= INTERVAL_MAX:
        raise ValueError("interval must be 120-300 seconds")
    if not 0 <= recheck_days <= RECHECK_MAX_DAYS:
        raise ValueError(f"recheck_days must be 0-{RECHECK_MAX_DAYS}")
    opener = opener or MailOpener(mail_host)
    runtime = files.runtime_state()
    runtime.update(started=clock(), running=True, reason=RUNNING)
    cycles = failures = 0

    def save(**changes):
        runtime.update(observed=clock(), **changes)
        atomic_json(files.runtime, runtime)

    save()
    try:
        while True:
            if not files.enabled() and not dry_run:
                return 0
            now_ts = clock()
            now = datetime.fromtimestamp(now_ts, KST)
            last = runtime.get("last_success")
            since_ts = (last - OVERLAP_SECONDS) if last else (now_ts - FIRST_WINDOW_SECONDS)
            if recheck_days:
                since_ts = min(since_ts, now_ts - recheck_days * 86400)
            since = datetime.fromtimestamp(since_ts, KST)
            delay = interval
            try:
                if not browser_running():
                    raise ConnectionError(BROWSER)
                state = AgentState.load(files.mail_state)
                with session_factory() as session:
                    guard = RequestGuard(session.context, mail_host)
                    with guard.watching():
                        result = scan_once(session, state, writer, list_mails=list_mails, now=now, since=since,
                                           allow_unread=files.unread_allowed(), dry_run=dry_run, guard=guard,
                                           opener=opener, limit=RECHECK_MAX_ROWS if recheck_days else MAX_ROWS,
                                           recheck=bool(recheck_days))
                if not dry_run:
                    state.mark_run(now.date())
                    state.save()
                if dry_run or not dispatch:
                    code = "DISPATCH_SKIPPED"
                elif not files.dispatch_enabled():
                    code = DISPATCH_OFF
                else:
                    code = dispatch(result.registered > 0)
                if not dry_run:
                    update_flash(files, result.flash, code == "DISPATCHED", now_ts)
                counts = result.counts() | {"uploads_failed": (getattr(writer, "uploads", None) or {}).get("failed", 0)}
                if dry_run:     # a rehearsal never moves the window of the real Radar
                    save(last_dry_run=now_ts, reason=RUNNING, counts=counts, dispatch=code)
                else:
                    save(last_scan=now_ts, last_success=now_ts, reason=RUNNING, counts=counts, dispatch=code)
                heartbeat("healthy", now, now, "0")
                log(RUNNING)
                failures = 0
            except AuthRequired:
                # Nothing restarts an exited Radar (its task runs at logon), so it waits instead:
                # once a person logs in again in the Ops Chrome, the next scan finds the session
                # valid and the Radar resumes by itself. Waiting backs off to AUTH_RETRY_MAX.
                failures += 1
                save(last_scan=now_ts, reason=AUTH)
                heartbeat("auth_required", now, None, "10")
                log(AUTH)
                delay = min(interval * 2 ** min(failures - 1, 3), AUTH_RETRY_MAX)
            except UiContractError as exc:
                if transient_list_failure(exc):
                    failures += 1
                    save(last_scan=now_ts, reason=TRANSPORT)
                    heartbeat("collector_error", now, None, TRANSPORT)
                    log(TRANSPORT)
                    delay = min(interval * 2 ** min(failures, 3), 900)
                    cycles += 1
                    if max_cycles is not None and cycles >= max_cycles:
                        return 0
                    _wait(files, delay, sleep, dry_run)
                    continue
                files.disable_unread(CONTRACT, now_ts)
                save(last_scan=now_ts, reason=CONTRACT)
                heartbeat("ui_changed", now, None, "20")
                log(CONTRACT)
                return 20
            except UnreadInvariantBroken:
                files.disable_unread(INVARIANT, now_ts)
                save(last_scan=now_ts, reason=INVARIANT)
                heartbeat("collector_error", now, None, INVARIANT)
                log(INVARIANT)
            except UnreadRestoreFailed:
                # A mail stayed read. Stop opening unread mail until an operator looks; read mail
                # is still scanned on the next cycle (this scan's ledger entries were not saved, so
                # those mails are read again and an existing task is found and reused).
                files.disable_unread(RESTORE, now_ts)
                save(last_scan=now_ts, reason=RESTORE)
                heartbeat("collector_error", now, None, RESTORE)
                log(RESTORE)
            except BrowserUnverified:
                # Fail closed without attaching; retried with backoff, alerted as critical.
                failures += 1
                save(last_scan=now_ts, reason=UNVERIFIED)
                heartbeat("collector_error", now, None, UNVERIFIED)
                log(UNVERIFIED)
                delay = min(interval * 2 ** min(failures, 3), 900)
            except AgentError:
                failures += 1
                save(last_scan=now_ts, reason=WRITE)
                heartbeat("collector_error", now, None, WRITE)
                log(WRITE)
                delay = min(interval * 2 ** min(failures, 3), 900)
            except Exception as exc:  # noqa: BLE001 - network, browser attach, unexpected: back off, never crash
                failures += 1
                code = BROWSER if str(exc) == BROWSER else TRANSPORT
                save(last_scan=now_ts, reason=code)
                heartbeat("collector_error", now, None, code)
                log(code)
                delay = min(interval * 2 ** min(failures, 3), 900)
            cycles += 1
            if max_cycles is not None and cycles >= max_cycles:
                return 0
            if not _wait(files, delay, sleep, dry_run):
                return 0
    finally:
        save(running=False)


def _wait(files: RadarFiles, seconds: float, sleep: Callable[[float], None], dry_run: bool) -> bool:
    """Sleep in short steps; False as soon as the operator disables the Radar."""
    remaining = seconds
    while remaining > 0:
        if not files.enabled() and not dry_run:
            return False
        part = min(remaining, 5)
        sleep(part)
        remaining -= part
    return True


def transient_list_failure(exc: UiContractError) -> bool:
    """Network errors and server errors from the LIST call are retried; a real contract change
    (missing read flag, non-JSON body, unrecognisable rows) fails closed."""
    text = str(exc)
    return text.startswith("list endpoint failed:") or text.startswith("mail list endpoint failed:") or bool(
        re.search(r"endpoint returned HTTP 5\d\d", text))
