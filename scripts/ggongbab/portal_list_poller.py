"""Local, LIST-only Stage A detection. No detail, AI, task writer or public export."""
from __future__ import annotations

import time
from copy import deepcopy
from datetime import datetime, timedelta

from .config import KST
from .heartbeat import build_heartbeat
from .portal_discovery import notice_timestamp
from .portal_list_contract import validate_page
from .portal_list_state import ListStateError, metadata
from .portal_session import ListTransportError, safe_reason_code, transport_reason
from .web.exit_codes import AuthRequired, UiContractError


# Stale-transport recovery: after this many consecutive transport failures (or the first
# one after a sleep), the next attempt rebuilds the HTTP session from the dedicated browser.
REBUILD_AFTER_FAILURES = 2
MAX_REBUILDS_PER_SERIES = 3
REBUILD_DELAY_SECONDS = 30


class ScanIncomplete(ListTransportError):
    def __init__(self):
        super().__init__(reason="PORTAL_LIST_SCAN_INCOMPLETE")


class PortalListPoller:
    def __init__(self, client, state, *, max_pages=20):
        if type(max_pages) is not int or not 2 <= max_pages <= 100:
            raise ValueError("max_pages must be between 2 and 100")
        self.client, self.state, self.max_pages = client, state, max_pages

    def poll_once(self):
        old = self.state.data
        baseline = not old["initialized"]
        floor = notice_timestamp(old["lower_bound"])
        observed = {}
        complete = False
        for index in range(1, self.max_pages + 1):
            payload = self.client.fetch_list_page(index)
            rows = validate_page(payload, index)
            page_entries = dict(metadata(row) for row in rows)
            for key, entry in page_entries.items():
                if key in observed and observed[key] != entry:
                    # A changing paginated snapshot must be retried, not checkpointed.
                    raise ScanIncomplete()
                observed[key] = entry
            anchor_page = bool(page_entries) and all(
                key in old["notices"] or (floor and notice_timestamp(entry["reg_dt"]) < floor)
                for key, entry in page_entries.items())
            end = index >= payload["page"]["totalPage"] or not rows
            if end or (index >= 2 and (baseline or anchor_page)):
                complete = True
                break
        if not complete:
            raise ScanIncomplete()

        new = deepcopy(old)
        counts = {"pages": index, "rows": len(observed), "new": 0, "updated": 0,
                  "candidates": 0, "baseline": baseline}
        for key, entry in observed.items():
            previous = old["notices"].get(key)
            eligible = floor is None or notice_timestamp(entry["reg_dt"]) >= floor
            # A broader reviewed discovery rule can newly qualify an unchanged
            # recent title. Preserve the baseline and reconsider only that transition.
            changed = (previous is None or previous["fingerprint"] != entry["fingerprint"]
                       or (entry["candidate"] and not previous["candidate"]))
            if not baseline and eligible and changed and entry["public"]:
                counts["new" if previous is None else "updated"] += 1
                if entry["candidate"]:
                    new["pending"][key] = entry
                    counts["candidates"] += 1
            if not entry["candidate"]:
                new["pending"].pop(key, None)
            new["notices"][key] = entry

        stamps = [notice_timestamp(r["reg_dt"]) for r in observed.values()]
        if stamps:
            # Initial baseline is deliberately recent, not a historical crawl.
            next_floor = min(stamps) if baseline else max(stamps) - timedelta(days=1)
            if floor:
                next_floor = max(floor, next_floor)
            new["lower_bound"] = next_floor.isoformat()
            new["notices"] = {k: r for k, r in new["notices"].items()
                              if notice_timestamp(r["reg_dt"]) >= next_floor}
        new["initialized"] = True
        # Detection outbox and dedup checkpoint commit together. No empty-body task.
        self.state.commit(new)
        counts["pending"] = len(new["pending"])
        return counts


