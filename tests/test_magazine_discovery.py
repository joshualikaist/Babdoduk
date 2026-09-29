# -*- coding: utf-8 -*-
"""Magazine discovery: provenance, dedup, quality, sparse lanes, image provenance, health and
the no-fabrication rule. Synthetic sources only - no network."""
from __future__ import annotations

import json
import urllib.error
from pathlib import Path

import pytest

from discovery import adapters, common, evaluate, pipeline, registry, select, store
from discovery.adapters import instagram, rss, web, youtube


@pytest.fixture()
def result(tmp_path):
    return evaluate.run_evaluation(tmp_path)


# --- the evaluation set -----------------------------------------------------------------
def test_evaluation_metrics_meet_the_release_bar(result):
    m = result["metrics"]
    assert m["fabricated"] == 0
    assert m["url_provenance"] == 1.0 and m["image_provenance"] == 1.0
    assert m["precision"] == 1.0 and m["stories"] == 3
    assert m["duplicates_suppressed"] == 1
    assert set(m["rejections"]) == {"AD_OR_SPONSORED", "BAD_URL", "OFF_TOPIC_RESTAURANT_TRAVEL"}


def test_duplicate_url_from_two_routes_is_one_candidate_with_both_routes(result):
    onion = [r for r in result["rows"] if r["canonicalUrl"] == "https://recipes.example.org/onion"]
    assert len(onion) == 1 and onion[0]["seenVia"] == ["rss:eval-recipes", "rss:eval-second"]


def test_duplicate_title_points_at_the_first_discovered_original(result):
    dup = [r for r in result["rows"] if r.get("duplicateOf")]
    assert len(dup) == 1 and dup[0]["title"] == "양파 간장 조림 레시피!"
    original = [r for r in result["rows"] if r["candidateId"] == dup[0]["duplicateOf"]][0]
    assert original["title"] == "양파 간장 조림 레시피"


def test_every_story_is_source_backed_and_the_summary_is_a_verbatim_excerpt(result):
    rows = {r["candidateId"]: r for r in result["rows"]}
    edition = result["edition"]
    stories = [edition["featured"]] + [i for s in edition["lanes"].values() for i in s["items"]]
    for story in stories:
        row = rows[story["candidateId"]]
        assert story["url"] == row["sourceUrl"] and story["title"] == row["title"]
        body = story["summary"].rstrip("…")
        assert body and body in row["sourceExcerpt"], "summary must be copied from the source text"
        assert story["medium"] in ("blog", "youtube") and story["source"]


def test_featured_prefers_a_story_with_its_own_validated_image(result):
    featured = result["edition"]["featured"]
    assert featured["image"] and featured["imageSource"] in ("feed_media", "youtube_thumbnail")


def test_a_story_without_an_image_is_published_without_one(result):
    tofu = [i for s in result["edition"]["lanes"].values() for i in s["items"] if i["url"].endswith("/tofu")]
    assert tofu and "image" not in tofu[0]


def test_a_failing_source_means_fewer_stories_and_a_health_warning_never_filler(result):
    health = result["health"]
    assert health["adapters"]["eval-broken"]["status"] == "FETCH_FAILED"
    assert health["adapters"]["eval-broken"]["code"] == "HTTP_404"
    assert "eval-broken" in health["summary"]["failing"] and health["summary"]["fabricated"] == 0
    assert result["edition"]["lanes"]["health"]["items"] == [] and result["edition"]["lanes"]["habit"]["items"] == []


def test_registry_health_fields_are_maintained(tmp_path):
    evaluate.run_evaluation(tmp_path)
    sources = {s["id"]: s for s in registry.load(pipeline.Paths(tmp_path).sources)}
    assert sources["eval-broken"]["failureCount"] == 1 and sources["eval-broken"]["lastFailureCode"] == "HTTP_404"
    assert sources["eval-recipes"]["lastSuccessAt"] and sources["eval-recipes"]["failureCount"] == 0


def test_a_second_run_keeps_the_same_decisions_and_records_the_query_history(tmp_path):
    first = evaluate.run_evaluation(tmp_path)
    second = evaluate.run_evaluation(tmp_path)
    key = lambda rows: sorted((r["candidateId"], r.get("duplicateOf"), r.get("rejectionReason")) for r in rows)
    assert key(first["rows"]) == key(second["rows"])
    runs = pipeline.Paths(tmp_path).runs.read_text(encoding="utf-8").splitlines()
    assert len(runs) == 2 and all(json.loads(line)["counts"]["fabricated"] == 0 for line in runs)


# --- adapters -----------------------------------------------------------------------------
def test_feed_html_images_are_found_after_unescaping():
    payload = (b'<?xml version="1.0"?><rss version="2.0"><channel><item><title>t</title><link>https://a.example/1</link>'
               b'<description>&lt;p&gt;&lt;img src="https://a.example/p.jpg"&gt; text&lt;/p&gt;</description></item></channel></rss>')
    [item] = rss.parse(payload)
    assert (item["imageUrl"], item["imageSource"]) == ("https://a.example/p.jpg", "feed_html")


def test_youtube_channel_feed_uses_the_official_thumbnail_and_video_id():
    result = youtube.discover_channel({"channelId": "UCevalchannel0000000000"}, fetcher=evaluate.fetcher)
    [item] = result.items
    assert item["sourceItemId"] == "yt:abcdefghijk" and item["imageSource"] == "youtube_thumbnail"


def test_youtube_search_is_not_configured_without_a_key_or_local_ytdlp():
    assert youtube.discover_search({"queries": ["집밥 레시피"]}, fetcher=None, env={}).status == adapters.NOT_CONFIGURED


