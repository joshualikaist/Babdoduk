# -*- coding: utf-8 -*-
"""Mailbox backfill: archive parsing, prefilter, safety limits, dedup, idempotency."""
from __future__ import annotations

import email.policy
import zipfile
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

import pytest

from ggongbab.backfill import run_backfill
from ggongbab.collectors.base import CollectorError
from ggongbab.collectors.mail_archive import (MailArchiveCollector, message_to_raw_item,
                                              read_state_of)
from ggongbab.config import KST
from ggongbab.db.repository import MemoryRepository
from ggongbab.pipeline import Pipeline
from ggongbab.prefilter import classify

from .conftest import FakeExtractor
from .test_pipeline_export import FUTURE, FUTURE_TEXT, ListCollector, _item, future_extraction

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 9000
GGONGBAB_BODY = (f"{FUTURE.month}월 {FUTURE.day}일 12시 N1 101호에서 삼성전자 Tech Lunch Talk을 진행합니다.\n"
                 "참석자에게 점심 도시락을 제공합니다.\n"
                 "문의: staff.kim@kaist.ac.kr, 042-350-1234\n김담당 드림")


def make_eml(subject: str, body: str, received: datetime, *, message_id: str = "<a@kaist.ac.kr>",
             read: bool | None = None, html: str = "", attach_png: bool = False) -> bytes:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = '"김담당" <staff.kim@kaist.ac.kr>'
    msg["To"] = "all-students@kaist.ac.kr"
    msg["Cc"] = "dept-office@kaist.ac.kr"
    msg["Date"] = received.strftime("%a, %d %b %Y %H:%M:%S %z")
    msg["Message-ID"] = message_id
    if read is not None:
        msg["Status"] = "RO" if read else "O"
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
    if attach_png:
        msg.add_attachment(PNG, maintype="image", subtype="png", filename="poster.png")
    return msg.as_bytes(policy=email.policy.default)


def write_eml(tmp_path: Path, name: str, **kw) -> Path:
    path = tmp_path / name
    path.write_bytes(make_eml(**kw))
    return path


RECEIVED = datetime(2026, 9, 3, 10, 0, tzinfo=KST)


# --- archive parsing ----------------------------------------------------------
def test_eml_parsed_into_raw_item(settings, tmp_path):
    write_eml(tmp_path, "a.eml", subject="삼성전자 Tech Lunch Talk", body=GGONGBAB_BODY, received=RECEIVED)
    items = MailArchiveCollector(settings, tmp_path).collect()
    assert len(items) == 1
    item = items[0]
    assert item.source_type == "dooray_mailbox"
    assert item.external_id == "a@kaist.ac.kr"
    assert item.subject == "삼성전자 Tech Lunch Talk"
    assert item.source_created_at == RECEIVED
    assert "점심 도시락을 제공합니다" in item.raw_text
    assert item.metadata["backfill"] is True


def test_read_mail_is_included(settings, tmp_path):
    """The whole point of the backfill: already-read mail must be processed."""
    write_eml(tmp_path, "read.eml", subject="채용 설명회", body=GGONGBAB_BODY, received=RECEIVED, read=True)
    items = MailArchiveCollector(settings, tmp_path, read_state="all").collect()
    assert len(items) == 1 and items[0].metadata["read_state"] == "read"
    only_read = MailArchiveCollector(settings, tmp_path, read_state="read").collect()
    assert len(only_read) == 1


def test_unread_mail_included_when_state_all(settings, tmp_path):
    write_eml(tmp_path, "r.eml", subject="채용 설명회", body=GGONGBAB_BODY, received=RECEIVED,
              read=True, message_id="<r@x>")
    write_eml(tmp_path, "u.eml", subject="채용 설명회", body=GGONGBAB_BODY, received=RECEIVED,
              read=False, message_id="<u@x>")
    states = {i.metadata["read_state"] for i in MailArchiveCollector(settings, tmp_path, read_state="all").collect()}
    assert states == {"read", "unread"}
    unread = MailArchiveCollector(settings, tmp_path, read_state="unread").collect()
    assert [i.metadata["read_state"] for i in unread] == ["unread"]


