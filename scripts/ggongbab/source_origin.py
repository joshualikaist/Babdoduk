# -*- coding: utf-8 -*-
"""Where a Dooray collection task really came from (owner decision 2026-10-31).

The Instagram radar (docs/INSTAGRAM_RADAR.md) and the reader tip board hand their owner-confirmed
events to the Dooray collection project through the same task writer as the mail Radar, so the
collector reads them as Dooray items. The public data names such an event after its true origin,
`instagram` (with a link to the post) or `tip` (no link), only when the task carries the whole
marker; anything less stays `dooray`. The raw item keeps its Dooray identity (source type, external
id, merge priority); the origin rides in its metadata and, for a post, in `source_url`.

A marked task must be an agent task (web/task_writer.build_task): an `-----Original Message-----`
block with no sender address, and the `[ggongbab-agent]` line. Then:

* Instagram: the subject is `[인스타 @<handle>] <title>` with <handle> listed in
  inputs/instagram/accounts.json, and the body holds the block the radar writes, a line
  `[인스타그램 @<same handle>…` followed by `원본: https://www.instagram.com/p/<code>/` lines. The
  published link is rebuilt from the first such code, never copied.
* Tip: the subject is `[꽁밥 제보] <title>` and a body line is exactly `제보 ID: <uuid>`.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from .config import ROOT

ACCOUNTS_FILE = ROOT / "inputs" / "instagram" / "accounts.json"
AGENT_LINE = re.compile(r"^\[ggongbab-agent\] collected from the Dooray mailbox", re.M)
INSTAGRAM_SUBJECT = re.compile(r"\[인스타 @([A-Za-z0-9._]{1,30})\] \S.*")
INSTAGRAM_BLOCK = r"^\[인스타그램 @{handle}[ \]].*\n(?:게시: .*\n)?((?:원본: .*(?:\n|$))+)"
PERMALINK = re.compile(r"https://www\.instagram\.com/(p|reel)/([A-Za-z0-9_-]{5,20})/?")
TIP_SUBJECT = re.compile(r"\[꽁밥 제보\] \S.*")
TIP_LINE = re.compile(r"^제보 ID: [0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.M)

# Origins a Dooray item may be published under, and those whose link is public.
ORIGINS = ("instagram", "tip")


@dataclass(frozen=True)
class Origin:
    kind: str          # "instagram" or "tip"
    url: str = ""      # the canonical post link (instagram only)


@lru_cache(maxsize=1)
def instagram_handles(path: Path = ACCOUNTS_FILE) -> frozenset[str]:
    """The followed accounts. A missing or unreadable list trusts no handle (fail closed)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return frozenset(str(a["username"]).lower() for a in data["accounts"] if a.get("username"))
    except (OSError, ValueError, KeyError, TypeError):
        return frozenset()


def instagram_post_url(url: Any) -> str:
    """The canonical `https://www.instagram.com/<p|reel>/<code>/` form of a post link, or ''."""
    match = PERMALINK.fullmatch(url) if isinstance(url, str) else None
    return f"https://www.instagram.com/{match.group(1)}/{match.group(2)}/" if match else ""


def task_origin(subject: str, body: str, *, sender_email: str, header_found: bool,
                handles: Optional[frozenset[str]] = None) -> Optional[Origin]:
    """The true origin of an agent task, or None (it stays a Dooray item)."""
    subject, body = (subject or "").strip(), body or ""
    if not header_found or sender_email or not AGENT_LINE.search(body):
        return None
    match = INSTAGRAM_SUBJECT.fullmatch(subject)
    if match:
        handle = match.group(1)
        if handle.lower() not in (instagram_handles() if handles is None else handles):
            return None
        block = re.search(INSTAGRAM_BLOCK.format(handle=re.escape(handle)), body, re.M)
        for line in (block.group(1).splitlines() if block else []):
            url = instagram_post_url(line[len("원본: "):].strip())
            if url:
                return Origin("instagram", url)
        return None
    if TIP_SUBJECT.fullmatch(subject) and TIP_LINE.search(body):
        return Origin("tip")
    return None


def public_type(source_type: str, metadata: Any, source_url: Any) -> tuple[str, str]:
    """(type, url) a stored raw item is published under: its origin when the collector recorded a
    valid one, otherwise its own source type and URL."""
    origin = metadata.get("origin") if isinstance(metadata, dict) and source_type == "dooray" else None
    if origin == "instagram":
        url = instagram_post_url(source_url)
        return ("instagram", url) if url else (source_type, "")
    if origin == "tip":
        return "tip", ""
    return source_type, source_url if isinstance(source_url, str) else ""
