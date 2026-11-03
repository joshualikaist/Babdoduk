# -*- coding: utf-8 -*-
"""Phase 1 pipeline regressions: stable events, a published event kept through a conflicting
second source, and refresh failures that are visible (exit classes, job summary).

Release port of the lab file: the Dooray agent and heartbeat tests stay on lab (lab-only systems)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

import refresh_ggongbab as refresh
from ggongbab.config import KST
from ggongbab.db.repository import MemoryRepository
from ggongbab.db.supabase_client import SupabaseError
from ggongbab.exporter import build_payload
from ggongbab.models import EventCandidate, RawItem
from ggongbab.pipeline import Pipeline

ROOT = Path(__file__).resolve().parents[2]


def _candidate(title, start, **kw) -> EventCandidate:
    return EventCandidate(
        title=title,
        event_start=start,
        confidence=0.95,
        food_provided=kw.pop("food_provided", "true"),
        food_type="lunchbox",
        building=kw.pop("building", "N1"),
        is_event=True,
        **kw,
    )


def test_same_raw_item_keeps_one_event_when_the_start_changes(settings):
    repo = MemoryRepository()
    pipe = Pipeline(settings, repo, None, [])
    first = datetime(2026, 9, 25, 12, 0, tzinfo=KST)
    later = datetime(2026, 10, 2, 18, 0, tzinfo=KST)
    event_id = pipe.store_candidate(_candidate("기업 설명회", first), "raw-1")
    again = pipe.store_candidate(_candidate("기업 설명회", later), "raw-1")
    assert again == event_id
    assert len(repo.events) == 1
    assert repo.events[event_id]["event_start"].startswith("2026-10-02T18:00:00")


def test_different_source_on_another_day_stays_a_separate_event(settings):
    repo = MemoryRepository()
    pipe = Pipeline(settings, repo, None, [])
    pipe.store_candidate(_candidate("기업 설명회", datetime(2026, 9, 25, 12, tzinfo=KST)), "raw-a")
    pipe.store_candidate(_candidate("기업 설명회", datetime(2026, 10, 2, 12, tzinfo=KST)), "raw-b")
    assert len(repo.events) == 2


def test_conflicting_second_source_keeps_the_public_event(settings):
    repo = MemoryRepository()
    pipe = Pipeline(settings, repo, None, [])
    start = datetime(2026, 9, 25, 12, 0, tzinfo=KST)
    event_id = pipe.store_candidate(_candidate("기업 설명회", start, building="N1"), "raw-a")
    pipe.store_candidate(
        _candidate("기업 설명회", start, building="E5", food_provided="false"), "raw-b")
    assert len(repo.events) == 1
    row = repo.get_event(event_id)
    assert row["status"] == "published" and row["needs_review"] is False
    assert row["building"] == "N1" and row["food_provided"] == "true"
    assert repo.conflicts and repo.conflicts[0]["event_id"] == event_id
    assert "building" in repo.conflicts[0]["summary"]
    payload = build_payload(repo.publishable_events(), settings, now=datetime(2026, 9, 20, tzinfo=KST),
                            food_only=True)
    assert payload["count"] == 1
    assert payload["events"][0]["id"] == event_id
    assert payload["events"][0]["location"]["building"] == "N1"
    assert "E5" not in payload["events"][0]["location"]["building"]


def test_refresh_exit_classes_and_workflow():
    assert refresh.classify_refresh_exit(export_code=0) == 0
    assert refresh.classify_refresh_exit(export_code=2) == 2
    assert refresh.classify_refresh_exit(collectors_all_failed=True) == 20
    assert refresh.classify_refresh_exit(supabase_error=True) == 21
    assert refresh.classify_refresh_exit(fatal="quota_exhausted", export_code=0) == 22
    assert refresh.classify_refresh_exit(fatal="auth", export_code=2) == 22
    assert refresh.classify_refresh_exit(publish_error=True) == 23
    for code in (20, 21, 22, 23):
        assert refresh.workflow_stays_green(code) is False
    # The workflow on main fails every non-zero exit: 2 ends with exit 1 and any other
    # non-zero code ends with that code; neither branch reaches a green exit 0.
    workflow = (ROOT / ".github" / "workflows" / "ggongbab-refresh.yml").read_text(encoding="utf-8")
    legacy = workflow.index('if [ "$code" -eq 2 ]; then')
    fail = workflow.index('if [ "$code" -ne 0 ]; then', legacy)
    assert legacy < workflow.index("exit 1", legacy) < fail
    assert "exit 0" not in workflow[legacy:fail]
    assert 'exit "$code"' in workflow[fail:]


def test_partial_run_is_visible_in_the_job_summary(tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

    class Stats:
        fatal_category = ""
        ai_errors = 2
        collector_errors = {}

    refresh.publish_job_summary(refresh.run_notice(Stats()))
    text = summary.read_text(encoding="utf-8")
    assert "partial: ai_errors=2" in text
    assert "subject" not in text


def test_conflict_log_failure_keeps_the_public_event_and_fails_the_run(settings):
    class Boom(MemoryRepository):
        def record_conflict(self, event_id, raw_item_id, reasons):
            raise SupabaseError("conflict log")

    repo = Boom()
    pipe = Pipeline(settings, repo, None, [])
    start = datetime(2026, 9, 25, 12, 0, tzinfo=KST)
    event_id = pipe.store_candidate(_candidate("기업 설명회", start, building="N1"), "raw-a")
    with pytest.raises(SupabaseError):
        pipe.store_candidate(_candidate("기업 설명회", start, building="E5", food_provided="false"), "raw-b")
    row = repo.get_event(event_id)
    assert row["status"] == "published" and row["needs_review"] is False
    assert row["building"] == "N1" and row["food_provided"] == "true"
    assert pipe.stats.events_updated == 0
    payload = build_payload(repo.publishable_events(), settings, now=datetime(2026, 9, 20, tzinfo=KST),
                            food_only=True)
    assert payload["count"] == 1 and payload["events"][0]["id"] == event_id

    class Exploding(Pipeline):
        def process_item(self, item):
            raise SupabaseError("conflict log")

    class OneItem:
        source_type = "manual"

        def enabled(self):
            return True

        def collect(self):
            return [RawItem(source_type="manual", external_id="1", subject="s", raw_text="body")]

    run_repo = MemoryRepository()
    with pytest.raises(SupabaseError):
        Exploding(settings, run_repo, None, [OneItem()]).run()
    recorded = next(iter(run_repo.ingest_runs.values()))
    assert recorded["status"] == "failed" and recorded["error_message"] == "supabase"
