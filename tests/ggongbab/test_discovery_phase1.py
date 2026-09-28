# -*- coding: utf-8 -*-
"""Discovery v2 Phase 1: first-come semantics, flash recall, rechecks, private timing, unread safety."""
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

import dooray_web_agent as agent
from ggongbab.config import KST, PROMPT_VERSION, Settings
from ggongbab.exporter import select_public_events
from ggongbab.ingest_marker import parse_timing, render_timing, strip_timing
from ggongbab.models import Evidence
from ggongbab.parsers.ai_parser import SYSTEM_PROMPT
from ggongbab.parsers.rule_parser import (analyze, end_condition, explicit_food_evidence, food_type_hint,
                                          is_real_eligibility, registration_evidence, supply_limit)
from ggongbab.parsers.validator import validate
from ggongbab.prefilter import PREFILTER_VERSION, classify
from ggongbab.web.mail_reader import MailHeader, _from_json_rows, parse_moment
from ggongbab.web.state import AgentState, MailRecord
from ggongbab.web.task_writer import MailPayload
from ggongbab.web.ui_contract import UiContract

from .conftest import REFERENCE, make_extraction

NOW = datetime(2026, 9, 28, 11, 45, tzinfo=KST)


# --- 선착순: registration or supply --------------------------------------------------
@pytest.mark.parametrize("text", ["선착순 50명 신청", "선착순 50명 모집", "선착순 마감됩니다.", "신청은 선착순으로 마감합니다",
                                  "선착순 접수", "참가 신청은 선착순입니다"])
def test_first_come_with_sign_up_wording_is_registration(text):
    assert registration_evidence(text) == "true"
    assert not supply_limit(text)


@pytest.mark.parametrize("text", ["방문자 전원 커피 제공 (선착순, 소진 시 종료)", "커피 선착순 제공", "선착순 커피 배부",
                                  "선착순 100명에게 간식 배부", "음료 증정 (소진 시 종료)", "선착순 기념품 증정"])
def test_first_come_hand_out_is_a_supply_limit_not_registration(text):
    assert registration_evidence(text) == "unknown"
    assert supply_limit(text)


def test_first_come_without_a_verb_decides_nothing():
    assert registration_evidence("선착순 50명") == "unknown" and not supply_limit("선착순 50명")


@pytest.mark.parametrize("text,expected", [("11:30 ~ 소진 시까지", "until_sold_out"), ("재고 소진 시 조기 종료", "until_sold_out"),
                                           ("소진될 때까지 드립니다", "until_sold_out"), ("12:00~13:00", "unknown")])
def test_until_sold_out(text, expected):
    assert end_condition(text) == expected


@pytest.mark.parametrize("phrase", ["선착순, 소진 시 종료", "방문자 전원 (선착순, 소진 시 종료)", "선착순 30명 커피 제공", "선착순 배부"])
def test_supply_limits_are_not_eligibility(phrase):
    assert not is_real_eligibility(phrase)


@pytest.mark.parametrize("phrase", ["선착순 50명", "KAIST 학부생 대상, 선착순 배부", "학부생 대상"])
def test_real_restrictions_survive_supply_wording(phrase):
    assert is_real_eligibility(phrase)


@pytest.mark.parametrize("text,kind", [("방문자 전원 커피 제공", "beverage"), ("음료를 무료로 드립니다", "beverage"),
                                       ("무료 푸드트럭 운영", "meal"), ("커피차에서 커피 무료 제공", "beverage")])
def test_coffee_and_drink_hand_outs_are_explicit_provision(text, kind):
    evidence = explicit_food_evidence(text)
    assert evidence and food_type_hint(" ".join(evidence)) == kind


# --- validator ----------------------------------------------------------------------
SUPPLY_TEXT = "10월 6일 11시 학생회관 앞 홍보 부스.\n방문자 전원 커피 제공 (선착순, 소진 시 종료)"


def test_a_supply_limit_read_as_registration_is_corrected_without_review():
    facts = analyze(SUPPLY_TEXT, REFERENCE)
    ai = make_extraction(event_start="2026-10-06T11:00:00+09:00", food_type="beverage", registration_required="true",
                         evidence=Evidence(event_time="10월 6일 11시", location="학생회관 앞",
                                           food="방문자 전원 커피 제공", registration="선착순, 소진 시 종료"))
    cand = validate(ai, facts, SUPPLY_TEXT, reference=REFERENCE)
    assert cand.registration_required == "unknown"
    assert not cand.needs_review, cand.review_reasons


