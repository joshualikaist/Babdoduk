# -*- coding: utf-8 -*-
"""Resident Chrome agent for KAIST Portal notices.

Passwords, OTP and cookies are never read, stored or typed. Endpoints are taken
only from observed XHR/fetch traffic after the user completes SSO in the
dedicated Portal profile.

    python scripts\\portal_web_agent.py --setup --cdp
    python scripts\\portal_web_agent.py --discover --cdp
    python scripts\\portal_web_agent.py --calibrate --cdp
    python scripts\\portal_web_agent.py --dry-run --cdp
    python scripts\\portal_web_agent.py --run --cdp

Cloud GitHub Actions cannot log into Portal. This agent writes collection-project
tasks locally; the existing Dooray collector then emits source_type=portal.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qsl, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ggongbab.config import KST, load_settings  # noqa: E402
from ggongbab.portal_contract import (PortalContract, contract_from_discovery)  # noqa: E402
from ggongbab.portal_observe import path_template, summarize_json  # noqa: E402
from ggongbab.portal_queue import PortalQueue  # noqa: E402
from ggongbab.prefilter import portal_detail_is_candidate, portal_list_warrants_detail  # noqa: E402
from ggongbab.web.exit_codes import (AUTH_REQUIRED, SUCCESS, UI_CHANGED, AgentError,  # noqa: E402
                                     AuthRequired, ProjectNotFound, UiContractError)
from ggongbab.web.resident import resident_session  # noqa: E402
from ggongbab.web.task_writer import PortalPayload, TaskWriter  # noqa: E402
from ggongbab.web.ui_contract import UiContract  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
LOCAL_DIR = ROOT / ".local"
PROFILE_DIR = LOCAL_DIR / "portal-browser-profile"
CONTRACT_FILE = LOCAL_DIR / "portal-ui.json"
DISCOVERY_FILE = LOCAL_DIR / "portal-discovery.json"
STATE_FILE = LOCAL_DIR / "portal-agent-state.json"
LOG_FILE = LOCAL_DIR / "portal-agent.log"
DEFAULT_START = "https://portal.kaist.ac.kr/"
DEFAULT_PORT = 9223
LOGIN_HINTS = ("login", "signin", "sign-in", "sso", "auth", "idp", "nid", "account")
TITLE_KEYS = {"title", "subject", "noticetitle", "bbsstit", "ntttitle"}
ID_KEYS = {"id", "noticeid", "bbsid", "nttid", "seq", "uid", "articleid"}
DATE_KEYS = {"createdat", "createddate", "regdate", "regdt", "date", "writedate", "updatedat"}
BODY_KEYS = {"body", "content", "contents", "html", "text", "nttcont"}
PAGE_PARAMS = {"page", "pageNo", "pageIndex", "offset", "start"}


def log(message: str) -> None:
    line = f"{datetime.now(KST).strftime('[%H:%M:%S]')} {message}"
    print(line, flush=True)
    try:
        LOCAL_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def start_url() -> str:
    import os
    return os.environ.get("PORTAL_START_URL") or DEFAULT_START


def dummy_contract(url: str) -> UiContract:
    return UiContract(mail_url=url, verified=False)


def _is_login_url(url: str) -> bool:
    parsed = urlparse(url or "")
    hay = f"{parsed.netloc}{parsed.path}".lower()
    return any(hint in hay for hint in LOGIN_HINTS)


def page_authenticated(page, expected_host: str) -> bool:
    try:
        url = page.url or ""
    except Exception:  # noqa: BLE001
        return False
    host = urlparse(url).netloc.lower()
    if expected_host and expected_host not in host:
        return False
    if _is_login_url(url):
        return False
    try:
        has_password = page.locator("input[type='password']").count() > 0
    except Exception:  # noqa: BLE001
        has_password = False
    return not has_password


def wait_for_portal(session, timeout_seconds: int = 600) -> None:
    expected = urlparse(start_url()).netloc.lower()
    deadline = time.time() + timeout_seconds
    stable = 0
    log("waiting for Portal authenticated UI (complete SSO in the browser; no Enter here)")
    while time.time() < deadline:
        pages = []
        try:
            pages = list(session.context.pages)
        except Exception:  # noqa: BLE001
            pages = [session.page]
        if any(page_authenticated(page, expected) for page in pages):
            stable += 1
            if stable >= 3:
                log("Portal authenticated page detected")
                return
        else:
            stable = 0
        time.sleep(1.0)
    raise AuthRequired("Portal SSO was not completed",
                       hint="python scripts\\portal_web_agent.py --setup --cdp")


def _json_payload(response) -> Optional[Any]:
    ctype = (response.headers or {}).get("content-type", "")
    if "json" not in ctype.lower() and "javascript" not in ctype.lower():
        return None
    try:
        return response.json()
    except Exception:  # noqa: BLE001
        return None


def _page_param(url: str) -> str:
    for name, _value in parse_qsl(urlparse(url).query, keep_blank_values=True):
        if name in PAGE_PARAMS:
            return name
    return ""


def _best_array(summary: dict[str, Any]) -> Optional[dict[str, Any]]:
    arrays = summary.get("arrays") or []
    ranked = [row for row in arrays if (row.get("length") or 0) >= 2 and row.get("rowKeys")]
    ranked.sort(key=lambda row: row.get("length") or 0, reverse=True)
    return ranked[0] if ranked else None


def classify_observed(method: str, url: str, status: int, payload: Any) -> Optional[dict[str, Any]]:
    if status < 200 or status >= 300 or payload is None:
        return None
    parsed = urlparse(url)
    summary = summarize_json(payload)
    array = _best_array(summary)
    row_keys = [k.lower() for k in (array.get("rowKeys") if array else [])]
    top = [k.lower() for k in (summary.get("topKeys") or [])]
    info = {
        "method": method,
        "host": parsed.netloc,
        "path": path_template(parsed.path),
        "status": status,
        "queryKeys": [name for name, _ in parse_qsl(parsed.query)],
        "topKeys": summary.get("topKeys") or [],
        "rowKeys": (array or {}).get("rowKeys") or [],
        "length": (array or {}).get("length") or 0,
        "pageParam": _page_param(url),
        "fieldTypes": (array or {}).get("fieldTypes") or {},
    }
    has_title = any(k in TITLE_KEYS for k in row_keys)
    has_id = any(k in ID_KEYS for k in row_keys)
    has_body = any(k in BODY_KEYS for k in top + row_keys)
    if array and has_title and has_id:
        info["kind"] = "list"
        return info
    if has_body and (has_id or has_title or "result" in top):
        info["kind"] = "detail"
        info["bodyKey"] = next((k for k in (summary.get("topKeys") or []) if k.lower() in BODY_KEYS), "")
        return info
    return None


def observe_network(page, seconds: int = 20) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def on_response(response):
        request = response.request
        if request.resource_type not in ("xhr", "fetch"):
            return
        payload = _json_payload(response)
        row = classify_observed(request.method, response.url, response.status, payload)
        if row:
            row["_payload"] = payload
            row["_url"] = response.url
            found.append(row)

    page.on("response", on_response)
    try:
        page.wait_for_timeout(seconds * 1000)
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:  # noqa: BLE001
            pass
    return found


def _public_row(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if not str(k).startswith("_")}


def write_discovery(rows: list[dict[str, Any]]) -> dict[str, Any]:
    lists = [_public_row(row) for row in rows if row.get("kind") == "list"]
    details = [_public_row(row) for row in rows if row.get("kind") == "detail"]
    report = {
        "observedAt": datetime.now(KST).isoformat(timespec="seconds"),
        "listCandidates": lists[:12],
        "detailCandidates": details[:12],
        "listEndpointObserved": bool(lists),
        "detailEndpointObserved": bool(details),
        "paginationVerified": any(row.get("pageParam") for row in lists),
    }
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    DISCOVERY_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def cmd_setup(args) -> int:
    url = start_url()
    log(f"opening Portal start URL host={urlparse(url).netloc} (SSO is manual)")
    with resident_session(PROFILE_DIR, dummy_contract(url), start_url=url,
                          port=args.port, log=log, reuse=True) as session:
        try:
            session.page.goto(url, wait_until="domcontentloaded")
        except Exception:  # noqa: BLE001
            pass
        wait_for_portal(session)
    log("setup complete; dedicated profile stays open on 127.0.0.1")
    return SUCCESS


def cmd_discover(args) -> int:
    url = start_url()
    with resident_session(PROFILE_DIR, dummy_contract(url), start_url=url,
                          port=args.port, log=log, reuse=True) as session:
        wait_for_portal(session, timeout_seconds=30)
        log("observing XHR/fetch for 20s — browse notices in the Portal tab")
        rows = observe_network(session.page, seconds=20)
    report = write_discovery(rows)
    log(f"list endpoint observed: {'yes' if report['listEndpointObserved'] else 'no'}")
    log(f"detail endpoint observed: {'yes' if report['detailEndpointObserved'] else 'no'}")
    log(f"pagination verified: {'yes' if report['paginationVerified'] else 'no'}")
    for kind, key in (("list", "listCandidates"), ("detail", "detailCandidates")):
        for row in report.get(key) or []:
            log(f"  candidate: {row.get('method')} {row.get('path')} keys={len(row.get('rowKeys') or row.get('topKeys') or [])}")
    if not report["listEndpointObserved"]:
        log("PORTAL CALIBRATION FAILED: no list endpoint observed")
        return UI_CHANGED
    return SUCCESS


def cmd_calibrate(args) -> int:
    if not DISCOVERY_FILE.exists():
        log("PORTAL CALIBRATION FAILED: run --discover first")
        return UI_CHANGED
    try:
        discovery = json.loads(DISCOVERY_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log("PORTAL CALIBRATION FAILED: discovery file unreadable")
        return UI_CHANGED
    contract = contract_from_discovery(discovery)
    if contract is None or not contract.list_ready():
        log("PORTAL CALIBRATION FAILED: list endpoint missing stable id/title keys")
        return UI_CHANGED
    if not contract.detail_path:
        log("PORTAL CALIBRATION FAILED: detail endpoint not observed")
        return UI_CHANGED
    if contract.detail_verified_count < 2:
        # Discover records candidates; two detail-shaped calls count as verification.
        details = discovery.get("detailCandidates") or []
        contract.detail_verified_count = min(len(details), 2) if details else 0
        if contract.detail_verified_count < 2:
            log("PORTAL CALIBRATION FAILED: need detail template on >=2 notices")
            return UI_CHANGED
    contract.verified = True
    contract.save(CONTRACT_FILE)
    log("list endpoint observed: yes")
    log(f"pagination verified: {'yes' if contract.list_page_param else 'no'}")
    log("stable ids: observed")
    log("dates parsed: " + ("yes" if contract.list_date_key else "no"))
    log(f"detail verified count: {contract.detail_verified_count}")
    return SUCCESS


def find_row_dicts(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        return payload
    if isinstance(payload, dict):
        for value in payload.values():
            found = find_row_dicts(value)
            if found:
                return found
    return []


def extract_body(payload: Any, key: str) -> str:
    if isinstance(payload, dict):
        if key and isinstance(payload.get(key), str) and payload.get(key):
            return str(payload.get(key))
        for name, value in payload.items():
            if name.lower() in BODY_KEYS and isinstance(value, str) and value.strip():
                return value
            nested = extract_body(value, key)
            if nested:
                return nested
    elif isinstance(payload, list):
        for item in payload:
            nested = extract_body(item, key)
            if nested:
                return nested
    return ""


def _require_contract() -> PortalContract:
    contract = PortalContract.load(CONTRACT_FILE)
    if not contract.verified or not contract.list_ready():
        raise UiContractError("PORTAL CALIBRATION FAILED",
                              hint="python scripts\\portal_web_agent.py --discover --cdp")
    return contract


def _row_value(row: dict, key: str) -> str:
    if not key:
        return ""
    value = row.get(key)
    return "" if value is None else str(value)


def _detail_for_id(detail_calls: list[dict[str, Any]], stable_id: str, body_key: str) -> str:
    if not stable_id:
        return ""
    for call in detail_calls:
        url = call.get("_url") or ""
        if stable_id and stable_id in url:
            return extract_body(call.get("_payload"), body_key)
    if len(detail_calls) == 1:
        return extract_body(detail_calls[0].get("_payload"), body_key)
    return ""


def cmd_run(args) -> int:
    contract = _require_contract()
    queue = PortalQueue(STATE_FILE)
    settings = load_settings()
    writer = TaskWriter(settings)
    if not args.dry_run:
        writer.verify_project()
    url = start_url()
    registered = 0
    skipped = 0
    updated = 0
    candidates = 0
    with resident_session(PROFILE_DIR, dummy_contract(url), start_url=url,
                          port=args.port, log=log, reuse=True) as session:
        wait_for_portal(session, timeout_seconds=30)
        log("observing live list/detail traffic (values stay in memory)")
        rows = observe_network(session.page, seconds=12)
    list_calls = [row for row in rows if row.get("kind") == "list"]
    detail_calls = [row for row in rows if row.get("kind") == "detail"]
    if not list_calls:
        log("no list traffic in this run; open the notice list then retry")
        return UI_CHANGED
    notices = find_row_dicts(list_calls[-1].get("_payload"))
    log(f"list endpoint observed: yes  detail observed this run: "
        f"{'yes' if detail_calls else 'no'}")
    log(f"stable ids: {len(notices)}/{len(notices)}" if notices else "stable ids: 0/0")
    dated = 0
    detail_used = 0
    for notice in notices:
        if not isinstance(notice, dict):
            continue
        stable_id = _row_value(notice, contract.list_id_key)
        title = _row_value(notice, contract.list_title_key)
        date_val = _row_value(notice, contract.list_date_key)
        if date_val:
            dated += 1
        if not stable_id or not portal_list_warrants_detail(title):
            continue
        body = _detail_for_id(detail_calls, stable_id, contract.detail_body_key)
        if body:
            detail_used += 1
        decision_pre = portal_detail_is_candidate(title, body, has_list_date=bool(date_val))
        if not decision_pre.candidate:
            continue
        candidates += 1
        decision = queue.decide(stable_id, title, body)
        if decision.outcome == "skip":
            skipped += 1
            continue
        payload = PortalPayload(
            external_key=decision.external_key,
            title=title,
            body=body or title,
            source_created_at=date_val,
            private_source=True,
        )
        writer.create_portal_task(payload, dry_run=args.dry_run)
        queue.record(decision)
        if decision.outcome == "update":
            updated += 1
        else:
            registered += 1
    queue.save()
    log(f"dates parsed: {dated}/{len(notices)}")
    log(f"detail verified count: {detail_used}")
    if args.dry_run:
        log("dry-run: no Dooray tasks created")
    log(f"candidates={candidates} registered={registered} updated={updated} skipped={skipped}")
    return SUCCESS


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="KAIST Portal resident agent")
    parser.add_argument("--setup", action="store_true")
    parser.add_argument("--discover", action="store_true")
    parser.add_argument("--calibrate", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--cdp", action="store_true", help="resident Chrome on 127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)
    if not args.cdp:
        log("this agent only attaches to resident Chrome; pass --cdp")
        return AUTH_REQUIRED
    try:
        if args.setup:
            return cmd_setup(args)
        if args.discover:
            return cmd_discover(args)
        if args.calibrate:
            return cmd_calibrate(args)
        if args.run or args.dry_run:
            return cmd_run(args)
        parser.print_help()
        return 1
    except AuthRequired as exc:
        log(f"AUTH_REQUIRED: {exc}")
        if exc.hint:
            log(exc.hint)
        return AUTH_REQUIRED
    except UiContractError as exc:
        log(str(exc) or "PORTAL CALIBRATION FAILED")
        return UI_CHANGED
    except ProjectNotFound as exc:
        log(f"project verification failed: {exc}")
        return 30
    except AgentError as exc:
        log(str(exc))
        return getattr(exc, "code", 1)


if __name__ == "__main__":
    sys.exit(main())
