# -*- coding: utf-8 -*-
"""Public web discovery through Exa (Agent Reach's semantic-search route) with page reading.

Route, in order:
  EXA_API_KEY set          Exa's REST search API with page text (optional; not required)
  otherwise                Exa's hosted MCP server, no key (web_search_exa + web_fetch_exa)
  BABDODUK_EXA_MCP=0       disabled (NOT_CONFIGURED)

A result is kept only with source text that was actually retrieved: the page text from
web_fetch_exa, else Jina Reader (r.jina.ai, public pages only), else the search highlights,
which are verbatim passages of the same page. The date comes from the search or page
metadata, else the page's own printed date near its top (publishedAtSource says which).
Trust tier and medium come from the result's host (discovery.hosts), never from the route:
a Naver blog is Tier C even when found by a news query. `site:blog.naver.com` in a query
restricts the MCP route through the query itself and the REST route through includeDomains.

Search is discovery only. Result order is Exa's, never presented as Naver's or anyone's
ranking, and nothing is written about a page beyond its own title and text.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from datetime import datetime, timedelta
from typing import Optional

from ..common import KST, UA, canonical_url, clean_text, is_public_url, parse_time
from ..hosts import classify_host, split_title
from . import FETCH_FAILED, NOT_CONFIGURED, OK, AdapterResult, failure_code
from .exa_mcp import ExaMCP, MCPError

EXA_URL = "https://api.exa.ai/search"
JINA_URL = "https://r.jina.ai/"
PER_QUERY = 6
PAGE_CHARS = 5000
MIN_TEXT = 120
JINA_PER_SOURCE = 8
FETCH_BATCH = 10            # pages per web_fetch_exa call: one run stays near 30 calls to the free server
DEFAULT_OBJECTIVE = ("Public Korean or international pages about food: news, reports, research or blog posts. "
                     "Exclude shopping and product listing pages.")
PAGE_DATE = re.compile(r"(20\d{2})\s*(?:[.\-/]|년)\s*(\d{1,2})\s*(?:[.\-/]|월)\s*(\d{1,2})")
DROP_LINE = re.compile(
    r"^\s*(!\[|\[!\[|(입력|수정|승인|등록|업데이트)\s*:?\s*20\d\d|.*기자\s*(구독|$)|.*구독하기|(/)?\s*(사진|그래픽|자료|영상)\s*=|"
    r".*/사진=|.*무단\s*전재|.*재배포\s*금지|.*copyright|.*ⓒ|.*©|.*저작권자|▶|※|좋아요|댓글|공유하기|기사\s*읽어주기|"
    r"글자\s*크기|advertisement|subscribe|sign up|cookie|이 블로그|블로그 메뉴|본문 바로가기|목록\s*열기)", re.I)
MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
BARE_URL = re.compile(r"https?://\S+")


def split_site(query: str) -> tuple[str, list[str]]:
    domains = re.findall(r"site:(\S+)", query)
    return re.sub(r"site:\S+", " ", query).strip(), domains


def expand(query: str, now: Optional[datetime]) -> str:
    """Query templates: {year} and {month} are the run's KST date, so an authored query never
    goes stale ("{year} {month}월 편의점 신상")."""
    when = (now or datetime.now(KST)).astimezone(KST)
    return query.replace("{year}", str(when.year)).replace("{month}", str(when.month))


def page_date(raw: str, now: Optional[datetime] = None) -> Optional[datetime]:
    """The first plausible date printed near the top of the page (a byline or a post date)."""
    for match in PAGE_DATE.finditer((raw or "")[:900]):
        year, month, day = (int(g) for g in match.groups())
        try:
            when = datetime(year, month, day, 12, 0, tzinfo=KST)
        except ValueError:
            continue
        if year >= 2015 and (now is None or when <= now + timedelta(days=1)):
            return when
    return None


def clean_page(raw: str, title: str = "") -> tuple[str, str]:
    """(body text, excerpt paragraph) from page markdown: bylines, captions, image lines,
    link targets, headings that repeat the title and page chrome are dropped."""
    paragraphs, body = [], []
    head = (title or "").strip().lower()
    for line in (raw or "").splitlines():
        text = MD_LINK.sub(r"\1", line).strip()
        text = BARE_URL.sub("", text).strip().lstrip(">").strip()
        if not text or DROP_LINE.match(text):
            continue
        heading = text.startswith("#")
        text = text.lstrip("#").strip()
        low = text.lower()
        if not text or (head and (low == head or head.startswith(low) or low.startswith(head))):
            continue
        if not re.search(r"[0-9A-Za-z가-힣]", text):
            continue
        body.append(text)
        if not heading and len(text) >= 40 and re.search(r"(다|요|죠|음|니다|[.!?])[\"'”’)]?\s*$", text):
            paragraphs.append(text)
    return clean_text("\n".join(body)), (paragraphs[0] if paragraphs else "")


def jina_read(url: str, fetcher) -> str:
    """Public pages only; the guard runs before anything is sent to the third-party reader."""
    if not is_public_url(url):
        return ""
    return clean_text(fetcher(JINA_URL + url, accept="text/plain").decode("utf-8", "replace"))[:4000]


def jina_page(url: str, fetcher) -> dict:
    """{"published", "raw"} from Jina Reader's text output (public pages only)."""
    if not is_public_url(url):
        return {}
    text = fetcher(JINA_URL + url, accept="text/plain").decode("utf-8", "replace")
    match = re.search(r"^Published Time:\s*(\S+)", text, re.M)
    raw = text.split("Markdown Content:", 1)[1] if "Markdown Content:" in text else text
    return {"published": match.group(1) if match else None, "raw": raw[:PAGE_CHARS * 2]}


