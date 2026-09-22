"""Phase 2A: synthetic data, fake DB/RPC only; never use live services."""
from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest

import refresh_ggongbab as refresh
from ggongbab.config import KST
from ggongbab.db.repository import MemoryRepository, SupabaseRepository
from ggongbab.db.supabase_client import SupabaseClient, SupabaseError
from ggongbab.exporter import build_payload, write_payload
from ggongbab.public_feed import (PUBLIC_FIELDS, PUBLIC_COLUMNS, PublicFeedError,
    commit_public_feed, prepare_public_feed, sync_public_feed, to_snapshot_event)
from ggongbab.public_sanitizer import public_url
from validate_content import validate_ggongbab_payload

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 23, 9, tzinfo=KST)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("LIVE_NETWORK_FORBIDDEN")
    monkeypatch.setattr("urllib.request.urlopen", forbidden)
    monkeypatch.setattr("requests.sessions.Session.send", forbidden)


def event(number=1, **overrides):
    return {
        "id": str(UUID(int=number)), "title": "Campus lunch seminar", "summary": "Lunch provided",
        "event_start": (NOW + timedelta(days=number)).isoformat(), "event_end": None,
        "status": "published", "needs_review": False, "confidence": 0.9,
        "food_provided": "true", "food_type": "lunchbox", "location_name": "N1",
        "_sources": [{"type": "dooray", "name": "PRIVATE_NAME", "url": "https://kaist.dooray.com/task/PRIVATE"}],
        **overrides,
    }


class Repo(MemoryRepository):
    def __init__(self, rows=None):
        super().__init__()
        self.events = {row["id"]: deepcopy(row) for row in (rows or [event()])}

    def publishable_events(self):
        # Return all canonical rows to prove the common policy is authoritative.
        return deepcopy(list(self.events.values()))


def test_publication_parity(settings):
    rows = [event(), event(2, status="review"), event(3, needs_review=True),
            event(4, confidence=0.1), event(5, food_provided="unknown"),
            event(6, food_provided="false"), event(7, event_start=None),
            event(8, event_start=(NOW - timedelta(days=2)).isoformat()),
            event(9, event_start=(NOW + timedelta(days=90)).isoformat()),
            event(10, event_end=(NOW - timedelta(days=1)).isoformat()),
            event(11, needs_review=None), event(12, confidence=float("nan")),
            event(13, event_start=(NOW - timedelta(days=4)).isoformat(),
                  event_end=(NOW + timedelta(hours=2)).isoformat())]
    repo = Repo(rows)
    snapshot = build_payload(rows, settings, NOW, food_only=True)
    sync_public_feed(repo, settings, NOW)
    assert set(repo.public_events) == {e["id"] for e in snapshot["events"]} == {rows[0]["id"], rows[-1]["id"]}


@pytest.mark.parametrize("hours,expected", [(-3, True), (-3.001, False), (1440, True), (1440.001, False)])
def test_policy_boundaries(settings, hours, expected):
    settings.expired_grace_hours, settings.export_horizon_days = 3, 60
    row = event(event_start=(NOW + timedelta(hours=hours)).isoformat())
    repo = Repo([row])
    payload = sync_public_feed(repo, settings, NOW)
    assert bool(payload["events"]) is expected
    assert bool(repo.public_events) is expected


def test_allowlist_and_private_values_do_not_escape(settings):
    row = event(raw_item_id="PRIVATE_RAW", source_id="PRIVATE_SOURCE", external_id="PRIVATE_ID",
                pstNo="PRIVATE_NOTICE", sender="PRIVATE_SENDER", sender_email="secret@example.com",
                raw_text="PRIVATE_BODY", raw_html="PRIVATE_HTML", parsed_json={"token": "PRIVATE_TOKEN"},
                metadata={"cookies": "PRIVATE_COOKIE"}, attachments=[{"url": "PRIVATE_ATTACHMENT"}],
                registration_url="https://portal.kaist.ac.kr/wz/api/board/recents/PRIVATE")
    repo = Repo([row])
    sync_public_feed(repo, settings, NOW)
    public = repo.public_events[row["id"]]
    assert set(public) == set(PUBLIC_COLUMNS)
    assert public["source_types"] == ["dooray"] and public["registration_url"] == ""
    assert "PRIVATE" not in json.dumps(public)
    assert not any(isinstance(v, dict) for v in public.values())


