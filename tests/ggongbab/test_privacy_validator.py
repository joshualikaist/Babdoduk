# -*- coding: utf-8 -*-
"""Structure-aware privacy validation of the public ggongbab JSON (latest.json and the archive).

The privacy patterns run on the public text fields only: an id, a timestamp or a URL path is
never read as a phone number, while real personal data in public text is still refused.
Synthetic data only; everything here is deterministic.
"""
from __future__ import annotations

import copy
import json
import random
import uuid
from datetime import datetime, timedelta

import pytest

import validate_content as vc
from ggongbab.config import KST
from ggongbab.exporter import archived_event, build_payload, public_event
from validate_content import PHONE_RE, validate_ggongbab_archive_payload, validate_ggongbab_payload

from .conftest import TEST_NOW
from .test_export_contract import row

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=KST)
# A valid uuid4 whose segments "b18-8387-8430" read as the mobile number 018-8387-8430. Under the
# old whole-JSON scan this id alone failed the export with "contains a phone number".
PHONE_LIKE_UUID = "af775085-697f-4b18-8387-8430f235e0b0"
NOTICE_URL = "https://www.kaist.ac.kr/kr/html/campus/053501.html"


def event(**over):
    base = {
        "id": "3f1c2a4e-5b6d-4e7f-8a9b-0c1d2e3f4a5b",
        "title": "진로 세미나", "summary": "점심 도시락을 제공하는 세미나입니다.",
        "startAt": (NOW + timedelta(days=2)).isoformat(), "endAt": (NOW + timedelta(days=2, hours=1)).isoformat(),
        "dateText": "9월 29일", "timeText": "12시",
        "location": {"name": "KI빌딩", "building": "N1", "room": "101호"},
        "food": {"provided": "true", "type": "lunchbox", "description": "점심 도시락"},
        "organizer": "경력개발센터", "eligibility": "KAIST 학생",
        "registration": {"required": "true", "deadline": (NOW + timedelta(days=1)).isoformat(),
                         "url": "https://forms.gle/AbCdEf123"},
        "confidence": 0.95,
        "sources": [{"type": "kaist_public", "name": "KAIST 공지", "url": NOTICE_URL}],
    }
    base.update(over)
    return base


def past_event(**over):
    ev = event(**over)
    del ev["registration"], ev["confidence"]  # a past listing carries no sign-up data
    ev["startAt"], ev["endAt"] = (NOW - timedelta(days=2, hours=1)).isoformat(), (NOW - timedelta(days=2)).isoformat()
    return ev


def live(*events):
    return {"generatedAt": NOW.isoformat(), "timezone": "Asia/Seoul", "count": len(events), "events": list(events)}


def archive(*events):
    return {"generatedAt": NOW.isoformat(), "timezone": "Asia/Seoul", "windowDays": 30,
            "count": len(events), "events": list(events)}


def check_live(ev):
    return validate_ggongbab_payload(live(ev), NOW)


def check_archive(ev):
    return validate_ggongbab_archive_payload(archive(ev))


# kind: (event factory, validator, event tag, message prefix)
VALIDATORS = {"live": (event, check_live, "events[0]", "ggongbab export"),
              "archive": (past_event, check_archive, "archive[0]", "ggongbab archive")}


def with_value(ev, path, value):
    """A copy of ev with the value at a dotted path such as "location.name" or "sources[0].name"."""
    ev = copy.deepcopy(ev)
    parts = path.replace("[0]", ".0").split(".")
    target = ev
    for part in parts[:-1]:
        target = target[int(part)] if part.isdigit() else target[part]
    target[int(parts[-1]) if parts[-1].isdigit() else parts[-1]] = value
    return ev


@pytest.mark.parametrize("kind", VALIDATORS)
def test_the_synthetic_events_are_valid(kind):
    make, check, _, _ = VALIDATORS[kind]
    assert check(make()) == []


