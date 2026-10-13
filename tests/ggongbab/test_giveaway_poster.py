# -*- coding: utf-8 -*-
"""Owner decisions 2026-10-14: food read only from a poster is published (source recorded), and a
prize draw or giveaway is listed with a gift mark, apart from free food. Synthetic data only."""
from __future__ import annotations

from datetime import datetime, timedelta

from ggongbab.config import KST, Settings
from ggongbab.exporter import build_archive, build_payload, publication_eligible
from ggongbab.models import Evidence
from ggongbab.parsers.rule_parser import analyze
from ggongbab.parsers.validator import validate
from ggongbab.public_feed import public_row, to_snapshot_event
from validate_content import validate_ggongbab_payload

from .conftest import REFERENCE, make_extraction

CONCERT = "자연과학 토크 콘서트\n10월 16일(목) 18:00 창의학습관 터만홀\n자세한 내용은 포스터를 참고하세요."
EXPO = "INNOVATE KOREA 2026\n10월 20일(월) 10:00~17:00 KAIST 스포츠컴플렉스\n방문객 대상 경품 추첨 이벤트를 진행합니다."
NOW = datetime(2026, 10, 14, 9, 0, tzinfo=KST)


def concert(**over):
    base = dict(title="자연과학 토크 콘서트", event_start="2026-10-16T18:00:00+09:00", date_text="10월 16일(목)",
                time_text="18:00", location_name="창의학습관 터만홀", building=None, food_type="lunchbox",
                food_description="저녁 도시락",
                evidence=Evidence(event_time="10월 16일(목) 18:00", location="창의학습관 터만홀",
                                  food="참석자 전원 저녁 도시락 제공", registration=None, from_poster=["food"]))
    base.update(over)
    return make_extraction(**base)


def test_food_only_in_a_poster_is_published_when_images_were_sent():
    facts = analyze(CONCERT, NOW)
    cand = validate(concert(), facts, CONCERT, reference=NOW, images=1)
    assert cand.food_provided == "true" and cand.food_evidence_source == "poster"
    assert not cand.needs_review and cand.review_reasons == []
    row = cand.to_db_row()
    assert row["status"] == "published" and row["food_evidence_source"] == "poster"


def test_a_poster_quote_without_any_image_sent_is_not_evidence():
    cand = validate(concert(), analyze(CONCERT, NOW), CONCERT, reference=NOW, images=0)
    assert cand.food_provided == "unknown" and cand.needs_review and cand.food_evidence_source is None


def test_a_poster_quote_must_still_be_explicit_provision():
    ext = concert(evidence=Evidence(event_time="10월 16일(목) 18:00", location=None, food="저녁 시간 토크",
                                    registration=None, from_poster=["food"]))
    cand = validate(ext, analyze(CONCERT, NOW), CONCERT, reference=NOW, images=2)
    assert cand.food_provided == "unknown" and cand.needs_review


def test_text_evidence_is_recorded_as_text():
    text = CONCERT + "\n참석자 전원 저녁 도시락 제공"
    cand = validate(concert(), analyze(text, NOW), text, reference=NOW, images=1)
    assert cand.food_evidence_source == "text" and not cand.needs_review


def test_a_date_read_from_the_poster_is_accepted_and_one_never_shown_is_not():
    text = "자연과학 토크 콘서트\n포스터를 참고하세요. 신청 마감 10월 10일"
    ext = concert(evidence=Evidence(event_time="10월 16일(목) 18:00", location="창의학습관 터만홀",
                                    food="참석자 전원 저녁 도시락 제공", registration=None,
                                    from_poster=["food", "event_time", "location"]))
    cand = validate(ext, analyze(text, NOW), text, reference=NOW, images=1)
    assert cand.event_start and cand.event_start.isoformat() == "2026-10-16T18:00:00+09:00"
    assert not cand.needs_review
    cand = validate(ext, analyze(text, NOW), text, reference=NOW, images=0)
    assert cand.needs_review and any("날짜" in r for r in cand.review_reasons)


def expo(**over):
    base = dict(title="INNOVATE KOREA 2026", event_start="2026-10-20T10:00:00+09:00",
                event_end="2026-10-20T17:00:00+09:00", date_text="10월 20일(월)", time_text="10:00~17:00",
                location_name="KAIST 스포츠컴플렉스", building=None, food_provided="unknown", food_type="unknown",
                food_description=None, giveaway="true", giveaway_description="경품 추첨",
                evidence=Evidence(event_time="10월 20일(월) 10:00~17:00", location="KAIST 스포츠컴플렉스", food=None,
                                  registration=None, giveaway="방문객 대상 경품 추첨 이벤트를 진행합니다."))
    base.update(over)
    return make_extraction(**base)


def test_a_prize_draw_without_food_is_a_publishable_giveaway():
    cand = validate(expo(), analyze(EXPO, NOW), EXPO, reference=NOW)
    assert cand.giveaway == "true" and cand.giveaway_description == "경품 추첨"
    assert cand.food_provided == "unknown" and not cand.needs_review


