# -*- coding: utf-8 -*-
"""Instagram and reader-tip origins of Dooray collection tasks (owner decision 2026-10-31).

Synthetic tasks only: built with the real task writer the way the Instagram radar's bridge and the
tip board build them, then read back by the real Dooray collector, pipeline and exporter.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from ggongbab import source_origin
from ggongbab.collectors.dooray import DoorayCollector
from ggongbab.db.repository import MemoryRepository
from ggongbab.exporter import build_payload, public_event
from ggongbab.models import Evidence
from ggongbab.pipeline import Pipeline
from ggongbab.public_feed import PUBLIC_FIELDS, prepare_public_feed, to_snapshot_event
from ggongbab.web.task_writer import MailPayload, TaskWriter

from .conftest import REFERENCE, TEST_NOW, FakeExtractor, make_extraction
from .test_pipeline_export import DOORAY_POST, FUTURE, FUTURE_TEXT, ListCollector

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from validate_content import validate_ggongbab_payload  # noqa: E402

HANDLES = frozenset({"kaist_cs", "i_love_mesc"})
READ_HANDLES = source_origin.instagram_handles.__wrapped__      # the loader itself, before the fixture
TIP_ID = "3f2b8c1e-9a4d-4e6f-8b2a-1c3d5e7f9a0b"


@pytest.fixture(autouse=True)
def followed(monkeypatch):
    monkeypatch.setattr(source_origin, "instagram_handles", lambda *a: HANDLES)


def bridge_body(handle="kaist_cs", links=("https://www.instagram.com/p/DfCRCEskwzw/",), caption=FUTURE_TEXT):
    """What the radar's bridge writes (scripts/ggongbab/instagram/radar.py)."""
    return (f"{caption}\n\n[인스타그램 @{handle} (KAIST 전산학부 학생회) 게시물]\n"
            f"게시: 2026-10-29 18:00 (KST)\n" + "\n".join(f"원본: {link}" for link in links))


def task(settings, subject, body, post_id="4454148888659858349"):
    """A Dooray post as the collector reads it back, made by the real task writer."""
    built = TaskWriter(settings).build_task(MailPayload(mail_id=f"x-{post_id}", subject=subject, body=body,
                                                        received_at=REFERENCE, discovered_at=REFERENCE))
    return {"id": post_id, "subject": built["subject"], "body": built["body"],
            "createdAt": "2026-10-29T09:00:00+00:00", "updatedAt": "2026-10-29T09:00:00+00:00", "files": []}


def collect(settings, post):
    return DoorayCollector(settings, client=object(), fetch_attachments=False).normalize_post(post)


# --- the marker ---------------------------------------------------------------------------------
def test_a_radar_task_is_an_instagram_item_with_the_rebuilt_post_link(settings):
    item = collect(settings, task(settings, "[인스타 @kaist_cs] 중간고사 간식 나눔", bridge_body()))
    assert item.source_type == "dooray"                     # still a Dooray item: identity and priority
    assert item.metadata["origin"] == "instagram"
    assert item.source_url == "https://www.instagram.com/p/DfCRCEskwzw/"


@pytest.mark.parametrize("link, expected", [
    ("https://www.instagram.com/reel/Cx_1-ab/", "https://www.instagram.com/reel/Cx_1-ab/"),
    ("https://www.instagram.com/p/DfCRCEskwzw", "https://www.instagram.com/p/DfCRCEskwzw/"),
])
def test_a_reel_or_a_link_without_the_slash_is_rebuilt_canonically(settings, link, expected):
    item = collect(settings, task(settings, "[인스타 @kaist_cs] 간식", bridge_body(links=(link,))))
    assert item.source_url == expected


def test_a_merged_group_links_its_first_post(settings):
    links = ("https://www.instagram.com/p/AAAAA1/", "https://www.instagram.com/p/BBBBB2/")
    item = collect(settings, task(settings, "[인스타 @kaist_cs] 간식", bridge_body(links=links)))
    assert item.source_url == links[0]


