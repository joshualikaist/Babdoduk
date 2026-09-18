# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from ggongbab.collectors.base import Collector, CollectorError
from ggongbab.collectors.dooray import DoorayCollector
from ggongbab.collectors.kaist_public import KaistPublicCollector, parse_card_list, parse_table_list
from ggongbab.collectors.manual import ManualCollector
from ggongbab.config import KST
from ggongbab.db.repository import MemoryRepository
from ggongbab.exporter import build_payload, write_payload
from ggongbab.models import Evidence, RawItem
from ggongbab.pipeline import Pipeline

from .conftest import NEGATIVE_TEXT, POSITIVE_TEXT, REFERENCE, FakeExtractor, make_extraction

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from validate_content import validate_ggongbab  # noqa: E402

FUTURE = (datetime.now(KST) + timedelta(days=3)).replace(hour=12, minute=0, second=0, microsecond=0)
FUTURE_TEXT = f"{FUTURE.month}월 {FUTURE.day}일 12시 N1에서 기업 설명회를 진행합니다.\n참석자에게 점심 도시락을 제공합니다."
DOORAY_POST = {
    "id": "3000000001",
    "subject": "FW: [안내] 기업 설명회",
    "createdAt": "2026-09-18T05:03:00+00:00",
    "updatedAt": "2026-09-18T05:03:00+00:00",
    "body": {"mimeType": "text/html", "content": (
        "<p>-----Original Message-----</p><p>From: \"김담당\" &lt;staff.kim@kaist.ac.kr&gt;<br>"
        "To: all@kaist.ac.kr<br>Sent: 2026-09-18 14:03 (GMT+09:00)<br>Subject: [안내] 기업 설명회</p>"
        "<p></p><p>" + FUTURE_TEXT.replace("\n", "<br>") + "</p><img src=\"/files/abcdef123456\">")},
    "files": [{"id": "abcdef123456", "name": "poster.png", "size": 1024}],
}


def future_extraction(text: str):
    return make_extraction(
        title="기업 설명회", event_start=FUTURE.isoformat(),
        date_text=f"{FUTURE.month}월 {FUTURE.day}일",
        evidence=Evidence(event_time=f"{FUTURE.month}월 {FUTURE.day}일 12시", location="N1에서",
                          food="참석자에게 점심 도시락을 제공합니다", registration=None))


class ListCollector(Collector):
    source_type = "manual"

    def __init__(self, items, fail=False):
        self.items = items
        self.fail = fail

    def collect(self):
        if self.fail:
            raise CollectorError("outage")
        return self.items


def _item(ext_id="post-1", text=FUTURE_TEXT, source="dooray", subject="기업 설명회"):
    return RawItem(source_type=source, external_id=ext_id, subject=subject, raw_text=text,
                   sender_email="staff.kim@kaist.ac.kr", source_created_at=REFERENCE)


# --- pipeline -------------------------------------------------------------------
def test_pipeline_end_to_end_and_idempotent(settings):
    repo = MemoryRepository()
    extractor = FakeExtractor(future_extraction)
    pipe = Pipeline(settings, repo, extractor, [ListCollector([_item()])])
    stats = pipe.run()
    assert stats.events_created == 1 and stats.ai_calls == 1 and stats.ai_fallback == 0
    assert len(repo.events) == 1 and len(repo.ai_runs) == 1
    event = next(iter(repo.events.values()))
    assert event["status"] == "published" and event["food_type"] == "lunchbox"
    assert repo.ai_runs[0]["usage_input_tokens"] == 120 and repo.ai_runs[0]["model"] == "gpt-5.6-luna"
    # PII must not reach the model
    sent = extractor.calls[0][1]
    assert "kaist.ac.kr" not in sent and "SUBJECT: 기업 설명회" in sent

    # second run: same post, same hash -> no AI, no new event
    pipe2 = Pipeline(settings, repo, extractor, [ListCollector([_item()])])
    stats2 = pipe2.run()
    assert stats2.ai_calls == 0 and stats2.ai_skipped == 1 and stats2.events_created == 0
    assert len(repo.events) == 1 and len(extractor.calls) == 1

    # changed content -> re-parse, merged into the same event
    changed = _item(text=FUTURE_TEXT + "\n신청: https://forms.gle/zzz")
    pipe3 = Pipeline(settings, repo, extractor, [ListCollector([changed])])
    stats3 = pipe3.run()
    assert stats3.ai_calls == 1 and stats3.events_updated == 1 and len(repo.events) == 1


