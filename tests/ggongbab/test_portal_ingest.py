# -*- coding: utf-8 -*-
"""Portal ingest marker, privacy-safe discovery, queue idempotency, pipeline source."""
from __future__ import annotations

import io
import json
from contextlib import redirect_stdout

from ggongbab.collectors.dooray import DoorayCollector
from ggongbab.collectors.portal import PortalCollector
from ggongbab.db.repository import MemoryRepository
from ggongbab.exporter import build_payload, public_event
from ggongbab.ingest_marker import (parse_ingest_marker, portal_content_hash, portal_external_key,
                                    render_portal_marker, strip_ingest_marker)
from ggongbab.pipeline import Pipeline
from ggongbab.portal_contract import contract_from_discovery
from ggongbab.portal_observe import path_template, sanitize_log_blob, summarize_json
from ggongbab.portal_queue import PortalQueue, decide
from ggongbab.prefilter import portal_detail_is_candidate, portal_list_warrants_detail
from ggongbab.web.task_writer import PortalPayload

from .conftest import FakeExtractor, make_extraction
from .test_pipeline_export import DOORAY_POST, FUTURE_TEXT, future_extraction
from .test_web_agent import FakeWriter


PORTAL_ID = "notice-secret-999"
TITLE = "기업 설명회 안내"
BODY = "9월 25일 12시 N1에서 기업 설명회를 진행합니다.\n참석자에게 점심 도시락을 제공합니다."


def test_portal_external_key_is_deterministic_and_opaque():
    a = portal_external_key(PORTAL_ID)
    b = portal_external_key(PORTAL_ID)
    assert a == b and len(a) == 64
    assert PORTAL_ID not in a
    assert portal_external_key("other") != a


def test_portal_marker_roundtrip_and_mail_unaffected():
    key = portal_external_key(PORTAL_ID)
    block = render_portal_marker(external_key=key, source_created_at="2026-09-20T09:00:00+09:00")
    marker = parse_ingest_marker(block + "\n\nOriginal Notice\n" + BODY)
    assert marker and marker.is_portal and marker.external_key == key and marker.private_source
    assert parse_ingest_marker("-----Original Message-----\nSubject: hello\n\n" + BODY) is None


def test_portal_task_serializes_marker_without_raw_id(settings):
    settings.dooray_token = "t"
    settings.dooray_project_id = "4424523215847914253"
    writer = FakeWriter(settings)
    writer.verify_project()
    key = portal_external_key(PORTAL_ID)
    writer.create_portal_task(PortalPayload(external_key=key, title=TITLE, body=BODY,
                                            source_created_at="2026-09-20T09:00:00+09:00"))
    blob = json.dumps(writer.posts[0], ensure_ascii=False)
    assert "[BABDODUK_INGEST_V1]" in blob and "source=portal" in blob
    assert key in blob and PORTAL_ID not in blob


def test_dooray_mail_task_stays_dooray(settings):
    settings.dooray_token = "x"
    item = DoorayCollector(settings, client=object(), fetch_attachments=False).normalize_post(DOORAY_POST)
    assert item.source_type == "dooray" and item.external_id == "3000000001"


def test_portal_marker_reaches_pipeline_as_portal(settings):
    settings.dooray_token = "x"
    key = portal_external_key(PORTAL_ID)
    post = {
        "id": "3000000099",
        "subject": TITLE,
        "createdAt": "2026-09-18T05:03:00+00:00",
        "updatedAt": "2026-09-18T05:03:00+00:00",
        "body": {"mimeType": "text/x-markdown", "content": (
            render_portal_marker(external_key=key, source_created_at="2026-09-20T12:00:00+09:00")
            + "\n\nOriginal Notice\nSubject: " + TITLE + "\n\n" + FUTURE_TEXT
        )},
        "files": [],
    }
    item = DoorayCollector(settings, client=object(), fetch_attachments=False).normalize_post(post)
    assert item.source_type == "portal"
    assert item.external_id == key
    assert item.source_url == ""
    assert PORTAL_ID not in item.raw_text
    assert "BABDODUK_INGEST_V1" not in item.raw_text
    assert "점심 도시락" in item.raw_text
    extractor = FakeExtractor(future_extraction)
    repo = MemoryRepository()
    pipe = Pipeline(settings, repo, extractor, [])
    pipe.process_item(item)
    stored = repo.find_raw_item("portal", key)
    assert stored is not None
    published = repo.publishable_events()
    assert published
    assert any(src.get("type") == "portal" for src in published[0].get("_sources") or [])
    payload = build_payload(published, settings, food_only=True)
    ev = payload["events"][0]
    assert all("url" not in src for src in ev["sources"] if src.get("type") == "portal")


def test_portal_private_url_not_exported(settings):
    row = {
        "id": "11111111-1111-1111-1111-111111111111",
        "title": "기업 설명회",
        "summary": FUTURE_TEXT,
        "event_start": "2026-09-25T12:00:00+09:00",
        "event_end": None, "registration_deadline": None,
        "date_text": "9월 25일", "time_text": "12시",
        "location_name": "N1", "building": "N1", "room": "101호",
        "food_provided": "true", "food_type": "lunchbox", "food_description": "점심 도시락 제공",
        "organizer": "", "eligibility": "", "registration_required": "unknown",
        "registration_url": "", "confidence": 0.99, "needs_review": False,
        "status": "published",
        "_sources": [{"type": "portal", "name": "KAIST Portal",
                      "url": "https://portal.kaist.ac.kr/notice/secret-id-999"}],
    }
    ev = public_event(row)
    assert ev["sources"][0]["type"] == "portal"
    assert "url" not in ev["sources"][0]