# ---------------------------------------------------------------------------
# The regression: a structural UUID is not a phone number
# ---------------------------------------------------------------------------
def test_the_fixed_uuid_reproduces_the_bug_class():
    assert uuid.UUID(PHONE_LIKE_UUID).version == 4 and str(uuid.UUID(PHONE_LIKE_UUID)) == PHONE_LIKE_UUID
    assert PHONE_RE.search(PHONE_LIKE_UUID).group() == "18-8387-8430"
    assert PHONE_RE.search(json.dumps(live(event(id=PHONE_LIKE_UUID))))  # what the old whole-JSON scan matched


@pytest.mark.parametrize("kind", VALIDATORS)
def test_a_phone_like_uuid_id_is_not_a_privacy_error(kind):
    make, check, _, _ = VALIDATORS[kind]
    assert check(make(id=PHONE_LIKE_UUID)) == []


def test_the_exporter_output_with_that_id_validates(settings):
    payload = build_payload([row(id=PHONE_LIKE_UUID)], settings, TEST_NOW, food_only=True)
    assert [ev["id"] for ev in payload["events"]] == [PHONE_LIKE_UUID]
    assert validate_ggongbab_payload(payload, TEST_NOW) == []


def seeded_uuids(n=4000, seed=20260927):
    rng = random.Random(seed)
    return [str(uuid.UUID(int=rng.getrandbits(128), version=4)) for _ in range(n)]


def test_structural_uuid_ids_never_trigger_privacy_errors():
    ids = seeded_uuids()
    phone_like = [uid for uid in ids if PHONE_RE.search(uid)]
    assert len(phone_like) >= 5, len(phone_like)  # the sample really contains the old ~0.28% false-positive class
    for uid in ids:
        assert validate_ggongbab_payload(live(event(id=uid)), NOW) == [], uid
        assert validate_ggongbab_archive_payload(archive(past_event(id=uid))) == [], uid


# ---------------------------------------------------------------------------
# Real personal data in public text is still refused
# ---------------------------------------------------------------------------
PHONES = ["010-1234-5678", "01012345678", "010 1234 5678", "010.1234.5678",
          "+82 10-1234-5678", "+82-10-1234-5678", "+821012345678"]
TEXT_PATHS = ["title", "summary", "dateText", "timeText", "organizer", "eligibility",
              "location.name", "location.building", "location.room", "food.description", "sources[0].name"]


@pytest.mark.parametrize("kind", VALIDATORS)
@pytest.mark.parametrize("path", TEXT_PATHS)
@pytest.mark.parametrize("phone", PHONES)
def test_a_real_phone_number_in_public_text_is_rejected(kind, path, phone):
    make, check, tag, prefix = VALIDATORS[kind]
    errors = check(with_value(make(), path, f"문의 {phone}"))
    assert f"{prefix} contains a phone number in {tag}.{path}" in errors, errors


LEAKS = [("someone@kaist.ac.kr", "an e-mail address"),
         ("sk-A1b2C3d4E5f6G7h8I9", "a token-like string"),
         ("eyJ" + "a" * 24 + "." + "b" * 12, "a token-like string"),
         ("dooray-api abcdef123", "a token-like string"),
         ("https://kaist.dooray.com/project/tasks/123", "a Dooray/private file link"),
         ("/files/AbCdEf123456", "a Dooray/private file link")]


@pytest.mark.parametrize("kind", VALIDATORS)
@pytest.mark.parametrize("path", ["title", "summary", "organizer", "location.name", "food.description", "sources[0].name"])
@pytest.mark.parametrize("leak, label", LEAKS)
def test_email_tokens_and_private_links_in_public_text_are_rejected(kind, path, leak, label):
    make, check, tag, prefix = VALIDATORS[kind]
    errors = check(with_value(make(), path, f"안내 {leak}"))
    assert f"{prefix} contains {label} in {tag}.{path}" in errors, errors


@pytest.mark.parametrize("kind", VALIDATORS)
@pytest.mark.parametrize("path", ["sender_email", "raw_text", "review_reason", "external_id", "location.recipient"])
def test_private_fields_are_refused_by_name(kind, path):
    make, check, tag, _ = VALIDATORS[kind]
    errors = check(with_value(make(), path, "x"))
    assert any("private field" in err and err.endswith(path.split(".")[-1]) for err in errors), errors
    assert f"{tag}.{path} is not in the reviewed public schema; privacy review required" in errors


