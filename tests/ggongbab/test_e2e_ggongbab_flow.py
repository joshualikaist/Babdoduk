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
    assert published == {"food-body", "food-pdf", "food-poster", "giveaway-expo", "giveaway-deadline", "multi-session"}
    assert [c["key"] for c in report.extractor_calls].count("진로 토크 콘서트") == 1
    # a poster-only food event and a deadline-only giveaway reach the page with their marks
    rows = {row.key: row for row in report.rows}
    assert "포스터 기준" in rows["food-poster"].card and "마감일" in rows["giveaway-deadline"].card
    assert "🎁" in rows["giveaway-expo"].card


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


@pytest.mark.xfail(strict=True, reason="KNOWN FINDING (reported to the owner, not fixed here): sanitizer._HEADER_LINE "
                                       "drops any line that starts with 'Date:', so a flyer's own date line is lost")
def test_a_flyer_line_labelled_date_survives_sanitizing():
    from ggongbab.parsers.sanitizer import sanitize_for_ai

    assert "September 24" in sanitize_for_ai("Startup Networking Day\nDate: September 24, 2026, 18:00-20:00\nDinner provided.")
