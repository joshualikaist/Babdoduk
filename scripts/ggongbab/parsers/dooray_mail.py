# -*- coding: utf-8 -*-
"""Parse the forwarded-mail block that Dooray automatic classification puts in a task body.

Dooray task `users.from` is the classification bot, not the original sender.
The original sender/date/subject live inside the body:

    -----Original Message-----
    From: "홍길동" <someone@kaist.ac.kr>
    To: ...
    Cc: ...
    Sent: 2026-09-18 14:03 (GMT+09:00)
    Subject: [안내] ...

    <mail body>
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Optional

from ..config import KST

_ORIGINAL_MARK = re.compile(r"-{2,}\s*Original Message\s*-{2,}", re.I)
_HEADER_LINE = re.compile(r"^\s*(From|To|Cc|Sent|Date|Subject|보낸\s*사람|받는\s*사람|참조|보낸\s*날짜|날짜|제목)\s*[:：]\s*(.*)$", re.I)
_HEADER_MAP = {
    "from": "from", "보낸사람": "from",
    "to": "to", "받는사람": "to",
    "cc": "cc", "참조": "cc",
    "sent": "sent", "date": "sent", "보낸날짜": "sent", "날짜": "sent",
    "subject": "subject", "제목": "subject",
}
_ADDR = re.compile(r"([\w.+-]+@[\w-]+(?:\.[\w-]+)+)")
_NAME_ADDR = re.compile(r"""^\s*"?([^"<]*?)"?\s*<\s*([\w.+-]+@[\w-]+(?:\.[\w-]+)+)\s*>\s*$""")
_TZ_PAREN = re.compile(r"\(GMT([+-]\d{1,2}):?(\d{2})\)")


@dataclass
class OriginalMessage:
    sender_name: str = ""
    sender_email: str = ""
    to: list[str] = field(default_factory=list)
    cc: list[str] = field(default_factory=list)
    sent_at: Optional[datetime] = None
    subject: str = ""
    body: str = ""
    found: bool = False


def parse_name_addr(value: str) -> tuple[str, str]:
    value = (value or "").strip()
    match = _NAME_ADDR.match(value)
    if match:
        return match.group(1).strip().strip('"'), match.group(2).strip()
    addr = _ADDR.search(value)
    if addr:
        name = value.replace(addr.group(1), "").strip(" <>\"'")
        return name, addr.group(1)
    return value, ""


def parse_sent(value: str) -> Optional[datetime]:
    value = (value or "").strip()
    if not value:
        return None
    tz_match = _TZ_PAREN.search(value)
    cleaned = _TZ_PAREN.sub("", value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y.%m.%d %H:%M:%S", "%Y.%m.%d %H:%M", "%Y/%m/%d %H:%M"):
        try:
            dt = datetime.strptime(cleaned, fmt)
            return dt.replace(tzinfo=KST)
        except ValueError:
            continue
    try:
        dt = parsedate_to_datetime(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=KST)
        return dt
    except (TypeError, ValueError, IndexError):
        pass
    match = re.search(r"(\d{4})[.\-/년]\s*(\d{1,2})[.\-/월]\s*(\d{1,2})\D*(\d{1,2}):(\d{2})", cleaned)
    if match:
        y, mo, d, h, mi = (int(x) for x in match.groups())
        try:
            return datetime(y, mo, d, h, mi, tzinfo=KST)
        except ValueError:
            return None
    if tz_match:
        return None
    return None


def parse_original_message(text: str) -> OriginalMessage:
    """Extract the original mail header block and body from Dooray task text."""
    result = OriginalMessage()
    if not text:
        return result
    marker = _ORIGINAL_MARK.search(text)
    if not marker:
        result.body = text.strip()
        return result
    result.found = True
    after = text[marker.end():].lstrip("\n")
    lines = after.splitlines()
    idx = 0
    headers: dict[str, str] = {}
    last_key: Optional[str] = None
    while idx < len(lines):
        line = lines[idx]
        if not line.strip():
            # a blank line ends the header block once we've seen at least one header
            if headers:
                idx += 1
                break
            idx += 1
            continue
        match = _HEADER_LINE.match(line)
        if match:
            key = _HEADER_MAP.get(re.sub(r"\s+", "", match.group(1)).lower())
            if key:
                headers[key] = match.group(2).strip()
                last_key = key
                idx += 1
                continue
        if last_key in {"to", "cc"} and headers:
            # continuation of a long recipient list
            headers[last_key] += " " + line.strip()
            idx += 1
            continue
        break
    result.body = "\n".join(lines[idx:]).strip()
    name, email = parse_name_addr(headers.get("from", ""))
    result.sender_name = name
    result.sender_email = email
    result.to = _ADDR.findall(headers.get("to", ""))
    result.cc = _ADDR.findall(headers.get("cc", ""))
    result.sent_at = parse_sent(headers.get("sent", ""))
    result.subject = headers.get("subject", "").strip()
    return result