def test_missing_read_flag_is_never_excluded(settings, tmp_path):
    """Plain .eml exports carry no Status header; dropping them would lose mail."""
    write_eml(tmp_path, "n.eml", subject="채용 설명회", body=GGONGBAB_BODY, received=RECEIVED)
    for state in ("all", "read", "unread"):
        items = MailArchiveCollector(settings, tmp_path, read_state=state).collect()
        assert len(items) == 1, state
        assert items[0].metadata["read_state"] == "unknown"


def test_date_range_filters_by_received_date(settings, tmp_path):
    write_eml(tmp_path, "aug.eml", subject="설명회", body=GGONGBAB_BODY,
              received=datetime(2026, 8, 20, 9, 0, tzinfo=KST), message_id="<aug@x>")
    write_eml(tmp_path, "sep.eml", subject="설명회", body=GGONGBAB_BODY, received=RECEIVED, message_id="<sep@x>")
    collector = MailArchiveCollector(settings, tmp_path, mail_from=date(2026, 9, 1), mail_to=date(2026, 9, 19))
    items = collector.collect()
    assert [i.external_id for i in items] == ["sep@x"]
    assert collector.stats.out_of_range == 1


def test_mbox_and_zip_and_directory(settings, tmp_path):
    a = make_eml(subject="설명회 A", body=GGONGBAB_BODY, received=RECEIVED, message_id="<m1@x>")
    b = make_eml(subject="설명회 B", body=GGONGBAB_BODY, received=RECEIVED, message_id="<m2@x>")
    mbox = tmp_path / "box.mbox"
    mbox.write_bytes(b"From someone@example.com Mon Sep  3 10:00:00 2026\n" + a +
                     b"\nFrom someone@example.com Mon Sep  3 10:01:00 2026\n" + b)
    assert {i.external_id for i in MailArchiveCollector(settings, mbox).collect()} == {"m1@x", "m2@x"}

    zip_path = tmp_path / "export.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("mail/1.eml", a)
        zf.writestr("mail/2.eml", b)
    assert len(MailArchiveCollector(settings, zip_path).collect()) == 2

    nested = tmp_path / "folder" / "sub"
    nested.mkdir(parents=True)
    (nested / "1.eml").write_bytes(a)
    (tmp_path / "folder" / "2.eml").write_bytes(b)
    assert len(MailArchiveCollector(settings, tmp_path / "folder").collect()) == 2


def test_duplicate_export_of_same_message_collapses(settings, tmp_path):
    payload = make_eml(subject="설명회", body=GGONGBAB_BODY, received=RECEIVED, message_id="<same@x>")
    (tmp_path / "1.eml").write_bytes(payload)
    (tmp_path / "copy.eml").write_bytes(payload)
    assert len(MailArchiveCollector(settings, tmp_path).collect()) == 1


def test_max_mails_guard(settings, tmp_path):
    for i in range(6):
        write_eml(tmp_path, f"{i}.eml", subject="설명회", body=GGONGBAB_BODY,
                  received=RECEIVED, message_id=f"<m{i}@x>")
    with pytest.raises(CollectorError, match="max-mails"):
        MailArchiveCollector(settings, tmp_path, max_mails=3).collect()


def test_html_only_mail_becomes_text(settings, tmp_path):
    msg = EmailMessage()
    msg["Subject"] = "설명회 안내"
    msg["From"] = "a@b.com"
    msg["Date"] = RECEIVED.strftime("%a, %d %b %Y %H:%M:%S %z")
    msg["Message-ID"] = "<h@x>"
    msg.set_content("<p>9월 25일 12시 N1</p><p>점심 도시락 제공</p>", subtype="html")
    (tmp_path / "h.eml").write_bytes(msg.as_bytes(policy=email.policy.default))
    item = MailArchiveCollector(settings, tmp_path).collect()[0]
    assert "9월 25일 12시 N1" in item.raw_text and "<p>" not in item.raw_text


