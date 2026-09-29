# -*- coding: utf-8 -*-
"""Public web discovery: Exa search (Agent Reach's semantic web route, used here through its
HTTP API) plus Jina Reader for reading a result page when the search returned no text.

Search is discovery only: a result is kept only with source text that was actually retrieved
(Exa's page contents or the Jina Reader text of that same public page). Result order is the
search engine's, never presented as Naver's own ranking. Needs EXA_API_KEY; without it the
adapter reports NOT_CONFIGURED and nothing is invented to compensate."""
from __future__ import annotations

import json
import os
import re
import urllib.request

from ..common import UA, clean_text, is_public_url, parse_time
from . import FETCH_FAILED, NOT_CONFIGURED, OK, AdapterResult, failure_code

EXA_URL = "https://api.exa.ai/search"
JINA_URL = "https://r.jina.ai/"
PER_QUERY = 5
MIN_TEXT = 120


def split_site(query: str) -> tuple[str, list[str]]:
    domains = re.findall(r"site:(\S+)", query)
    return re.sub(r"site:\S+", " ", query).strip(), domains


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


def jina_read(url: str, fetcher) -> str:
    """Public pages only; the guard runs before anything is sent to the third-party reader."""
    if not is_public_url(url):
        return ""
    return clean_text(fetcher(JINA_URL + url, accept="text/plain").decode("utf-8", "replace"))[:4000]


def discover(source: dict, *, fetcher, env=os.environ, opener=urllib.request.urlopen) -> AdapterResult:
    key = env.get("EXA_API_KEY")
    if not key:
        return AdapterResult(NOT_CONFIGURED, code="EXA_NOT_CONFIGURED")
    items, ran = [], []
    for query in source.get("queries") or []:
        try:
            results = exa_search(query, key, opener)
        except Exception as exc:  # noqa: BLE001
            return AdapterResult(FETCH_FAILED, items=items, code=failure_code(exc), queries=ran)
        ran.append(query)
        for rank, hit in enumerate(results, 1):
            url = hit.get("url") or ""
            if not is_public_url(url):
                continue
            text = clean_text(hit.get("text") or "")
            if len(text) < MIN_TEXT and env.get("BABDODUK_JINA_READER") == "1":
                try:
                    text = jina_read(url, fetcher)
                except Exception:  # noqa: BLE001 - an unreadable page stays unreadable
                    text = ""
            host = re.sub(r"^www\.", "", url.split("/")[2]) if "//" in url else ""
            items.append({"title": clean_text(hit.get("title")), "sourceUrl": url, "sourceItemId": url,
                          "publishedAt": parse_time(hit.get("publishedDate")), "text": text,
                          "imageUrl": hit.get("image") or "", "imageSource": "search_result_image" if hit.get("image") else "",
                          "medium": "blog", "discoveryQuery": query, "searchRank": rank, "siteName": host})
    return AdapterResult(OK, items=items, queries=ran)