def exa_search(query: str, key: str, opener=urllib.request.urlopen) -> list[dict]:
    text, domains = split_site(query)
    body = {"query": text, "numResults": PER_QUERY, "type": "auto",
            "contents": {"text": {"maxCharacters": 3000}}}
    if domains:
        body["includeDomains"] = domains
    request = urllib.request.Request(EXA_URL, data=json.dumps(body).encode("utf-8"), method="POST",
                                     headers={"x-api-key": key, "Content-Type": "application/json", "User-Agent": UA})
    with opener(request, timeout=30) as res:
        return json.loads(res.read().decode("utf-8")).get("results") or []


def build_item(hit_url: str, title: str, *, published, published_source: str, raw_page: str, highlights: str,
               query: str, lane: Optional[str], rank: int, method: str, now: Optional[datetime]) -> dict:
    headline, suffix = split_title(title)
    host = classify_host(hit_url)
    body, lead = clean_page(raw_page, headline)
    published = published if isinstance(published, datetime) else parse_time(published)
    if not published and raw_page:
        found = page_date(raw_page, now)
        if found:
            published, published_source = found, "page_text"
    text = body or clean_text(highlights)
    first_highlight = highlights.split("\n")[0] if highlights else ""
    return {"title": clean_text(headline)[:200], "sourceUrl": hit_url, "sourceItemId": canonical_url(hit_url),
            "publishedAt": published, "publishedAtSource": published_source if published else "",
            "text": text[:6000], "excerptText": lead or clean_text(first_highlight),
            "evidenceText": clean_text(highlights), "imageUrl": "", "imageSource": "",
            "medium": host["medium"], "trustTier": host["tier"], "commerce": host["commerce"],
            "siteName": host["name"] if host["known"] else (suffix or host["name"]),
            "discoveryQuery": query, "discoveryLane": lane, "searchRank": rank, "discoveryMethod": method}


