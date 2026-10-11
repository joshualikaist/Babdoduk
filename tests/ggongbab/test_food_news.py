"""Synthetic campus news sources; no live Portal/database/mailbox access."""
import json
from copy import deepcopy
from datetime import datetime, timedelta

import pytest

from ggongbab.config import KST
from ggongbab.exporter import build_payload, build_archive
from ggongbab.food_news import (build_news, extract_reviewed_news, export_news, is_news_candidate, load_news,
                                publish_review, review_to_public, validate_news_payload)
from ggongbab.prefilter import portal_list_warrants_detail
from validate_content import validate_ggongbab_payload

NOW = datetime(2026, 9, 30, 9, tzinfo=KST)


def reviewed(**changes):
    record = {"title": "교내 신규 식당 오픈 안내", "noticeDate": "2026-09-30", "dateVerified": True,
              "sourceType": "portal", "reviewed": True, "campusEvidence": "교내",
              "evidence": "교내 신규 식당 오픈 안내\n점심 영업을 시작합니다.\n무료 제공 없음.",
              "summary": "점심 영업을 시작합니다.", "noFreeOfferEvidence": "무료 제공 없음"}
    record.update(changes)
    return record


@pytest.mark.parametrize("title", ["신규 식당 오픈 안내", "카페 운영시간 변경", "교내 매장 폐점 안내",
    "캠퍼스 급식 서비스 개시", "New campus restaurant opening", "Cafeteria operating hours changed",
    "교내 버거 매장 오픈", "BBQ 신규 입점 안내", "NBB opening notice"])
def test_food_news_survives_stage_a(title):
    assert is_news_candidate(title)
    assert portal_list_warrants_detail(title)


@pytest.mark.parametrize("title", ["신규 연구실 오픈", "신규 연구센터 개소", "도서관 운영시간 변경",
    "Job opening in a research lab", "신규 커피 연구실 오픈", "No Brand Burger", "BBQ"])
def test_not_a_service_change(title):
    assert not is_news_candidate(title)


def test_unrelated_opening_does_not_survive_portal_prefilter():
    assert not portal_list_warrants_detail("신규 연구실 오픈")


def test_signal_alone_never_publishes():
    with pytest.raises(ValueError, match="NEWS_REVIEW_REQUIRED"):
        extract_reviewed_news(reviewed(reviewed=False))
    with pytest.raises(ValueError, match="CAMPUS_EVIDENCE"):
        extract_reviewed_news(reviewed(campusEvidence="도심"))
    with pytest.raises(ValueError, match="FACT_NOT_IN_SOURCE"):
        extract_reviewed_news(reviewed(location="N99"))
    with pytest.raises(ValueError, match="DATE_UNVERIFIED"):
        extract_reviewed_news(reviewed(dateVerified=False))


def test_explicit_no_free_and_unknown_remain_distinct():
    assert extract_reviewed_news(reviewed())["hasFreeOffer"] is False
    unknown = extract_reviewed_news(reviewed(noFreeOfferEvidence=None))
    assert "hasFreeOffer" not in unknown


def test_news_and_validated_free_event_can_coexist(settings):
    evidence = "교내 신규 식당 오픈 안내\n점심 영업을 시작합니다.\n커피 무료 제공"
    news = build_news(review_to_public([reviewed(evidence=evidence, noFreeOfferEvidence=None,
                                                 freeOfferEvidence="커피 무료 제공")]), NOW)
    assert news["items"][0]["hasFreeOffer"] is True
    event = {"id": "free-offer", "title": "교내 신규 식당 오픈 안내", "food_provided": "true",
             "status": "published", "needs_review": False, "confidence": .99,
             "event_start": (NOW + timedelta(hours=2)).isoformat(), "contentType": "free_food"}
    mixed = [event, {**event, "id": "news-only", "contentType": "campus_food_news"}]
    payload = build_payload(mixed, settings, NOW, food_only=True)
    assert payload["count"] == 1 and payload["events"][0]["id"] == "free-offer"
    archived = build_archive(mixed, settings, {"free-offer", "news-only"}, NOW + timedelta(days=1))
    assert [item["id"] for item in archived["events"]] == ["free-offer"]
    assert validate_news_payload(news) == []
    assert validate_ggongbab_payload({"generatedAt": NOW.isoformat(), "timezone": "Asia/Seoul",
        "count": 1, "events": news["items"]}, NOW)  # Wrong channel is refused.


@pytest.mark.parametrize("key,value", [("pstNo", "PRIVATE-ID"), ("url", "https://portal.kaist.ac.kr/wz/private"),
    ("title", "공지 pstNo=PRIVATE-ID"), ("location", "portal.kaist.ac.kr/private")])
