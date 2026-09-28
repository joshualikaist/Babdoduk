# -*- coding: utf-8 -*-
"""Same start + same room + one supporting signal is one event (DUP-001, 2026-09-28)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ggongbab.config import Settings
from ggongbab.dedup import find_match, same_slot, score_pair
from ggongbab.db.repository import MemoryRepository
from ggongbab.models import EventCandidate
from ggongbab.parsers.validator import parse_iso

ROOT = Path(__file__).resolve().parents[2]
CASES = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((ROOT / "tests/fixtures/ggongbab/dedup").glob("DUP-*.json"))]


def candidate(fields: dict) -> EventCandidate:
    return EventCandidate(title=fields["title"], event_start=parse_iso(fields["event_start"]),
                          location_name=fields.get("location_name"), building=fields.get("building"),
                          room=fields.get("room"), organizer=fields.get("organizer"),
                          food_provided="true", food_type="meal", confidence=0.9)


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_the_second_mail_joins_the_existing_event(case):
    cand, row = candidate(case["incoming"]), dict(case["existing"])
    assert same_slot(cand, row)
    match = find_match(cand, [row], Settings().dedup_threshold)
    assert (match is not None) is case["expected"]["same_event"], score_pair(cand, row)


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_controls(case):
    for control in case["controls"]:
        cand = candidate({**case["incoming"], **control["incoming"]})
        strong = same_slot(cand, case["existing"]) and score_pair(cand, case["existing"]) >= 0.95
        assert strong is control["expected"]["strong_slot_match"], control["name"]


def test_the_pipeline_keeps_one_event_with_both_sources():
    case = CASES[0]
    repo = MemoryRepository()
    first = repo.insert_event({**candidate(case["existing"]).to_db_row(), "event_start": case["existing"]["event_start"]})
    repo.link_event_source(first, "raw-1", 1.0)
    cand = candidate(case["incoming"])
    match = find_match(cand, repo.candidate_events(cand.event_start), Settings().dedup_threshold)
    assert match is not None and match.event["id"] == first
    repo.link_event_source(first, "raw-2", match.score)
    assert len(repo.events) == 1 and {r for (e, r) in repo.event_sources if e == first} == {"raw-1", "raw-2"}
