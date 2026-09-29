# -*- coding: utf-8 -*-
"""Deterministic magazine evaluation: synthetic sources through the real pipeline.

Cases: a real recipe source, a YouTube item, a duplicate URL (two routes), a duplicate title,
a missing image, a valid feed image, a bad source URL, an ad-like item, an irrelevant
restaurant/travel item, a sparse lane and a source fetch failure. No network.

    python -m discovery.evaluate      (from scripts/)
"""
from __future__ import annotations

import json
import tempfile
import urllib.error
from datetime import datetime
from pathlib import Path

from . import pipeline, select
from .common import KST, dump_json

NOW = datetime(2026, 9, 29, 10, 30, tzinfo=KST)
LONG = ("이 레시피는 양파를 먼저 볶아 단맛을 낸 뒤 간장과 설탕을 넣어 졸이는 방식입니다. 불은 중불로 유지하고 "
        "마지막에 참기름을 둘러 마무리합니다. 재료는 양파 한 개, 간장 두 큰술, 설탕 한 큰술입니다.")


def rss(items: list[dict]) -> bytes:
    body = ""
    for it in items:
        media = f'<media:content url="{it["image"]}" medium="image"/>' if it.get("image") else ""
        body += (f"<item><title>{it['title']}</title><link>{it['link']}</link>"
                 f"<pubDate>{it.get('date', 'Mon, 28 Sep 2026 09:00:00 +0900')}</pubDate>"
                 f"<description><![CDATA[{it.get('text', LONG)}]]></description>{media}</item>")
    return (f'<?xml version="1.0"?><rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">'
            f"<channel><title>t</title>{body}</channel></rss>").encode("utf-8")


def atom_youtube(video: str, title: str) -> bytes:
    return (f'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015" '
            f'xmlns:media="http://search.yahoo.com/mrss/"><entry><yt:videoId>{video}</yt:videoId><title>{title}</title>'
            f'<link rel="alternate" href="https://www.youtube.com/watch?v={video}"/><published>2026-09-28T08:00:00+00:00</published>'
            f'<media:group><media:description>자취생을 위한 10분 계란 볶음밥 레시피 영상입니다. 재료와 순서를 자막으로 안내합니다.</media:description>'
            f'<media:thumbnail url="https://i.ytimg.com/vi/{video}/hqdefault.jpg"/></media:group></entry></feed>').encode("utf-8")


FEEDS = {
    "https://recipes.example.org/feed": rss([
        {"title": "양파 간장 조림 레시피", "link": "https://recipes.example.org/onion", "image": "https://recipes.example.org/onion.jpg"},
        {"title": "두부 부침 만드는 법", "link": "https://recipes.example.org/tofu"},                       # missing image
        {"title": "쿠팡파트너스 주방템 추천", "link": "https://recipes.example.org/ad", "text": LONG + " 쿠팡파트너스 활동의 일환으로 수수료를 받습니다."},
        {"title": "제주 맛집 여행 코스", "link": "https://recipes.example.org/jeju"},                        # off topic
        {"title": "나쁜 링크 레시피", "link": "javascript:alert(1)"},                                        # bad URL
        {"title": "양파 간장 조림 레시피!", "link": "https://recipes.example.org/onion-2"},                   # duplicate title
    ]),
    "https://second.example.org/feed": rss([
        {"title": "양파 간장 조림 (다른 경로)", "link": "https://recipes.example.org/onion?utm_source=x"},    # duplicate URL
    ]),
    "https://www.youtube.com/feeds/videos.xml?channel_id=UCevalchannel0000000000": atom_youtube("abcdefghijk", "10분 계란 볶음밥 레시피"),
}
RELEVANT = {"https://recipes.example.org/onion", "https://recipes.example.org/tofu",
            "https://www.youtube.com/watch?v=abcdefghijk"}


def fetcher(url, **_):
    if url in FEEDS:
        return FEEDS[url]
    raise urllib.error.HTTPError(url, 404, "not found", {}, None)


def sources() -> list[dict]:
    base = {"enabled": True}
    return [
        dict(base, id="eval-recipes", name="Eval Recipes", type="rss", url="https://recipes.example.org/feed",
             trustTier="B", categories=["tips"], discoveryMethod="rss"),
        dict(base, id="eval-second", name="Eval Second", type="rss", url="https://second.example.org/feed",
             trustTier="B", categories=["tips"], discoveryMethod="rss"),
        dict(base, id="eval-youtube", name="Eval Channel", type="youtube_channel", channelId="UCevalchannel0000000000",
             trustTier="B", categories=["tips"], discoveryMethod="youtube_feed"),
        dict(base, id="eval-broken", name="Broken Feed", type="rss", url="https://broken.example.org/feed",
             trustTier="B", categories=["health"], discoveryMethod="rss"),
    ]


def run_evaluation(root: Path) -> dict:
    paths = pipeline.Paths(root, registry_path=Path(root) / "eval-sources.json")
    paths.research.mkdir(parents=True, exist_ok=True)
    paths.registry.write_text(dump_json({"version": 1, "sources": sources()}), encoding="utf-8")
    run = pipeline.discover(paths, NOW, fetcher=fetcher, env={}, validate=lambda url: url.startswith("https://"),
                            log=lambda _: None)
    edition, chosen = select.build(run["store"].all(), date="2026-09-29", generated_at="2026-09-29T10:30:00+09:00",
                                   recent=set())
    report = pipeline.finish(paths, run, edition, chosen, NOW)
    stories = [edition["featured"]] + [i for s in edition["lanes"].values() for i in s["items"]]
    stories = [s for s in stories if s]
    rows = run["store"].all()
    return {
        "edition": edition,
        "rows": rows,
        "health": report,
        "metrics": {
            "stories": len(stories),
            "precision": round(sum(1 for s in stories if s["url"] in RELEVANT) / len(stories), 3) if stories else 0.0,
            "duplicates_suppressed": sum(1 for r in rows if r.get("duplicateOf")),
            "url_provenance": round(sum(1 for s in stories if s["url"].startswith("https://")) / len(stories), 3) if stories else 1.0,
            "image_provenance": round(sum(1 for s in stories if not s.get("image") or s.get("imageSource")) / len(stories), 3)
            if stories else 1.0,
            "fabricated": sum(1 for s in stories if s.get("medium") == "desk" or not s.get("url")),
            "rejections": sorted({r["rejectionReason"] for r in rows if r.get("rejectionReason")}),
        },
    }


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        result = run_evaluation(Path(tmp))
    print(json.dumps(result["metrics"], ensure_ascii=False, indent=1))