def test_read_state_of_headers():
    msg = EmailMessage()
    assert read_state_of(msg) == "unknown"
    msg["Status"] = "RO"
    assert read_state_of(msg) == "read"


def test_mailbox_is_never_mutated(settings, tmp_path):
    """The collector only reads files; nothing can mark a message read."""
    import inspect

    from ggongbab.collectors import mail_archive

    source = inspect.getsource(mail_archive)
    for forbidden in ("urlopen", "requests.", "http.client", ".post(", ".patch(", ".delete(", "write_bytes", "unlink"):
        assert forbidden not in source, forbidden
    path = write_eml(tmp_path, "a.eml", subject="설명회", body=GGONGBAB_BODY, received=RECEIVED)
    before = path.read_bytes(), path.stat().st_mtime
    MailArchiveCollector(settings, tmp_path).collect()
    assert (path.read_bytes(), path.stat().st_mtime) == before


# --- prefilter ----------------------------------------------------------------
@pytest.mark.parametrize("subject,body", [
    ("점심 뭐 먹지", "오늘 점심 같이 먹을래?"),
    ("[결제 완료] 영수증 안내", "카드 승인 12,000원"),
    ("비밀번호 재설정 안내", "인증 번호는 123456 입니다"),
    ("뉴스레터 구독 안내", "수신 거부는 아래 링크"),
    ("회의록 공유", "지난주 회의 내용을 공유드립니다"),
    ("Undelivered Mail Returned to Sender", "delivery status notification"),
])
def test_prefilter_rejects_obvious_non_event(subject, body):
    assert not classify(subject, body).candidate


def test_prefilter_accepts_strong_ggongbab_mail():
    d = classify("삼성전자 Tech Lunch Talk", GGONGBAB_BODY)
    assert d.candidate and d.strong
    assert d.has_event_word and d.has_food_word and d.has_date


def test_prefilter_accepts_lunch_time_seminar_without_food_word():
    """'12시 세미나' is a candidate, but that alone is never food evidence."""
    d = classify("연구 세미나", "9월 25일 12시에 세미나를 진행합니다.")
    assert d.candidate and not d.strong
    assert d.has_meal_time and not d.has_food_word


def test_prefilter_rejects_event_without_date():
    assert not classify("세미나 안내", "곧 세미나를 열 예정입니다.").candidate


def test_prefilter_never_decides_food_provided():
    """Keyword presence must not leak into the food decision - that needs the validator."""
    from ggongbab.parsers.rule_parser import explicit_food_evidence

    body = "9월 25일 12시 점심시간에 세미나를 진행합니다."
    assert classify("세미나", body).candidate
    assert explicit_food_evidence(body) == []


# --- backfill driver ----------------------------------------------------------
def archive_items(settings, tmp_path, count=1, subject="삼성전자 Tech Lunch Talk", body=None):
    for i in range(count):
        write_eml(tmp_path, f"{i}.eml", subject=subject, body=body or GGONGBAB_BODY,
                  received=RECEIVED, message_id=f"<mail{i}@kaist.ac.kr>")
    return MailArchiveCollector(settings, tmp_path).collect()


def test_backfill_end_to_end_and_pii_sanitized(settings, tmp_path):
    items = archive_items(settings, tmp_path)
    repo = MemoryRepository()
    extractor = FakeExtractor(future_extraction)
    report = run_backfill(settings, repo, extractor, items, event_until=date(2026, 9, 30))
    assert report.scanned == 1 and report.rule_candidates == 1 and report.ai_candidates == 1
    assert report.likely_events == 1 and report.food_provided == 1 and report.in_window == 1
    sent = extractor.calls[0][1]
    assert "staff.kim@kaist.ac.kr" not in sent and "kaist.ac.kr" not in sent
    assert "042-350-1234" not in sent
    assert "점심 도시락을 제공합니다" in sent
    assert len(repo.events) == 1
    event_id = next(iter(repo.events))
    raw_id = next(iter(repo.raw_items))
    assert (event_id, raw_id) in repo.event_sources


