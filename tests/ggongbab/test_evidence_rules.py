# -*- coding: utf-8 -*-
"""Eligibility and registration must rest on explicit wording, never on inference."""
from __future__ import annotations

import pytest

from ggongbab.models import Evidence
from ggongbab.parsers.rule_parser import analyze, is_real_eligibility, registration_evidence
from ggongbab.parsers.validator import validate

from .conftest import POSITIVE_TEXT, REFERENCE, make_extraction


def run(text, **ai_kw):
    facts = analyze(text, REFERENCE)
    return validate(make_extraction(**ai_kw), facts, text, reference=REFERENCE)


# --- eligibility -------------------------------------------------------------
@pytest.mark.parametrize("phrase", [
    "참석자", "참석자에게", "참가자", "참여자", "방문자", "신청자", "전원", "attendees", "everyone", "all",
])
def test_attendee_words_are_not_eligibility(phrase):
    assert not is_real_eligibility(phrase)


@pytest.mark.parametrize("phrase", [
    "KAIST 학부생 대상", "기계공학과 학생", "석·박사 과정 학생", "신입생만 참여 가능", "외국인 학생 대상",
    "선착순 50명", "3학년 이상", "교직원 대상", "graduate students only", "open to undergraduate students",
])
def test_real_restrictions_are_eligibility(phrase):
    assert is_real_eligibility(phrase)


def test_validator_drops_attendee_eligibility_regression():
    """The first live run turned '참석자에게 점심 도시락을 제공합니다' into eligibility='참석자'."""
    cand = run(POSITIVE_TEXT, eligibility="참석자")
    assert cand.eligibility is None


def test_validator_keeps_real_eligibility():
    text = POSITIVE_TEXT + "\nKAIST 학부생 대상입니다."
    cand = run(text, eligibility="KAIST 학부생 대상")
    assert cand.eligibility == "KAIST 학부생 대상"


def test_validator_drops_eligibility_absent_from_source():
    cand = run(POSITIVE_TEXT, eligibility="기계공학과 대학원생 대상")
    assert cand.eligibility is None


# --- registration ------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("사전 신청 바랍니다.", "true"),
    ("신청 필수입니다.", "true"),
    ("등록이 필요합니다.", "true"),
    ("선착순 마감됩니다.", "true"),
    ("RSVP by Friday.", "true"),
    ("아래 구글 폼으로 신청해 주세요.", "true"),
    ("별도 신청 없이 참석 가능합니다.", "false"),
    ("사전 신청 불필요합니다.", "false"),
    ("현장 참여 가능합니다.", "false"),
    ("No registration required.", "false"),
    ("Walk-ins welcome.", "false"),
    ("9월 25일 12시 N1에서 설명회를 진행합니다.", "unknown"),
    ("점심 도시락을 제공합니다.", "unknown"),
])
def test_registration_evidence_detection(text, expected):
    assert registration_evidence(text) == expected


def test_registration_unknown_when_source_is_silent_regression():
    """The first live run published required=false although the mail never mentioned it."""
    cand = run(POSITIVE_TEXT, registration_required="false",
               evidence=Evidence(event_time="9월 25일 12시", location="N1", food="점심 도시락을 제공합니다", registration=None))
    assert cand.registration_required == "unknown"
    assert any("신청 불필요 근거 없음" in r for r in cand.review_reasons)


def test_registration_false_needs_explicit_evidence():
    text = POSITIVE_TEXT + "\n별도 신청 없이 현장 참여 가능합니다."
    cand = run(text, registration_required="false",
               evidence=Evidence(event_time="9월 25일 12시", location="N1",
                                 food="점심 도시락을 제공합니다", registration="별도 신청 없이 현장 참여 가능합니다"))
    assert cand.registration_required == "false"
    assert not any("신청" in r for r in cand.review_reasons), cand.review_reasons


def test_registration_true_needs_evidence():
    cand = run(POSITIVE_TEXT, registration_required="true",
               evidence=Evidence(event_time="9월 25일 12시", location="N1",
                                 food="점심 도시락을 제공합니다", registration=None))
    assert cand.registration_required == "unknown"
    assert any("신청 필요 근거 없음" in r for r in cand.review_reasons)


def test_registration_true_from_source_wording():
    text = POSITIVE_TEXT + "\n사전 신청 바랍니다: https://forms.gle/abc"
    cand = run(text, registration_required="true", registration_url="https://forms.gle/abc",
               evidence=Evidence(event_time="9월 25일 12시", location="N1",
                                 food="점심 도시락을 제공합니다", registration="사전 신청 바랍니다"))
    assert cand.registration_required == "true"
    assert cand.registration_url == "https://forms.gle/abc"


def test_registration_url_alone_implies_required():
    text = POSITIVE_TEXT + "\n신청 링크: https://forms.gle/abc"
    cand = run(text, registration_required="unknown", registration_url="https://forms.gle/abc")
    assert cand.registration_required == "true"
