# -*- coding: utf-8 -*-
"""RSS 2.0 / Atom adapter (Agent Reach routes RSS through feedparser; this stdlib parser covers
the same fields for our feeds without a new dependency)."""
from __future__ import annotations

import html
import re
import time
import xml.etree.ElementTree as ET

from ..common import clean_text, parse_time
from . import OK, PARSE_FAILED, FETCH_FAILED, AdapterResult, failure_code

NS = {"atom": "http://www.w3.org/2005/Atom", "media": "http://search.yahoo.com/mrss/",
      "content": "http://purl.org/rss/1.0/modules/content/", "yt": "http://www.youtube.com/xml/schemas/2015",
      "dc": "http://purl.org/dc/elements/1.1/"}
# A dc:date with no zone ("2026-10-12 13:33:32") is the publisher's local time; our feeds are Korean.
LOCAL_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?$")
IMG_SRC = re.compile(r"""<img[^>]+?src=["']([^"']+)["']""", re.I)
BAD_IMAGE = re.compile(r"(1x1|pixel|spacer|blank\.gif|gravatar|emoji|/icons?/|logo|avatar|feeds\.feedburner)", re.I)


def usable_image(url: str) -> str:
    src = html.unescape((url or "").strip())
    if src.startswith("//"):
        src = "https:" + src
    if not src.startswith(("http://", "https://")) or src.lower().endswith(".svg") or BAD_IMAGE.search(src):
        return ""
    return src


def _text(node, path: str) -> str:
    el = node.find(path, NS)
    return (el.text or "") if el is not None else ""


def item_image(node) -> tuple[str, str]:
    """Only images that belong to this exact feed item: media, enclosure, then the first <img>
    inside the item's own HTML. Returns (url, imageSource)."""
    for path in ("media:group/media:thumbnail", "media:thumbnail", "media:content", "media:group/media:content"):
        el = node.find(path, NS)
        if el is not None:
            src = usable_image(el.get("url") or "")
            if src and (path.endswith("thumbnail") or (el.get("medium") or el.get("type") or "image").startswith("image")):
                return src, "feed_media"
    enclosure = node.find("enclosure")
    if enclosure is not None and (enclosure.get("type") or "").startswith("image"):
        src = usable_image(enclosure.get("url") or "")
        if src:
            return src, "feed_media"
    for path in ("content:encoded", "description", "atom:content", "atom:summary"):
        blob = html.unescape(_text(node, path))      # feed HTML arrives entity-escaped
        for match in IMG_SRC.finditer(blob):
            src = usable_image(match.group(1))
            if src:
                return src, "feed_html"
    return "", ""


def item_date(node):
    """pubDate, else the Dublin Core dc:date that some Korean feeds carry instead (헬스조선, 레이디경향,
    푸드투데이, 경향): without it every item of those feeds was undated and could not run."""
    published = parse_time(_text(node, "pubDate"))
    if published:
        return published
    raw = _text(node, "dc:date").strip()
    if LOCAL_DATE.match(raw):
        raw = raw.replace(" ", "T") + "+09:00"
    return parse_time(raw)


def item_text(node) -> str:
    bodies = [clean_text(_text(node, p)) for p in ("content:encoded", "description", "atom:content",
                                                 "atom:summary", "media:group/media:description")]
    return max(bodies, key=len) if bodies else ""


def parse(payload: bytes) -> list[dict]:
    root = ET.fromstring(payload)
    out = []
    for node in root.findall("./channel/item"):
        link = (_text(node, "link") or "").strip()
        guid = (_text(node, "guid") or "").strip()
        image, image_source = item_image(node)
        out.append({"title": clean_text(_text(node, "title")), "sourceUrl": link or guid, "sourceItemId": guid or link,
                    "publishedAt": item_date(node), "text": item_text(node),
                    "imageUrl": image, "imageSource": image_source})
    for node in root.findall("atom:entry", NS):
        link_el = node.find("atom:link[@rel='alternate']", NS)
        if link_el is None:                       # an Element with no children is falsy: no `or`
            link_el = node.find("atom:link", NS)
        link = link_el.get("href") if link_el is not None else ""
        image, image_source = item_image(node)
        stats = node.find("media:group/media:community/media:statistics", NS)
        views = stats.get("views") if stats is not None else None
        out.append({"title": clean_text(_text(node, "atom:title")), "sourceUrl": link,
                    "sourceItemId": _text(node, "yt:videoId") or _text(node, "atom:id") or link,
                    "publishedAt": parse_time(_text(node, "atom:published") or _text(node, "atom:updated")),
                    "text": item_text(node), "imageUrl": image, "imageSource": image_source,
                    "viewCount": int(views) if views and views.isdigit() else None})
    return [row for row in out if row["title"] and row["sourceUrl"]]


ACCEPT = "application/rss+xml, application/atom+xml, application/xml, text/xml"
PAGE_PAUSE = 2.0          # seconds between two requests to the same site


def page_urls(source: dict) -> list[str]:
    """The feed, then its older pages when the registry says the feed pages back (WordPress
    feeds take ?paged=N): a recipe blog then brings a reserve of evergreen stories, not only its
    newest few."""
    url = source["url"]
    pages = int(source.get("feedPages") or 1)
    if pages <= 1 or source.get("pagedFeed") != "wordpress":
        return [url]
    joiner = "&" if "?" in url else "?"
    return [url] + [f"{url}{joiner}paged={n}" for n in range(2, pages + 1)]


def discover(source: dict, *, fetcher, sleep=time.sleep) -> AdapterResult:
    first, *older = page_urls(source)
    try:
        payload = fetcher(first, accept=ACCEPT)
    except Exception as exc:  # noqa: BLE001
        return AdapterResult(FETCH_FAILED, code=failure_code(exc))
    try:
        items = parse(payload)
    except ET.ParseError:
        return AdapterResult(PARSE_FAILED, code="PARSE")
    seen = {row["sourceUrl"] for row in items}
    for url in older:
        sleep(PAGE_PAUSE)
        try:
            page = parse(fetcher(url, accept=ACCEPT))
        except Exception:  # noqa: BLE001 - an older page is a bonus: the feed itself already answered
            break
        new = [row for row in page if row["sourceUrl"] not in seen]
        if not new:
            break                                 # past the last page, or a site that ignores ?paged
        seen.update(row["sourceUrl"] for row in new)
        items += new
    medium = "news" if source.get("kind") == "news" else "blog"
    return AdapterResult(OK, items=[dict(row, medium=medium) for row in items])
