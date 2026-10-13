# -*- coding: utf-8 -*-
"""Read one Dooray mail in full for the Radar: body, attachment text and poster images.

Owner decision 2026-10-14 (two missed events: food only in a poster, a prize draw without food):
every new mail is opened, unread ones too. Opening a mail (the detail GET) marks it read in the
mailbox, verified on the live tenant, so an unread mail is marked unread again afterwards with the
web app's own call, `POST <mails>/unread {"mailIdList": [id]}`. If that restore fails the caller
fails closed (UnreadRestoreFailed): no further unread mail is opened until an operator looks.

Only GETs of this one mail (detail, its attachment parts, its same-host inline images) and that
restore POST are sent. Images hosted elsewhere are never fetched: a third-party image in a mail is
often a read-tracking pixel. Nothing is written to disk; the text and images live in memory for the
prefilter and, for a candidate, go into its collection task.
"""
from __future__ import annotations

import hashlib
import json
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional
from urllib.parse import urljoin, urlparse

from ..parsers.attachment_text import (IMAGE_EXTENSIONS, TEXT_EXTENSIONS, extension, extract, image_mime,
                                       normalize_image)
from .mail_reader import detail_body
from .read_state import path_value

FILE_LIST_PATH = "result.content.fileList"
BODY_HTML_MAX = 400_000
TEXT_FILE_MAX_BYTES = 15 * 1024 * 1024
IMAGE_FILE_MAX_BYTES = 6 * 1024 * 1024
MIN_IMAGE_BYTES = 8 * 1024          # icons, signatures and spacer images are smaller
MAX_TEXT_FILES = 4
MAX_IMAGE_DOWNLOADS = 6
MAX_IMAGES = 3                      # posters kept for the task (the AI reads the first ones)
BODY_CHARS = 12_000
ATTACHMENT_CHARS = 8_000
_IMG_SRC = re.compile(r"""<img\b[^>]*?\bsrc\s*=\s*["']([^"']+)["']""", re.I)


class MailUnavailable(Exception):
    """The detail could not be read (deleted or moved since the listing, server error)."""


class UnreadRestoreFailed(Exception):
    """An unread mail was opened and could not be marked unread again."""


@dataclass
class OpenedMail:
    body: str = ""
    attachment_texts: list[tuple[str, str]] = field(default_factory=list)   # (label, text)
    images: list[tuple[str, bytes]] = field(default_factory=list)           # (mime, data), loaded on demand
    image_refs: list[tuple[str, str, int]] = field(default_factory=list)    # (kind, url, size)
    page_images: list[tuple[str, bytes]] = field(default_factory=list)      # rendered poster documents
    statuses: dict[str, int] = field(default_factory=dict)
    restored: Optional[bool] = None    # None: the mail was already read

    def count(self, status: str) -> None:
        self.statuses[status] = self.statuses.get(status, 0) + 1

    @property
    def image_count(self) -> int:
        """Images known without downloading: attachments, same-host inline images, poster pages."""
        return len(self.image_refs) + len(self.page_images)

    def filter_text(self) -> str:
        return "\n\n".join([self.body] + [text for _, text in self.attachment_texts])

    def task_body(self) -> str:
        """The body for the collection task: the mail text, then each attachment's text under a
        label that carries no file name (names can hold personal names)."""
        parts = [self.body[:BODY_CHARS]]
        budget = ATTACHMENT_CHARS
        for label, text in self.attachment_texts:
            if budget <= 0:
                break
            chunk = text[:budget]
            budget -= len(chunk)
            parts.append(f"[{label}]\n{chunk}")
        return "\n\n".join(p for p in parts if p.strip())


def mails_base(detail_api: str) -> str:
    """https://host/v2/wapi/mails from the calibrated detail URL template."""
    return detail_api.split("{id}", 1)[0].rstrip("/")


def restore_unread(page, contract, mail_id: str) -> bool:
    try:
        response = page.request.post(f"{mails_base(contract.detail_api)}/unread",
                                     data=json.dumps({"mailIdList": [mail_id]}),
                                     headers={"Content-Type": "application/json"}, timeout=30_000)
        if response.status >= 400:
            return False
        header = (response.json() or {}).get("header") or {}
        return header.get("isSuccessful") is not False
    except Exception:  # noqa: BLE001 - any failure is a failed restore
        return False


def _get(page, url: str, max_bytes: int) -> bytes:
    response = page.request.get(url, timeout=60_000)
    if response.status >= 400:
        raise MailUnavailable(f"HTTP {response.status}")
    body = response.body()
    if len(body) > max_bytes:
        raise MailUnavailable("too large")
    return body


def _same_host(url: str, host: str) -> Optional[str]:
    parsed = urlparse(url)
    if parsed.scheme in ("", "https") and parsed.netloc in ("", host) and parsed.path.startswith("/"):
        return urljoin(f"https://{host}/", url)
    return None


