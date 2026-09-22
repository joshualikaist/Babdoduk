# -*- coding: utf-8 -*-
"""Mailbox backfill from an exported mail archive.

Why a file archive and not an API: Gov-Dooray's public REST API has no mail
service. Probed read-only on 2026-09-19 (see docs/GGONGBAB_PAGE.md "Mailbox
backfill"): every `/mail/v1/*` path answers 404, while `common`, `project`,
`messenger`, `calendar`, `drive` and `wiki` answer 200, and an unauthenticated
request to an existing route answers 401 instead of 404. `/mail/v1/mails` is 404
on the commercial host too, so the route does not exist in the product's open API
at all. Rather than invent an endpoint, this collector reads what the user can
export from the mail client.

Supported inputs (file, directory, or a mix):
  * `.eml`  - one RFC 5322 message per file (what "save/download mail" produces)
  * `.mbox` - many messages in one file
  * `.zip`  - archive containing any of the above
  * a directory, walked recursively

Read-only in every sense: the mailbox itself is never contacted, so no message
can be marked read, moved or deleted by this code.
"""
from __future__ import annotations

import email
import email.policy
import hashlib
import io
import mailbox
import re
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Iterator, Optional

from ..config import KST, Settings
from ..models import RawAttachment, RawItem
from ..parsers.html_text import html_to_text
from .base import Collector, CollectorError

EML_SUFFIXES = {".eml", ".msg.eml", ".mail"}
MAX_BODY_CHARS = 20000
# mbox/Maildir convention: Status "R" = read, "O" = old (already seen by the client).
_READ_FLAG = re.compile(r"R", re.I)


@dataclass
class MailStats:
    files: int = 0
    messages: int = 0
    skipped_unparsable: int = 0
    out_of_range: int = 0
    filtered_read_state: int = 0


def _decode(value: Optional[str]) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value))).strip()
    except (UnicodeDecodeError, LookupError, ValueError):
        return str(value).strip()


def _received_at(msg: EmailMessage) -> Optional[datetime]:
    raw = msg.get("Date")
    if raw:
        try:
            dt = parsedate_to_datetime(str(raw))
            if dt is not None:
                return (dt if dt.tzinfo else dt.replace(tzinfo=KST)).astimezone(KST)
        except (TypeError, ValueError, IndexError):
            pass
    # Fall back to the timestamp of the topmost Received header.
    received = msg.get_all("Received") or []
    if received:
        tail = str(received[0]).rsplit(";", 1)
        if len(tail) == 2:
            try:
                dt = parsedate_to_datetime(tail[1].strip())
                if dt is not None:
                    return (dt if dt.tzinfo else dt.replace(tzinfo=KST)).astimezone(KST)
            except (TypeError, ValueError, IndexError):
                pass
    return None


def read_state_of(msg: EmailMessage) -> str:
    """'read' | 'unread' | 'unknown'.

    Plain .eml exports usually carry no read flag, so 'unknown' is the honest and
    common answer. Read state is never used to exclude a mail by default.
    """
    status = str(msg.get("Status") or "")
    xstatus = str(msg.get("X-Status") or "")
    if _READ_FLAG.search(status) or _READ_FLAG.search(xstatus):
        return "read"
    if status or xstatus:
        return "unread"
    return "unknown"


def _body_and_attachments(msg: EmailMessage) -> tuple[str, str, list[tuple[str, str, bytes]]]:
    """Return (text, html, [(filename, mime, payload)])."""
    text_parts: list[str] = []
    html_parts: list[str] = []
    files: list[tuple[str, str, bytes]] = []
    if msg.is_multipart():
        walker = msg.walk()
    else:
        walker = iter([msg])
    for part in walker:
        if part.is_multipart():
            continue
        ctype = (part.get_content_type() or "").lower()
        disposition = (part.get_content_disposition() or "").lower()
        filename = _decode(part.get_filename())
        if disposition == "attachment" or (filename and not ctype.startswith("text/")) or ctype.startswith("image/"):
            try:
                payload = part.get_payload(decode=True) or b""
            except Exception:  # noqa: BLE001 - a broken part must not lose the mail
                payload = b""
            if payload:
                files.append((filename or f"part.{ctype.split('/')[-1]}", ctype, payload))
            continue
        try:
            payload = part.get_content()
        except Exception:  # noqa: BLE001
            raw = part.get_payload(decode=True) or b""
            payload = raw.decode(part.get_content_charset() or "utf-8", "replace")
        if ctype == "text/plain":
            text_parts.append(payload)
        elif ctype == "text/html":
            html_parts.append(payload)
    html = "\n".join(html_parts)
    text = "\n".join(text_parts).strip()
    if not text and html:
        text = html_to_text(html)
    return text[:MAX_BODY_CHARS], html[: MAX_BODY_CHARS * 4], files


def _external_id(msg: EmailMessage, raw: bytes) -> str:
    """Stable across re-exports: prefer the RFC Message-ID, else hash the bytes."""
    message_id = _decode(msg.get("Message-ID"))
    if message_id:
        return message_id.strip("<> ")[:250]
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def message_to_raw_item(msg: EmailMessage, raw: bytes, origin: str) -> Optional[RawItem]:
    subject = _decode(msg.get("Subject"))
    received = _received_at(msg)
    text, html, files = _body_and_attachments(msg)
    if not subject and not text:
        return None
    sender = _decode(msg.get("From"))
    sender_email = ""
    match = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", sender)
    if match:
        sender_email = match.group(0)
    sender_name = re.sub(r"<[^>]*>", "", sender).strip().strip('"')

    attachments: list[RawAttachment] = []
    for index, (filename, ctype, payload) in enumerate(files):
        attachments.append(RawAttachment(
            external_file_id=f"{index}:{filename}"[:200],
            filename=filename,
            mime_type=ctype,
            size=len(payload),
            inline=False,
        ))
    item = RawItem(
        source_type="dooray_mailbox",
        external_id=_external_id(msg, raw),
        subject=subject,
        sender_name=sender_name,
        sender_email=sender_email,
        raw_text=text,
        raw_html=html,
        source_url="",
        source_created_at=received,
        metadata={
            "origin": origin,
            "read_state": read_state_of(msg),
            "to_count": len(msg.get_all("To") or []),
            "cc_count": len(msg.get_all("Cc") or []),
            "backfill": True,
        },
        attachments=attachments,
    )
    # Payloads are already in memory; hand them over only if the pipeline asks,
    # so a cached mail costs nothing.
    item.attachment_loader = _loader(item, files)
    return item