def test_youtube_api_failure_never_echoes_the_key():
    def fetcher(url, **_):
        raise urllib.error.HTTPError(url, 403, "forbidden", {}, None)
    result = youtube.discover_search({"queries": ["q"]}, fetcher=fetcher, env={"YOUTUBE_API_KEY": "SECRET-KEY-123"})
    assert result.status == adapters.FETCH_FAILED and result.code == "HTTP_403" and "SECRET" not in repr(result)


def test_web_search_is_not_configured_without_exa_and_keeps_query_provenance_with_it():
    assert web.discover({"queries": ["집밥 레시피"]}, fetcher=None, env={}).status == adapters.NOT_CONFIGURED

    class Response:
        def __init__(self, body):
            self.body = body

        def read(self):
            return self.body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    sent = []

    def opener(request, timeout):
        sent.append(json.loads(request.data))
        return Response(json.dumps({"results": [
            {"title": "자취 볶음밥", "url": "https://blog.naver.com/x/1", "text": "레시피 " * 60},
            {"title": "사설 주소", "url": "http://192.168.0.2/recipe", "text": "레시피 " * 60}]}).encode())

    result = web.discover({"queries": ["site:blog.naver.com 자취 요리"]}, fetcher=None, env={"EXA_API_KEY": "k"},
                          opener=opener)
    assert sent[0]["includeDomains"] == ["blog.naver.com"] and sent[0]["query"] == "자취 요리"
    assert [i["sourceUrl"] for i in result.items] == ["https://blog.naver.com/x/1"]      # private address dropped
    assert result.items[0]["discoveryQuery"] == "site:blog.naver.com 자취 요리" and result.queries


def test_instagram_is_not_configured_and_contributes_nothing():
    result = instagram.discover({"id": "instagram-opencli"})
    assert result.status == adapters.NOT_CONFIGURED and result.items == []


@pytest.mark.parametrize("url,ok", [
    ("https://www.koreanbapsang.com/x", True), ("http://localhost:8000/", False), ("http://10.0.0.5/a", False),
    ("https://kaist.gov-dooray.com/mail", False), ("https://portal.kaist.ac.kr/x", False),
    ("https://user:pw@example.org/", False), ("javascript:alert(1)", False), ("file:///etc/passwd", False),
])
def test_only_public_urls_are_fetched_or_sent_to_a_reader(url, ok):
    assert common.is_public_url(url) is ok


def test_jina_reader_is_never_called_for_a_private_url():
    calls = []
    assert web.jina_read("https://kaist.gov-dooray.com/mail/1", lambda url, **kw: calls.append(url) or b"x") == ""
    assert calls == []


# --- stored editions ----------------------------------------------------------------------
def test_sanitize_removes_desk_filler_idea_desks_and_generated_summaries():
    old = {"date": "2026-09-28", "featured": {"title": "desk", "source": "밥도둑 데스크", "url": "", "medium": "desk"},
           "lanes": {"tips": {"lead": "x", "items": [
               {"title": "real", "source": "Korean Bapsang", "url": "https://www.koreanbapsang.com/a", "medium": "blog",
                "summary": "잣죽. 오늘 밥상에 올리기 좋다.", "tags": ["잣죽"]},
               {"title": "desk", "source": "밥도둑 데스크", "url": "", "medium": "desk"}]}},
           "desks": {"instagram": [{"title": "탐색", "url": "https://www.instagram.com/explore/tags/x/"}]}}
    cleaned, removed = select.sanitize(old)
    assert removed == 3 and cleaned["featured"] is None and "desks" not in cleaned
    [item] = cleaned["lanes"]["tips"]["items"]
    assert "summary" not in item and "tags" not in item and item["url"].startswith("https://")


def test_the_validator_rejects_fabricated_and_linkless_stories(tmp_path):
    import validate_content
    path = tmp_path / "2026-09-28.json"
    lanes = {lane: {"items": []} for lane in ("tips", "trend", "health", "habit")}
    lanes["tips"]["items"] = [{"title": "x", "source": "밥도둑 데스크", "url": "", "medium": "desk"}]
    path.write_text(json.dumps({"date": "2026-09-28", "featured": None, "lanes": lanes}), encoding="utf-8")
    errors = validate_content.validate_magazine(path)
    assert any("without a real source URL" in e for e in errors) and any("fabricated" in e for e in errors)
    lanes["tips"]["items"] = []
    path.write_text(json.dumps({"date": "2026-09-28", "featured": None, "lanes": lanes}), encoding="utf-8")
    assert validate_content.validate_magazine(path) == []            # a sparse edition is valid


def test_the_store_is_bounded_and_keeps_no_session_material(tmp_path):
    from datetime import timedelta
    s = store.CandidateStore(tmp_path / "c.jsonl")
    old = evaluate.NOW - timedelta(days=store.RETAIN_DAYS + 5)
    s.upsert({"sourceUrl": "https://a.example/old", "title": "old", "cookie": "x"}, old)
    s.upsert({"sourceUrl": "https://a.example/new", "title": "new"}, evaluate.NOW)
    assert s.prune(evaluate.NOW) == 1
    s.save()
    text = (tmp_path / "c.jsonl").read_text(encoding="utf-8")
    assert "cookie" not in text and "a.example/new" in text and "a.example/old" not in text


def test_the_default_registry_is_valid_and_keeps_discovery_routes_explicit():
    sources = registry.default_sources()
    assert registry.validate(sources) == []
    by_type = {}
    for s in sources:
        by_type.setdefault(s["type"], []).append(s)
    assert by_type["instagram"][0]["enabled"] is False
    assert all(s["trustTier"] == "C" for s in by_type["web_search"] + by_type["youtube_search"])