@pytest.mark.parametrize("subject, body", [
    # a handle the radar does not follow
    ("[인스타 @kaist_fake] 간식", bridge_body(handle="kaist_fake")),
    # the subject and the block name different accounts
    ("[인스타 @kaist_cs] 간식", bridge_body(handle="i_love_mesc")),
    # a handle that only starts like a followed one
    ("[인스타 @kaist_cs] 간식", bridge_body(handle="kaist_csx")),
    # not an Instagram post link
    ("[인스타 @kaist_cs] 간식", bridge_body(links=("https://instagram.com.evil.example/p/DfCRCEskwzw/",))),
    ("[인스타 @kaist_cs] 간식", bridge_body(links=("http://www.instagram.com/p/DfCRCEskwzw/",))),
    ("[인스타 @kaist_cs] 간식", bridge_body(links=("https://www.instagram.com/p/DfCRCEskwzw/?igsh=abc",))),
    ("[인스타 @kaist_cs] 간식", bridge_body(links=("https://www.instagram.com/stories/kaist_cs/1/",))),
    # the marker without a permalink
    ("[인스타 @kaist_cs] 간식", bridge_body(links=())),
    # a permalink only in the caption, outside the radar's block
    ("[인스타 @kaist_cs] 간식", "원본: https://www.instagram.com/p/DfCRCEskwzw/\n" + FUTURE_TEXT),
    # the block without the subject marker
    ("인스타 간식 안내", bridge_body()),
    ("공지 [인스타 @kaist_cs] 간식", bridge_body()),
])
def test_a_partial_or_forged_instagram_marker_stays_a_dooray_item(settings, subject, body):
    item = collect(settings, task(settings, subject, body))
    assert "origin" not in item.metadata and item.source_url == ""


def test_a_forwarded_mail_carrying_the_marker_stays_a_dooray_item(settings):
    """A mail sorted into the project by rule has a sender; agent tasks never do."""
    post = dict(DOORAY_POST, subject="[인스타 @kaist_cs] 간식", body={"mimeType": "text/plain", "content": (
        "-----Original Message-----\nFrom: \"Someone\" <someone@example.com>\nSent: 2026-10-29 18:00 (GMT+09:00)\n"
        "Subject: [인스타 @kaist_cs] 간식\n\n" + bridge_body()
        + "\n\n[ggongbab-agent] collected from the Dooray mailbox\nmail_key=abc")})
    item = collect(settings, post)
    assert "origin" not in item.metadata and item.source_url == ""


def test_the_followed_accounts_come_from_the_radar_list_and_a_missing_list_trusts_none(tmp_path):
    assert {"i_love_mesc", "shoutoutto.ee"} <= READ_HANDLES(ROOT / "inputs/instagram/accounts.json")
    assert READ_HANDLES(tmp_path / "absent.json") == frozenset()
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    assert READ_HANDLES(tmp_path / "broken.json") == frozenset()


def test_a_tip_board_task_is_a_tip_without_a_link(settings):
    item = collect(settings, task(settings, "[꽁밥 제보] N1 로비 피자", f"{FUTURE_TEXT}\n\n제보 ID: {TIP_ID}"))
    assert item.metadata["origin"] == "tip" and item.source_url == ""


@pytest.mark.parametrize("subject, body", [
    ("[꽁밥 제보] 피자", FUTURE_TEXT),                                         # no ID line
    ("[꽁밥 제보] 피자", f"{FUTURE_TEXT}\n제보 ID: 1234"),                      # not a UUID
    ("[꽁밥 제보] 피자", f"{FUTURE_TEXT}\n제보 ID: {TIP_ID.upper()}"),          # not the board's form
    ("[꽁밥 제보] 피자", f"{FUTURE_TEXT}\n제보 ID: {TIP_ID} 추가"),            # not the whole line
    ("꽁밥 제보: 피자", f"{FUTURE_TEXT}\n제보 ID: {TIP_ID}"),                   # no subject marker
])
def test_a_partial_tip_marker_stays_a_dooray_item(settings, subject, body):
    item = collect(settings, task(settings, subject, body))
    assert "origin" not in item.metadata


def test_an_ordinary_mail_task_is_unchanged(settings):
    item = collect(settings, DOORAY_POST)
    assert item.source_type == "dooray" and item.source_url == "" and "origin" not in item.metadata


