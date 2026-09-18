# -*- coding: utf-8 -*-
"""KAIST public notice collector.

Only publicly reachable official KAIST pages are used (no login). Markup was
verified against the live site on 2026-09-19:

* 학사공지  https://www.kaist.ac.kr/kr/html/footer/0802.html
    list rows:  <tr id='BBSList{hash}'> <td class=title><a href='?mode=V&no={hash}&GotoPage=1'>title</a>
                <td class=reg_date>YYYY-MM-DD</td>
    detail:     ?mode=V&no={hash}   body in <div class="ui bbs--view--content">
* 문화행사  https://www.kaist.ac.kr/kr/html/campus/053501.html
    cards:      <strong class="ui-list__title">title</strong> + <ul class="list-1st"> (장소/일시/시간 ...)
                <a class="btn" href="/kr/html/campus/053501.html?mode=V&mng_no=NNNN">
    detail:     ?mode=V&mng_no=NNNN   body in <div class="ui bbs--view--content">

Detail pages are fetched only for entries whose title matches the event
keyword set; the body is then pre-filtered with the food keyword set, so
unrelated notices never reach the AI parser.
"""
from __future__ import annotations

import html as htmlmod
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Optional

from ..config import KST, Settings
from ..models import RawItem
from ..parsers.html_text import html_to_text
from ..parsers.rule_parser import _EVENT_WORDS, _FOOD_WORDS
from .base import Collector, CollectorError

UA = "BabdodukGgongbab/1.0 (+https://github.com/joshualikaist/Babdoduk)"
_FOOD_RE = re.compile(_FOOD_WORDS, re.I)

BOARDS = [
    {"key": "kaist-0802", "name": "KAIST 학사공지", "url": "https://www.kaist.ac.kr/kr/html/footer/0802.html", "kind": "table"},
    {"key": "kaist-053501", "name": "KAIST 문화행사", "url": "https://www.kaist.ac.kr/kr/html/campus/053501.html", "kind": "card"},
]

_TABLE_ROW = re.compile(
    r"<tr[^>]*id=['\"]BBSList(?P<hash>[0-9a-f]{16,})['\"][^>]*>(?P<row>.*?)</tr>", re.S | re.I)
_TABLE_TITLE = re.compile(r"<td[^>]*class=['\"]?title[^>]*>.*?<a[^>]*href=['\"](?P<href>[^'\"]+)['\"][^>]*>(?P<title>.*?)</a>", re.S | re.I)
_TABLE_DATE = re.compile(r"<td[^>]*class=['\"]?reg_date[^>]*>\s*(\d{4}-\d{2}-\d{2})", re.S | re.I)
_CARD = re.compile(r"<div class=\"item\">(?P<card>.*?)<a class=\"btn\" href=\"(?P<href>[^\"]*mng_no=(?P<id>\d+)[^\"]*)\"", re.S | re.I)
_CARD_TITLE = re.compile(r"<strong class=\"ui-list__title\">(.*?)</strong>", re.S | re.I)
_CARD_META = re.compile(r"<li><em>(.*?)</em><span>(.*?)</span></li>", re.S | re.I)
_VIEW_CONTENT = re.compile(r"<div class=\"ui bbs--view--content\">(?P<body>.*?)</div>\s*</div>\s*</div>", re.S | re.I)
_VIEW_CONTENT_LOOSE = re.compile(r"<div class=\"ui bbs--view--content\">(?P<body>.*)", re.S | re.I)