def test_backfill_second_run_makes_no_ai_call(settings, tmp_path):
    repo = MemoryRepository()
    extractor = FakeExtractor(future_extraction)
    first = run_backfill(settings, repo, extractor, archive_items(settings, tmp_path), event_until=date(2026, 9, 30))
    assert first.ai_calls == 1

    second = run_backfill(settings, repo, extractor, archive_items(settings, tmp_path), event_until=date(2026, 9, 30))
    assert second.scanned == 1 and second.rule_candidates == 1
    assert second.ai_calls == 0 and second.ai_skipped == 1
    assert len(extractor.calls) == 1
    assert len(repo.events) == 1 and len(repo.raw_items) == 1
    assert len(repo.ai_runs) == 1


def test_backfill_attachment_not_reloaded_when_cached(settings, tmp_path):
    write_eml(tmp_path, "p.eml", subject="설명회", body=GGONGBAB_BODY, received=RECEIVED,
              message_id="<p@x>", attach_png=True)
    repo = MemoryRepository()
    extractor = FakeExtractor(future_extraction)
    items = MailArchiveCollector(settings, tmp_path).collect()
    run_backfill(settings, repo, extractor, items, event_until=date(2026, 9, 30))
    assert extractor.calls[0][2] == 1, "poster should reach the model on the first pass"

    fresh = MailArchiveCollector(settings, tmp_path).collect()
    run_backfill(settings, repo, extractor, fresh, event_until=date(2026, 9, 30))
    assert len(extractor.calls) == 1
    assert fresh[0].attachments[0].data is None, "cached mail must not decode its attachment"


def test_backfill_max_ai_candidates_stops_before_any_call(settings, tmp_path):
    items = archive_items(settings, tmp_path, count=4)
    extractor = FakeExtractor(future_extraction)
    report = run_backfill(settings, MemoryRepository(), extractor, items, max_ai_candidates=2)
    assert report.stopped_reason and "max-ai-candidates" in report.stopped_reason
    assert report.ai_candidates == 0 and extractor.calls == []


def test_backfill_force_overrides_limit(settings, tmp_path):
    items = archive_items(settings, tmp_path, count=3)
    extractor = FakeExtractor(future_extraction)
    report = run_backfill(settings, MemoryRepository(), extractor, items, max_ai_candidates=2, force=True)
    assert report.stopped_reason is None and report.ai_candidates == 3


def test_backfill_no_ai_makes_no_call(settings, tmp_path):
    extractor = FakeExtractor(future_extraction)
    report = run_backfill(settings, MemoryRepository(), extractor, archive_items(settings, tmp_path), use_ai=False)
    assert extractor.calls == [] and report.rule_candidates == 1


def test_dry_run_writes_no_events(settings, tmp_path):
    """--dry-run uses an in-memory repository, so the real DB and latest.json are untouched."""
    repo = MemoryRepository()
    run_backfill(settings, repo, FakeExtractor(future_extraction), archive_items(settings, tmp_path))
    assert len(repo.events) == 1        # only in memory
    report_text = run_backfill(settings, MemoryRepository(), FakeExtractor(future_extraction),
                               archive_items(settings, tmp_path)).render(date(2026, 9, 30), dry_run=True)
    assert "DRY RUN - nothing was written" in report_text


