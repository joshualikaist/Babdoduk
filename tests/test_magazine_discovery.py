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
    assert health["adapters"]["eval-broken"]["adapter"] == "FETCH_FAILED"
    assert health["adapters"]["eval-broken"]["status"] == "DEGRADED"
    assert health["adapters"]["eval-broken"]["code"] == "HTTP_404"
    assert "eval-broken" in health["summary"]["failing"] and health["summary"]["fabricated"] == 0
    assert result["edition"]["lanes"]["health"]["items"] == [] and result["edition"]["lanes"]["habit"]["items"] == []


def test_registry_health_is_kept_apart_from_the_authored_registry(tmp_path):
    evaluate.run_evaluation(tmp_path)
    paths = pipeline.Paths(tmp_path, registry_path=tmp_path / "eval-sources.json")
    authored = registry.load(paths.registry)
    assert registry.validate(authored) == []                    # no runtime fields written back
    health = registry.load_health(paths.source_health)
    assert health["eval-broken"]["failureCount"] == 1 and health["eval-broken"]["lastFailureCode"] == "HTTP_404"
    assert health["eval-broken"]["status"] == "DEGRADED" and health["eval-recipes"]["status"] == "ACTIVE"
    assert health["eval-recipes"]["lastSuccessAt"] and health["eval-recipes"]["failureCount"] == 0


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


def test_the_one_registry_is_valid_and_honest_about_what_runs():
    sources = registry.load()                                   # scripts/discovery/sources.json
    assert registry.validate(sources) == []
    by_type = {}
    for s in sources:
        by_type.setdefault(s["type"], []).append(s)
    # Adapters that need a credential or a local browser exist but are not enabled or claimed.
    for s in by_type["instagram"] + by_type["web_search"] + by_type["youtube_search"]:
        assert s["enabled"] is False and s.get("note"), s["id"]
    assert all(s["trustTier"] == "C" for s in by_type["web_search"] + by_type["youtube_search"])
    assert all(s.get("knownIssue") for s in by_type["youtube_channel"])
    import refresh_magazine
    source_text = Path(refresh_magazine.__file__).read_text(encoding="utf-8")
    assert "youtube.com/feeds" not in source_text and ".tistory.com" not in source_text   # no second list


# --- audit fixes: freshness, recycling, evidence, excerpts, status ------------------------
def _row(**kw):
    base = {"candidateId": kw.get("cid", "c_x"), "title": "t", "sourceExcerpt": "레시피 " * 20, "textLength": 200,
            "sourceUrl": "https://a.example/x", "canonicalUrl": "https://a.example/x", "medium": "blog",
            "trustTier": "B", "categoryHints": ["tips"], "discoveredSeq": 1}
    base.update(kw)
    base.pop("cid", None)
    return base


def test_old_items_never_land_in_the_trend_lane():
    from datetime import timedelta
    from discovery import process
    old = _row(title="편의점 신상 먹방 트렌드", publishedAt=(evaluate.NOW - timedelta(days=45)).isoformat(), categoryHints=["trend"])
    new = _row(title="편의점 신상 먹방 트렌드", publishedAt=(evaluate.NOW - timedelta(days=3)).isoformat(), categoryHints=["trend"])
    assert process.classify(old, evaluate.NOW) != "trend" and process.classify(new, evaluate.NOW) == "trend"
    ancient = _row(title="오래된 김치찌개 레시피", publishedAt=(evaluate.NOW - timedelta(days=400)).isoformat())
    assert process.rejection(ancient, evaluate.NOW) == "TOO_OLD"


def test_a_story_is_published_once_and_not_recycled_the_next_day(tmp_path):
    first = evaluate.run_evaluation(tmp_path)
    edition = first["edition"]
    published = {i["candidateId"] for s in edition["lanes"].values() for i in s["items"]} | {edition["featured"]["candidateId"]}
    rows = store.CandidateStore(pipeline.Paths(tmp_path).candidates).all()
    assert {r["candidateId"] for r in rows if r.get("selectedFor") == "2026-09-29"} == published
    tomorrow, _ = select.build(rows, date="2026-09-30", generated_at="x", recent=set())
    again = {i["candidateId"] for s in tomorrow["lanes"].values() for i in s["items"]}
    assert not again & published and tomorrow["featured"] is None


