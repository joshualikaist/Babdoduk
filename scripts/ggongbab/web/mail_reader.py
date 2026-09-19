# -*- coding: utf-8 -*-
"""Read the mail list from the Dooray web app, and discover how to do so.

Two strategies, in order of preference:

1. `list_api` - an internal JSON endpoint that the web app itself calls. The
   request goes through the browser context, so the session cookie is reused
   without this code ever reading or storing it. Stabler than the DOM, and
   listing mails does not open them.
2. DOM selectors - the fallback when discovery finds no usable JSON endpoint.

Opening a mail body marks it read in the mailbox. That is a real, visible side
effect, so it happens only when the caller asks for it and never for a mail that
was already processed.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from ..config import KST
from .browser import Session
from .exit_codes import UiContractError

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_DATE_FORMATS = ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S",
                 "%Y-%m-%d %H:%M", "%m-%d", "%m/%d", "%m.%d")
_MAX_BODY_CHARS = 20000

# Landmark discovery runs in the page. Kept small and side-effect free.
_LANDMARK_JS = """
() => {
  const counts = {};
  document.querySelectorAll('[class]').forEach(el => {
    const cls = (el.getAttribute('class') || '').trim().split(/\\s+/).slice(0, 2).join('.');
    if (cls) counts[cls] = (counts[cls] || 0) + 1;
  });
  const repeated = Object.entries(counts)
    .filter(e => e[1] >= 5 && e[1] <= 300)
    .sort((a, b) => b[1] - a[1]).slice(0, 25)
    .map(e => ({ selector: '.' + e[0], count: e[1] }));
  const attrs = {};
  document.querySelectorAll('*').forEach(el => {
    for (const a of el.attributes) {
      if (a.name.startsWith('data-') || a.name === 'id') {
        attrs[a.name] = (attrs[a.name] || 0) + 1;
      }
    }
  });
  const idAttrs = Object.entries(attrs)
    .filter(e => e[1] >= 5).sort((a, b) => b[1] - a[1]).slice(0, 20)
    .map(e => ({ attribute: e[0], count: e[1] }));
  return { repeated, idAttrs, title: document.title || '' };
}
"""


@dataclass
class MailHeader:
    mail_id: str
    subject: str
    preview: str = ""
    received: Optional[date] = None
    unread: Optional[bool] = None
    body: str = ""
    body_opened: bool = False

    @property
    def text_for_filter(self) -> str:
        return f"{self.body or self.preview}"


# Key-name heuristics used only to CLASSIFY observed responses and to explain the
# classification in the report. They are never used to guess a URL or a selector,
# and a classification never sets `verified` by itself.
SUBJECT_KEYS = {"subject", "title", "mailsubject", "mailtitle"}
DATE_KEYS = {"receivedat", "sentat", "createdat", "date", "receiveddate", "senddate", "receivedtime"}
ID_KEYS = {"id", "mailid", "messageid", "seq", "uid", "mailseq"}
BODY_KEYS = {"body", "content", "html", "text", "mailbody", "contents"}
READ_KEYS = {"read", "isread", "unread", "isunread", "readflag", "unreadflag", "readyn", "seen"}
MAX_INSPECT_BYTES = 2_000_000


def parse_day(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, (int, float)) and value > 10_000_000:
        seconds = value / 1000 if value > 10_000_000_000 else value
        try:
            return datetime.fromtimestamp(seconds, KST).date()
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(KST).date()
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
        if "%Y" not in fmt:
            parsed = parsed.replace(year=datetime.now(KST).year)
        return parsed.date()
    return None


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------
def redact(url: str) -> str:
    """Keep the shape of a URL and drop every value."""
    url = _EMAIL.sub("[email]", url or "")
    base, sep, query = url.partition("?")
    if not sep:
        return base
    keys = [part.split("=", 1)[0] for part in query.split("&") if part]
    return base + "?" + "&".join(f"{k}=<v>" for k in keys)


def shape_of(payload: Any) -> dict[str, Any]:
    """Describe a JSON response by SHAPE only: key names and counts, never values.

    Key names are schema, not content, so they are safe to write down and they are
    what makes filling the contract possible without a second guessing round.
    """
    rows = _find_rows(payload)
    if rows:
        keys: list[str] = []
        for row in rows[:5]:
            for key in row:
                if key not in keys:
                    keys.append(key)
        return {"kind": "rows", "rowCount": len(rows), "rowKeys": keys[:30]}
    if isinstance(payload, dict):
        target = payload.get("result") if isinstance(payload.get("result"), dict) else payload
        keys = list(target.keys())[:30] if isinstance(target, dict) else []
        longest = 0
        if isinstance(target, dict):
            for value in target.values():
                if isinstance(value, str):
                    longest = max(longest, len(value))
                elif isinstance(value, dict):
                    for nested in value.values():
                        if isinstance(nested, str):
                            longest = max(longest, len(nested))
        return {"kind": "object", "objectKeys": keys, "longestTextLength": longest}
    return {"kind": type(payload).__name__}


def _lower(names: Any) -> set[str]:
    return {str(n).lower() for n in (names or [])}


def classify_call(call: dict[str, Any]) -> tuple[str, list[str]]:
    """(category, reasons). Categories: mail-list / mail-detail / other."""
    reasons: list[str] = []
    shape = call.get("shape") or {}
    content_type = call.get("contentType") or ""
    if "json" in content_type:
        reasons.append("content-type json")
    if call.get("hitCount", 1) > 1:
        reasons.append(f"called {call['hitCount']}x")
    if call.get("afterReload"):
        reasons.append("fired again after reloading the inbox")
    if call.get("onMailScreen"):
        reasons.append("observed while the mail screen was open")

    if shape.get("kind") == "rows":
        keys = _lower(shape.get("rowKeys"))
        has_subject = bool(keys & SUBJECT_KEYS)
        has_when = bool(keys & DATE_KEYS)
        has_id = bool(keys & ID_KEYS)
        if has_subject:
            reasons.append("rows carry a subject-like key")
        if has_when:
            reasons.append("rows carry a date-like key")
        if has_id:
            reasons.append("rows carry an id-like key")
        reasons.append(f"{shape.get('rowCount')} rows")
        if has_subject and (has_when or has_id) and shape.get("rowCount", 0) >= 2:
            return "mail-list", reasons
    if shape.get("kind") == "object":
        keys = _lower(shape.get("objectKeys"))
        if keys & BODY_KEYS and shape.get("longestTextLength", 0) > 200:
            reasons.append("single object with a long body-like field")
            return "mail-detail", reasons
    return "other", reasons


class NetworkObserver:
    """Collects XHR/fetch shapes. Nothing is persisted here.

    `target` is a page OR a browser context. Attaching to the context is what
    setup uses: Dooray may move the mailbox to another tab, and a page-level
    listener would then see none of its traffic.
    """

    def __init__(self, page):  # noqa: ANN001
        self.page = page
        self.calls: dict[str, dict[str, Any]] = {}
        self._attached = False
        self.after_reload = False
        self.on_mail_screen = False
        # Bound once: `self._on_response` builds a new object on every access, so
        # registering and removing would otherwise use two different callables.
        self._handler = self._on_response

    def _on_response(self, response) -> None:  # noqa: ANN001
        try:
            request = response.request
            if request.resource_type not in ("xhr", "fetch"):
                return
            content_type = (response.header_value("content-type") or "").split(";")[0]
            key = f"{request.method} {redact(response.url)}"
            entry = self.calls.get(key)
            if entry is None:
                entry = {
                    "method": request.method,
                    "url": redact(response.url),
                    "status": response.status,
                    "contentType": content_type,
                    "hitCount": 0,
                    "afterReload": False,
                    "onMailScreen": False,
                    "shape": None,
                }
                self.calls[key] = entry
            entry["hitCount"] += 1
            entry["afterReload"] = entry["afterReload"] or self.after_reload
            entry["onMailScreen"] = entry["onMailScreen"] or self.on_mail_screen
            if entry["shape"] is None and "json" in content_type and response.status < 400:
                length = response.header_value("content-length")
                if length and length.isdigit() and int(length) > MAX_INSPECT_BYTES:
                    return
                try:
                    entry["shape"] = shape_of(response.json())
                except Exception:  # noqa: BLE001 - body may be gone or not JSON
                    pass
        except Exception:  # noqa: BLE001 - observation must never break the page
            pass

    def start(self) -> None:
        if not self._attached:
            self.page.on("response", self._handler)
            self._attached = True

    def stop(self) -> None:
        if self._attached:
            try:
                self.page.remove_listener("response", self._handler)
            except Exception:  # noqa: BLE001
                pass
            self._attached = False

    # -- findings ------------------------------------------------------
    def classified(self) -> dict[str, list[dict[str, Any]]]:
        buckets: dict[str, list[dict[str, Any]]] = {"mail-list": [], "mail-detail": [], "other": []}
        for call in self.calls.values():
            category, reasons = classify_call(call)
            row = dict(call)
            row["why"] = reasons
            buckets[category].append(row)
        for rows in buckets.values():
            rows.sort(key=lambda r: (-(r.get("hitCount") or 0), r["url"]))
        return buckets

    def list_candidates(self) -> list[dict[str, Any]]:
        return self.classified()["mail-list"]

    def observed_read_state_keys(self) -> list[str]:
        """Which read/unread key names actually exist. Empty means: do not invent one."""
        found: list[str] = []
        for call in self.calls.values():
            shape = call.get("shape") or {}
            for key in shape.get("rowKeys") or []:
                if str(key).lower() in READ_KEYS and key not in found:
                    found.append(str(key))
        return found


def recommend_list_api(candidates: list[dict[str, Any]]) -> Optional[str]:
    """Suggest an endpoint only when exactly one candidate is unambiguous.

    All of: JSON, rows carrying subject/id/date-like keys, seen again after the
    inbox was reloaded, and observed while the mail view was open. With two or
    more candidates nothing is recommended - reporting beats guessing.
    """
    if len(candidates) != 1:
        return None
    call = candidates[0]
    shape = call.get("shape") or {}
    keys = _lower(shape.get("rowKeys"))
    if not (keys & SUBJECT_KEYS and keys & ID_KEYS and keys & DATE_KEYS):
        return None
    if not (call.get("afterReload") and call.get("onMailScreen")):
        return None
    if "json" not in (call.get("contentType") or ""):
        return None
    return call.get("url")


def write_discovery_report(observer: NetworkObserver, row_evidence: dict[str, Any], out_path: Path, *,
                           page_url: str, confirmed_by_user: bool) -> dict[str, Any]:
    """`row_evidence` comes from page_select.mail_row_evidence on the SELECTED frame."""
    buckets = observer.classified()
    lists = buckets["mail-list"]
    report = {
        "recordedAt": datetime.now(KST).isoformat(timespec="seconds"),
        "pageUrl": redact(page_url),
        "note": ("Redacted. URL query values are replaced with <v>. JSON responses are summarised by "
                 "SHAPE ONLY - key names and row counts - never values. No bodies, headers, cookies, "
                 "addresses or mail text are stored."),
        "evidence": {
            "A_mailListCallObserved": bool(lists),
            "B_confirmedByUser": confirmed_by_user,
            # C counts groups that look like MAIL ROWS, not merely repeated elements.
            "C_mailRowGroups": len(row_evidence.get("mailRowGroups") or []),
            "C_strong": bool(row_evidence.get("strong")),
            "repeatedContainers": row_evidence.get("repeatedContainers", 0),
        },
        "mailListCandidates": lists,
        "mailDetailCandidates": buckets["mail-detail"],
        "recommendedListApi": recommend_list_api(lists),
        "otherJsonCalls": [c for c in buckets["other"] if "json" in (c.get("contentType") or "")][:40],
        "nonJsonCalls": [{"method": c["method"], "url": c["url"], "status": c["status"]}
                         for c in buckets["other"] if "json" not in (c.get("contentType") or "")][:30],
        "observedReadStateKeys": observer.observed_read_state_keys(),
        "domRowGroups": row_evidence,
        "nextStep": ("Copy the chosen list_api (and detail_api) into .local/dooray-ui.json, confirm the "
                     "response shape is really the inbox, then set \"verified\": true by hand."),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def observe(session: Session, observer: NetworkObserver, seconds: int, *,
            reload: bool = False, target=None) -> None:  # noqa: ANN001
    """Watch for a while, optionally reloading to force the list call.

    `target` is a page_select.MailTarget. Reloading the target (a tab or a frame)
    rather than the launch page is what makes the inbox re-issue its list request.
    """
    page = getattr(target, "page", None) or session.page
    if reload:
        observer.after_reload = True
        if target is not None:
            target.reload()
        else:
            try:
                page.reload(wait_until="domcontentloaded")
            except Exception:  # noqa: BLE001
                pass
    page.wait_for_timeout(max(1, seconds) * 1000)
    try:
        page.mouse.wheel(0, 1500)
        page.wait_for_timeout(2000)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------
def _pick(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return None


def _from_json_rows(rows: list[dict[str, Any]]) -> list[MailHeader]:
    out: list[MailHeader] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        mail_id = _pick(row, "id", "mailId", "messageId", "seq", "uid")
        subject = _pick(row, "subject", "title", "mailSubject")
        if mail_id is None or subject is None:
            continue
        received = parse_day(_pick(row, "receivedAt", "sentAt", "createdAt", "date", "receivedDate"))
        unread = _pick(row, "unread", "isUnread", "unreadFlag")
        if unread is None:
            read_flag = _pick(row, "read", "isRead")
            unread = (not read_flag) if read_flag is not None else None
        out.append(MailHeader(
            mail_id=str(mail_id),
            subject=str(subject),
            preview=str(_pick(row, "summary", "preview", "snippet", "bodyPreview") or ""),
            received=received,
            unread=bool(unread) if unread is not None else None,
        ))
    return out


def _find_rows(payload: Any) -> list[dict[str, Any]]:
    """Locate the list of mail objects inside an unknown JSON envelope."""
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("result", "results", "data", "items", "contents", "list", "mails", "messages"):
        value = payload.get(key)
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value
        if isinstance(value, dict):
            nested = _find_rows(value)
            if nested:
                return nested
    return []


def list_mails_via_api(session: Session, url: str, limit: int) -> list[MailHeader]:
    """Fetch the list endpoint through the browser context (session cookies apply)."""
    try:
        response = session.page.request.get(url, timeout=30_000)
    except Exception as exc:  # noqa: BLE001
        raise UiContractError(f"mail list endpoint failed: {exc.__class__.__name__}",
                              hint="re-run --discover; the internal API may have changed") from exc
    if response.status in (401, 403):
        from .exit_codes import AuthRequired

        raise AuthRequired("mail list endpoint rejected the session",
                           hint="run --setup to log in again")
    if response.status >= 400:
        raise UiContractError(f"mail list endpoint returned HTTP {response.status}",
                              hint="re-run --discover")
    try:
        payload = response.json()
    except Exception as exc:  # noqa: BLE001
        raise UiContractError("mail list endpoint did not return JSON",
                              hint="re-run --discover") from exc
    headers = _from_json_rows(_find_rows(payload))
    if not headers:
        raise UiContractError("mail list endpoint returned no recognisable mail rows",
                              hint="re-run --discover and update list_api in .local/dooray-ui.json")
    return headers[:limit]


def list_mails_via_dom(session: Session, limit: int) -> list[MailHeader]:
    contract = session.contract
    page = session.page
    try:
        page.wait_for_selector(contract.row, timeout=20_000)
    except Exception as exc:  # noqa: BLE001
        raise UiContractError("no mail rows matched the recorded selector",
                              hint="the mail UI changed; re-run --discover") from exc
    rows = page.query_selector_all(contract.row)[:limit]
    out: list[MailHeader] = []
    for index, row in enumerate(rows):
        try:
            subject_el = row.query_selector(contract.row_subject) if contract.row_subject else None
            subject = (subject_el.inner_text() if subject_el else row.inner_text()) or ""
            subject = " ".join(subject.split())[:300]
            mail_id = ""
            if contract.row_id_attr:
                mail_id = row.get_attribute(contract.row_id_attr) or ""
            if not mail_id:
                # No stable id means we cannot promise idempotency, so refuse.
                raise UiContractError("mail rows carry no stable id attribute",
                                      hint="set row_id_attr in .local/dooray-ui.json via --discover")
            preview = ""
            if contract.row_preview:
                el = row.query_selector(contract.row_preview)
                preview = " ".join((el.inner_text() if el else "").split())[:500]
            received = None
            if contract.row_date:
                el = row.query_selector(contract.row_date)
                received = parse_day(el.inner_text() if el else "")
            unread = None
            if contract.row_unread_marker:
                unread = row.query_selector(contract.row_unread_marker) is not None
            out.append(MailHeader(mail_id=str(mail_id), subject=subject, preview=preview,
                                  received=received, unread=unread))
        except UiContractError:
            raise
        except Exception:  # noqa: BLE001 - one odd row must not kill the scan
            continue
    if not out:
        raise UiContractError("mail rows matched but none could be read",
                              hint="re-run --discover")
    return out


def list_mails(session: Session, limit: int = 100) -> list[MailHeader]:
    contract = session.contract
    contract.require_ready()
    if contract.list_api:
        return list_mails_via_api(session, contract.list_api, limit)
    return list_mails_via_dom(session, limit)


def open_body(session: Session, header: MailHeader) -> str:
    """Load one mail's body. This marks the mail read in the mailbox."""
    contract = session.contract
    if contract.detail_api:
        url = contract.detail_api.replace("{id}", header.mail_id)
        try:
            response = session.page.request.get(url, timeout=30_000)
            if response.status < 400:
                payload = response.json()
                body = _extract_body(payload)
                if body:
                    header.body = body[:_MAX_BODY_CHARS]
                    header.body_opened = True
                    return header.body
        except Exception:  # noqa: BLE001 - fall through to the DOM
            pass
    if not contract.body_container:
        return ""
    try:
        session.page.click(f"{contract.row}[{contract.row_id_attr}='{header.mail_id}']")
        session.page.wait_for_selector(contract.body_container, timeout=20_000)
        text = session.page.inner_text(contract.body_container) or ""
    except Exception:  # noqa: BLE001
        return ""
    header.body = text[:_MAX_BODY_CHARS]
    header.body_opened = bool(header.body)
    return header.body


def _extract_body(payload: Any) -> str:
    """Pull mail text out of an unknown JSON detail envelope."""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        for key in ("body", "content", "text", "html", "mailBody"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value
            if isinstance(value, dict):
                nested = _extract_body(value)
                if nested:
                    return nested
        for key in ("result", "data"):
            if key in payload:
                nested = _extract_body(payload[key])
                if nested:
                    return nested
    return ""