def _fetch(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
    with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as res:
        raw = res.read()
    charset = "utf-8"
    ctype = res.headers.get("Content-Type", "")
    match = re.search(r"charset=([\w-]+)", ctype, re.I) or re.search(rb"charset=[\"']?([\w-]+)", raw[:4000], re.I)
    if match:
        charset = match.group(1) if isinstance(match.group(1), str) else match.group(1).decode("ascii", "ignore")
    return raw.decode(charset or "utf-8", errors="replace")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", htmlmod.unescape(re.sub(r"<[^>]+>", " ", text or ""))).strip()


def extract_view_body(page: str) -> str:
    match = _VIEW_CONTENT.search(page) or _VIEW_CONTENT_LOOSE.search(page)
    if not match:
        return ""
    body = match.group("body")
    # stop at the page controls that follow the article body
    for marker in ("content_controll", "controll_wrap", "bbs--view--foot", "<footer"):
        idx = body.find(marker)
        if idx > 0:
            body = body[:idx]
    return body


def parse_table_list(page: str, base_url: str) -> list[dict[str, str]]:
    entries = []
    for row in _TABLE_ROW.finditer(page):
        title_m = _TABLE_TITLE.search(row.group("row"))
        if not title_m:
            continue
        date_m = _TABLE_DATE.search(row.group("row"))
        href = htmlmod.unescape(title_m.group("href"))
        entries.append({
            "id": row.group("hash"),
            "title": _clean(title_m.group("title")),
            "url": urllib.parse.urljoin(base_url, href),
            "date": date_m.group(1) if date_m else "",
            "meta": "",
        })
    return entries


def parse_card_list(page: str, base_url: str) -> list[dict[str, str]]:
    entries = []
    for card in _CARD.finditer(page):
        title_m = _CARD_TITLE.search(card.group("card"))
        meta_lines = [f"{_clean(k)}: {_clean(v)}" for k, v in _CARD_META.findall(card.group("card"))]
        entries.append({
            "id": card.group("id"),
            "title": _clean(title_m.group(1)) if title_m else "",
            "url": urllib.parse.urljoin(base_url, htmlmod.unescape(card.group("href"))),
            "date": "",
            "meta": "\n".join(meta_lines),
        })
    return entries


def _posted(value: str) -> Optional[datetime]:
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=KST)
    except ValueError:
        return None


class KaistPublicCollector(Collector):
    source_type = "kaist_public"
    name = "KAIST 공지"

    def __init__(self, settings: Settings, boards: Optional[list[dict[str, str]]] = None, fetch=_fetch):
        self.settings = settings
        self.boards = boards or BOARDS
        self.fetch = fetch

    def enabled(self) -> bool:
        return self.settings.kaist_public_enabled

    def collect(self) -> list[RawItem]:
        items: list[RawItem] = []
        failures = 0
        for board in self.boards:
            try:
                page = self.fetch(board["url"])
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                failures += 1
                print(f"[warn] kaist_public {board['key']}: {exc.__class__.__name__}")
                continue
            entries = parse_table_list(page, board["url"]) if board["kind"] == "table" else parse_card_list(page, board["url"])
            for entry in entries[: self.settings.kaist_public_max_items]:
                haystack = f"{entry['title']}\n{entry['meta']}"
                if not _EVENT_WORDS.search(haystack) and not _FOOD_RE.search(haystack):
                    continue
                try:
                    detail = self.fetch(entry["url"])
                except (urllib.error.URLError, TimeoutError, OSError) as exc:
                    print(f"[warn] kaist_public detail {entry['id'][:8]}: {exc.__class__.__name__}")
                    continue
                body_html = extract_view_body(detail)
                text = html_to_text(body_html)
                if entry["meta"]:
                    text = entry["meta"] + "\n\n" + text
                full = f"{entry['title']}\n{text}"
                if not (_EVENT_WORDS.search(full) and _FOOD_RE.search(full)):
                    continue
                items.append(RawItem(
                    source_type="kaist_public",
                    external_id=f"{board['key']}:{entry['id']}",
                    subject=entry["title"],
                    raw_text=text,
                    raw_html=body_html,
                    source_url=entry["url"],
                    source_created_at=_posted(entry["date"]) if entry["date"] else None,
                    metadata={"board": board["key"], "board_name": board["name"]},
                ))
        if failures and failures == len(self.boards):
            raise CollectorError("all KAIST public boards failed")
        return items