def test_pipeline_dedups_across_sources(settings):
    repo = MemoryRepository()
    extractor = FakeExtractor(future_extraction)
    items = [_item("post-1", source="dooray"), _item("kaist-0802:abc", source="kaist_public")]
    Pipeline(settings, repo, extractor, [ListCollector(items)]).run()
    assert len(repo.events) == 1
    event_id = next(iter(repo.events))
    linked = [r for (e, r) in repo.event_sources if e == event_id]
    assert len(linked) == 2
    published = repo.publishable_events()
    assert {s["type"] for s in published[0]["_sources"]} == {"dooray", "kaist_public"}


def test_pipeline_fallback_only_when_ambiguous(settings):
    repo = MemoryRepository()

    def primary(text):
        # claims food from a time-of-day phrase -> validator flags -> fallback
        return make_extraction(event_start=FUTURE.isoformat(), food_provided="true", food_type="meal",
                               evidence=Evidence(event_time="12시", location="N1", food="12시 점심시간에", registration=None))

    def fallback(text):
        return make_extraction(event_start=FUTURE.isoformat(), food_provided="unknown", food_type="unknown",
                               evidence=Evidence(event_time="12시", location="N1", food=None, registration=None))

    extractor = FakeExtractor(primary, fallback)
    neg = _item(text=NEGATIVE_TEXT.replace("9월 25일", f"{FUTURE.month}월 {FUTURE.day}일"))
    stats = Pipeline(settings, repo, extractor, [ListCollector([neg])]).run()
    assert stats.ai_fallback == 1 and len(extractor.calls) == 2
    assert extractor.calls[1][0] == "gpt-5.6-terra"
    event = next(iter(repo.events.values()))
    assert event["food_provided"] != "true"
    assert [r["role"] for r in repo.ai_runs] == ["primary", "fallback"]


def test_pipeline_ai_failure_keeps_raw_item_retryable(settings):
    repo = MemoryRepository()
    failing = FakeExtractor(lambda text: None)
    stats = Pipeline(settings, repo, failing, [ListCollector([_item()])]).run()
    assert stats.ai_errors == 1 and len(repo.events) == 0 and len(repo.raw_items) == 1
    assert repo.ai_runs[0]["status"] == "error"
    ok = FakeExtractor(future_extraction)
    stats2 = Pipeline(settings, repo, ok, [ListCollector([_item()])]).run()
    assert stats2.ai_calls == 1 and len(repo.events) == 1


def test_pipeline_collector_outage_is_recorded(settings):
    repo = MemoryRepository()
    stats = Pipeline(settings, repo, FakeExtractor(future_extraction), [ListCollector([], fail=True)]).run()
    assert stats.collector_errors == {"manual": "outage"}
    assert list(repo.ingest_runs.values())[0]["status"] == "failed"


# --- collectors ----------------------------------------------------------------
def test_dooray_normalize_post(settings):
    settings.dooray_token = "x"
    collector = DoorayCollector(settings, client=object(), fetch_attachments=False)
    item = collector.normalize_post(DOORAY_POST)
    assert item.external_id == "3000000001"
    assert item.subject == "[안내] 기업 설명회"
    assert item.sender_email == "staff.kim@kaist.ac.kr"
    assert item.source_created_at == datetime(2026, 9, 18, 14, 3, tzinfo=KST)
    assert "점심 도시락을 제공" in item.raw_text and "Original Message" not in item.raw_text
    assert [a.external_file_id for a in item.attachments] == ["abcdef123456"]
    assert item.metadata["to_count"] == 1


def test_manual_collector(settings, tmp_path):
    path = tmp_path / "manual.json"
    path.write_text(json.dumps({"items": [{"id": "m1", "title": "T", "text": FUTURE_TEXT, "date": "2026-09-19"}]}), encoding="utf-8")
    items = ManualCollector(settings, path).collect()
    assert len(items) == 1 and items[0].source_type == "manual" and items[0].external_id == "m1"