def run_poller(provider, state, *, emit_heartbeat, log=print, interval=60,
               max_pages=20, once=False, max_cycles=None, sleep=time.sleep,
               monotonic=time.monotonic, now=lambda: datetime.now(KST),
               stop_requested=None, max_failures=None, on_retry=None):
    """One handoff; auth/schema failures stop until an operator restarts after recovery."""
    if interval not in (30, 60):
        raise ValueError("interval must be 30 or 60 seconds")
    client = None
    scanned = None
    successful = None

    def beat(status, exit_class):
        row = build_heartbeat(agent_id="portal-list-poller", version="portal-list-v1",
                              status=status, exit_class=exit_class,
                              auth_required=status == "auth_required",
                              ui_contract_changed=status == "ui_changed",
                              last_scan_at=scanned, last_success_at=successful)
        try:
            emit_heartbeat(row)
        except Exception:
            log("PORTAL_HEARTBEAT_WRITE_FAILED")
            raise ListStateError("PORTAL_HEARTBEAT_WRITE_FAILED") from None

    try:
        if stop_requested and stop_requested():
            return 0
        scanned = now()
        client = provider.acquire()
        poller = PortalListPoller(client, state, max_pages=max_pages)
        failures = cycles = rebuilds = 0
        planned = interval
        while True:
            if stop_requested and stop_requested():
                return 0
            started = monotonic()
            previous_scan, scanned = scanned, now()
            # A wall-clock gap far beyond the planned wait means the PC slept or the
            # process was suspended; the handed-off HTTP connection is then likely stale.
            resumed = previous_scan is not None and (scanned - previous_scan).total_seconds() > max(600, 3 * planned)
            delay = interval
            try:
                if client is None:
                    # Rebuild of a stale transport: the same handoff from the already-open
                    # dedicated browser. No Chrome restart, no SSO, no state or baseline change.
                    client = provider.acquire()
                    poller = PortalListPoller(client, state, max_pages=max_pages)
                    log("PORTAL_LIST_SESSION_REBUILT")
                counts = poller.poll_once()
                successful = now()
                beat("healthy", "0")
                log("Portal list scan: " + " ".join(f"{k}={v}" for k, v in counts.items()))
                failures = rebuilds = 0
                code = 0
            except ListTransportError as exc:
                failures += 1
                delay = max(min(interval * 2 ** min(failures, 5), 900), exc.retry_after)
                reason = safe_reason_code(exc)
                # Authentication failures never reach here (AuthRequired stops the worker).
                # A transport that keeps failing, or fails right after a sleep, is rebuilt.
                stale = reason != "PORTAL_LIST_SCAN_INCOMPLETE" and (failures >= REBUILD_AFTER_FAILURES or resumed)
                if stale and client is not None and rebuilds < MAX_REBUILDS_PER_SERIES:
                    rebuilds += 1
                    client.close()
                    client = None
                    delay = max(min(delay, REBUILD_DELAY_SECONDS), exc.retry_after)
                if on_retry:
                    on_retry(delay)
                beat("collector_error", reason)
                log(reason)
                code = 1
            planned = delay
            cycles += 1
            if max_failures is not None and failures >= max_failures:
                return 1
            if once or (max_cycles is not None and cycles >= max_cycles):
                return code
            # Monotonic cadence; no overlapping scans or tight retry loops.
            # Retry-After starts at the failure response, not at request start.
            remaining = delay if code else max(1, delay - (monotonic() - started))
            while remaining > 0:
                if stop_requested and stop_requested():
                    return 0
                part = min(remaining, 5 if stop_requested else 30)
                sleep(part)
                remaining -= part
    except AuthRequired as exc:
        reason = safe_reason_code(exc)
        log(reason)
        try:
            if reason in {"PORTAL_RESIDENT_OWNER_UNVERIFIED", "PORTAL_CDP_ATTACH_TIMEOUT"}:
                beat("collector_error", reason)
            else:
                beat("auth_required", "10")
        except ListStateError:
            return 1
        log("Portal list authentication unavailable; complete manual setup and restart --poll-list")
        return 10
    except UiContractError:
        try:
            beat("ui_changed", "20")
        except ListStateError:
            return 1
        log("Portal list contract changed; polling stopped; values suppressed")
        return 20
    except (ListTransportError, ListStateError) as exc:
        reason = safe_reason_code(exc)
        try:
            beat("collector_error", reason)
        except ListStateError:
            pass
        log(reason)
        return 1
    except KeyboardInterrupt:
        log("Portal list polling stopped")
        return 0
    except Exception as exc:
        reason = transport_reason(exc)
        try:
            beat("collector_error", reason)
        except ListStateError:
            pass
        log(reason)
        return 1
    finally:
        if client is not None:
            client.close()
