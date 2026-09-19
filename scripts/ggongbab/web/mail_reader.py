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


def discover(session: Session, out_path: Path, settle_seconds: int = 12) -> dict[str, Any]:
    """Record what the mail page actually does. No content is captured.

    The report holds request shapes and DOM landmark counts only: no response
    bodies, no headers, no cookies, no mail text, no addresses.
    """
    calls: list[dict[str, Any]] = []
    page = session.page

    def on_response(response) -> None:  # noqa: ANN001
        try:
            request = response.request
            if request.resource_type not in ("xhr", "fetch"):
                return
            calls.append({
                "method": request.method,
                "url": redact(response.url),
                "status": response.status,
                "contentType": (response.header_value("content-type") or "").split(";")[0],
            })
        except Exception:  # noqa: BLE001 - discovery must never break the page
            pass

    page.on("response", on_response)
    try:
        page.wait_for_timeout(settle_seconds * 1000)
        try:
            page.mouse.wheel(0, 2000)
            page.wait_for_timeout(2500)
        except Exception:  # noqa: BLE001
            pass
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:  # noqa: BLE001
            pass

    try:
        landmarks = page.evaluate(_LANDMARK_JS)
    except Exception as exc:  # noqa: BLE001
        landmarks = {"error": exc.__class__.__name__}

    seen: set[str] = set()
    unique_calls = []
    for call in calls:
        key = f"{call['method']} {call['url']}"
        if key in seen:
            continue
        seen.add(key)
        unique_calls.append(call)

    report = {
        "recordedAt": datetime.now(KST).isoformat(timespec="seconds"),
        "pageUrl": redact(session.url),
        "note": "Redacted: URL shapes and DOM landmark counts only. No bodies, cookies or mail text.",
        "jsonCalls": [c for c in unique_calls if "json" in (c["contentType"] or "")],
        "otherCalls": [c for c in unique_calls if "json" not in (c["contentType"] or "")][:40],
        "domLandmarks": landmarks,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


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
