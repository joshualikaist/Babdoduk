"""Local Portal agent: passive discovery, verified contracts, active bounded GETs.

SSO is manual. No credentials, notice values or raw IDs are logged or persisted
in discovery/queue files. Dry runs never instantiate a Dooray writer or save a queue.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ggongbab.config import KST, load_settings
from ggongbab.portal_contract import PortalContract, contract_from_discovery
from ggongbab.portal_discovery import build_discovery, notice_date, stable_id
from ggongbab.portal_diagnostics import Diagnostics, capture_response
from ggongbab.portal_fetch import fetch_detail, iter_notices, request_context
from ggongbab.portal_queue import PortalQueue
from ggongbab.prefilter import portal_detail_is_candidate, portal_list_warrants_detail
from ggongbab.web.exit_codes import (AUTH_REQUIRED, SUCCESS, UI_CHANGED,
                                     AuthRequired, ProjectNotFound, UiContractError)
from ggongbab.web.resident import resident_session
from ggongbab.web.task_writer import PortalPayload, TaskWriter
from ggongbab.web.ui_contract import UiContract

ROOT = Path(__file__).resolve().parents[1]
LOCAL_DIR = ROOT / ".local"
PROFILE_DIR = LOCAL_DIR / "portal-browser-profile"
CONTRACT_FILE = LOCAL_DIR / "portal-ui.json"
DISCOVERY_FILE = LOCAL_DIR / "portal-discovery.json"
DEBUG_FILE = LOCAL_DIR / "portal-discovery-debug.json"
STATE_FILE = LOCAL_DIR / "portal-agent-state.json"
LOG_FILE = LOCAL_DIR / "portal-agent.log"
DEFAULT_START = "https://portal.kaist.ac.kr/"
DEFAULT_PORT = 9223
LOGIN_HINTS = ("login", "signin", "sign-in", "sso", "auth", "idp", "nid", "account")


def log(message):
    line = f"{datetime.now(KST).strftime('[%H:%M:%S]')} {message}"
    print(line, flush=True)
    try:
        LOCAL_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def start_url():
    import os
    url = os.environ.get("PORTAL_START_URL") or DEFAULT_START
    p = urlparse(url)
    if p.scheme != "https" or not p.netloc or p.query or p.fragment or p.username or p.password:
        raise UiContractError("Portal start URL must be an HTTPS page without credentials or query values")
    return url


def dummy_contract(url):
    return UiContract(mail_url=url, verified=False)


def page_authenticated(page, expected_host, *, notice_api_observed=False):
    """A public landing page is never positive evidence by itself."""
    try:
        parsed = urlparse(page.url)
        if parsed.scheme != "https" or parsed.netloc != expected_host:
            return False
        if any(h in parsed.path.lower() for h in LOGIN_HINTS):
            return False
        return bool(notice_api_observed and page.locator("input[type='password']").count() == 0)
    except Exception:
        return False


def observe_network(session, seconds=20, *, stop_on_auth=False, diagnostics=None):
    found = []
    diagnostics = diagnostics or Diagnostics()
    positive_pages = set()
    host = urlparse(start_url()).netloc

    def on_response(response):
        try:
            row = capture_response(response, host, diagnostics)
            if row:
                found.append(row)
                if (row["kind"] == "list" and row["_method"] == "GET"
                        and row["_resource"] in ("xhr", "fetch")
                        and urlparse(response.url).netloc == host):
                    positive_pages.add(response.request.frame.page)
        except Exception:
            diagnostics.rejected["observer errors"] += 1

    # BrowserScope attaches to every live context, including newly opened SSO tabs.
    session.context.on("response", on_response)
    deadline = time.monotonic() + seconds
    try:
        while time.monotonic() < deadline:
            pages = session.context.pages
            if stop_on_auth and any(page_authenticated(p, host, notice_api_observed=p in positive_pages)
                                    for p in pages):
                return found
            # Pump Playwright events, rather than starving callbacks with time.sleep.
            if not pages:
                raise AuthRequired("Portal browser has no open pages")
            pages[-1].wait_for_timeout(min(250, max(1, (deadline - time.monotonic()) * 1000)))
    finally:
        session.context.remove_listener("response", on_response)
    if stop_on_auth:
        raise AuthRequired("Portal notice API not observed; complete SSO and open the notice list")
    return found


def wait_for_portal(session, timeout_seconds=600):
    log("complete manual SSO and open the notice list; waiting for a successful notice API response")
    observe_network(session, timeout_seconds, stop_on_auth=True)


def write_discovery(rows, diagnostics=None):
    report = build_discovery(rows, start_url(), diagnostics)
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    DISCOVERY_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # Never copy observations or contracts here: debug output is counts/reasons only.
    debug = {"diagnostics": report["diagnostics"], "reasons": report["reasons"]}
    DEBUG_FILE.write_text(json.dumps(debug, indent=2) + "\n", encoding="utf-8")
    return report


def open_session(args, url):
    # resident startup diagnostics are not Portal count-only logs.
    return resident_session(PROFILE_DIR, dummy_contract(url), start_url=url,
                            port=args.port, log=lambda _: None, reuse=True)


def cmd_setup(args):
    log("opening dedicated Portal browser; SSO is manual")
    with open_session(args, start_url()) as session:
        wait_for_portal(session)
    log("setup complete: authenticated list-like Portal response observed")
    log("setup success does not mean replay contract verified")
    return SUCCESS


def cmd_discover(args):
    diagnostics = Diagnostics()
    with open_session(args, start_url()) as session:
        log("observing for 60s: open the notice list, next page, and two distinct notice details")
        rows = observe_network(session, seconds=60, diagnostics=diagnostics)
    report = write_discovery(rows, diagnostics)
    log_discovery(report)
    return SUCCESS if report["listReplayable"] else UI_CHANGED


def log_discovery(report):
    log("Portal discovery diagnostics:")
    for key, count in report["diagnostics"]["counts"].items():
        log(f"  {key}: {count}")
    log("Rejected:")
    for key, count in report["diagnostics"]["rejected"].items():
        log(f"  {key}: {count}")
    log_stages(report)
    log("Discovery result:")
    log("  list endpoint: " + ("candidate found" if report["listEndpointObserved"] else "not observed"))
    log("  list replay contract: " + ("accepted" if report["listReplayable"] else "rejected"))
    log("  detail replay contract: " + ("accepted" if report["detailReplayable"] else "rejected"))
    for reason in report["reasons"]:
        log("  reason: " + reason)


def _names(values):
    return "[" + ", ".join(values) + "]" if values else "[]"


def log_stages(report):
    """Stage-by-stage view. Key names, JSON paths and counts only - no values."""
    diagnostics = report.get("diagnostics", {})
    safe = diagnostics.get("safe", {})
    counts = diagnostics.get("counts", {})
    rejected = diagnostics.get("rejected", {})
    candidate = safe.get("listCandidate") or {}
    pagination = safe.get("paginationCandidates") or []
    # A key that merely changes is a candidate, not a verified mechanism; say so
    # rather than printing a name that reads like a decision.
    verified = report.get("paginationVerified")
    log("List discovery:")
    log("  schema candidate: " + ("yes" if counts.get("list-schema candidates") else "no"))
    log("  request shape: " + ("accepted" if report.get("listReplayable") else "rejected"))
    if candidate.get("host"):
        log("  candidate host: " + candidate["host"])
        log("  candidate path: " + (candidate.get("templatedPath") or "<unsafe path, withheld>"))
        log("  candidate method: " + f"{candidate.get('method', '')} ({candidate.get('resourceType', '')})")
        log("  query keys: " + _names(candidate.get("queryKeys") or []))
    log("  unsafe query keys: " + _names(safe.get("unsafeQueryKeys") or []))
    log("  static structural keys: " + _names(safe.get("staticStructuralKeys") or []))
    if pagination:
        for entry in pagination:
            log(f"  pagination candidate key: {entry['key']} "
                f"(numericMonotonic={str(entry['numericMonotonic']).lower()}, "
                f"opaqueChanging={str(entry['opaqueChanging']).lower()})")
    else:
        log("  pagination candidate key: none")
    log("  pagination verified: " + ("yes" if verified else "no (candidate is not authorization)"))
    log("Detail discovery:")
    log(f"  candidates observed: {counts.get('detail-schema candidates', 0)}")
    log(f"  ambiguous body responses: {rejected.get('body path ambiguous', 0)}")
    log("  candidate body paths: " + _names(safe.get("detailBodyCandidatePaths") or []))
    log("  body disambiguated by id subtree: "
        + ("yes" if safe.get("bodyDisambiguatedByIdSubtree") else "no"))
    log(f"  distinct replayable details: {counts.get('replayable detail candidates', 0)}")


def cmd_calibrate(args):
    # Invalidate earlier authorization if this calibration fails.
    if CONTRACT_FILE.exists():
        old = PortalContract.load(CONTRACT_FILE)
        old.verified = False
        old.save(CONTRACT_FILE)
    try:
        discovery = json.loads(DISCOVERY_FILE.read_text(encoding="utf-8"))
        contract = contract_from_discovery(discovery)
    except (OSError, ValueError, TypeError):
        contract = None
    if contract is None or not contract.list_ready():
        log("PORTAL CALIBRATION FAILED: need an observed replayable list contract")
        return UI_CHANGED
    if contract.detail_verified_count < 2 or len(set(contract.detail_id_hashes)) < 2:
        log("PORTAL CALIBRATION FAILED: need two distinct notice details")
        return UI_CHANGED
    if not contract.detail_ready():
        log("PORTAL CALIBRATION FAILED: detail path or read-state semantics require review")
        return UI_CHANGED
    contract.verified = True
    contract.save(CONTRACT_FILE)
    log(f"detail verified count: {contract.detail_verified_count}")
    log(f"pagination verified: {contract.pagination != 'none'}")
    log(f"dates parsed: {bool(contract.list_date_key)}")
    log("calibration complete; run --dry-run --cdp before --run")
    return SUCCESS


def _require_contract():
    contract = PortalContract.load(CONTRACT_FILE)
    if not contract.verified or not contract.list_ready() or not contract.detail_ready():
        raise UiContractError("PORTAL CALIBRATION FAILED: run discovery and calibration first")
    if contract.list_host != urlparse(start_url()).netloc or contract.detail_host != contract.list_host:
        raise UiContractError("Portal contract host does not match the dedicated Portal origin")
    return contract


def cmd_run(args):
    contract = _require_contract()
    since, until = args.date_from, args.date_to
    if (since or until) and not contract.list_date_key:
        raise UiContractError("Portal date window requires a verified date field")
    queue = PortalQueue(STATE_FILE)
    writer = None
    if not args.dry_run:
        writer = TaskWriter(load_settings())
        writer.verify_project()
    counts = dict(loaded_rows=0, date_matched=0, detail_fetched=0, candidates=0,
                  new=0, updated=0, already_queued=0, registered=0)
    with open_session(args, start_url()) as session:
        request, initial_payload = request_context(session, contract)
        for row in iter_notices(request, contract, max_pages=args.max_pages,
                                max_items=args.max_items, date_from=since, initial_payload=initial_payload):
            counts["loaded_rows"] += 1
            parsed_date = notice_date(row.get(contract.list_date_key))
            if since or until:
                # Undated notices do not silently become current notices.
                if parsed_date is None or (since and parsed_date < since) or (until and parsed_date > until):
                    continue
            if parsed_date is not None:
                counts["date_matched"] += 1
            title = row[contract.list_title_key]
            if not portal_list_warrants_detail(title):
                continue
            identifier = stable_id(row[contract.list_id_key])
            body = fetch_detail(request, contract, identifier)
            counts["detail_fetched"] += 1
            if not portal_detail_is_candidate(title, body, has_list_date=parsed_date is not None).candidate:
                continue
            counts["candidates"] += 1
            decision = queue.decide(identifier, title, body)
            counts[{"new": "new", "update": "updated", "skip": "already_queued"}[decision.outcome]] += 1
            if args.dry_run or decision.outcome == "skip":
                continue
            payload = PortalPayload(external_key=decision.external_key, title=title, body=body,
                                    source_created_at=str(row.get(contract.list_date_key) or ""))
            try:
                task_id = writer.create_portal_task(payload, dry_run=False)
            except Exception:
                raise ProjectNotFound("Portal task creation failed; queue not advanced for this notice") from None
            if not task_id:
                raise ProjectNotFound("Portal task creation unconfirmed; queue not advanced")
            queue.record(decision)
            queue.save()
            counts["registered"] += 1
    for key, value in counts.items():
        suffix = " (dry run)" if key == "registered" and args.dry_run else ""
        log(f"{key.replace('_', ' ')}: {value}{suffix}")
    return SUCCESS


def positive_int(value):
    value = int(value)
    if value <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description="KAIST Portal resident agent")
    modes = parser.add_mutually_exclusive_group(required=True)
    for mode in ("setup", "discover", "calibrate", "run", "dry-run"):
        modes.add_argument("--" + mode, action="store_true")
    parser.add_argument("--cdp", action="store_true")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--from", dest="date_from", type=date.fromisoformat)
    parser.add_argument("--to", dest="date_to", type=date.fromisoformat)
    parser.add_argument("--max-items", type=positive_int, default=500)
    parser.add_argument("--max-pages", type=positive_int, default=20)
    args = parser.parse_args(argv)
    if args.date_from and args.date_to and args.date_from > args.date_to:
        parser.error("--from must not be after --to")
    if not args.cdp:
        log("pass --cdp to attach to the dedicated Portal browser")
        return AUTH_REQUIRED
    try:
        if args.setup:
            return cmd_setup(args)
        if args.discover:
            return cmd_discover(args)
        if args.calibrate:
            return cmd_calibrate(args)
        return cmd_run(args)
    except AuthRequired:
        log("AUTH_REQUIRED: complete manual Portal setup and open the notice list")
        return AUTH_REQUIRED
    except UiContractError as exc:
        log(str(exc))  # Only fixed, value-free messages from Portal helpers.
        return UI_CHANGED
    except ProjectNotFound:
        log("Portal task/project operation failed; unsuccessful notice was not recorded")
        return 30
    except Exception:
        log("Portal operation failed; diagnostic values suppressed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