def discover(source: dict, *, fetcher, env=os.environ, opener=urllib.request.urlopen, client=None,
             now: Optional[datetime] = None) -> AdapterResult:
    queries = [expand(q, now) for q in source.get("queries") or []]
    lane = source.get("lane")
    if env.get("EXA_API_KEY"):
        return _discover_rest(queries, lane, env["EXA_API_KEY"], fetcher, env, opener, now)
    if env.get("BABDODUK_EXA_MCP") == "0":
        return AdapterResult(NOT_CONFIGURED, code="EXA_MCP_DISABLED")
    client = client or ExaMCP(opener=opener)
    try:
        client.start()
    except MCPError as exc:
        return AdapterResult(FETCH_FAILED, code=exc.code)
    except Exception as exc:  # noqa: BLE001
        return AdapterResult(FETCH_FAILED, code=failure_code(exc))
    objective = source.get("objective") or DEFAULT_OBJECTIVE
    found, ran, failure = [], [], ""
    for query in queries:
        try:
            hits = client.search(query, objective, PER_QUERY)
        except MCPError as exc:
            failure = exc.code
            break
        except Exception as exc:  # noqa: BLE001 - what was found stays, the failure is recorded
            failure = failure_code(exc)
            break
        ran.append(query)
        public = [h for h in hits if is_public_url(h.get("url") or "")]
        found.extend((query, rank, hit) for rank, hit in enumerate(public, 1))
    # One page read per distinct URL, in batches, after all searches.
    urls = list(dict.fromkeys(hit["url"] for _, _, hit in found))
    pages: dict = {}
    for at in range(0, len(urls), FETCH_BATCH):
        try:
            pages.update({canonical_url(p["url"]): p for p in client.fetch(urls[at:at + FETCH_BATCH], PAGE_CHARS)})
        except Exception:  # noqa: BLE001 - highlights and Jina remain
            break
    items, jina_used = [], 0
    for query, rank, hit in found:
        page = pages.get(canonical_url(hit["url"])) or {}
        raw, published = page.get("body") or "", hit.get("published")
        date_source = "search_metadata" if published else ""
        if not published and page.get("published"):
            published, date_source = page["published"], "page_metadata"
        if len(clean_text(raw)) < MIN_TEXT and jina_used < JINA_PER_SOURCE:
            jina_used += 1
            try:
                read = jina_page(hit["url"], fetcher)
            except Exception:  # noqa: BLE001 - an unreadable page stays unreadable
                read = {}
            raw = read.get("raw") or raw
            if not published and read.get("published"):
                published, date_source = read["published"], "page_metadata"
        title = hit.get("title") or ""
        if page.get("title") and (not title or title.rstrip().endswith(("...", "…"))):
            title = page["title"]            # search titles are cut off; the page's own is whole
        items.append(build_item(hit["url"], title, published=published,
                                published_source=date_source, raw_page=raw,
                                highlights=hit.get("highlights") or "", query=query, lane=lane, rank=rank,
                                method="exa_mcp", now=now))
    return AdapterResult(FETCH_FAILED if failure else OK, items=items, code=failure, queries=ran)


def _discover_rest(queries, lane, key, fetcher, env, opener, now) -> AdapterResult:
    items, ran = [], []
    for query in queries:
        try:
            results = exa_search(query, key, opener)
        except Exception as exc:  # noqa: BLE001 - never echo the request: it carries the key
            return AdapterResult(FETCH_FAILED, items=items, code=failure_code(exc), queries=ran)
        ran.append(query)
        for rank, hit in enumerate(results, 1):
            url = hit.get("url") or ""
            if not is_public_url(url):
                continue
            raw = hit.get("text") or ""
            if len(clean_text(raw)) < MIN_TEXT and env.get("BABDODUK_JINA_READER") == "1":
                try:
                    raw = jina_page(url, fetcher).get("raw") or raw
                except Exception:  # noqa: BLE001
                    pass
            item = build_item(url, hit.get("title") or "", published=hit.get("publishedDate"),
                              published_source="search_metadata" if hit.get("publishedDate") else "", raw_page=raw,
                              highlights="", query=query, lane=lane, rank=rank, method="exa_api", now=now)
            if hit.get("image"):
                item["imageUrl"], item["imageSource"] = hit["image"], "search_result_image"
            items.append(item)
    return AdapterResult(OK, items=items, queries=ran)