def _loader(item: RawItem, files: list[tuple[str, str, bytes]]):
    def load() -> None:
        for att, (_name, ctype, payload) in zip(item.attachments, files):
            att.data = payload
            att.mime_type = ctype
            att.size = len(payload)
            att.compute_sha()
            att.parse_status = "downloaded" if ctype.startswith("image/") else "skipped"
    return load


def iter_messages(path: Path) -> Iterator[tuple[EmailMessage, bytes, str]]:
    """Yield (message, raw_bytes, origin_label) from a file, archive or directory."""
    if path.is_dir():
        for child in sorted(path.rglob("*")):
            if child.is_file():
                yield from iter_messages(child)
        return
    suffix = path.suffix.lower()
    try:
        if suffix == ".zip":
            with zipfile.ZipFile(path) as archive:
                for name in sorted(archive.namelist()):
                    if name.endswith("/"):
                        continue
                    if not name.lower().endswith((".eml", ".mail", ".mbox")):
                        continue
                    data = archive.read(name)
                    if name.lower().endswith(".mbox"):
                        yield from _iter_mbox_bytes(data, f"{path.name}!{name}")
                    else:
                        yield _parse(data), data, f"{path.name}!{name}"
            return
        if suffix == ".mbox":
            box = mailbox.mbox(str(path), factory=None, create=False)
            try:
                for key in box.keys():
                    raw = box.get_bytes(key)
                    yield _parse(raw), raw, f"{path.name}#{key}"
            finally:
                box.close()
            return
        if suffix in EML_SUFFIXES or suffix == "":
            raw = path.read_bytes()
            if raw.lstrip()[:5] == b"From " and raw.count(b"\nFrom ") > 0:
                yield from _iter_mbox_bytes(raw, path.name)
            else:
                yield _parse(raw), raw, path.name
    except (OSError, zipfile.BadZipFile) as exc:
        raise CollectorError(f"cannot read {path.name}: {exc.__class__.__name__}") from exc


def _iter_mbox_bytes(data: bytes, origin: str) -> Iterator[tuple[EmailMessage, bytes, str]]:
    chunks = re.split(rb"(?m)^From .*\r?\n", data)
    for index, chunk in enumerate(chunks):
        if not chunk.strip():
            continue
        yield _parse(chunk), chunk, f"{origin}#{index}"


def _parse(raw: bytes) -> EmailMessage:
    return email.message_from_bytes(raw, policy=email.policy.default)  # type: ignore[return-value]


class MailArchiveCollector(Collector):
    """Reads an exported mail archive. Never contacts the mailbox."""

    source_type = "dooray_mailbox"
    name = "Dooray 메일함"

    def __init__(self, settings: Settings, path: Path, mail_from: Optional[date] = None,
                 mail_to: Optional[date] = None, read_state: str = "all", max_mails: int = 500):
        self.settings = settings
        self.path = Path(path)
        self.mail_from = mail_from
        self.mail_to = mail_to
        self.read_state = read_state
        self.max_mails = max_mails
        self.stats = MailStats()

    def enabled(self) -> bool:
        return self.path.exists()

    def _in_range(self, received: Optional[datetime]) -> bool:
        if self.mail_from is None and self.mail_to is None:
            return True
        if received is None:
            return True  # undated export: let the AI/validator judge the event date
        day = received.astimezone(KST).date()
        if self.mail_from and day < self.mail_from:
            return False
        if self.mail_to and day > self.mail_to:
            return False
        return True

    def _read_state_ok(self, state: str) -> bool:
        if self.read_state == "all":
            return True
        if state == "unknown":
            # The export carries no flag; excluding it would silently drop mail.
            return True
        return state == self.read_state

    def collect(self) -> list[RawItem]:
        if not self.path.exists():
            raise CollectorError(f"mail archive not found: {self.path}")
        items: list[RawItem] = []
        seen: set[str] = set()
        for msg, raw, origin in iter_messages(self.path):
            self.stats.messages += 1
            if self.stats.messages > self.max_mails:
                raise CollectorError(
                    f"archive holds more than --max-mails ({self.max_mails}) messages; "
                    f"narrow --mail-from/--mail-to or raise the limit")
            try:
                item = message_to_raw_item(msg, raw, origin)
            except Exception:  # noqa: BLE001 - one broken message must not stop a backfill
                self.stats.skipped_unparsable += 1
                continue
            if item is None:
                self.stats.skipped_unparsable += 1
                continue
            if not self._in_range(item.source_created_at):
                self.stats.out_of_range += 1
                continue
            if not self._read_state_ok(item.metadata.get("read_state", "unknown")):
                self.stats.filtered_read_state += 1
                continue
            if item.external_id in seen:
                continue           # the same message exported twice
            seen.add(item.external_id)
            items.append(item)
        self.stats.files = 1
        return items
