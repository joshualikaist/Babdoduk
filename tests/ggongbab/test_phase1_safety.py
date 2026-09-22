# -*- coding: utf-8 -*-
"""Phase 1 regressions: retryable writes, stable events, visible failures, heartbeat."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

import dooray_web_agent as agent
import refresh_ggongbab as refresh
from ggongbab.config import KST
from ggongbab.db.repository import MemoryRepository
from ggongbab.exporter import build_payload
from ggongbab.heartbeat import HeartbeatWriter, build_heartbeat, heartbeat_alert
from ggongbab.models import EventCandidate
from ggongbab.pipeline import Pipeline
from ggongbab.web.exit_codes import AUTH_REQUIRED, PROJECT_NOT_FOUND, ProjectNotFound
from ggongbab.web.state import AgentState
from ggongbab.web.task_writer import MailPayload, mail_identity

from .test_web_agent import FakeWriter

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def dooray_settings(settings):
    settings.dooray_token = "t"
    settings.dooray_project_id = "4424523215847914253"
    return settings


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


def test_failed_write_is_retried_and_success_is_skipped(tmp_path, dooray_settings):
    state = AgentState.load(tmp_path / "state.json")
    agent.finalize_mail(state, "mail-1", "subject", date(2026, 9, 1), failed=True, post_id=None)
    assert not state.seen("mail-1")

    # A legacy write-failed row must not block the next run either.
    state.record("mail-1", "subject", date(2026, 9, 1), registered=False, outcome="write-failed")
    assert not state.seen("mail-1")

    writer = FakeWriter(dooray_settings)
    writer.verify_project()
    mail_id = writer.create_task(MailPayload(
        mail_id="mail-1", subject="기업 설명회", body="점심 도시락을 제공합니다."))
    assert mail_id == "9001" and len(writer.posts) == 1
    agent.finalize_mail(state, "mail-1", "subject", date(2026, 9, 1), failed=False, post_id=mail_id)
    state.save()
    assert AgentState.load(tmp_path / "state.json").seen("mail-1")
    blob = (tmp_path / "state.json").read_text(encoding="utf-8")
    assert "기업 설명회" not in blob and "mail-1" not in blob


def test_ambiguous_retry_does_not_create_a_second_task(dooray_settings):
    first = FakeWriter(dooray_settings)
    first.verify_project()
    mail = MailPayload(mail_id="mail-9", subject="기업 설명회", body="점심 도시락을 제공합니다.")
    assert first.create_task(mail) == "9001"
    body = first.posts[0]["body"]["body"]["content"]
    assert f"mail_key={mail_identity('mail-9')}" in body
    assert "mail-9" not in body

    class LookupWriter(FakeWriter):
        def _request(self, method, path, payload=None):
            if method == "GET" and "/posts/" in path:
                return {"result": {"id": "9001", "body": {"content": body}}}
            if method == "GET" and "/posts" in path:
                return {"result": [{"id": "9001"}]}
            return super()._request(method, path, payload)

    second = LookupWriter(dooray_settings)
    second.verify_project()
    assert second.create_task(mail) == "9001"
    assert second.posts == []


def test_failed_post_does_not_mark_the_mail_seen(dooray_settings, tmp_path):
    class Boom(FakeWriter):
        def _request(self, method, path, body=None):
            if method == "POST":
                raise ProjectNotFound("down")
            if method == "GET" and "/posts" in path:
                return {"result": []}
            return super()._request(method, path, body)

    writer = Boom(dooray_settings)
    writer.verify_project()
    state = AgentState.load(tmp_path / "s.json")
    with pytest.raises(ProjectNotFound):
        writer.create_task(MailPayload(mail_id="mail-2", subject="s", body="b"))
    agent.finalize_mail(state, "mail-2", "s", None, failed=True, post_id=None)
    assert writer.posts == [] and not state.seen("mail-2")


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
    assert refresh.workflow_stays_green(2) is True
    assert refresh.classify_refresh_exit(collectors_all_failed=True) == 20
    assert refresh.classify_refresh_exit(supabase_error=True) == 21
    assert refresh.classify_refresh_exit(fatal="quota_exhausted", export_code=0) == 22
    assert refresh.classify_refresh_exit(fatal="auth", export_code=2) == 22
    assert refresh.classify_refresh_exit(publish_error=True) == 23
    for code in (20, 21, 22, 23):
        assert refresh.workflow_stays_green(code) is False
    workflow = (ROOT / ".github" / "workflows" / "ggongbab-refresh.yml").read_text(encoding="utf-8")
    keep = workflow.index("nothing safe to publish")
    fail = workflow.index("infrastructure or publication failure")
    assert keep < workflow.index("exit 0", keep) < fail
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


def test_heartbeat_is_operational_metadata_only():
    now = datetime(2026, 9, 22, 11, 0, tzinfo=KST)
    row = build_heartbeat(status="auth_required", exit_class="10", auth_required=True,
                          ui_contract_changed=False, last_scan_at=now)
    assert set(row) == {
        "agent_id", "last_scan_at", "last_success_at", "last_publish_at", "status",
        "exit_class", "auth_required", "ui_contract_changed", "version",
    }
    assert row["auth_required"] is True and row["status"] == "auth_required"
    blob = str(row)
    for leaked in ("cookie", "token", "subject", "preview", "@"):
        assert leaked not in blob

    class Client:
        def __init__(self):
            self.rows = []

        def upsert(self, table, payload, on_conflict):
            assert table == "agent_heartbeats" and on_conflict == "agent_id"
            self.rows.append(payload)

    client = Client()
    HeartbeatWriter(client).write(row)
    assert client.rows == [row]
    dirty = dict(row)
    dirty["body"] = "nope"
    with pytest.raises(ValueError):
        HeartbeatWriter(client).write(dirty)
    assert heartbeat_alert(row, now, timedelta(hours=6)) == "auth_required"
    fresh = build_heartbeat(status="healthy", exit_class="0", last_scan_at=now)
    assert heartbeat_alert(fresh, now, timedelta(hours=6)) is None
    assert heartbeat_alert(fresh, now + timedelta(hours=7), timedelta(hours=6)) == "stale"
    beat = agent.heartbeat_from_exit(AUTH_REQUIRED, published=False)
    assert beat["status"] == "auth_required" and beat["auth_required"] is True
    assert beat["last_publish_at"] is None


def test_default_run_does_not_open_unread_bodies():
    args = agent.build_parser().parse_args(["--run"])
    assert args.read_state == "read" and args.allow_unread_body is False
    opened = 0
    for unread in (True, True):
        if args.read_state == "read" and unread:
            continue
        if unread and not agent.unread_body_permitted(args.read_state, args.allow_unread_body):
            continue
        opened += 1
    assert opened == 0
    opted = agent.build_parser().parse_args(["--run", "--read-state", "all", "--allow-unread-body"])
    assert agent.unread_body_permitted(opted.read_state, opted.allow_unread_body) is True
    cmd = (ROOT / "scripts" / "run_ggongbab_agent.cmd").read_text(encoding="utf-8")
    assert "--read-state read" in cmd
    source = Path(agent.__file__).read_text(encoding="utf-8")
    body = source[source.index("def cmd_run("):source.index("def _run_pipeline(")]
    assert body.index("unread_body_permitted") < body.index("open_body(")