@pytest.mark.parametrize("field", ["title", "summary", "location_name", "organizer", "eligibility", "food_description"])
def test_text_fields_strip_html_email_private_urls_and_tokens(settings, field):
    row = event(**{field: 'Lunch <b>provided</b> secret@example.com https://portal.kaist.ac.kr/p/PRIVATE '
                         'https://kaist.dooray.com/tasks/PRIVATE JSESSIONID=PRIVATE sk-abcdefghijklmnopqrstuv'})
    repo = Repo([row])
    sync_public_feed(repo, settings, NOW)
    blob = json.dumps(repo.public_events)
    assert all(value not in blob for value in ("PRIVATE", "secret@example.com", "<b>", "JSESSIONID", "sk-"))


@pytest.mark.parametrize("url", ["https://portal.kaist.ac.kr/x", "https://kaist.dooray.com/x",
    "https://api.gov-dooray.com/x", "https://sso.kaist.ac.kr/x", "javascript:alert(1)",
    "https://forms.gle/x?token=PRIVATE", "https://forms.gle/x#PRIVATE", "https://user:pass@forms.gle/x",
    "https://forms.gle.evil.test/x", "http://forms.gle/x", "https://127.0.0.1/x",
    "https://docs.google.com/document/private", "https://forms.gle/x%3Ftoken=PRIVATE"])
def test_url_policy_withholds_unreviewed_or_sensitive_urls(url):
    assert public_url(url) == ""


def test_registration_link_survives_and_sources_are_sorted(settings):
    row = event(registration_url="https://forms.gle/example", _sources=[
        {"type": "portal", "name": "PRIVATE", "url": "https://portal.kaist.ac.kr/private"},
        {"type": "manual", "name": "PRIVATE"}, {"type": "portal"}, {"type": "PRIVATE"}])
    repo = Repo([row])
    sync_public_feed(repo, settings, NOW)
    public = repo.public_events[row["id"]]
    assert public["registration_url"] == "https://forms.gle/example"
    assert public["source_types"] == ["manual", "portal"]
    before = public["content_revision"]
    repo.events[row["id"]]["_sources"].reverse()
    sync_public_feed(repo, settings, NOW)
    assert repo.public_events[row["id"]]["content_revision"] == before


@pytest.mark.parametrize("field,value", [
    ("title", "Changed title"), ("summary", "Changed summary"),
    ("event_start", "2026-09-25T10:00:00+09:00"), ("event_end", "2026-09-26T10:00:00+09:00"),
    ("date_text", "Sept 25"), ("time_text", "noon"), ("location_name", "Auditorium"),
    ("building", "E1"), ("room", "101"), ("food_type", "meal"), ("food_description", "Rice"),
    ("organizer", "Club"), ("eligibility", "All students"), ("registration_required", "true"),
    ("registration_deadline", "2026-09-23T12:00:00+09:00"),
    ("registration_url", "https://forms.gle/changed"), ("confidence", 0.95),
    ("_sources", [{"type": "manual"}]),
])
def test_public_content_changes_revision(settings, field, value):
    repo = Repo()
    sync_public_feed(repo, settings, NOW)
    key = next(iter(repo.events))
    before = repo.public_events[key]["content_revision"]
    repo.events[key][field] = value
    sync_public_feed(repo, settings, NOW)
    assert repo.public_events[key]["content_revision"] != before


def test_idempotent_and_operational_changes_do_not_touch_public_rows(settings):
    repo = Repo()
    sync_public_feed(repo, settings, NOW)
    before = deepcopy(repo.public_events)
    row = next(iter(repo.events.values()))
    row.update(updated_at="later", last_seen_at="later", metadata={"private": "changed"})
    sync_public_feed(repo, settings, NOW + timedelta(minutes=1))
    assert repo.public_events == before
    assert repo.public_feed_generation() == 2


