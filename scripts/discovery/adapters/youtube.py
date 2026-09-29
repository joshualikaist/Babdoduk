# -*- coding: utf-8 -*-
"""YouTube: known channels through their public Atom feeds; query discovery through the
YouTube Data API (when YOUTUBE_API_KEY exists) or yt-dlp (Agent Reach's YouTube route; local
only, metadata only, never a video download). No transcript is fetched, so no text here ever
claims what a video says beyond its own title and description."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.parse

from ..common import clean_text, parse_time, youtube_id
from . import FETCH_FAILED, NOT_CONFIGURED, OK, PARSE_FAILED, AdapterResult, failure_code
from . import rss

PER_QUERY = 4


def _thumb(vid: str) -> str:
    return f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg" if vid else ""


def discover_channel(source: dict, *, fetcher) -> AdapterResult:
    url = "https://www.youtube.com/feeds/videos.xml?channel_id=" + urllib.parse.quote(source["channelId"])
    try:
        payload = fetcher(url, accept="application/atom+xml, application/xml")
    except Exception as exc:  # noqa: BLE001 - YouTube answers 404 to some cloud runners
        return AdapterResult(FETCH_FAILED, code=failure_code(exc))
    try:
        items = rss.parse(payload)
    except Exception:  # noqa: BLE001
        return AdapterResult(PARSE_FAILED, code="PARSE")
    out = []
    for row in items:
        vid = youtube_id(row["sourceUrl"]) or row.get("sourceItemId")
        image = row.get("imageUrl") or _thumb(vid)
        out.append(dict(row, sourceItemId=f"yt:{vid}", medium="youtube", imageUrl=image,
                        imageSource="youtube_thumbnail" if image else ""))
    return AdapterResult(OK, items=out)


def discover_search(source: dict, *, fetcher, env=os.environ, runner=subprocess.run) -> AdapterResult:
    queries = list(source.get("queries") or [])
    if env.get("YOUTUBE_API_KEY"):
        return _api_search(queries, env["YOUTUBE_API_KEY"], fetcher)
    if env.get("BABDODUK_YTDLP") == "1" and shutil.which("yt-dlp"):
        return _ytdlp_search(queries, runner)
    return AdapterResult(NOT_CONFIGURED, code="YOUTUBE_SEARCH_NOT_CONFIGURED", queries=[])


def _api_search(queries, key, fetcher) -> AdapterResult:
    items, ran = [], []
    for query in queries:
        params = urllib.parse.urlencode({"part": "snippet", "type": "video", "maxResults": PER_QUERY, "q": query,
                                         "regionCode": "KR", "relevanceLanguage": "ko", "key": key})
        try:
            data = json.loads(fetcher("https://www.googleapis.com/youtube/v3/search?" + params, accept="application/json"))
        except Exception as exc:  # noqa: BLE001 - never echo the URL: it carries the key
            return AdapterResult(FETCH_FAILED, items=items, code=failure_code(exc), queries=ran)
        ran.append(query)
        for entry in data.get("items") or []:
            vid = (entry.get("id") or {}).get("videoId")
            snip = entry.get("snippet") or {}
            if not vid:
                continue
            items.append({"title": clean_text(snip.get("title")), "sourceUrl": f"https://www.youtube.com/watch?v={vid}",
                          "sourceItemId": f"yt:{vid}", "publishedAt": parse_time(snip.get("publishedAt")),
                          "text": clean_text(snip.get("description")), "imageUrl": _thumb(vid),
                          "imageSource": "youtube_thumbnail", "medium": "youtube", "discoveryQuery": query,
                          "channelTitle": clean_text(snip.get("channelTitle"))})
    return AdapterResult(OK, items=items, queries=ran)


def _ytdlp_search(queries, runner) -> AdapterResult:
    items, ran = [], []
    for query in queries:
        try:
            done = runner(["yt-dlp", "--skip-download", "--no-warnings", "--dump-json",
                           f"ytsearch{PER_QUERY}:{query}"], capture_output=True, text=True, timeout=120)
        except Exception as exc:  # noqa: BLE001
            return AdapterResult(FETCH_FAILED, items=items, code=failure_code(exc), queries=ran)
        if done.returncode != 0:
            return AdapterResult(FETCH_FAILED, items=items, code="YTDLP_FAILED", queries=ran)
        ran.append(query)
        for line in (done.stdout or "").splitlines():
            try:
                meta = json.loads(line)
            except ValueError:
                continue
            vid = meta.get("id")
            if not vid:
                continue
            upload = meta.get("upload_date") or ""
            published = parse_time(f"{upload[:4]}-{upload[4:6]}-{upload[6:8]}T00:00:00+09:00") if len(upload) == 8 else None
            items.append({"title": clean_text(meta.get("title")), "sourceUrl": f"https://www.youtube.com/watch?v={vid}",
                          "sourceItemId": f"yt:{vid}", "publishedAt": published,
                          "text": clean_text(meta.get("description")), "imageUrl": _thumb(vid),
                          "imageSource": "youtube_thumbnail", "medium": "youtube", "discoveryQuery": query,
                          "channelTitle": clean_text(meta.get("channel") or meta.get("uploader"))})
    return AdapterResult(OK, items=items, queries=ran)