def test_an_unsupported_registration_claim_without_supply_wording_still_goes_to_review():
    text = "10월 6일 12시 N1 설명회.\n점심 도시락을 제공합니다."
    ai = make_extraction(event_start="2026-10-06T12:00:00+09:00", registration_required="true",
                         evidence=Evidence(event_time="10월 6일 12시", location="N1", food="점심 도시락을 제공합니다",
                                           registration=None))
    cand = validate(ai, analyze(text, REFERENCE), text, reference=REFERENCE)
    assert cand.registration_required == "unknown" and cand.needs_review


# --- prompt -------------------------------------------------------------------------
def test_prompt_separates_first_come_supply_from_registration():
    assert PROMPT_VERSION == "ggongbab-extract-v3"
    rule_6a = SYSTEM_PROMPT[SYSTEM_PROMPT.index("6a."):SYSTEM_PROMPT.index("6b.")]
    assert "선착순 신청/모집/접수/마감" in rule_6a and "SUPPLY" in rule_6a and "NOT registration" in rule_6a
    assert "(사전 신청, 신청 필수, 등록 필요,\n   선착순, RSVP" not in SYSTEM_PROMPT
    assert "소진 시 종료" in SYSTEM_PROMPT[SYSTEM_PROMPT.index("6b."):]
    assert "커피 제공" in SYSTEM_PROMPT and "event_end = null" in SYSTEM_PROMPT


# --- prefilter ----------------------------------------------------------------------
@pytest.mark.parametrize("subject,body", [
    ("커피차와 함께하는 캠퍼스 홍보 행사", ""),                       # MISS-001: subject only, no date
    ("안내", "방문자 전원 커피 제공 (선착순, 소진 시 종료)"),
    ("(광고) 캠퍼스 이벤트", "학생 여러분께 커피를 무료로 드립니다.\n수신거부는 아래 링크를 누르세요."),
    ("무료 푸드트럭", "학생회관 앞에서 운영합니다."),
])
def test_flash_hand_outs_are_candidates_without_a_date(subject, body):
    decision = classify(subject, body, NOW)
    assert decision.candidate and decision.has_provision, decision.reason


def test_transactional_body_wording_still_denies():
    assert not classify("안내", "결제 완료 영수증입니다. 커피 무료 쿠폰 증정", NOW).candidate


@pytest.mark.parametrize("subject,body,level", [
    ("캠퍼스 홍보 행사", "방문자 전원 커피 제공 (선착순, 소진 시 종료)", "high"),
    ("세미나", "2026년 9월 28일 16시 세미나, 다과 제공", "high"),          # today
    ("세미나", "10월 30일 16시 세미나, 다과 제공", "normal"),
])
def test_urgency_orders_work_but_never_decides_truth(subject, body, level):
    assert classify(subject, body, NOW).urgency == level


# --- filtered mail is rechecked when the rules change -------------------------------------
def _state(tmp_path, *, rules, received):
    state = AgentState(path=tmp_path / "s.json")
    record = MailRecord(id_hash="", subject_hash="", received=received, processed_at="2026-09-22T09:46:00+09:00",
                        registered=False, outcome="filtered", rules=rules)
    from ggongbab.web.state import digest
    record.id_hash = digest("m1")
    state.mails[record.id_hash] = record
    return state


def test_recent_mail_filtered_by_older_rules_is_looked_at_again(tmp_path):
    recent = (datetime.now(KST) - timedelta(days=2)).date().isoformat()
    assert not _state(tmp_path, rules="", received=recent).seen("m1")
    assert _state(tmp_path, rules=PREFILTER_VERSION, received=recent).seen("m1")


def test_old_filtered_mail_is_not_rechecked(tmp_path):
    old = (datetime.now(KST) - timedelta(days=30)).date().isoformat()
    assert _state(tmp_path, rules="", received=old).seen("m1")


# --- private timing -----------------------------------------------------------------
def test_receive_time_is_kept_to_the_minute_only_with_a_zone():
    assert parse_moment("2026-09-28T11:45:37+09:00") == datetime(2026, 9, 28, 11, 45, tzinfo=KST)
    assert parse_moment("2026-09-28T02:45:37Z") == datetime(2026, 9, 28, 11, 45, tzinfo=KST)
    assert parse_moment("2026-09-28 11:45") is None and parse_moment("2026-09-28") is None
    [header] = _from_json_rows([{"id": "1", "subject": "s", "createdAt": "2026-09-28T11:45:37+09:00"}])
    assert header.received == date(2026, 9, 28) and header.received_at.minute == 45


