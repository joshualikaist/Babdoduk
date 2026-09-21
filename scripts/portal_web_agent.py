"""Local Portal agent: passive discovery, verified contracts, bounded API replay.

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


def write_discovery(rows, diagnostics=None, approve_post=()):
    report = build_discovery(rows, start_url(), diagnostics, approve_post=approve_post)
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    persisted = dict(report)
    contract = report.get("contract")
    if contract and "POST" in (contract.get("list_method"), contract.get("detail_method")):
        # Approved scalar defaults belong ONLY in the local contract, never the
        # discovery/debug report. Calibration explicitly promotes this draft.
        if PortalContract.load(CONTRACT_FILE).schema_kind != "generic":
            persisted["contract"] = None
            persisted["knownContractPreserved"] = True
        else:
            PortalContract(**contract).save(CONTRACT_FILE)
            persisted["postContractDraft"] = True
        persisted["contract"] = None
    DISCOVERY_FILE.write_text(json.dumps(persisted, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
    report = write_discovery(rows, diagnostics, getattr(args, "approve_post_field", ()))
    log_discovery(report)
    return SUCCESS if report["listReplayable"] else UI_CHANGED


def cmd_discover_detail_alternatives(args):
    from ggongbab.portal_detail_alternatives import observe, report_lines
    # Attach only: unlike setup/discovery, this mode must not open or reload a URL.
    with resident_session(PROFILE_DIR, dummy_contract(DEFAULT_START), start_url="",
                          port=args.port, log=lambda _: None, reuse=True, attach_only=True) as session:
        report = observe(session, log)
    for line in report_lines(report):
        log(line)
    # These are observation results, never a replay contract or authorization.
    return SUCCESS if any(not c["view-counter field present"] for c in report["candidates"]) else UI_CHANGED


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
    chosen_list = safe.get("selectedList") or {}
    chosen_detail = safe.get("selectedDetail") or {}
    pagination = safe.get("paginationCandidates") or []

    log("Interaction correlation:")
    log(f"  list-like JSON candidates: {counts.get('list-like JSON candidates', 0)}")
    log(f"  detail-like JSON candidates: {counts.get('detail-like JSON candidates', 0)}")
    log(f"  correlated list/detail pairs: {counts.get('correlated list/detail pairs', 0)}")
    log(f"  correlated distinct ids: {counts.get('correlated distinct ids', 0)}")
    log(f"  correlated via URL: {counts.get('correlated via URL', 0)}")
    log(f"  correlated via POST body: {counts.get('correlated via POST body', 0)}")
    log("POST observation:")
    log(f"  notice-like POST candidates: {counts.get('observed notice-like POST candidate', 0)}")
    log(f"  correlated POST endpoints: {counts.get('correlated POST endpoints', 0)}")
    log("  selected method: " + (chosen_detail.get("method") or "none"))
    log("  keys: " + _names(safe.get("postRequestKeys") or []))
    log("  request scalar paths: " + _names(safe.get("postRequestScalarPaths") or []))
    log("  request id path: " + (chosen_detail.get("requestIdPath") or "unknown"))
    for entry in safe.get("postPaginationCandidates") or []:
        log(f"  pagination body candidate: {entry['path']} numericMonotonic={entry['numericMonotonic']}")
    log("  filter paths: " + _names(safe.get("postFilterPaths") or []))

    log("Selected notice list:")
    log("  correlated: " + _yes(chosen_list.get("correlated")))
    if chosen_list.get("correlated"):
        log("  method: " + chosen_list.get("method", "GET"))
        log("  candidate path: " + (chosen_list.get("candidatePath") or "<unsafe path, withheld>"))
        log("  array path: " + (chosen_list.get("arrayPath") or "unknown"))
        log("  row keys: " + _names(chosen_list.get("rowKeys") or safe.get("rowKeys") or []))
        log("  id key: " + (chosen_list.get("idKey") or "unknown"))
        log("  title key: " + (chosen_list.get("titleKey") or "unknown"))
        log("  date key: " + (chosen_list.get("dateKey") or "unknown"))
    elif candidate.get("host"):
        # Nothing was chosen, but say what was seen so the next run is targeted.
        log("  observed host: " + candidate["host"])
        log("  observed path: " + (candidate.get("templatedPath") or "<unsafe path, withheld>"))
        log("  observed query keys: " + _names(candidate.get("queryKeys") or []))
    log("  unsafe query keys: " + _names(safe.get("unsafeQueryKeys") or []))
    log("  static structural keys: " + _names(safe.get("staticStructuralKeys") or []))

    log("Selected notice detail:")
    log("  correlated: " + _yes(chosen_detail.get("correlated")))
    log(f"  ambiguous body responses: {rejected.get('body path ambiguous', 0)}")
    if chosen_detail.get("correlated"):
        log("  method: " + chosen_detail.get("method", "GET"))
        log("  request id path: " + (chosen_detail.get("requestIdPath") or "unknown"))
        log("  candidate path: " + (chosen_detail.get("candidatePath") or "<unsafe path, withheld>"))
        log("  id path: " + (chosen_detail.get("idPath") or "unknown"))
        log("  body candidate paths: " + _names(chosen_detail.get("bodyCandidatePaths") or []))
        log("  body path selected: " + (chosen_detail.get("bodyPathSelected") or "ambiguous"))
        log("  body disambiguated by id subtree: " + _yes(safe.get("bodyDisambiguatedByIdSubtree")))
    log(f"  distinct replayable details: {counts.get('replayable detail candidates', 0)}")

    log("Pagination:")
    if not chosen_list.get("correlated"):
        log("  evaluated only after notice list correlation: not reached")
        return
    for entry in pagination:
        log(f"  candidate key: {entry['key']} "
            f"(numericMonotonic={str(entry['numericMonotonic']).lower()}, "
            f"opaqueChanging={str(entry['opaqueChanging']).lower()})")
    if not pagination:
        log("  candidate key: none")
    log("  mechanism: " + (report.get("contract", {}) or {}).get("pagination", "none"
        if report.get("listReplayable") else "unverified"))


def _yes(value):
    return "yes" if value else "no"


def cmd_calibrate(args):
    if PortalContract.load(CONTRACT_FILE).schema_kind != "generic":
        log("Known Portal contract preserved; use --calibrate-known --cdp")
        return UI_CHANGED
    # Invalidate earlier authorization if this calibration fails.
    if CONTRACT_FILE.exists():
        old = PortalContract.load(CONTRACT_FILE)
        old.verified = False
        old.save(CONTRACT_FILE)
    try:
        discovery = json.loads(DISCOVERY_FILE.read_text(encoding="utf-8"))
        contract = (PortalContract.load(CONTRACT_FILE) if discovery.get("postContractDraft")
                    else contract_from_discovery(discovery))
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
    if contract.schema_kind != "generic" and (contract.potential_view_side_effect or not contract.detail_side_effect_reviewed):
        from ggongbab.portal_known_schema import VIEW_BLOCKED
        raise UiContractError(VIEW_BLOCKED)
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
            if contract.schema_kind != "generic":
                from ggongbab.portal_known_schema import public_row
                if not public_row(row):
                    continue
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
            body = fetch_detail(request, contract, identifier, row)
            counts["detail_fetched"] += 1
            if not portal_detail_is_candidate(title, body, has_list_date=parsed_date is not None).candidate:
                continue
            counts["candidates"] += 1
            decision = queue.decide(identifier, title, body)
            counts[{"new": "new", "update": "updated", "skip": "already_queued"}[decision.outcome]] += 1
            if args.dry_run or decision.outcome == "skip":
                continue
            source_created_at = str(row.get(contract.list_date_key) or "")
            if contract.schema_kind != "generic":
                from ggongbab.portal_discovery import notice_timestamp
                source_created_at = notice_timestamp(source_created_at).isoformat()
            payload = PortalPayload(external_key=decision.external_key, title=title, body=body,
                                    source_created_at=source_created_at)
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


def cmd_calibrate_known(args):
    from ggongbab.portal_known_schema import known_contract, calibrate, VIEW_BLOCKED, KNOWN_HOST
    c = known_contract()
    # A failed re-calibration must not leave an older authorization runnable.
    c.save(CONTRACT_FILE)
    try:
        if urlparse(start_url()).netloc != KNOWN_HOST:
            raise UiContractError("KNOWN_PORTAL_HOST_REQUIRED")
        with open_session(args, c.start_url) as session:
            calibrate(session, c, log)
    finally:
        c.save(CONTRACT_FILE)
    log("Known Portal calibration:")
    for message in ("host verified: yes", "list endpoint verified: yes", "list schema verified: yes",
                    "page 1 verified: yes", "page 2 verified: yes", "pagination: pageIndex +1",
                    "date field: regDt", "date format verified: yes", "detail endpoint verified: yes",
                    f"distinct details verified: {c.detail_verified_count}", "detail id path: pstNo",
                    "detail body path: pstCn", "row-bound detail query: boardNo", "public gate: publicYn == Y"):
        log("  " + message)
    # Do not name an account field in persisted logs; only state the privacy result.
    log("  account-identifying query persisted: no")
    log("  potential view counter field observed: " + _yes(c.view_counter_observed))
    log("  potential view side effect: " + ("review-required" if c.potential_view_side_effect else "no"))
    log("  date descending verified: " + _yes(c.list_date_descending))
    if not c.verified:
        log(VIEW_BLOCKED)
        return UI_CHANGED
    log("calibration complete")
    return SUCCESS


def main(argv=None):
    parser = argparse.ArgumentParser(description="KAIST Portal resident agent")
    modes = parser.add_mutually_exclusive_group(required=True)
    for mode in ("setup", "discover", "discover-detail-alternatives", "calibrate", "calibrate-known", "run", "dry-run"):
        modes.add_argument("--" + mode, action="store_true")
    parser.add_argument("--cdp", action="store_true")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--from", dest="date_from", type=date.fromisoformat)
    parser.add_argument("--to", dest="date_to", type=date.fromisoformat)
    parser.add_argument("--max-items", type=positive_int, default=500)
    parser.add_argument("--max-pages", type=positive_int, default=20)
    parser.add_argument("--approve-post-field", action="append", default=[], metavar="list:PATH|detail:PATH",
                        help="Explicitly approve a POST structural field name; values must still be invariant and safe")
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
        if args.discover_detail_alternatives:
            return cmd_discover_detail_alternatives(args)
        if args.calibrate:
            return cmd_calibrate(args)
        if args.calibrate_known:
            return cmd_calibrate_known(args)
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