@pytest.mark.parametrize("kind", VALIDATORS)
def test_text_hidden_in_the_wrong_shape_is_refused(kind):
    make, check, tag, _ = VALIDATORS[kind]
    assert f"{tag}.location has an unexpected shape" in check(with_value(make(), "location", "문의 010-1234-5678"))
    assert f"{tag}.title must be text" in check(with_value(make(), "title", 1012345678))


@pytest.mark.parametrize("kind", VALIDATORS)
def test_ids_are_plain_identifiers(kind):
    make, check, tag, prefix = VALIDATORS[kind]
    for bad in ("someone@kaist.ac.kr", "https://kaist.dooray.com/x", "id with spaces"):
        assert f"{tag}.id is not a plain identifier" in check(make(id=bad)), bad
    assert f"{prefix} contains a token-like string in {tag}.id" in check(make(id="sk-A1b2C3d4E5f6G7h8I9"))


# ---------------------------------------------------------------------------
# URLs: URL rules, not text rules
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("kind", VALIDATORS)
@pytest.mark.parametrize("url", [
    "https://www.kaist.ac.kr/kr/html/news/01012345678",                              # phone-like digits in the path
    "https://www.kaist.ac.kr/kr/html/campus/053501.html?mode=V&mng_no=1712345678",   # a numeric id, no dial prefix
    "https://www.kaist.ac.kr/kr/html/campus/053501.html?mode=V&mng_no=12345",
    "https://example.org/notice/" + PHONE_LIKE_UUID,
])
def test_a_public_url_with_numeric_ids_is_accepted(kind, url):
    make, check, _, _ = VALIDATORS[kind]
    assert check(with_value(make(), "sources[0].url", url)) == []


def test_a_registration_url_with_numeric_ids_is_accepted():
    assert check_live(with_value(event(), "registration.url", "https://forms.gle/10123456789")) == []


BAD_URLS = [
    ("javascript:alert(1)", "invalid"),
    ("mailto:someone@kaist.ac.kr", "invalid"),
    ("https:///no-host", "invalid"),
    ("https://user:secret@example.org/form", "carries credentials"),
    ("https://kaist.dooray.com/project/tasks/123", "a Dooray/private file link"),
    ("https://example.org/files/AbCdEf123456", "a Dooray/private file link"),
    ("https://example.org/form?email=someone@kaist.ac.kr", "an e-mail address"),
    ("https://example.org/form?email=someone%40kaist.ac.kr", "an e-mail address"),
    ("https://example.org/form?key=sk-A1b2C3d4E5f6G7h8I9", "a token-like string"),
    ("https://docs.google.com/forms/d/e/x/viewform?entry.1234567890=010-1234-5678", "a phone number"),
    ("https://example.org/form?tel=%2B82-10-1234-5678", "a phone number"),
    ("https://example.org/form#tel=01012345678", "a phone number"),
]


@pytest.mark.parametrize("kind", VALIDATORS)
@pytest.mark.parametrize("url, label", BAD_URLS)
def test_a_private_or_unsafe_source_url_is_rejected(kind, url, label):
    make, check, tag, _ = VALIDATORS[kind]
    errors = check(with_value(make(), "sources[0].url", url))
    assert any(label in err and f"{tag}.sources[0].url" in err for err in errors), errors


@pytest.mark.parametrize("url, label", BAD_URLS)
def test_a_private_or_unsafe_registration_url_is_rejected(url, label):
    errors = check_live(with_value(event(), "registration.url", url))
    assert any(label in err and "events[0].registration.url" in err for err in errors), errors


@pytest.mark.parametrize("kind", VALIDATORS)
@pytest.mark.parametrize("source_type", ["dooray", "dooray_mailbox", "portal"])
def test_an_internal_source_never_carries_a_url(kind, source_type):
    make, check, tag, _ = VALIDATORS[kind]
    ev = with_value(make(), "sources", [{"type": source_type, "name": "x", "url": "https://example.org/notice/1"}])
    assert f"{tag} exposes a {source_type} source URL; only public notice links may be kept" in check(ev)