def test_kaist_public_parsers_and_filter(settings):
    table = ("<tr id='BBSListf18cddccb9ccb689202859d0e37d5f65'><td class=ntt_no>573</td><td class=title>"
             "<a href='?mode=V&amp;no=f18cddccb9ccb689202859d0e37d5f65&amp;GotoPage=1'>[학사] 취업 설명회 안내</a></td>"
             "<td class=wrt>학사팀</td><td class=inq_cnt>1</td><td class=reg_date>2026-09-16</td></tr>")
    rows = parse_table_list(table, "https://www.kaist.ac.kr/kr/html/footer/0802.html")
    assert rows[0]["id"] == "f18cddccb9ccb689202859d0e37d5f65" and rows[0]["date"] == "2026-09-16"
    assert rows[0]["url"].endswith("0802.html?mode=V&no=f18cddccb9ccb689202859d0e37d5f65&GotoPage=1")
    card = ('<div class="item"><strong class="ui-list__title">피아노 리사이틀</strong><ul class="list-1st">'
            '<li><em>장소</em><span>대강당(E15)&nbsp;</span></li></ul>'
            '<a class="btn" href="/kr/html/campus/053501.html?mode=V&amp;mng_no=7081">')
    cards = parse_card_list(card, "https://www.kaist.ac.kr/kr/html/campus/053501.html")
    assert cards[0]["id"] == "7081" and "장소: 대강당(E15)" in cards[0]["meta"]

    pages = {
        "https://x/list": table,
        "https://x/list?mode=V&no=f18cddccb9ccb689202859d0e37d5f65&GotoPage=1":
            '<div class="ui bbs--view--content"><p>' + FUTURE_TEXT + '</p></div></div></div>',
    }
    settings.kaist_public_enabled = True
    collector = KaistPublicCollector(settings, boards=[{"key": "t", "name": "T", "url": "https://x/list", "kind": "table"}],
                                     fetch=lambda url: pages[url])
    items = collector.collect()
    assert len(items) == 1 and items[0].external_id == "t:f18cddccb9ccb689202859d0e37d5f65"
    assert items[0].source_url == "https://x/list?mode=V&no=f18cddccb9ccb689202859d0e37d5f65&GotoPage=1"


# --- export ---------------------------------------------------------------------
def _published_row(**over):
    row = {"id": "11111111-1111-1111-1111-111111111111", "title": "기업 설명회", "summary": "요약",
           "event_start": FUTURE.isoformat(), "event_end": None, "registration_deadline": None,
           "date_text": "", "time_text": "", "location_name": "N1", "building": "N1", "room": "101호",
           "food_provided": "true", "food_type": "lunchbox", "food_description": "점심 도시락 제공",
           "organizer": "경력개발센터", "eligibility": "", "registration_required": "true",
           "registration_url": "https://forms.gle/a", "confidence": 0.9, "needs_review": False,
           "review_reason": None, "status": "published",
           "_sources": [{"type": "dooray", "name": "Dooray", "url": ""}]}
    row.update(over)
    return row


def test_export_privacy_and_validation(settings, tmp_path):
    rows = [
        _published_row(),
        _published_row(id="2", status="review", needs_review=True),
        _published_row(id="3", confidence=0.3),
        _published_row(id="4", event_start=(datetime.now(KST) - timedelta(days=2)).isoformat()),
    ]
    payload = build_payload(rows, settings)
    assert payload["count"] == 1
    ev = payload["events"][0]
    assert ev["food"] == {"provided": True, "type": "lunchbox", "description": "점심 도시락 제공"}
    assert ev["sources"] == [{"type": "dooray", "name": "Dooray"}]
    assert "review_reason" not in ev and "sender_email" not in json.dumps(payload)
    path = write_payload(payload, tmp_path)
    assert validate_ggongbab(path) == []


def test_export_validator_catches_private_fields(tmp_path):
    bad = {"generatedAt": datetime.now(KST).isoformat(), "timezone": "Asia/Seoul", "events": [{
        "id": "a", "title": "x", "startAt": FUTURE.isoformat(), "confidence": 0.9,
        "food": {"provided": True, "type": "meal"}, "registration": {}, "sources": [{"type": "dooray", "name": "Dooray"}],
        "sender_email": "a@b.com", "raw_text": "hi"}, {
        "id": "a", "title": "x", "startAt": (datetime.now(KST) - timedelta(days=3)).isoformat(), "confidence": 2,
        "food": {"provided": "yes", "type": "pizza"}, "registration": {"url": "javascript:alert(1)"}, "sources": []}]}
    path = tmp_path / "latest.json"
    path.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    errors = validate_ggongbab(path)
    joined = "\n".join(errors)
    for needle in ("e-mail address", "private field", "duplicate id", "expired", "confidence out of range",
                   "food.provided must be boolean", "food.type invalid", "registration.url invalid", "has no sources"):
        assert needle in joined, needle


def test_refresh_dry_run_runs(settings, tmp_path, monkeypatch):
    import subprocess

    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "refresh_ggongbab.py"), "--dry-run", "--only", "manual"],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"timezone": "Asia/Seoul"' in result.stdout