def test_append_tasks_upsert_latest_portal_content_even_when_old_task_replays(settings):
    settings.dooray_token = "x"
    settings.dooray_project_id = "4424523215847914253"
    writer = FakeWriter(settings)
    writer.verify_project()
    key = portal_external_key(PORTAL_ID)
    collector = DoorayCollector(settings, client=object(), fetch_attachments=False)
    repo = MemoryRepository()
    pipe = Pipeline(settings, repo, FakeExtractor(future_extraction), [])
    items = []
    for number, extra in ((1, "이전 장소"), (2, "변경된 최신 장소")):
        writer.create_portal_task(PortalPayload(external_key=key, title=TITLE,
                                                body=FUTURE_TEXT + "\n" + extra,
                                                source_created_at="2026-09-18T12:00:00+09:00"))
        post = {
            **writer.posts[-1]["body"],
            "id": f"different-task-{number}", "subject": TITLE,
            "createdAt": f"2026-09-{18 + number}T05:03:00+00:00",
            "updatedAt": f"2026-09-{18 + number}T05:03:00+00:00",
            "files": [],
        }
        item = collector.normalize_post(post)
        items.append(item)
        pipe.process_item(item)
    latest = repo.find_raw_item("portal", key)
    assert len(repo.raw_items) == 1
    assert "변경된 최신 장소" in latest["raw_text"]
    assert latest["content_hash"] == items[1].content_hash
    pipe.process_item(items[0])
    replayed = repo.find_raw_item("portal", key)
    assert replayed["id"] == latest["id"]
    assert replayed["raw_text"] == latest["raw_text"]
    assert replayed["content_hash"] == latest["content_hash"]


def test_unchanged_portal_notice_skips_queue(tmp_path):
    queue = PortalQueue(tmp_path / "state.json")
    first = queue.decide(PORTAL_ID, TITLE, BODY)
    assert first.outcome == "new"
    queue.record(first)
    queue.save()
    again = PortalQueue(tmp_path / "state.json")
    second = again.decide(PORTAL_ID, TITLE, BODY)
    assert second.outcome == "skip"
    changed = again.decide(PORTAL_ID, TITLE, BODY + "\n장소 변경")
    assert changed.outcome == "update"
    blob = (tmp_path / "state.json").read_text(encoding="utf-8")
    assert PORTAL_ID not in blob and TITLE not in blob and "도시락" not in blob


def test_content_hash_changes_with_body():
    assert portal_content_hash(TITLE, BODY) != portal_content_hash(TITLE, BODY + " x")
    assert decide({}, PORTAL_ID, TITLE, BODY).outcome == "new"


def test_discovery_summaries_have_no_values():
    payload = {
        "result": [
            {"id": PORTAL_ID, "title": TITLE, "createdAt": "2026-09-20", "secret": "token-value"},
            {"id": "n2", "title": "다른 제목", "createdAt": "2026-09-21"},
        ]
    }
    summary = summarize_json(payload)
    blob = json.dumps(summary, ensure_ascii=False)
    assert PORTAL_ID not in blob and TITLE not in blob and "token-value" not in blob
    assert "id" in summary["arrays"][0]["rowKeys"]
    assert path_template("/board/notices/12345/detail") == "/board/notices/<v>/detail"
    assert "<id>" in sanitize_log_blob("saw abcdef12345678")


def test_calibration_missing_list_fails_closed():
    assert contract_from_discovery({"listCandidates": [], "detailCandidates": []}) is None
    weak = contract_from_discovery({
        "listCandidates": [{"method": "GET", "host": "x", "path": "/unknown", "rowKeys": ["foo"]}],
        "detailCandidates": [],
    })
    assert weak is None or not weak.list_ready()


def test_portal_prefilter_reuses_event_food_words():
    assert portal_list_warrants_detail("기업 설명회 안내")
    assert portal_list_warrants_detail("세미나 일정")
    assert not portal_list_warrants_detail("비밀번호 변경 안내")
    ok = portal_detail_is_candidate("기업 설명회", BODY, has_list_date=True)
    assert ok.candidate
    lunch_only = portal_detail_is_candidate(
        "정기 세미나", "참석자에게 점심 도시락을 제공합니다.", has_list_date=True)
    assert lunch_only.candidate


def test_portal_collector_stays_disabled_in_cloud(settings):
    collector = PortalCollector(settings)
    assert collector.enabled() is False and collector.collect() == []


def test_raw_portal_id_not_logged_by_queue_helpers(tmp_path):
    buf = io.StringIO()
    with redirect_stdout(buf):
        queue = PortalQueue(tmp_path / "s.json")
        decision = queue.decide(PORTAL_ID, TITLE, BODY)
        queue.record(decision)
        queue.save()
    assert PORTAL_ID not in buf.getvalue()
    stripped = strip_ingest_marker(render_portal_marker(external_key="abc") + "\n\nOriginal Notice\n" + BODY)
    assert "BABDODUK" not in stripped and "도시락" in stripped