# --- through the pipeline and the exporter ---------------------------------------------------------
def future_extraction(_text):
    return make_extraction(
        title="기업 설명회", event_start=FUTURE.isoformat(), date_text=f"{FUTURE.month}월 {FUTURE.day}일",
        evidence=Evidence(event_time=f"{FUTURE.month}월 {FUTURE.day}일 12시", location="N1에서",
                          food="참석자에게 점심 도시락을 제공합니다", registration=None))


def run(settings, *posts):
    repo = MemoryRepository()
    items = [collect(settings, post) for post in posts]
    Pipeline(settings, repo, FakeExtractor(future_extraction), [ListCollector(items)]).run()
    return repo, build_payload(repo.publishable_events(), settings, TEST_NOW)


def test_an_instagram_event_merged_with_its_mail_lists_both_and_links_only_the_post(settings):
    insta = task(settings, "[인스타 @kaist_cs] 기업 설명회", bridge_body(), post_id="4454148888659858350")
    repo, payload = run(settings, DOORAY_POST, insta)
    assert len(repo.events) == 1
    [event] = payload["events"]
    assert event["sources"] == [{"type": "dooray", "name": "Dooray"},
                                {"type": "instagram", "name": "Instagram",
                                 "url": "https://www.instagram.com/p/DfCRCEskwzw/"}]
    assert validate_ggongbab_payload(payload, TEST_NOW) == []


def test_a_tip_event_is_published_as_a_tip_without_a_link(settings):
    _, payload = run(settings, task(settings, "[꽁밥 제보] 기업 설명회", f"{FUTURE_TEXT}\n\n제보 ID: {TIP_ID}"))
    assert payload["events"][0]["sources"] == [{"type": "tip", "name": "제보"}]
    assert validate_ggongbab_payload(payload, TEST_NOW) == []


def test_an_origin_read_after_the_item_was_stored_is_recorded_without_a_new_parse(settings):
    """A task stored before this change gains its origin on the next run, from the cache."""
    post = task(settings, "[인스타 @kaist_cs] 기업 설명회", bridge_body())
    repo = MemoryRepository()
    extractor = FakeExtractor(future_extraction)
    old = collect(settings, post)
    old.metadata.pop("origin")
    old.source_url = ""
    Pipeline(settings, repo, extractor, [ListCollector([old])]).run()
    Pipeline(settings, repo, extractor, [ListCollector([collect(settings, post)])]).run()
    assert len(extractor.calls) == 1
    [event] = build_payload(repo.publishable_events(), settings, TEST_NOW)["events"]
    assert event["sources"][0]["type"] == "instagram"


def row(**sources):
    base = {"id": "6f1c2b9e-0d4a-4c1e-9f7a-2b3c4d5e6f70", "title": "간식", "status": "published", "needs_review": False,
            "confidence": 0.95, "event_start": (TEST_NOW + timedelta(days=1)).isoformat(), "food_provided": "true",
            "food_type": "snack", "content_type": "free_food"}
    return base | sources


def test_the_exporter_keeps_only_a_canonical_post_link_and_never_a_tip_link():
    event = public_event(row(_sources=[
        {"type": "instagram", "url": "https://www.instagram.com/p/DfCRCEskwzw/"},
        {"type": "tip", "url": "https://example.com/private"},
        {"type": "dooray", "url": "https://kaist.dooray.com/project/1"}]))
    assert event["sources"] == [{"type": "instagram", "name": "Instagram", "url": "https://www.instagram.com/p/DfCRCEskwzw/"},
                                {"type": "tip", "name": "제보"}, {"type": "dooray", "name": "Dooray"}]
    forged = public_event(row(_sources=[{"type": "instagram", "url": "https://www.instagram.com/p/DfCRCEskwzw/?x=1"}]))
    assert forged["sources"] == [{"type": "instagram", "name": "Instagram"}]


@pytest.mark.parametrize("source, error", [
    ({"type": "instagram", "name": "Instagram", "url": "https://www.instagram.com/p/DfCRCEskwzw"}, "canonical post link"),
    ({"type": "instagram", "name": "Instagram", "url": "https://example.com/p/DfCRCEskwzw/"}, "canonical post link"),
    ({"type": "tip", "name": "제보", "url": "https://example.com/tip"}, "only public notice links"),
])
def test_the_validator_refuses_a_non_canonical_post_link_and_any_tip_link(settings, source, error):
    _, payload = run(settings, DOORAY_POST)
    payload["events"][0]["sources"] = [source]
    assert any(error in e for e in validate_ggongbab_payload(payload, TEST_NOW))