def test_similar_titles_from_different_sites_are_not_merged():
    from discovery import process
    a = _row(cid="c_a", title="Kimchi Fried Rice", canonicalUrl="https://one.example/kfr",
             sourceExcerpt="첫 번째 블로그의 김치볶음밥 " * 8, discoveredSeq=1)
    b = _row(cid="c_b", title="Kimchi Fried Rice!", canonicalUrl="https://two.example/kfr",
             sourceExcerpt="전혀 다른 글의 설명 문장 " * 8, discoveredSeq=2)
    a["candidateId"], b["candidateId"] = "c_a", "c_b"
    assert process.mark_duplicates([a, b]) == 0
    c = _row(title="Kimchi Fried Rice!!", canonicalUrl="https://one.example/kfr-2",
             sourceExcerpt="첫 번째 블로그의 김치볶음밥 " * 8, discoveredSeq=3)
    c["candidateId"] = "c_c"
    assert process.mark_duplicates([a, c]) == 1 and c["duplicateOf"] == "c_a"


def test_card_summaries_are_short_and_free_of_links_and_hashtags():
    text = "바삭한 크럼블 사과 파이 레시피입니다. https://example.org/buy #베이킹 #레시피 " + "설명 문장이 이어집니다. " * 20
    summary = select.card_summary(text)
    assert len(summary) <= select.SUMMARY_CHARS + 1 and "http" not in summary and "#" not in summary
    assert summary.startswith("바삭한 크럼블 사과 파이 레시피입니다.")
    assert select.card_summary("구독 #shorts https://x.example") == ""        # too thin: title + source only


def test_a_skipped_source_type_is_recorded_as_degraded_not_success(tmp_path):
    paths = pipeline.Paths(tmp_path, registry_path=tmp_path / "eval-sources.json")
    paths.research.mkdir(parents=True, exist_ok=True)
    paths.registry.write_text(common.dump_json({"version": 1, "sources": evaluate.sources()}), encoding="utf-8")
    run = pipeline.discover(paths, evaluate.NOW, fetcher=evaluate.fetcher, env={}, validate=lambda u: True,
                            log=lambda _: None, skip_types=("youtube_channel",))
    assert run["health"]["eval-youtube"]["adapter"] == "SKIPPED"
    assert run["sourceHealth"]["eval-youtube"]["status"] == "DEGRADED"
    assert run["sourceHealth"]["eval-youtube"]["lastFailureCode"] == "SKIPPED_CLOUD_PARITY"


def test_a_source_without_recent_items_is_stale():
    from datetime import timedelta
    entry = {"lastSuccessAt": evaluate.NOW.isoformat(), "newestItemAt": (evaluate.NOW - timedelta(days=200)).isoformat()}
    assert registry.status({"enabled": True}, entry, evaluate.NOW) == "STALE"
    assert registry.status({"enabled": False}, entry, evaluate.NOW) == "DISABLED"


def test_a_lane_needs_the_sources_own_category_or_two_signals():
    from discovery import process
    porridge = _row(title="Jeonbokjuk (Korean Abalone Porridge)", categoryHints=["tips", "health"],
                    sourceExcerpt="A comforting porridge, great for breakfast, made with leftover rice." * 2)
    assert process.classify(porridge) in ("tips", "health")          # one "breakfast" is not a habit story
    habit = _row(title="아침 식사 루틴과 식습관", categoryHints=["tips"],
                 sourceExcerpt="아침 식사 습관을 바꾸는 루틴 이야기입니다." * 3)
    assert process.classify(habit) == "habit"


def test_contests_and_giveaways_are_rejected_as_promotions():
    from discovery import process
    row = _row(title="JOC Cooking Challenge September 2026",
               sourceExcerpt="Join the September cooking challenge and enter to win a prize. " * 3)
    assert process.rejection(row, evaluate.NOW) == "PROMOTION"


def test_embed_boilerplate_and_a_repeated_title_are_not_the_summary():
    text = "Watch How to Make This Yukhoe Kimbap When I was going to culinary school in Paris, I hosted supper clubs."
    summary = select.card_summary(text, "Yukhoe Kimbap")
    assert summary.startswith("When I was going to culinary school")


def test_a_repeated_embed_heading_is_dropped_but_a_normal_sentence_is_kept():
    text = "Chicken Katsu with Caviar Chicken katsu with caviar is one of those dishes that feels playful."
    assert select.card_summary(text, "Easy Chicken Katsu with Caviar | Luxurious Japanese Recipe").startswith(
        "Chicken katsu with caviar is one of those")
    normal = "Miso Eggplant Stir-Fry recipe with silky Japanese eggplant in a sweet-savory glaze."
    assert select.card_summary(normal, "Miso Eggplant Stir-Fry") == normal
