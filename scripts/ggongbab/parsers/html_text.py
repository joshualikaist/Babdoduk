# -*- coding: utf-8 -*-
"""HTML -> plain text conversion that keeps line structure (stdlib only)."""
from __future__ import annotations

import html as htmlmod
import re

_BLOCK_TAGS = r"p|div|br|li|tr|h[1-6]|table|ul|ol|blockquote|section|article|header|footer|pre"
_INLINE_FILE_IMG = re.compile(r"""<img[^>]+src=["']([^"']*/files/([A-Za-z0-9_-]+)[^"']*)["'][^>]*>""", re.I)


def inline_file_ids(html: str) -> list[str]:
    """Return Dooray file ids referenced as <img src="/files/{id}"> inside the body."""
    ids: list[str] = []
    for match in _INLINE_FILE_IMG.finditer(html or ""):
        file_id = match.group(2)
        if file_id and file_id not in ids:
            ids.append(file_id)
    return ids


def html_to_text(html: str) -> str:
    if not html:
        return ""
    text = html
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<\s*br\s*/?\s*>", "\n", text, flags=re.I)
    text = re.sub(rf"</\s*(?:{_BLOCK_TAGS})\s*>", "\n", text, flags=re.I)
    text = re.sub(rf"<\s*(?:{_BLOCK_TAGS})(\s[^>]*)?>", "\n", text, flags=re.I)
    text = re.sub(r"<\s*td[^>]*>", " ", text, flags=re.I)
    # keep href targets so registration URLs survive when anchor text is a label
    text = re.sub(r"""<a[^>]+href=["'](https?://[^"']+)["'][^>]*>(.*?)</a>""",
                  lambda m: f"{m.group(2)} ({m.group(1)})" if m.group(1) not in m.group(2) else m.group(2),
                  text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = htmlmod.unescape(text)
    text = text.replace("\xa0", " ").replace("​", "")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    out: list[str] = []
    blank = 0
    for line in lines:
        if not line:
            blank += 1
            if blank <= 1:
                out.append("")
            continue
        blank = 0
        out.append(line)
    return "\n".join(out).strip()
