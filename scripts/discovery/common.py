# -*- coding: utf-8 -*-
"""Shared helpers: clock, polite fetch, text cleaning, URL normalization, atomic writes."""
from __future__ import annotations

import hashlib
import html
import ipaddress
import json
import os
import re
import ssl
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

KST = timezone(timedelta(hours=9))
UA = "BabdodukMagazine/2.0 (+https://github.com/joshualikaist/Babdoduk)"
MAX_BYTES = 3_000_000
YT_ID = re.compile(r"(?:youtu\.be/|v=|shorts/|embed/)([A-Za-z0-9_-]{11})")
TRACKING = re.compile(r"^(utm_|fbclid$|gclid$|igshid$|si$|feature$|ref$|ref_src$|spm$|mc_)", re.I)
EMOJI = re.compile(r"[\U0001F300-\U0001FAFF\U00002700-\U000027BF\U0001F000-\U0001F2FF]+")


def now_kst() -> datetime:
    return datetime.now(KST)


def iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.astimezone(KST).isoformat(timespec="seconds") if dt else None


def parse_time(value) -> Optional[datetime]:
    """RFC 822 (RSS), ISO 8601 (Atom/YouTube) or None."""
    if not value:
        return None
    text = str(value).strip()
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    from email.utils import parsedate_to_datetime
    try:
        dt = parsedate_to_datetime(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError, IndexError):
        return None


def fetch(url: str, *, timeout: int = 20, accept: str = "*/*", headers: Optional[dict] = None) -> bytes:
    """GET a public http(s) URL with a size cap. Raises on HTTP or transport errors."""
    if not is_public_url(url):
        raise ValueError("not a public http(s) URL")
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept, **(headers or {})})
    with urllib.request.urlopen(request, timeout=timeout, context=ssl.create_default_context()) as res:
        return res.read(MAX_BYTES)


def is_public_url(url: str) -> bool:
    """http(s) only; no credentials, no loopback/private/link-local hosts, no KAIST private
    services or Dooray. Guards every server-side fetch and every third-party reader call."""
    try:
        parsed = urllib.parse.urlparse(url or "")
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        return False
    host = parsed.hostname.lower()
    if host in ("localhost",) or host.endswith((".local", ".internal", ".invalid", ".lan")):
        return False
    if "dooray" in host or host in ("portal.kaist.ac.kr", "sso.kaist.ac.kr", "klms.kaist.ac.kr"):
        return False
    try:
        address = ipaddress.ip_address(host)
        if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved:
            return False
    except ValueError:
        pass
    return True


def clean_text(raw: str) -> str:
    """Plain text from feed HTML: unescape (feeds often escape twice), drop tags and emoji."""
    text = html.unescape(html.unescape(raw or ""))
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = EMOJI.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def canonical_url(url: str) -> str:
    """Scheme/host lower-cased, www. and fragments dropped, tracking parameters removed,
    trailing slash normalized. YouTube watch/short/youtu.be forms become one watch URL."""
    if not url:
        return ""
    vid = youtube_id(url)
    if vid:
        return f"https://www.youtube.com/watch?v={vid}"
    try:
        p = urllib.parse.urlparse(url.strip())
    except ValueError:
        return ""
    host = (p.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host.startswith("m.") and host.endswith(("blog.naver.com", "tistory.com")):
        host = host[2:]
    query = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=False) if not TRACKING.match(k)]
    path = re.sub(r"/+$", "", p.path) or "/"
    return urllib.parse.urlunparse(("https", host, path, "", urllib.parse.urlencode(sorted(query)), ""))


def youtube_id(url: str) -> str:
    match = YT_ID.search(url or "")
    return match.group(1) if match else ""


def normalize_title(title: str) -> str:
    text = clean_text(title).lower()
    text = re.sub(r"\[[^\]]*\]|\([^)]*\)|#\S+", " ", text)
    return re.sub(r"[^0-9a-z가-힣]+", "", text)


def trigrams(text: str) -> set[str]:
    return {text[i:i + 3] for i in range(max(0, len(text) - 2))} or ({text} if text else set())


def title_similarity(a: str, b: str) -> float:
    x, y = trigrams(normalize_title(a)), trigrams(normalize_title(b))
    if not x or not y:
        return 0.0
    return len(x & y) / len(x | y)


def sha(text: str, n: int = 16) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:n]


def excerpt(text: str, limit: int = 140) -> str:
    """A verbatim prefix of the source text, cut at a sentence or word boundary. Never adds words."""
    body = clean_text(text)
    if len(body) <= limit:
        return body
    cut = body[:limit]
    for mark in (". ", "다. ", "요. ", "! ", "? ", "。"):
        at = cut.rfind(mark)
        if at >= limit * 0.5:
            return cut[:at + len(mark)].strip()
    at = cut.rfind(" ")
    return (cut[:at] if at >= limit * 0.5 else cut).rstrip(" ,.;:") + "…"


def atomic_write(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".disc-", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def dump_json(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def read_json(path: Path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