# ---------------------------------------------------------------------------
# Contract: privacy scanning follows an explicit, reviewed schema
# ---------------------------------------------------------------------------
# Changing this list is a privacy decision. Review the new field, then update both lists.
EXPECTED_TEXT_FIELDS = ("title", "summary", "dateText", "timeText", "organizer", "eligibility",
                        "location.name", "location.building", "location.room", "food.description", "sources[].name")


def test_the_privacy_scanned_text_fields_are_an_explicit_reviewed_list():
    assert vc.GG_PUBLIC_TEXT_FIELDS == EXPECTED_TEXT_FIELDS


def test_privacy_patterns_run_only_on_the_allowlisted_text_fields(monkeypatch):
    scanned = []
    real = vc.gg_text_errors
    monkeypatch.setattr(vc, "gg_text_errors", lambda prefix, where, text: scanned.append(where) or real(prefix, where, text))
    assert validate_ggongbab_payload(live(event(id=PHONE_LIKE_UUID)), NOW) == []
    assert sorted(scanned) == sorted(f"events[0].{field.replace('[]', '[0]')}" for field in EXPECTED_TEXT_FIELDS)


def schema_kind(path):
    node = vc.GG_EVENT_SCHEMA
    for part in path.split("."):
        key, is_list = (part[:-2], True) if part.endswith("[]") else (part, False)
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key][0] if is_list else node[key]
    return node


def leaf_paths(value, path=""):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from leaf_paths(item, f"{path}.{key}" if path else key)
    elif isinstance(value, list):
        for item in value:
            yield from leaf_paths(item, path + "[]")
    else:
        yield path


def full_row():
    """A canonical row with every column the exporter reads, filled in."""
    return {"id": PHONE_LIKE_UUID, "title": "t", "summary": "s",
            "event_start": "2026-10-01T03:00:00+00:00", "event_end": "2026-10-01T04:00:00+00:00",
            "date_text": "d", "time_text": "t", "location_name": "n", "building": "b", "room": "r",
            "food_provided": "true", "food_type": "meal", "food_description": "f", "organizer": "o",
            "eligibility": "e", "registration_required": "true",
            "registration_deadline": "2026-09-30T03:00:00+00:00", "registration_url": "https://forms.gle/AbC",
            "confidence": 0.9, "_sources": [{"type": "kaist_public", "name": "KAIST 공지", "url": NOTICE_URL}]}


@pytest.mark.parametrize("export", [public_event, archived_event])
def test_every_field_the_exporter_publishes_has_a_privacy_classification(export):
    unclassified = sorted({path for path in leaf_paths(export(full_row())) if schema_kind(path) is None})
    assert not unclassified, (f"new public field(s) {unclassified}: review them for privacy and classify them "
                              "in validate_content.GG_EVENT_SCHEMA")


@pytest.mark.parametrize("kind, path", [("live", "contact"), ("live", "location.floor"), ("archive", "food.allergens")])
def test_an_unreviewed_field_is_refused_not_silently_scanned(kind, path):
    make, check, tag, _ = VALIDATORS[kind]
    errors = check(with_value(make(), path, "3층"))
    assert f"{tag}.{path} is not in the reviewed public schema; privacy review required" in errors


def test_unreviewed_top_level_keys_and_preview_diagnostics():
    assert any("top-level 'notes'" in err for err in validate_ggongbab_payload({**live(event()), "notes": "x"}, NOW))
    counters = {**live(event()), "_preview": {"publicCount": 1, "inputTokens": 1712345678}}  # a big counter is not a phone
    assert validate_ggongbab_payload(counters, NOW) == []
    counters["_preview"]["subject"] = "PRIVATE"
    assert "ggongbab export _preview must hold numeric counters only" in validate_ggongbab_payload(counters, NOW)
    assert any("top-level '_preview'" in err
               for err in validate_ggongbab_archive_payload({**archive(past_event()), "_preview": {"n": 1}}))