# --- the lab projection ----------------------------------------------------------------------------
def test_the_projection_carries_the_origin_and_its_link_once_migration_007_is_applied(settings):
    insta = task(settings, "[인스타 @kaist_cs] 기업 설명회", bridge_body(), post_id="4454148888659858350")
    repo, payload = run(settings, DOORAY_POST, insta)
    [public] = prepare_public_feed(repo, settings, TEST_NOW).rows
    assert public["source_types"] == ["dooray", "instagram"]
    assert public["source_links"] == [{"type": "instagram", "url": "https://www.instagram.com/p/DfCRCEskwzw/"}]
    assert to_snapshot_event(public)["sources"] == payload["events"][0]["sources"]


def test_before_migration_007_the_projection_keeps_the_006_shape(settings):
    insta = task(settings, "[인스타 @kaist_cs] 기업 설명회", bridge_body(), post_id="4454148888659858350")
    tip = task(settings, "[꽁밥 제보] 기업 설명회", f"{FUTURE_TEXT}\n\n제보 ID: {TIP_ID}", post_id="4454148888659858351")
    repo, payload = run(settings, DOORAY_POST, insta, tip)
    repo.public_feed_links = False
    [public] = prepare_public_feed(repo, settings, TEST_NOW).rows
    assert public["source_types"] == ["dooray"] and "source_links" not in public
    # exactly the 006 row, revision included, so an unmigrated projection is not rewritten
    assert set(public) == set(PUBLIC_FIELDS) | {"content_revision"}
    canonical = json.dumps({key: public[key] for key in PUBLIC_FIELDS}, sort_keys=True, ensure_ascii=False,
                           separators=(",", ":"), allow_nan=False)
    assert public["content_revision"] == hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ProbeClient:
    def __init__(self, error=None):
        self.error, self.calls = error, []

    def select(self, table, params):
        self.calls.append((table, params))
        if self.error:
            from ggongbab.db.supabase_client import SupabaseError
            raise SupabaseError(self.error)
        return []


def test_the_migration_probe_reads_one_column_and_only_a_missing_column_means_not_applied():
    from ggongbab.db.repository import SupabaseRepository
    from ggongbab.db.supabase_client import SupabaseError
    applied = ProbeClient()
    assert SupabaseRepository(applied).public_feed_has_links() is True
    assert applied.calls == [("ggongbab_public_events", {"select": "source_links", "limit": 0})]
    missing = ProbeClient('GET ggongbab_public_events: HTTP 400 {"code":"42703","message":"column does not exist"}')
    assert SupabaseRepository(missing).public_feed_has_links() is False
    with pytest.raises(SupabaseError):
        SupabaseRepository(ProbeClient("GET ggongbab_public_events: HTTP 503 unavailable")).public_feed_has_links()


def test_migration_007_widens_the_allowlist_and_keeps_the_006_keys_accepted():
    sql = (ROOT / "supabase/migrations/007_ggongbab_source_links.sql").read_text(encoding="utf-8").lower()
    assert "\nbegin;" in sql and "\ncommit;" in sql and sql.index("\nbegin;") < sql.index("\ncommit;")
    assert "'instagram', 'tip']::text[]" in sql
    assert "optional_keys constant text[] := array['food_source', 'giveaway', 'giveaway_description', 'source_links']" in sql
    assert "add column if not exists source_links jsonb not null default '[]'::jsonb" in sql
    assert "check (public.ggongbab_public_source_links_ok(source_links))" in sql
    assert "'^https://www\\.instagram\\.com/(p|reel)/[a-za-z0-9_-]{5,20}/$'" in sql
    assert "security definer" not in sql and sql.count("security invoker") == 1
    grants = [line for line in sql.splitlines() if line.startswith("grant ")]
    assert grants and all(line.endswith("to service_role;") for line in grants)
    assert "drop table" not in sql and "alter publication" not in sql