def test_private_fields_and_identifiers_fail_closed(key, value):
    payload = build_news(review_to_public([reviewed()]), NOW)
    payload["items"][0][key] = value
    assert validate_news_payload(payload)


def test_portal_source_never_exports_private_links_or_review_evidence():
    item = extract_reviewed_news(reviewed(pstNo="PRIVATE-ID", url="https://portal.kaist.ac.kr/wz/private"))
    assert item["sources"] == [{"type": "portal", "name": "KAIST 포탈"}]
    serialized = json.dumps(item)
    assert all(word not in serialized for word in ("PRIVATE-ID", "pstNo", "portal.kaist", "evidence", "reviewed"))


def test_invalid_review_preserves_last_good_public_input(tmp_path):
    review, public = tmp_path / ".local/food-news-review.json", tmp_path / "inputs/food-news.json"
    review.parent.mkdir(parents=True)
    review.write_text(json.dumps({"records": [reviewed()]}), encoding="utf-8")
    assert publish_review(review, public) == 1
    before = public.read_bytes()
    review.write_text(json.dumps({"records": [reviewed(), reviewed(reviewed=False)]}), encoding="utf-8")
    with pytest.raises(ValueError):
        publish_review(review, public)
    assert public.read_bytes() == before


def test_the_review_evidence_never_reaches_the_committed_input(tmp_path):
    """The repository is public: the committed input carries the public items alone."""
    review, public = tmp_path / "review.json", tmp_path / "food-news.json"
    review.write_text(json.dumps({"records": [reviewed(pstNo="PRIVATE-ID")]}), encoding="utf-8")
    publish_review(review, public)
    committed = json.loads(public.read_text(encoding="utf-8"))
    assert set(committed) == {"items"} and set(committed["items"][0]) <= {
        "id", "contentType", "noticeDate", "title", "summary", "location", "sources", "hasFreeOffer"}
    text = public.read_text(encoding="utf-8")
    excerpt = json.dumps(reviewed()["evidence"], ensure_ascii=False)[1:-1]     # as it would appear in JSON
    assert all(word not in text for word in (excerpt, "무료 제공 없음", "evidence", "campusEvidence", "reviewed",
                                             "dateVerified", "PRIVATE-ID", "pstNo"))


@pytest.mark.parametrize("tamper", [
    lambda item: item.update(evidence="교내 신규 식당 오픈 안내 전문"),           # review material
    lambda item: item.update(title="교내 신규 카페 오픈 안내"),                  # a fact changed, not its id
    lambda item: item.update(summary="자세히는 portal.kaist.ac.kr/wz/1 참고"),     # a Portal link
    lambda item: item.update(sources=[{"type": "portal", "name": "KAIST Portal 1234"}]),
])
def test_the_refresh_checks_every_public_item_again(tmp_path, tamper):
    public, output = tmp_path / "food-news.json", tmp_path / "news.json"
    items = review_to_public([reviewed()])
    public.write_text(json.dumps({"items": items}), encoding="utf-8")
    export_news(public, output, NOW)
    before = output.read_bytes()
    tamper(items[0])
    public.write_text(json.dumps({"items": items}), encoding="utf-8")
    with pytest.raises(ValueError):
        export_news(public, output, NOW)
    assert output.read_bytes() == before


def test_the_refresh_refuses_a_review_file(tmp_path):
    """The old review format (records with excerpts) is not a public input."""
    public = tmp_path / "food-news.json"
    public.write_text(json.dumps({"records": [reviewed()]}), encoding="utf-8")
    with pytest.raises(ValueError, match="NEWS_PUBLIC_INPUT_INVALID"):
        load_news(public, NOW)


def test_news_timestamp_only_is_not_a_publish_change():
    import publish_generated
    before = build_news(review_to_public([reviewed()]), NOW)
    after = {**before, "generatedAt": (NOW + timedelta(minutes=30)).isoformat()}
    assert publish_generated.meaningful_changes(["data/ggongbab/news.json"],
        lambda _: json.dumps(before), lambda _: json.dumps(after)) == []


def test_duplicate_news_and_invalid_dates_rejected():
    with pytest.raises(ValueError):
        review_to_public([reviewed(), reviewed()])
    with pytest.raises(ValueError):
        review_to_public([reviewed(noticeDate="2026-02-30")])
    item = review_to_public([reviewed()])[0]
    with pytest.raises(ValueError):
        build_news([item, dict(item)], NOW)