@pytest.mark.parametrize("change", [
    {"status": "archived"}, {"status": "draft"}, {"needs_review": True},
    {"food_provided": "false"}, {"food_provided": "unknown"}, {"confidence": 0.1},
    {"event_start": "2026-01-01T10:00:00+09:00"},
    {"event_start": "2027-01-01T10:00:00+09:00"},
])
def test_no_longer_publishable_is_removed(settings, change):
    repo = Repo()
    sync_public_feed(repo, settings, NOW)
    next(iter(repo.events.values())).update(change)
    sync_public_feed(repo, settings, NOW)
    assert repo.public_events == {}


def test_deleted_canonical_and_clock_expiry_are_reconciled(settings):
    repo = Repo([event(), event(2)])
    sync_public_feed(repo, settings, NOW)
    del repo.events[event(2)["id"]]
    sync_public_feed(repo, settings, NOW + timedelta(days=3))
    assert not repo.public_events


def test_failed_preparation_never_writes_or_deletes(settings, monkeypatch):
    repo = Repo()
    sync_public_feed(repo, settings, NOW)
    before = deepcopy(repo.public_events)
    repo.events[event()["id"]]["summary"] = {"private": "PRIVATE"}
    replace = Mock(side_effect=AssertionError("must not write"))
    monkeypatch.setattr(repo, "replace_public_feed", replace)
    with pytest.raises(PublicFeedError, match="^PUBLIC_FEED_PREPARATION_FAILED$"):
        sync_public_feed(repo, settings, NOW)
    replace.assert_not_called()
    assert repo.public_events == before


def test_failed_write_does_not_delete_healthy_rows_and_preserves_canonical(settings, monkeypatch):
    repo = Repo()
    sync_public_feed(repo, settings, NOW)
    before = deepcopy(repo.public_events)
    repo.events[event()["id"]]["title"] = "New canonical title"
    monkeypatch.setattr(repo, "replace_public_feed", Mock(side_effect=SupabaseError("PRIVATE_DB_BODY")))
    with pytest.raises(PublicFeedError, match="^PUBLIC_FEED_SYNC_FAILED$"):
        sync_public_feed(repo, settings, NOW)
    assert repo.public_events == before
    assert repo.events[event()["id"]]["title"] == "New canonical title"


def test_concurrent_stale_replacement_rejected(settings):
    repo = Repo()
    old = prepare_public_feed(repo, settings, NOW)
    repo.events[event()["id"]]["title"] = "Newer publication"
    sync_public_feed(repo, settings, NOW)
    with pytest.raises(PublicFeedError):
        commit_public_feed(repo, old)
    assert repo.public_events[event()["id"]]["title"] == "Newer publication"


def test_snapshot_compatible_and_mapping_reads_no_private_state(settings, tmp_path):
    repo = Repo()
    payload = sync_public_feed(repo, settings, NOW)
    assert validate_ggongbab_payload(payload, NOW) == []
    path = write_payload(payload, tmp_path)
    assert json.loads(path.read_text(encoding="utf-8")) == payload
    public = deepcopy(next(iter(repo.public_events.values())))
    public["start_at"] = "2026-09-24T00:00:00+00:00"
    assert to_snapshot_event(public) == payload["events"][0]


def test_stage_a_cannot_publish_and_sync_never_reads_pending(settings, monkeypatch):
    pending = {"id": "hashed-notice", "reg_dt": NOW.isoformat(), "candidate": True, "public": True}
    repo = Repo([pending])
    monkeypatch.setattr(Path, "read_text", Mock(side_effect=AssertionError("no local state read")))
    sync_public_feed(repo, settings, NOW)
    assert not repo.public_events


def test_portal_poller_has_no_publication_dependency():
    source = (ROOT / "scripts/ggongbab/portal_list_poller.py").read_text(encoding="utf-8")
    assert all(name not in source for name in ("public_feed", "ggongbab_public_events", "refresh_ggongbab"))


def test_repository_uses_one_atomic_rpc():
    client = Mock()
    client.rpc.return_value = 5
    repo = SupabaseRepository(client)
    assert repo.replace_public_feed(4, []) == 5
    client.rpc.assert_called_once_with("ggongbab_replace_public_feed", {"p_generation": 4, "p_rows": []}, returning=True)
    client.update.assert_not_called()
    client.upsert.assert_not_called()


