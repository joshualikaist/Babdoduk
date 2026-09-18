# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime

from ggongbab.config import KST
from ggongbab.parsers.dooray_mail import parse_original_message, parse_sent
from ggongbab.parsers.html_text import html_to_text, inline_file_ids
from ggongbab.parsers.rule_parser import analyze, extract_dates, extract_times, explicit_food_evidence
from ggongbab.parsers.sanitizer import contains_pii, sanitize_for_ai

from .conftest import NEGATIVE_TEXT, POSITIVE_TEXT, REFERENCE

DOORAY_BODY = """안녕하세요. 자동 분류된 메일입니다.

-----Original Message-----
From: "김담당" <staff.kim@kaist.ac.kr>
To: "전체학생" <all-students@kaist.ac.kr>; other.person@gmail.com
Cc: dept-office@kaist.ac.kr
Sent: 2026-09-18 14:03 (GMT+09:00)
Subject: [안내] 삼성전자 Tech Lunch Talk (9/25, 점심 제공)

안녕하세요, 경력개발센터입니다.
9월 25일(목) 12:00 N1 101호에서 삼성전자 Tech Lunch Talk을 진행합니다.
참석자 전원에게 점심 도시락을 제공합니다.
신청: https://forms.gle/abc123 (마감 9월 24일 18:00)
문의: 042-350-1234, staff.kim@kaist.ac.kr
감사합니다.
김담당 드림
"""


# --- Dooray original message -------------------------------------------------
def test_original_message_parsing():
    msg = parse_original_message(DOORAY_BODY)
    assert msg.found
    assert msg.sender_name == "김담당"
    assert msg.sender_email == "staff.kim@kaist.ac.kr"
    assert "all-students@kaist.ac.kr" in msg.to and "other.person@gmail.com" in msg.to
    assert msg.cc == ["dept-office@kaist.ac.kr"]
    assert msg.sent_at == datetime(2026, 9, 18, 14, 3, tzinfo=KST)
    assert msg.subject.startswith("[안내] 삼성전자 Tech Lunch Talk")
    assert msg.body.startswith("안녕하세요, 경력개발센터입니다.")
    assert "-----Original" not in msg.body


def test_original_message_absent_keeps_body():
    msg = parse_original_message("그냥 본문입니다.")
    assert not msg.found
    assert msg.body == "그냥 본문입니다."
    assert msg.sender_email == ""


def test_parse_sent_formats():
    assert parse_sent("2026-09-18 14:03 (GMT+09:00)") == datetime(2026, 9, 18, 14, 3, tzinfo=KST)
    assert parse_sent("Thu, 18 Sep 2026 14:03:00 +0900") == datetime(2026, 9, 18, 14, 3, tzinfo=KST)
    assert parse_sent("2026년 9월 18일 오후 2:03") is not None


# --- HTML -> text -----------------------------------------------------------
def test_html_to_text_keeps_lines_and_links():
    html = ('<div><p>9월 25일 <b>12:00</b></p><br><p>신청: <a href="https://forms.gle/x1">여기</a></p>'
            '<img src="/files/4f2a8c9b1d"><p>&nbsp;끝</p><script>alert(1)</script></div>')
    text = html_to_text(html)
    assert "9월 25일 12:00" in text
    assert "https://forms.gle/x1" in text
    assert "alert" not in text
    assert text.splitlines()[0].startswith("9월 25일")
    assert inline_file_ids(html) == ["4f2a8c9b1d"]


# --- PII sanitization -------------------------------------------------------
def test_sanitizer_removes_pii_keeps_event_info():
    msg = parse_original_message(DOORAY_BODY)
    clean = sanitize_for_ai(msg.body)
    assert "kaist.ac.kr" not in clean and "gmail.com" not in clean
    assert "042-350-1234" not in clean
    assert "9월 25일(목) 12:00 N1 101호" in clean
    assert "점심 도시락을 제공" in clean
    assert "https://forms.gle/abc123" in clean
    assert not contains_pii(clean)


def test_sanitizer_strips_headers_and_dooray_ids():
    text = "To: a@b.com\nCc: c@d.org\n본문 @[홍길동](dooray://123/members/456) memberId=1234567 010-1234-5678"
    clean = sanitize_for_ai(text)
    assert "To:" not in clean and "Cc:" not in clean
    assert "dooray://" not in clean and "1234567" not in clean
    assert "010-1234-5678" not in clean


# --- dates / times / KST ------------------------------------------------------
def test_date_extraction_infers_year_forward():
    ref = REFERENCE.date()
    assert extract_dates("9월 25일 12시", ref) == ["2026-09-25"]
    assert extract_dates("2026.05.18(월) 11:30", ref) == ["2026-05-18"]
    assert extract_dates("1월 10일 행사", ref) == ["2027-01-10"]  # far past -> next year
    assert extract_dates("9/25 ~ 9/26", ref) == ["2026-09-25", "2026-09-26"]
    assert extract_dates("Sep 25, 2026", ref) == ["2026-09-25"]


def test_time_extraction():
    assert extract_times("12시") == ["12:00"]
    assert extract_times("오후 3시 30분") == ["15:30"]
    assert extract_times("11:30~12:30") == ["11:30", "12:30"]
    assert extract_times("7pm") == ["19:00"]
    assert extract_times("낮 12시 반") == ["12:30"]


def test_rule_facts_positive_fixture():
    facts = analyze(POSITIVE_TEXT, REFERENCE)
    assert facts.dates == ["2026-09-25"]
    assert facts.times == ["12:00"]
    assert facts.buildings == ["N1"]
    assert facts.explicit_food
    assert facts.food_type_hint == "lunchbox"
    assert facts.lunch_time_only is False
    assert facts.looks_like_event


def test_rule_facts_lunch_time_false_positive():
    facts = analyze(NEGATIVE_TEXT, REFERENCE)
    assert facts.dates == ["2026-09-25"]
    assert not facts.explicit_food
    assert facts.lunch_time_only is True


def test_explicit_food_detection_phrases():
    positives = ["점심 제공", "식사 제공", "중식 제공", "도시락 제공", "간식 제공", "다과 제공", "커피 제공",
                 "피자 제공", "샌드위치 제공", "식권 지급", "케이터링 제공", "refreshments provided",
                 "lunch provided", "meal provided", "Lunch will be provided", "무료 점심"]
    for phrase in positives:
        assert explicit_food_evidence(f"설명회 안내. {phrase}."), phrase
    negatives = ["점심시간에 진행", "12시 시작", "lunch session", "점심 후 시작합니다", "식사는 제공되지 않습니다"]
    for phrase in negatives:
        assert not explicit_food_evidence(f"설명회 안내. {phrase}."), phrase
