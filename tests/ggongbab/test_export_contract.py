# -*- coding: utf-8 -*-
"""Public JSON contract: UTF-8, tri-state semantics and Asia/Seoul timestamps."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ggongbab.config import KST
from ggongbab.exporter import build_payload, kst_iso, tri_state, write_payload

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from validate_content import validate_ggongbab  # noqa: E402

FUTURE_UTC = (datetime.now(timezone.utc) + timedelta(days=4)).replace(hour=3, minute=0, second=0, microsecond=0)


def row(**over):
    base = {
        "id": "11111111-1111-1111-1111-111111111111",
        "title": "기업 설명회",
        "summary": "9월 25일 12시 N1에서 기업 설명회를 진행합니다.",
        # As Postgres returns it: timestamptz rendered in UTC.
        "event_start": FUTURE_UTC.isoformat(),
        "event_end": None, "registration_deadline": None,
        "date_text": "9월 25일", "time_text": "12시",
        "location_name": "N1", "building": "N1", "room": "101호",
        "food_provided": "true", "food_type": "lunchbox", "food_description": "점심 도시락 제공",
        "organizer": "경력개발센터", "eligibility": "", "registration_required": "unknown",
        "registration_url": "", "confidence": 0.99, "needs_review": False, "review_reason": None,
        "status": "published", "_sources": [{"type": "dooray", "name": "Dooray", "url": ""}],
    }
    base.update(over)
    return base


# --- UTF-8 -------------------------------------------------------------------
def test_utf8_json_roundtrip_is_real_korean(settings, tmp_path):
    payload = build_payload([row()], settings)
    path = write_payload(payload, tmp_path)
    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "no BOM"
    data = json.loads(raw.decode("utf-8"))          # must decode as UTF-8, not cp949
    ev = data["events"][0]
    assert ev["title"] == "기업 설명회"
    # The bytes really are Korean code points, not escapes or mojibake.
    assert ev["title"].encode("unicode_escape") == b"\\uae30\\uc5c5 \\uc124\\uba85\\ud68c"
    assert "기업 설명회".encode("utf-8") in raw
    assert "\\u" not in raw.decode("utf-8"), "ensure_ascii must stay False"
    assert ev["food"]["description"] == "점심 도시락 제공"


def test_mojibake_would_be_caught():
    """Sanity check for the diagnosis: cp949-misread UTF-8 does not round-trip."""
    correct = "기업 설명회"
    mojibake = correct.encode("utf-8").decode("cp949", errors="replace")
    assert mojibake != correct


# --- tri-state ---------------------------------------------------------------
@pytest.mark.parametrize("value,expected", [
    ("true", "true"), ("false", "false"), ("unknown", "unknown"),
    (None, "unknown"), ("", "unknown"), ("maybe", "unknown"), ("TRUE", "true"),
])
def test_tri_state_normalization(value, expected):
    assert tri_state(value) == expected


def test_unknown_food_stays_unknown_in_public_export(settings):
    payload = build_payload([row(food_provided="unknown", food_type="unknown", food_description="")], settings)
    food = payload["events"][0]["food"]
    assert food["provided"] == "unknown"
    assert food["provided"] is not False, "unknown must not collapse into false"


def test_explicit_false_food_is_preserved(settings):
    payload = build_payload([row(food_provided="false", food_type="unknown")], settings)
    assert payload["events"][0]["food"]["provided"] == "false"


def test_unknown_registration_stays_unknown_in_public_export(settings):
    payload = build_payload([row(registration_required="unknown")], settings)
    reg = payload["events"][0]["registration"]
    assert reg["required"] == "unknown"
    assert reg["required"] is not False


def test_registration_true_and_false_survive(settings):
    assert build_payload([row(registration_required="true")], settings)["events"][0]["registration"]["required"] == "true"
    assert build_payload([row(registration_required="false")], settings)["events"][0]["registration"]["required"] == "false"


def test_validator_rejects_boolean_tri_state(tmp_path, settings):
    payload = build_payload([row()], settings)
    payload["events"][0]["food"]["provided"] = True          # the old boolean contract
    payload["events"][0]["registration"]["required"] = False
    path = tmp_path / "latest.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    errors = "\n".join(validate_ggongbab(path))
    assert "food.provided must be true/false/unknown" in errors
    assert "registration.required must be true/false/unknown" in errors


# --- timezone ----------------------------------------------------------------
def test_kst_iso_converts_utc_to_seoul():
    assert kst_iso("2026-09-25T03:00:00+00:00") == "2026-09-25T12:00:00+09:00"
    assert kst_iso("2026-09-25T12:00:00+09:00") == "2026-09-25T12:00:00+09:00"
    assert kst_iso(datetime(2026, 9, 25, 3, 0, tzinfo=timezone.utc)) == "2026-09-25T12:00:00+09:00"
    assert kst_iso(None) is None and kst_iso("") is None


def test_export_normalizes_db_utc_timestamps_to_kst(settings):
    end_utc = (FUTURE_UTC + timedelta(hours=1)).isoformat()
    deadline_utc = (FUTURE_UTC - timedelta(days=1)).isoformat()
    payload = build_payload([row(event_end=end_utc, registration_deadline=deadline_utc,
                                 registration_required="true")], settings)
    ev = payload["events"][0]
    for value in (ev["startAt"], ev["endAt"], ev["registration"]["deadline"], payload["generatedAt"]):
        assert value.endswith("+09:00"), value
    # Same instant, Seoul wall clock: 03:00 UTC is 12:00 KST.
    assert datetime.fromisoformat(ev["startAt"]) == FUTURE_UTC
    assert datetime.fromisoformat(ev["startAt"]).hour == FUTURE_UTC.astimezone(KST).hour == 12


def test_validator_rejects_non_kst_offset(tmp_path, settings):
    payload = build_payload([row()], settings)
    payload["events"][0]["startAt"] = FUTURE_UTC.isoformat()   # +00:00
    path = tmp_path / "latest.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    assert any("not +09:00" in e for e in validate_ggongbab(path))


def test_full_payload_passes_validator(settings, tmp_path):
    payload = build_payload([row()], settings)
    path = write_payload(payload, tmp_path)
    assert validate_ggongbab(path) == []