def test_a_giveaway_without_wording_in_the_quote_or_the_text_is_dropped():
    ext = expo(evidence=Evidence(event_time="10월 20일(월) 10:00~17:00", location=None, food=None,
                                 registration=None, giveaway="많은 참여 바랍니다"))
    plain = EXPO.replace("방문객 대상 경품 추첨 이벤트를 진행합니다.", "많은 참여 바랍니다.")
    cand = validate(ext, analyze(plain, NOW), plain, reference=NOW)
    assert cand.giveaway == "unknown" and "경품 근거 없음" in cand.review_reasons


def test_a_weak_giveaway_quote_is_backed_by_gift_wording_in_the_text():
    """Measured on the real expo mail: 1 run in 4 quoted '이벤트를 진행합니다' without the prize words."""
    ext = expo(evidence=Evidence(event_time="10월 20일(월) 10:00~17:00", location=None, food=None,
                                 registration=None, giveaway="이벤트를 진행합니다"))
    cand = validate(ext, analyze(EXPO, NOW), EXPO, reference=NOW)
    assert cand.giveaway == "true" and not cand.needs_review


def test_food_handed_out_is_not_also_a_giveaway():
    text = "10월 20일 12:00 N1 설명회\n참석자에게 커피 증정"
    ext = make_extraction(title="설명회", event_start="2026-10-20T12:00:00+09:00", food_type="beverage",
                          giveaway="true",
                          evidence=Evidence(event_time="10월 20일 12:00", location="N1", food="참석자에게 커피 증정",
                                            registration=None, giveaway="참석자에게 커피 증정"))
    cand = validate(ext, analyze(text, NOW), text, reference=NOW)
    assert cand.food_provided == "true" and cand.giveaway == "unknown" and not cand.needs_review


def test_a_giveaway_without_an_event_date_is_listed_until_its_deadline():
    text = "INNOVATE KOREA 사전 등록 이벤트\n사전 등록자 대상 추첨을 통해 기념품을 드립니다. 신청 마감 10월 18일 23:59"
    ext = expo(event_start=None, event_end=None, date_text=None, time_text=None, location_name=None,
               registration_required="true", registration_deadline="2026-10-18T23:59:00+09:00",
               evidence=Evidence(event_time=None, location=None, food=None, registration="신청 마감 10월 18일 23:59",
                                 giveaway="사전 등록자 대상 추첨을 통해 기념품을 드립니다."))
    cand = validate(ext, analyze(text, NOW), text, reference=NOW)
    assert cand.event_start == cand.registration_deadline and not cand.needs_review


def _row(cand, event_id):
    row = cand.to_db_row()
    row.update(id=event_id, _sources=[{"type": "dooray_mailbox", "name": "Dooray 메일함"}])
    return row


def test_the_feed_lists_free_food_and_giveaways_and_validates():
    poster_food = _row(validate(concert(), analyze(CONCERT, NOW), CONCERT, reference=NOW, images=1),
                       "11111111-1111-4111-8111-111111111111")
    gift = _row(validate(expo(), analyze(EXPO, NOW), EXPO, reference=NOW), "22222222-2222-4222-8222-222222222222")
    neither = dict(gift, id="33333333-3333-4333-8333-333333333333", giveaway="unknown", title="그냥 행사")
    settings = Settings()
    assert publication_eligible(gift, settings, food_only=True) and not publication_eligible(neither, settings, food_only=True)
    payload = build_payload([poster_food, gift, neither], settings, NOW, food_only=True)
    assert [e["title"] for e in payload["events"]] == ["자연과학 토크 콘서트", "INNOVATE KOREA 2026"]
    food_event, gift_event = payload["events"]
    assert food_event["food"]["source"] == "poster" and "giveaway" not in food_event
    assert gift_event["giveaway"] == {"provided": "true", "description": "경품 추첨"}
    assert gift_event["food"] == {"provided": "unknown", "type": "unknown", "description": ""}
    assert validate_ggongbab_payload(payload, NOW) == []
    for event in payload["events"]:                       # the DB projection round-trips both fields
        assert to_snapshot_event(public_row(event)) == event
    later = NOW + timedelta(days=10)
    archive = build_archive([poster_food, gift], settings, {poster_food["id"], gift["id"]}, later)
    assert {e["id"] for e in archive["events"]} == {poster_food["id"], gift["id"]}


def test_the_validator_refuses_a_listing_with_neither_food_nor_a_giveaway():
    payload = build_payload([_row(validate(expo(), analyze(EXPO, NOW), EXPO, reference=NOW),
                                  "22222222-2222-4222-8222-222222222222")], Settings(), NOW, food_only=True)
    event = payload["events"][0]
    event.pop("giveaway")
    assert any("unless the listing is a giveaway" in e for e in validate_ggongbab_payload(payload, NOW))
    event["giveaway"] = {"provided": "false", "description": ""}
    assert any("giveaway must be" in e for e in validate_ggongbab_payload(payload, NOW))
    event["giveaway"] = {"provided": "true", "description": "경품"}
    event["food"]["source"] = "poster"
    assert any("food.source" in e for e in validate_ggongbab_payload(payload, NOW))


def test_reference_date_is_unchanged():
    assert REFERENCE.year == 2026     # conftest's clock: the synthetic suite never reads the wall clock
