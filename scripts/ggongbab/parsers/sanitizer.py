# -*- coding: utf-8 -*-
"""Remove personal information before anything is sent to the AI parser.

What is stripped or masked:
  * every e-mail address (KAIST or external, sender/recipient/inline)
  * phone numbers (Korean mobile/landline formats, +82)
  * Dooray member ids / mention markup
  * mail header lines (To/Cc/From/Sent) and signature tails
  * long quoted-reply chains after the first message

What is kept: event title/body, dates, venues, organizer *names of departments or
companies*, food information, registration information and URLs (except mailto:).
"""
from __future__ import annotations

import re

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.I)
_MAILTO = re.compile(r"mailto:[^\s)>\]]+", re.I)
_PHONE = re.compile(
    r"(?<!\d)(?:\+?82[-\s.]?)?(?:0?1[016789]|0?2|0?[3-6]\d|042|044|070|080)[-\s.)]?\d{3,4}[-\s.]?\d{4}(?!\d)"
)
_INTERNAL_EXT = re.compile(r"(?:내선|ext\.?|extension)\s*[:：]?\s*\d{3,5}", re.I)
_DOORAY_MEMBER = re.compile(r"(?:member(?:Id)?|dooray-member)\s*[:=]\s*\d{6,}", re.I)
_MENTION = re.compile(r"@\[[^\]]+\]\(dooray://[^)]+\)")
_DOORAY_URI = re.compile(r"dooray://\S+")
_HEADER_LINE = re.compile(r"^\s*(To|Cc|Bcc|From|Sent|Date|받는\s*사람|참조|숨은\s*참조|보낸\s*사람|보낸\s*날짜)\s*[:：].*$", re.I | re.M)
_SIGNATURE_START = re.compile(
    r"^\s*(?:--\s*$|__+\s*$|Best regards|Kind regards|Sincerely|Thanks(?:,|\s*$)|감사합니다\.?\s*$|드림\s*$|올림\s*$)",
    re.I | re.M,
)
_QUOTE_CHAIN = re.compile(r"(?:^|\n)\s*(?:-{2,}\s*Original Message\s*-{2,}|On .{5,80} wrote:|\d{4}[./-]\d{1,2}[./-]\d{1,2}.{0,40}님이 작성:)", re.I)
_STUDENT_ID = re.compile(r"(?<!\d)20\d{6}(?!\d)")  # KAIST 8-digit student ids like 2024xxxx


def strip_emails(text: str) -> str:
    text = _MAILTO.sub("", text)
    return _EMAIL.sub("[email]", text)


def strip_phones(text: str) -> str:
    text = _PHONE.sub("[phone]", text)
    return _INTERNAL_EXT.sub("[ext]", text)


def strip_dooray_ids(text: str) -> str:
    text = _MENTION.sub("[member]", text)
    text = _DOORAY_URI.sub("", text)
    return _DOORAY_MEMBER.sub("[member]", text)


def strip_headers(text: str) -> str:
    return _HEADER_LINE.sub("", text)


def strip_quote_chain(text: str) -> str:
    """Keep only the first message when the body contains earlier quoted replies."""
    match = _QUOTE_CHAIN.search(text)
    if match and match.start() > 200:
        return text[: match.start()].rstrip()
    return text


def strip_signature(text: str) -> str:
    """Drop a trailing signature block. Only cuts when the remaining body stays substantial."""
    matches = list(_SIGNATURE_START.finditer(text))
    if not matches:
        return text
    cut = matches[-1].start()
    if cut > len(text) * 0.6 and cut > 120:
        return text[:cut].rstrip()
    return text


def sanitize_for_ai(text: str) -> str:
    """Full sanitization pipeline for mail/notice text."""
    if not text:
        return ""
    out = text.replace("\r\n", "\n")
    out = strip_quote_chain(out)
    out = strip_headers(out)
    out = strip_dooray_ids(out)
    out = strip_emails(out)
    out = strip_phones(out)
    out = _STUDENT_ID.sub("[id]", out)
    out = strip_signature(out)
    out = re.sub(r"[ \t]+\n", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def contains_pii(text: str) -> bool:
    """Helper for tests and export validation."""
    if not text:
        return False
    return bool(_EMAIL.search(text) or _PHONE.search(text) or _MENTION.search(text) or _DOORAY_URI.search(text))