@pytest.mark.parametrize("response", [None, {}, "not json", [None]])
def test_incomplete_reads_fail_instead_of_empty_feed(monkeypatch, response):
    client = SupabaseClient("https://synthetic.invalid", "fake")
    monkeypatch.setattr(client, "_request", Mock(return_value=response))
    with pytest.raises(SupabaseError, match="PUBLICATION_READ_INVALID"):
        client.select_all("events", {"order": "id.asc"})


def test_complete_paging_even_under_server_cap(monkeypatch):
    client = SupabaseClient("https://synthetic.invalid", "fake")
    request = Mock(side_effect=[[{"id": "1"}], [{"id": "2"}], []])
    monkeypatch.setattr(client, "_request", request)
    assert client.select_all("events", {"order": "id.asc"}) == [{"id": "1"}, {"id": "2"}]
    assert [call.args[2]["offset"] for call in request.call_args_list] == [0, 1, 2]


def test_supabase_publication_has_no_500_row_or_two_day_cutoff(monkeypatch):
    client = Mock()
    rows = [event(i) for i in range(1, 602)]
    client.select_all.return_value = rows
    repo = SupabaseRepository(client)
    monkeypatch.setattr(repo, "_with_sources", lambda chunk: chunk)
    assert len(repo.publishable_events()) == 601
    assert client.select_all.call_args.args == ("events", {
        "status": "eq.published", "needs_review": "eq.false", "order": "id.asc"})


def test_export_writes_snapshot_and_syncs_same_ids(settings, monkeypatch, tmp_path):
    current = datetime.now(KST)
    repo = Repo([event(event_start=(current + timedelta(days=1)).isoformat())])
    monkeypatch.setattr(refresh, "ROOT", tmp_path)
    monkeypatch.setattr(refresh, "DATA_DIR", tmp_path / "data")
    assert refresh.export(settings, repo, False) == 0
    payload = json.loads((tmp_path / "data/latest.json").read_text(encoding="utf-8"))
    assert {e["id"] for e in payload["events"]} == set(repo.public_events)


