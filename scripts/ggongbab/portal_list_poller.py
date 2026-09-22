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
from .portal_session import ListTransportError
from .web.exit_codes import AuthRequired, UiContractError


class ScanIncomplete(ListTransportError):
    def __init__(self):
        super().__init__()
        self.args = ("PORTAL_LIST_SCAN_INCOMPLETE",)


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
            changed = previous is None or previous["fingerprint"] != entry["fingerprint"]
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
               monotonic=time.monotonic, now=lambda: datetime.now(KST)):
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
            log("Portal heartbeat write failed; values suppressed")
            raise ListStateError() from None

    try:
        scanned = now()
        client = provider.acquire()
        poller = PortalListPoller(client, state, max_pages=max_pages)
        failures = cycles = 0
        while True:
            started = monotonic()
            scanned = now()
            delay = interval
            try:
                counts = poller.poll_once()
                successful = now()
                beat("healthy", "0")
                log("Portal list scan: " + " ".join(f"{k}={v}" for k, v in counts.items()))
                failures = 0
                code = 0
            except ListTransportError as exc:
                failures += 1
                delay = max(min(interval * 2 ** min(failures, 5), 900), exc.retry_after)
                beat("collector_error", "scan_incomplete" if isinstance(exc, ScanIncomplete) else "transport")
                log("Portal list scan incomplete" if isinstance(exc, ScanIncomplete)
                    else "Portal list transport unavailable; retry scheduled")
                code = 1
            cycles += 1
            if once or (max_cycles is not None and cycles >= max_cycles):
                return code
            # Monotonic cadence; no overlapping scans or tight retry loops.
            # Retry-After starts at the failure response, not at request start.
            remaining = delay if code else max(1, delay - (monotonic() - started))
            while remaining > 0:
                part = min(remaining, 30)
                sleep(part)
                remaining -= part
    except AuthRequired:
        try:
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
    except (ListTransportError, ListStateError):
        try:
            beat("collector_error", "local_or_transport")
        except ListStateError:
            pass
        log("Portal list operation stopped; values suppressed")
        return 1
    except KeyboardInterrupt:
        log("Portal list polling stopped")
        return 0
    except Exception:
        try:
            beat("collector_error", "unexpected")
        except ListStateError:
            pass
        log("Portal list operation stopped; values suppressed")
        return 1
    finally:
        if client is not None:
            client.close()
