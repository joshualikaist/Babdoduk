# -*- coding: utf-8 -*-
"""scripts/e2e_ggongbab_flow.py with the scripted AI: mail -> Radar -> task -> pipeline -> exporter -> page.
Synthetic fixtures, in-memory repository, a temp feed, a fixed clock and no network beyond loopback."""
from __future__ import annotations

import pytest

import e2e_ggongbab_flow as flow

pytest.importorskip("playwright")


def test_every_fixture_follows_its_expected_path_from_mail_to_card():
    with flow.offline():
        report = flow.run_flow("fake")
    assert report.problems == []
    published = {row.key for row in report.rows if row.published == "yes"}
    assert published == {"food-body", "food-pdf", "food-poster", "giveaway-expo", "giveaway-booth", "multi-session"}
    assert [c["key"] for c in report.extractor_calls].count("진로 토크 콘서트") == 1
    # a poster-only food event and a deadline-only giveaway reach the page with their marks
    rows = {row.key: row for row in report.rows}
    assert "포스터 기준" in rows["food-poster"].card and "마감일" in rows["giveaway-booth"].card
    assert "🎁" in rows["giveaway-expo"].card
    # a survey prize draw with no event is not listed (owner decision 2026-10-15)
    assert rows["giveaway-deadline"].published == "no" and rows["giveaway-deadline"].card == "-"


def test_the_harness_notices_a_poster_event_that_is_not_published(monkeypatch):
    original = flow.SCRIPT["진로 토크 콘서트"]

    def without_poster_marks():
        extraction = original()
        extraction.evidence.from_poster = None
        return extraction

    monkeypatch.setitem(flow.SCRIPT, "진로 토크 콘서트", without_poster_marks)
    with flow.offline():
        report = flow.run_flow("fake", page=False)
    assert any(p.startswith("food-poster: published=False") for p in report.problems)


def test_the_offline_guard_refuses_a_non_loopback_connection():
    import socket

    with flow.offline():
        with pytest.raises(AssertionError, match="offline e2e"):
            socket.socket().connect(("203.0.113.9", 443))


def test_a_flyer_line_labelled_date_survives_sanitizing():
    from ggongbab.parsers.sanitizer import sanitize_for_ai

    text = "Startup Networking Day\nDate: September 24, 2026, 18:00-20:00\nVenue: E3\nDinner provided."
    assert "Date: September 24, 2026, 18:00-20:00" in sanitize_for_ai(text)


def test_header_lines_are_stripped_only_in_a_mail_header_block():
    from ggongbab.parsers.sanitizer import sanitize_for_ai

    top = "From: A <a@x.com>\nTo: b@y.com\nSent: 2026-09-19\n\n본문 9월 24일"
    assert sanitize_for_ai(top) == "본문 9월 24일"
    forwarded = "안내드립니다.\n-----Original Message-----\n보낸 사람: 홍길동\n받는 사람: 전체\n\n내용"
    clean = sanitize_for_ai(forwarded)
    assert "홍길동" not in clean and "받는 사람" not in clean and "내용" in clean
    assert "Cc:" not in sanitize_for_ai("Cc: z@w.com\nTo: q@w.com\nbody")
    # a lone Date line at the top names no address field: it is content
    assert sanitize_for_ai("Date: September 24\n행사 안내") == "Date: September 24\n행사 안내"
    # an address field in the middle of a body is not a header block, but its address is still masked
    assert "[email]" in sanitize_for_ai("행사 안내\nTo: q@w.com")
