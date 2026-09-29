# -*- coding: utf-8 -*-
"""Image provenance. Priority: feed media, the item's own feed HTML, the official YouTube
thumbnail, then the og:image / twitter:image declared by the item's OWN page. An image of
another article is never used and no image is ever made up. `imageValidated` means the URL
answered 200 with an image content type."""
from __future__ import annotations

import html
import re
import ssl
import urllib.request

from .common import UA, is_public_url

META_IMAGE = re.compile(r"""<meta[^>]+(?:property|name)=["'](?:og:image|twitter:image)(?::src)?["'][^>]*>""", re.I)
CONTENT = re.compile(r"""content=["']([^"']+)["']""", re.I)
PAGE_BUDGET = 30
PER_LANE_BUDGET = 12        # every lane's best candidates get an image check, not only the global top


def page_image(url: str, fetcher) -> str:
    """og:image of this exact page (public pages only)."""
    if not is_public_url(url):
        return ""
    head = fetcher(url, accept="text/html")[:400_000].decode("utf-8", "replace")
    for tag in META_IMAGE.findall(head):
        match = CONTENT.search(tag)
        if match:
            src = html.unescape(match.group(1).strip())
            if src.startswith("//"):
                src = "https:" + src
            if src.startswith(("http://", "https://")) and not src.lower().endswith(".svg"):
                return src
    return ""


def image_ok(url: str, opener=urllib.request.urlopen) -> bool:
    if not is_public_url(url):
        return False
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Range": "bytes=0-2047"})
    try:
        with opener(request, timeout=15, context=ssl.create_default_context()) as res:
            status = int(getattr(res, "status", 200) or 200)
            kind = (res.headers.get("Content-Type") or "").lower()
            return status in (200, 206) and kind.startswith("image/")
    except Exception:  # noqa: BLE001
        return False


def enrich(rows: list[dict], fetcher, *, validate=image_ok, budget: int = PAGE_BUDGET) -> dict:
    """For the best-ranked eligible rows only (bounded requests: the overall top `budget` plus
    each lane's top PER_LANE_BUDGET): validate feed images and look up the item's own og:image
    when the feed had none."""
    counts = {"page_lookups": 0, "validated": 0}
    ranked = sorted((r for r in rows if not r.get("duplicateOf") and not r.get("rejectionReason")),
                    key=lambda r: (-(r.get("score") or 0), r.get("candidateId") or ""))
    picked, per_lane = [], {}
    for row in ranked:
        lane = row.get("assignedCategory")
        if len(picked) < budget or per_lane.get(lane, 0) < PER_LANE_BUDGET:
            picked.append(row)
            per_lane[lane] = per_lane.get(lane, 0) + 1
    for row in picked:
        if not row.get("imageUrl") and row.get("medium") != "youtube":
            counts["page_lookups"] += 1
            try:
                found = page_image(row["sourceUrl"], fetcher)
            except Exception:  # noqa: BLE001
                found = ""
            if found:
                row["imageUrl"], row["imageSource"] = found, "source_page_og"
        if row.get("imageUrl") and not row.get("imageValidated"):
            row["imageValidated"] = bool(validate(row["imageUrl"]))
            counts["validated"] += int(row["imageValidated"])
    return counts