def test_refresh_sync_failure_is_non_green_and_snapshot_survives(settings, monkeypatch, tmp_path, capsys):
    repo = Repo([event(event_start=(datetime.now(KST) + timedelta(days=1)).isoformat())])
    monkeypatch.setattr(refresh, "ROOT", tmp_path)
    monkeypatch.setattr(refresh, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(refresh, "load_settings", lambda: settings)
    monkeypatch.setattr(refresh, "build_repo", lambda *args: repo)
    monkeypatch.setattr(repo, "replace_public_feed", Mock(side_effect=SupabaseError("PRIVATE")))
    monkeypatch.setattr("sys.argv", ["refresh_ggongbab.py", "--export-only"])
    code = refresh.main()
    assert code == 23 and not refresh.workflow_stays_green(code)
    assert (tmp_path / "data/latest.json").exists()
    assert len(repo.events) == 1
    assert "PRIVATE" not in capsys.readouterr().out


def test_migration_allowlist_privileges_and_atomicity():
    sql = (ROOT / "supabase/migrations/004_ggongbab_public_feed.sql").read_text(encoding="utf-8").lower()
    table = sql.split("create table if not exists public.ggongbab_public_events (", 1)[1].split("\n);", 1)[0]
    columns = re.findall(r"^  (\w+) (?:uuid|text|timestamptz|double)", table, re.M)
    assert set(columns) == set(PUBLIC_COLUMNS)
    assert "references" not in table and "jsonb" not in table
    assert "alter table public.ggongbab_public_events enable row level security" in sql
    assert "revoke all on table public.ggongbab_public_events from public, anon, authenticated, service_role" in sql
    assert "grant select on table public.ggongbab_public_events to anon, authenticated" in sql
    assert "grant select, insert, update, delete on table public.ggongbab_public_events to service_role" in sql
    assert "for select to anon, authenticated using (true)" in sql
    grants = [line for line in sql.splitlines() if line.startswith("grant ")]
    assert all("ggongbab_public" in line or "ggongbab_replace_public_feed" in line for line in grants)
    assert all("grant select on table" in line for line in grants if "anon" in line or "authenticated" in line)
    assert "security invoker" in sql and "security definer" not in sql
    assert "for update;" in sql and "p_generation is distinct from current_generation" in sql
    assert sql.index("insert into public.ggongbab_public_events as existing") < sql.index("delete from public.ggongbab_public_events")
    assert "where existing.content_revision is distinct from excluded.content_revision" in sql
    assert "revoke all on function public.ggongbab_replace_public_feed(bigint, jsonb) from public, anon, authenticated" in sql
    assert "if not exists (select 1 from pg_publication_tables" in sql
    additions = re.findall(r"alter publication supabase_realtime add table ([\w.]+)", sql)
    assert additions == ["public.ggongbab_public_events"]
    assert "replica identity default" in sql and "puballtables" in sql
    assert sql.rstrip().endswith("commit;") and "\nbegin;" in sql


def test_missing_backend_configuration_cannot_claim_success(settings):
    with pytest.raises(SupabaseError, match="SUPABASE_CONFIGURATION_REQUIRED"):
        refresh.build_repo(settings, False)
    assert isinstance(refresh.build_repo(settings, True), MemoryRepository)


def test_failed_snapshot_validation_is_non_green_and_never_syncs(settings, monkeypatch, tmp_path):
    repo = Repo([event(event_start=(datetime.now(KST) + timedelta(days=1)).isoformat())])
    monkeypatch.setattr(refresh, "DATA_DIR", tmp_path)
    monkeypatch.setattr(refresh, "validate_export", lambda _: ["PRIVATE_VALIDATION_DETAIL"])
    replace = Mock()
    monkeypatch.setattr(repo, "replace_public_feed", replace)
    assert refresh.export(settings, repo, False) == refresh.EXIT_PUBLISH
    replace.assert_not_called()


def test_resident_maps_projection_failure_to_non_green_heartbeat(monkeypatch):
    import dooray_web_agent as resident
    from ggongbab.web.exit_codes import PipelineFailed
    monkeypatch.setattr(resident, "log", lambda _: None)
    monkeypatch.setattr(resident.subprocess, "run", Mock(return_value=SimpleNamespace(returncode=23, stdout="", stderr="")))
    with pytest.raises(PipelineFailed):
        resident._run_pipeline()
    beat = resident.heartbeat_from_exit(40, published=False)
    assert beat["status"] == "pipeline_error" and beat["last_publish_at"] is None


def test_archive_path_surfaces_publication_failure(settings, monkeypatch, capsys):
    monkeypatch.setattr(refresh, "load_settings", lambda: settings)
    monkeypatch.setattr(refresh, "build_repo", lambda *args: Repo())
    monkeypatch.setattr(refresh, "backfill_mail_archive", Mock(side_effect=PublicFeedError("PRIVATE")))
    monkeypatch.setattr("sys.argv", ["refresh_ggongbab.py", "--backfill-mail-archive", "fake.eml"])
    assert refresh.main() == 23
    assert "PRIVATE" not in capsys.readouterr().out


def test_dry_run_does_not_prepare_or_sync(settings, monkeypatch):
    repo = Repo()
    monkeypatch.setattr(repo, "public_feed_generation", Mock(side_effect=AssertionError("no sync")))
    assert refresh.export(settings, repo, True) == 0


def test_safe_portal_attach_timeout_diagnostic(tmp_path):
    from contextlib import contextmanager
    from ggongbab.portal_session import PortalSessionProvider, safe_reason_code
    from ggongbab.portal_list_poller import run_poller
    from ggongbab.portal_list_state import PortalListState
    from ggongbab.web.exit_codes import AuthRequired
    from ggongbab.web.resident import ResidentAttachTimeout

    @contextmanager
    def attach(*args, **kwargs):
        raise ResidentAttachTimeout("PRIVATE_DIAGNOSTIC")
        yield

    provider = PortalSessionProvider(tmp_path, 9223, owner_check=lambda *args: None, attach=attach)
    logs, beats = [], []
    code = run_poller(provider, PortalListState(tmp_path / "state"), emit_heartbeat=beats.append,
                      log=logs.append, once=True)
    assert code == 10 and "PORTAL_CDP_ATTACH_TIMEOUT" in logs
    assert "PRIVATE" not in str(logs) + str(beats)
    assert safe_reason_code(AuthRequired("JSESSIONID=PRIVATE")) == "PORTAL_SESSION_HANDOFF_FAILED"
