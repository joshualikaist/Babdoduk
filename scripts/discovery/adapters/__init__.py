# -*- coding: utf-8 -*-
"""Discovery adapters. Each takes one registry source and returns an AdapterResult with raw
items (verbatim source text, never generated), a status and a fixed failure code."""
from __future__ import annotations

from dataclasses import dataclass, field

OK = "OK"
FETCH_FAILED = "FETCH_FAILED"
PARSE_FAILED = "PARSE_FAILED"
NOT_CONFIGURED = "NOT_CONFIGURED"


@dataclass
class AdapterResult:
    status: str
    items: list = field(default_factory=list)
    code: str = ""
    queries: list = field(default_factory=list)


def failure_code(exc: Exception) -> str:
    """A fixed code, never the exception text (workflow logs of this repository are public)."""
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return f"HTTP_{code}"
    name = exc.__class__.__name__
    return {"URLError": "NETWORK", "TimeoutError": "TIMEOUT", "timeout": "TIMEOUT",
            "ParseError": "PARSE", "ValueError": "INVALID"}.get(name, name.upper()[:24])


def run(source: dict, *, fetcher, env) -> AdapterResult:
    from . import instagram, rss, web, youtube
    method = source.get("type")
    if method == "rss":
        return rss.discover(source, fetcher=fetcher)
    if method == "youtube_channel":
        return youtube.discover_channel(source, fetcher=fetcher)
    if method == "youtube_search":
        return youtube.discover_search(source, fetcher=fetcher, env=env)
    if method == "web_search":
        return web.discover(source, fetcher=fetcher, env=env)
    if method == "instagram":
        return instagram.discover(source)
    return AdapterResult(NOT_CONFIGURED, code="UNKNOWN_TYPE")
