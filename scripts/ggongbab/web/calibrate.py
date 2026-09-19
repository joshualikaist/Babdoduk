# -*- coding: utf-8 -*-
"""Fill the UI contract from a live, authenticated inbox - no hand editing.

The first live discovery showed why this is needed and how it must work:

  * Dooray's mail list endpoint was there all along, but its content-type does
    not say `json`, so the header-based filter filed it under "non-JSON" and its
    shape was never inspected. Sniffing the body fixed that.
  * The inbox DOM uses generated class names (`css-15hz540`) that change on every
    deployment, and every row carried the *same* attribute value, so the DOM gives
    no stable per-row id. The JSON endpoint does.

So calibration prefers the endpoint the web app itself calls, verifies it by
reading real rows, and only then marks the contract verified. Nothing is written
to the mailbox at any point.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .exit_codes import AuthRequired, UiContractError
from .read_state import crosscheck_dom, inspect_read_schema, path_value, unread_value, safe_path
from .mail_reader import (DATE_KEYS, ID_KEYS, READ_KEYS, SUBJECT_KEYS, MailHeader,
                          _find_rows, _from_json_rows, _lower, redact)

MIN_SMOKE_ROWS = 5
PAGE_PARAMS = ("page", "pageno", "pagenumber", "offset")
SIZE_PARAMS = ("size", "limit", "count", "pagesize")


def set_query(url: str, **params: Any) -> str:
    """Replace query parameters, keeping everything else identical."""
    parsed = urlparse(url)
    pairs = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key, value in params.items():
        if value is None:
            pairs.pop(key, None)
        else:
            pairs[key] = str(value)
    return urlunparse(parsed._replace(query=urlencode(pairs)))


def query_param_named(url: str, names: tuple[str, ...]) -> str:
    """The actual parameter name this endpoint uses, or '' when it has none."""
    keys = [k for k, _v in parse_qsl(urlparse(url).query, keep_blank_values=True)]
    lowered = {k.lower(): k for k in keys}
    for candidate in names:
        if candidate in lowered:
            return lowered[candidate]
    return ""


def endpoint_score(call: dict[str, Any]) -> int:
    """Rank mail-list candidates by evidence, never by their URL wording."""
    shape = call.get("shape") or {}
    if shape.get("kind") != "rows":
        return -1
    keys = _lower(shape.get("rowKeys"))
    score = 0
    if keys & SUBJECT_KEYS:
        score += 5
    if keys & DATE_KEYS:
        score += 3
    if keys & ID_KEYS:
        score += 3
    if keys & READ_KEYS:
        score += 1
    rows = int(shape.get("rowCount") or 0)
    score += min(rows, 50) // 10
    if call.get("afterReload"):
        score += 2
    if call.get("onMailScreen"):
        score += 1
    if query_param_named(call.get("rawUrl") or "", PAGE_PARAMS):
        score += 2          # a pageable endpoint can reach September
    return score


def choose_list_endpoint(calls: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    ranked = sorted(((endpoint_score(c), c) for c in calls), key=lambda pair: pair[0], reverse=True)
    if not ranked or ranked[0][0] <= 0:
        return None
    best_score, best = ranked[0]
    # Require the essentials: without a subject and a stable id there is nothing
    # to filter on and nothing to deduplicate by.
    keys = _lower((best.get("shape") or {}).get("rowKeys"))
    if not (keys & SUBJECT_KEYS and keys & ID_KEYS):
        return None
    if len(ranked) > 1 and ranked[1][0] == best_score:
        return None         # ambiguous: fail closed rather than pick a coin toss
    return best


PREVIEW_PATHS = ("mailSummary.previewText", "previewText", "summary", "preview",
                 "snippet", "bodyPreview")
MIN_PREVIEW_CHARS = 20


def detect_preview_key(rows: list[dict[str, Any]]) -> str:
    """The path that actually carries preview text, verified across rows.

    On this tenant it is `mailSummary.previewText`: a nested string, while
    `mailSummary` itself is an object. A flat key lookup found nothing, which is
    why every header used to arrive with an empty preview.
    """
    from .mail_reader import path_value_safe

    sample = rows[:30]
    if not sample:
        return ""
    for path in PREVIEW_PATHS:
        values = [path_value_safe(row, path) for row in sample]
        texts = [v for v in values if isinstance(v, str) and len(v.strip()) >= MIN_PREVIEW_CHARS]
        if len(texts) >= max(3, len(sample) * 0.6):
            return path
    return ""


def detect_read_key(rows: list[dict[str, Any]]) -> str:
    """One explicit, consistently typed semantic field; never arbitrary truthiness."""
    return inspect_read_schema(rows)[2]


@dataclass
class SmokeResult:
    rows_seen: int = 0
    headers_parsed: int = 0
    stable_ids: int = 0
    unique_ids: int = 0
    dates_parsed: int = 0
    read_count: int = 0
    unread_count: int = 0
    read_key: str = ""
    preview_key: str = ""
    row_keys: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    nested_schema: dict[str, list[str]] = field(default_factory=dict)
    read_candidates: list[dict] = field(default_factory=list)
    dom_check: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return (self.headers_parsed >= MIN_SMOKE_ROWS
                and self.unique_ids == self.headers_parsed
                and self.dates_parsed == self.headers_parsed
                and not self.errors)

    def lines(self) -> list[str]:
        out = [
            f"mail headers parsed: {self.headers_parsed}",
            f"stable ids: {self.unique_ids}/{self.headers_parsed}",
            f"dates parsed: {self.dates_parsed}/{self.headers_parsed}",
        ]
        out.append(f"preview field: {self.preview_key}" if self.preview_key
                   else "preview field: none found (rows carry no preview text)")
        if self.read_key:
            out.append(f"read-state detected: {self.read_count} read / {self.unread_count} unread"
                       f"  (field: {self.read_key})")
        else:
            out.append("read-state detected: none (no unambiguous validated read-state field)")
        for err in self.errors:
            out.append(f"problem: {err}")
        return out


def fetch_rows(page, url: str, read_state_key: Optional[str] = None,  # noqa: ANN001
               preview_key: str = "") -> tuple[list[dict[str, Any]], list[MailHeader]]:
    """GET through the browser context, so the session cookie is reused untouched."""
    try:
        response = page.request.get(url, timeout=30_000)
    except Exception as exc:  # noqa: BLE001
        raise UiContractError(f"list endpoint failed: {exc.__class__.__name__}") from exc
    if response.status in (401, 403):
        raise AuthRequired("the mail list endpoint rejected the session",
                           hint="run: python scripts/dooray_web_agent.py --setup --cdp")
    if response.status >= 400:
        raise UiContractError(f"list endpoint returned HTTP {response.status}")
    try:
        payload = response.json()
    except Exception:  # noqa: BLE001
        import json as _json

        try:
            payload = _json.loads(response.text())
        except Exception as exc:  # noqa: BLE001
            raise UiContractError("list endpoint did not return JSON") from exc
    rows = _find_rows(payload)
    return rows, _from_json_rows(rows, read_state_key, preview_key)


def smoke_test(page, url: str, limit: int = 10, dom_frame=None) -> SmokeResult:  # noqa: ANN001
    """Read a handful of headers. No body is opened and nothing is written."""
    result = SmokeResult()
    rows, headers = fetch_rows(page, url)
    result.rows_seen = len(rows)
    if not rows:
        result.errors.append("endpoint returned no rows")
        return result
    result.row_keys = sorted(rows[0].keys())[:30]
    result.nested_schema, result.read_candidates, result.read_key = inspect_read_schema(rows)
    result.preview_key = detect_preview_key(rows)
    if result.read_key and dom_frame is not None:
        result.dom_check = crosscheck_dom(dom_frame, rows, result.read_key)
        if result.dom_check["matched"] > result.dom_check["agreement"]:
            # An explicit contradiction invalidates the field, not the list API.
            result.read_key = ""
    headers = headers[:limit]
    result.headers_parsed = len(headers)
    ids = [h.mail_id for h in headers if h.mail_id]
    result.stable_ids = len(ids)
    result.unique_ids = len(set(ids))
    result.dates_parsed = sum(1 for h in headers if h.received is not None)
    if result.read_key:
        for row in rows[:limit]:
            unread = unread_value(path_value(row, result.read_key), result.read_key)
            if unread:
                result.unread_count += 1
            else:
                result.read_count += 1
    if result.headers_parsed < MIN_SMOKE_ROWS:
        result.errors.append(f"only {result.headers_parsed} headers parsed (need {MIN_SMOKE_ROWS})")
    if result.unique_ids != result.headers_parsed:
        result.errors.append("mail ids are not unique per row")
    if result.dates_parsed != result.headers_parsed:
        result.errors.append("some rows have no parsable received date")
    return result


ID_IN_PATH = __import__("re").compile(r"/(\d{6,})(?=[/?]|$)")


def detail_template(url: str, mail_id: str) -> str:
    """Turn an observed detail URL into a `{id}` template.

    Only the exact mail id is replaced, so a numeric folder or tenant id in the
    same path is left alone.
    """
    if not url or not mail_id or mail_id not in url:
        return ""
    return url.replace(mail_id, "{id}", 1)


def discover_detail_api(page, rows: list[dict], observer=None, log=print) -> tuple[str, str]:  # noqa: ANN001
    """Find the detail endpoint and the path to the body inside its response.

    Driven by what the browser actually requested when a mail was opened. Both
    the URL template and the body path are then re-verified against a *second*
    mail, so a one-off coincidence cannot become the contract.

    Only mails already marked read are touched, so no unread mail is opened.
    """
    from .mail_reader import detail_body, longest_string_paths

    read_rows = [r for r in rows if str(r.get("id") or "")]
    if len(read_rows) < 2:
        return "", ""

    template = ""
    if observer is not None:
        ids = {str(r.get("id")) for r in read_rows}
        for call in observer.calls.values():
            raw = call.get("rawUrl") or ""
            hit = next((i for i in ids if i and i in raw), "")
            if hit and (call.get("shape") or {}).get("kind") == "object":
                template = detail_template(raw, hit)
                break
    if not template:
        return "", ""

    body_path = ""
    verified = 0
    for row in read_rows[:2]:
        mail_id = str(row["id"])
        try:
            response = page.request.get(template.replace("{id}", mail_id), timeout=30_000)
            if response.status >= 400:
                return "", ""
            payload = response.json()
        except Exception:  # noqa: BLE001
            return "", ""
        if not body_path:
            candidates = [p for p, n in longest_string_paths(payload) if n >= 40]
            body_path = next((p for p in candidates if p.rsplit(".", 1)[-1].lower() in
                              ("content", "body", "text", "html")), candidates[0] if candidates else "")
        if body_path and detail_body(payload, body_path):
            verified += 1
    if verified < 2:
        log("  detail endpoint found, but the body path did not verify on two mails")
        return "", ""
    log(f"detail endpoint: {redact(template)}")
    log(f"  body path: {body_path}  (verified on {verified} already-read mails)")
    return template, body_path


def calibrate(page, observer, contract, log=print, dom_frame=None) -> dict[str, Any]:  # noqa: ANN001
    """Choose the endpoint, verify it, and fill the contract. Returns a summary."""
    contract.verified = False
    contract.read_state_key = ""
    candidates = [c for c in observer.calls.values() if (c.get("shape") or {}).get("kind") == "rows"]
    chosen = choose_list_endpoint(candidates)
    summary: dict[str, Any] = {"strategy": None, "listApi": None, "smoke": None}
    if chosen is None:
        summary["strategy"] = "none"
        log("no unambiguous mail-list endpoint was observed.")
        return summary

    raw_url = chosen.get("rawUrl") or ""
    log(f"list endpoint: {redact(raw_url)}")
    log(f"  row keys: {', '.join(safe_path(k) for k in (chosen.get('shape') or {}).get('rowKeys') or [])}")

    result = smoke_test(page, raw_url, dom_frame=dom_frame)
    log("nested schema (key paths and primitive types only):")
    for path, types in result.nested_schema.items():
        if "." in path:
            log(f"  {path}: {', '.join(types)}")
    for candidate in result.read_candidates:
        log(f"  read-state candidate: {candidate['path']} "
            f"valid rows: {candidate['validRows']}/{candidate['rows']}")
    if not result.read_candidates:
        log("  read-state candidates: none")
    if result.dom_check.get("verified"):
        log("verified read-state candidate (DOM cross-check):")
    elif result.dom_check.get("matched", 0) > result.dom_check.get("agreement", 0):
        log("DOM read-state verification: disagreement; candidate rejected")
    else:
        log("DOM read-state verification: unavailable or insufficient; no UI agreement claimed")
    if result.dom_check:
        log(f"  matched rows: {result.dom_check['matched']}")
        log(f"  agreement: {result.dom_check['agreement']}/{result.dom_check['matched']}")
    for line in result.lines():
        log(f"  {line}")
    summary["strategy"] = "api"
    summary["listApi"] = redact(raw_url)
    summary["smoke"] = result

    if not result.ok:
        log("  -> smoke test failed; contract left unverified.")
        return summary

    contract.list_api = raw_url
    contract.list_page_param = query_param_named(raw_url, PAGE_PARAMS)
    contract.list_size_param = query_param_named(raw_url, SIZE_PARAMS)
    contract.read_state_key = result.read_key
    contract.preview_key = result.preview_key
    contract.verified = True

    # Subjects alone cannot decide whether food is provided, so the body matters.
    # Discovery runs last, only against mails already marked read.
    rows, _headers = fetch_rows(page, raw_url)
    detail_api, body_path = discover_detail_api(page, rows, observer, log=log)
    if detail_api:
        contract.detail_api = detail_api
        contract.detail_body_path = body_path
    else:
        log("  no verified detail endpoint; bodies stay unavailable and runs are subject/preview only")
    summary["detailApi"] = redact(detail_api) if detail_api else None
    return summary
