"""Conservative publication helpers; never serialize arbitrary objects or metadata."""
from __future__ import annotations

import html
import re
from urllib.parse import urlsplit

from .parsers.sanitizer import sanitize_for_ai


def public_text(value) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("PUBLIC_FIELD_NOT_TEXT")
    text = html.unescape(value)
    text = re.sub(r"<[^>]*>", "", text)
    # Links belong only in the separately checked registration/source URL fields.
    text = re.sub(r"(?:https?://|www\.)\S+", "[link]", text, flags=re.I)
    text = re.sub(r"(?:JSESSIONID|pstNo|external_id|mail_id|token|password)\s*[:=]\s*\S+",
                  "[private]", text, flags=re.I)
    text = re.sub(r"sk-[A-Za-z0-9_-]{16,}|eyJ[A-Za-z0-9_.-]{20,}|dooray-api\s+\S+",
                  "[secret]", text, flags=re.I)
    text = re.sub(r"(?<!\d)\d{12,}(?!\d)", "[id]", text)
    return sanitize_for_ai(text)


def public_url(value) -> str:
    """HTTPS links on reviewed public hosts only, without query/fragment material.

    No network resolution/following redirects. Unknown hosts are withheld pending
    review. This deliberately tightens, never broadens, the snapshot URL policy.
    """
    if not isinstance(value, str) or not value or re.search(r"[\s\\<>]", value):
        return ""
    try:
        url = urlsplit(value)
        if (url.scheme != "https" or url.username or url.password or url.port
                or url.query or url.fragment or "%" in value or ";" in value):
            return ""
        if url.hostname in {"forms.gle", "forms.office.com", "forms.microsoft.com"}:
            return value
        if url.hostname == "docs.google.com" and url.path.startswith("/forms/"):
            return value
        if url.hostname in {"www.kaist.ac.kr", "kaist.ac.kr"} and url.path.startswith(("/kr/html/", "/en/html/")):
            return value
    except ValueError:
        pass
    return ""