def read_mail(page, contract, mail_id: str, host: str) -> OpenedMail:
    """Detail, body text, attachment text and the list of images. Raises MailUnavailable."""
    try:
        response = page.request.get(contract.detail_api.replace("{id}", mail_id), timeout=30_000)
    except Exception as exc:  # noqa: BLE001
        raise MailUnavailable(exc.__class__.__name__) from None
    if response.status >= 400:
        raise MailUnavailable(f"HTTP {response.status}")
    try:
        payload = response.json()
    except Exception:  # noqa: BLE001
        raise MailUnavailable("not JSON") from None
    mail = OpenedMail(body=detail_body(payload, contract.detail_body_path))
    html = path_value(payload, contract.detail_body_path) if contract.detail_body_path else ""
    html = html if isinstance(html, str) else ""

    text_files = 0
    for index, entry in enumerate(_file_list(payload), start=1):
        name, size = str(entry.get("name") or ""), int(entry.get("size") or 0)
        ext = (str(entry.get("extension") or "") or extension(name)).lower()
        url = _same_host(str(entry.get("downloadUrl") or ""), host)
        if not url or entry.get("deleted") or entry.get("encrypted") or entry.get("bigfile") or entry.get("driveLink"):
            mail.count("file-skipped")
            continue
        if ext in IMAGE_EXTENSIONS:
            if MIN_IMAGE_BYTES <= size <= IMAGE_FILE_MAX_BYTES or not size:
                mail.image_refs.append(("attachment", url, size))
            continue
        if ext not in TEXT_EXTENSIONS or text_files >= MAX_TEXT_FILES or size > TEXT_FILE_MAX_BYTES:
            mail.count("file-skipped")
            continue
        text_files += 1
        try:
            data = _get(page, url, TEXT_FILE_MAX_BYTES)
        except Exception:  # noqa: BLE001
            mail.count("file-download-failed")
            continue
        result = extract(name or f"file.{ext}", data)
        mail.count(f"file-{result.status}")
        if result.text:
            mail.attachment_texts.append((f"첨부 {index} · {ext.upper()} 본문", result.text))
        mail.page_images.extend(result.images)

    seen: set[str] = {url for _, url, _ in mail.image_refs}
    for src in _IMG_SRC.findall(html[:BODY_HTML_MAX]):
        url = _same_host(src, host)
        if url is None:
            if src.startswith(("http://", "https://")):
                mail.count("external-image-skipped")
            continue
        if url not in seen:
            seen.add(url)
            mail.image_refs.append(("inline", url, 0))
    return mail


def load_images(page, mail: OpenedMail) -> list[tuple[str, bytes]]:
    """Download and shrink up to MAX_IMAGES posters: attachments first (largest first), then inline
    images, after any rendered poster document. Duplicates and icons are dropped."""
    refs = sorted(mail.image_refs, key=lambda ref: (ref[0] != "attachment", -ref[2]))
    found: list[tuple[str, bytes]] = list(mail.page_images)
    digests = {hashlib.sha256(data).hexdigest() for _, data in found}
    for _, url, _ in refs[:MAX_IMAGE_DOWNLOADS]:
        if len(found) >= MAX_IMAGES:
            break
        try:
            data = _get(page, url, IMAGE_FILE_MAX_BYTES)
        except Exception:  # noqa: BLE001
            mail.count("image-download-failed")
            continue
        mime = image_mime(data)
        digest = hashlib.sha256(data).hexdigest()
        if not mime or len(data) < MIN_IMAGE_BYTES or digest in digests:
            continue
        digests.add(digest)
        found.append(normalize_image(mime, data))
    mail.images = found[:MAX_IMAGES]
    return mail.images


@contextmanager
def opened_mail(page, contract, mail_id: str, host: str, *, unread: bool) -> Iterator[OpenedMail]:
    """Read a mail; an unread one is marked unread again when the block ends, after any image
    download, whatever happened inside. Raises UnreadRestoreFailed when that is not possible."""
    mail: Optional[OpenedMail] = None
    try:
        mail = read_mail(page, contract, mail_id, host)
        yield mail
    finally:
        if unread:
            ok = restore_unread(page, contract, mail_id)
            if mail is not None:
                mail.restored = ok
            if not ok:
                raise UnreadRestoreFailed()


class MailOpener:
    """What the Radar calls: open(session, header) and images(session, mail)."""

    def __init__(self, mail_host: str):
        self.mail_host = mail_host

    def open(self, session, header):
        return opened_mail(session.page, session.contract, header.mail_id, self.mail_host, unread=bool(header.unread))

    def images(self, session, mail: OpenedMail) -> list[tuple[str, bytes]]:
        return load_images(session.page, mail)


def _file_list(payload: Any) -> list[dict]:
    files = path_value(payload, FILE_LIST_PATH)
    return [f for f in files if isinstance(f, dict)] if isinstance(files, list) else []