# --- cross-source dedup -------------------------------------------------------
def test_mailbox_then_project_does_not_create_second_event(settings, tmp_path):
    """The same mail arrives twice: once from the export, once as an auto-classified task."""
    repo = MemoryRepository()
    extractor = FakeExtractor(future_extraction)
    run_backfill(settings, repo, extractor, archive_items(settings, tmp_path), event_until=date(2026, 9, 30))
    assert len(repo.events) == 1

    project_item = _item(ext_id="3000000001", source="dooray", subject="삼성전자 Tech Lunch Talk")
    stats = Pipeline(settings, repo, extractor, [ListCollector([project_item])]).run()
    assert stats.events_created == 0 and stats.events_updated == 1
    assert len(repo.events) == 1
    event_id = next(iter(repo.events))
    assert len([r for (e, r) in repo.event_sources if e == event_id]) == 2
    types = {s["type"] for s in repo.publishable_events()[0]["_sources"]}
    assert types == {"dooray_mailbox", "dooray"}


def test_project_then_mailbox_does_not_create_second_event(settings, tmp_path):
    repo = MemoryRepository()
    extractor = FakeExtractor(future_extraction)
    Pipeline(settings, repo, extractor, [ListCollector([_item(source="dooray")])]).run()
    run_backfill(settings, repo, extractor, archive_items(settings, tmp_path), event_until=date(2026, 9, 30))
    assert len(repo.events) == 1


# --- expiry -------------------------------------------------------------------
def test_past_event_stored_but_not_exported(settings, tmp_path):
    from ggongbab.exporter import build_payload

    past = (datetime.now(KST) - timedelta(days=4)).replace(hour=12, minute=0, second=0, microsecond=0)
    # The body must state the same past date, otherwise the validator rightly
    # rejects the extraction as a date conflict and there is nothing to test here.
    past_body = (f"{past.month}월 {past.day}일 12시 N1 101호에서 설명회를 진행했습니다.\n"
                 "참석자에게 점심 도시락을 제공합니다.")
    repo = MemoryRepository()

    def past_extraction(text):
        return future_extraction(text).model_copy(update={
            "event_start": past.isoformat(),
            "date_text": f"{past.month}월 {past.day}일",
            "evidence": future_extraction(text).evidence.model_copy(
                update={"event_time": f"{past.month}월 {past.day}일 12시"}),
        })

    items = archive_items(settings, tmp_path, body=past_body)
    report = run_backfill(settings, repo, FakeExtractor(past_extraction), items, event_until=date(2026, 9, 30))
    assert report.likely_events == 1 and report.past_events == 1 and report.in_window == 0
    assert len(repo.events) == 1, "a past event is still recorded in the database"
    assert build_payload(repo.publishable_events(), settings)["count"] == 0, "but never published"


def test_future_september_event_is_exported(settings, tmp_path):
    from ggongbab.exporter import build_payload

    repo = MemoryRepository()
    run_backfill(settings, repo, FakeExtractor(future_extraction), archive_items(settings, tmp_path),
                 event_until=date(2026, 9, 30))
    payload = build_payload(repo.publishable_events(), settings)
    assert payload["count"] == 1
    ev = payload["events"][0]
    assert ev["food"]["provided"] == "true" and ev["startAt"].endswith("+09:00")
    assert ev["sources"] == [{"type": "dooray_mailbox", "name": "Dooray 메일함"}]


def test_public_export_holds_no_mail_internals(settings, tmp_path):
    import json
    import sys

    from ggongbab.exporter import build_payload, write_payload

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from validate_content import validate_ggongbab

    repo = MemoryRepository()
    run_backfill(settings, repo, FakeExtractor(future_extraction), archive_items(settings, tmp_path))
    payload = build_payload(repo.publishable_events(), settings)
    blob = json.dumps(payload, ensure_ascii=False)
    for leak in ("staff.kim", "kaist.ac.kr", "Message-ID", "mail0@", "042-350"):
        assert leak not in blob, leak
    assert validate_ggongbab(write_payload(payload, tmp_path / "out")) == []
