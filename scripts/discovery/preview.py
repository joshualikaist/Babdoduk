# -*- coding: utf-8 -*-
"""The publisher's own preview for a published card (docs/MAGAZINE_SOURCES.md).

A card's sentence comes from text the publisher wrote to present the page: a registered feed's
own item text, else the page's og:description, meta description or twitter:description. A web
search result carries the page body, not a preview, and a story its feed no longer lists has no
text left (the store keeps none, decision 6), so once such a story is chosen for the edition this
module reads the publisher's page once for that description:

  - robots.txt of the page's host decides, read once per host and run; one that answers 401/403
    or cannot be read (server error, timeout) counts as a refusal, a missing one (other 4xx) as
    none (the convention of urllib.robotparser)
  - two seconds or more between two requests to one host (common.HostPacer), and a host that
    answers 403 or 429 is not asked again in the run
  - only the page head's description is read; nothing of the page is kept
  - a page that cannot be read leaves the card with title, source, date and link

Nothing is read for a story shown by title and link only (process.excerpt_allowed) or on a host
open discovery may not read (hosts.collectable).
"""
from __future__ import annotations

import html
import re
import urllib.error
import urllib.parse
import urllib.robotparser
from typing import Callable, Iterator, Optional

from .common import UA, is_public_url
from .hosts import collectable
from .select import card_summary, shows_media

META = re.compile(r"<meta\b[^>]*>", re.I)
ATTR = re.compile(r"([a-zA-Z:_-]+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)')")
KEYS = ("og:description", "description", "twitter:description")
CHARSET = re.compile(rb"charset\s*=\s*[\"']?([A-Za-z0-9_-]+)", re.I)
HEAD_CHARS = 400_000
CODECS = {"euc-kr": "cp949", "ks_c_5601-1987": "cp949", "x-windows-949": "cp949"}


def decode(page: bytes) -> str:
    """The page as text in the charset it declares (older Korean news sites use EUC-KR)."""
    found = CHARSET.search(page[:4096])
    name = found.group(1).decode("ascii").lower() if found else "utf-8"
    try:
        return page.decode(CODECS.get(name, name), "replace")
    except LookupError:
        return page.decode("utf-8", "replace")


def description(page: str) -> str:
    """The page's own description from its head: og:description, else meta description, else
    twitter:description; empty when it has none."""
    head = page[:HEAD_CHARS]
    end = re.search(r"</head\s*>", head, re.I)
    head = head[:end.start()] if end else head
    found: dict[str, str] = {}
    for tag in META.findall(head):
        attrs = {m.group(1).lower(): m.group(2) if m.group(2) is not None else m.group(3) for m in ATTR.finditer(tag)}
        key = (attrs.get("property") or attrs.get("name") or "").strip().lower()
        content = (attrs.get("content") or "").strip()
        if key in KEYS and content and key not in found:
            found[key] = html.unescape(content)
    return next((found[key] for key in KEYS if key in found), "")


class Robots:
    """robots.txt per host, read once per run through the same (paced) fetcher."""

    def __init__(self, fetcher: Callable):
        self.fetcher = fetcher
        self.parsers: dict[str, Optional[urllib.robotparser.RobotFileParser]] = {}

    def allowed(self, url: str) -> bool:
        parts = urllib.parse.urlparse(url)
        root = f"{parts.scheme}://{parts.netloc}"
        if root not in self.parsers:
            self.parsers[root] = self._read(root + "/robots.txt")
        parser = self.parsers[root]
        return parser is not None and parser.can_fetch(UA, url)

    def _read(self, robots_url: str) -> Optional[urllib.robotparser.RobotFileParser]:
        parser = urllib.robotparser.RobotFileParser()
        try:
            body = self.fetcher(robots_url, accept="text/plain")
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403) or exc.code >= 500:
                return None
            parser.parse([])                        # no robots.txt: nothing is disallowed
            return parser
        except Exception:  # noqa: BLE001 - unreadable robots.txt: do not read the page
            return None
        parser.parse(decode(body).splitlines())
        return parser


def needs_preview(row: dict) -> bool:
    """A chosen story without the publisher's preview in hand: a web search result (its text is the
    page body), or a story stored without its text whose feed no longer lists it."""
    return shows_media(row) and (row.get("sourceType") == "web_search" or not row.get("sourceExcerpt"))


def _cards(edition: dict) -> Iterator[dict]:
    if edition.get("featured"):
        yield edition["featured"]
    for lane in (edition.get("lanes") or {}).values():
        yield from lane.get("items") or []


def fill(edition: dict, rows: dict, fetcher: Callable, log=print) -> int:
    """Give every chosen card that needs one the publisher's own sentence. `rows` maps candidate
    ids to store rows. Returns how many cards got a sentence."""
    robots, refused, filled = Robots(fetcher), set(), 0
    for card in _cards(edition):
        row = rows.get(card.get("candidateId"))
        if card.get("summary") or row is None or not needs_preview(row):
            continue
        url = card.get("url") or ""
        host = (urllib.parse.urlparse(url).hostname or "").lower()
        if host in refused or not is_public_url(url) or not collectable(url) or not robots.allowed(url):
            continue
        try:
            page = fetcher(url, accept="text/html")
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 429):
                refused.add(host)
            continue
        except Exception:  # noqa: BLE001 - an unreadable page keeps the card without a sentence
            continue
        sentence = card_summary(description(decode(page)), card.get("title") or "")
        if sentence:
            card["summary"] = sentence
            filled += 1
    log(f"magazine previews: {filled} card sentences from publishers' own descriptions")
    return filled