def test_timing_line_round_trips_and_is_removed():
    stamp = datetime(2026, 9, 28, 11, 47, 12, tzinfo=KST)
    line = render_timing(discovered_at=stamp)
    text = f"본문\n{line}\nmail_key=abc"
    assert parse_timing(text) == {"discovered_at": "2026-09-28T11:47:12+09:00"}
    assert "babdoduk_timing" not in strip_timing(text) and "mail_key=abc" in strip_timing(text)
    assert render_timing(discovered_at=None) == ""


def test_timing_reaches_private_metadata_but_never_the_ai_or_the_feed(settings):
    from ggongbab.collectors.dooray import DoorayCollector
    from ggongbab.parsers.sanitizer import sanitize_for_ai
    from ggongbab.web.task_writer import TaskWriter

    writer = TaskWriter.__new__(TaskWriter)
    task = writer.build_task(MailPayload(
        mail_id="m1", subject="커피차 홍보 행사", body="방문자 전원 커피 제공 (선착순, 소진 시 종료)",
        received=date(2026, 9, 28), received_at=datetime(2026, 9, 28, 11, 45, tzinfo=KST),
        discovered_at=datetime(2026, 9, 28, 11, 47, 12, tzinfo=KST)))
    content = task["body"]["content"]
    assert "Sent: 2026-09-28 11:45 (GMT+09:00)" in content and "babdoduk_timing: discovered_at=" in content
    item = DoorayCollector(settings, client=SimpleNamespace()).normalize_post(
        {"id": "p1", "subject": "커피차 홍보 행사", "createdAt": "2026-09-28T11:47:30+09:00", "body": task["body"]})
    assert item.metadata["discovered_at"] == "2026-09-28T11:47:12+09:00"
    assert item.metadata["mail_received_at"] == "2026-09-28T11:45:00+09:00"
    assert item.source_created_at == datetime(2026, 9, 28, 11, 45, tzinfo=KST)
    assert "babdoduk_timing" not in item.raw_text and "discovered_at" not in sanitize_for_ai(item.raw_text)
    row = {"id": "e1", "title": "t", "status": "published", "needs_review": False, "confidence": 0.9,
           "event_start": "2026-09-28T11:30:00+09:00", "event_end": None, "food_provided": "true",
           "food_type": "beverage", "_sources": [{"type": "dooray"}], "metadata": item.metadata}
    [public] = select_public_events([row], Settings(), NOW, food_only=True)
    assert "discovered_at" not in json.dumps(public) and "received_at" not in json.dumps(public)


# --- unread rows are never classified, opened or written in the scheduled mode --------------
def test_unread_rows_are_skipped_before_classification_body_or_write(monkeypatch):
    contract = UiContract(verified=True, list_api="https://x/mails", read_state_key="mailSummary.flags.read")
    monkeypatch.setattr(agent, "load_contract", lambda _: contract)
    monkeypatch.setattr(agent, "load_settings", lambda: None)
    monkeypatch.setattr(agent.AgentState, "load", lambda path: agent.AgentState(path=path))
    monkeypatch.setattr(agent.AgentState, "save", lambda self: None)
    monkeypatch.setattr(agent, "select_mail_page", lambda *_: None)
    headers = [MailHeader(mail_id="u1", subject="커피차 홍보 행사", preview="방문자 전원 커피 제공",
                          received=date.today(), unread=True)]
    monkeypatch.setattr(agent, "list_mails", lambda *a, **kw: headers)
    monkeypatch.setattr(agent, "classify", lambda *a, **kw: pytest.fail("an unread row was classified"))
    monkeypatch.setattr(agent, "open_body", lambda *a, **kw: pytest.fail("an unread body was opened"))

    class Writer:
        def __init__(self, *a, **kw):
            pass

        def verify_project(self):
            pass

        def create_task(self, *a, **kw):
            pytest.fail("an unread row was written")

    monkeypatch.setattr(agent, "TaskWriter", Writer)

    @contextmanager
    def session(*a, **kw):
        yield SimpleNamespace(context=None, assert_authenticated=lambda: None)

    monkeypatch.setattr(agent, "open_session", session)
    monkeypatch.setattr("sys.argv", ["agent", "--run", "--read-state", "read"])
    assert agent.main() == 0
