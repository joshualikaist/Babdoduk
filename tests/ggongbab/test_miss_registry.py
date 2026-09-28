# -*- coding: utf-8 -*-
"""Every confirmed miss stays fixed: each registry fixture replays through the real stages.

tests/fixtures/ggongbab/misses/MISS-*.json holds a sanitized source text and what each
stage must conclude (see docs/GGONGBAB_DISCOVERY.md, "Miss registry"). A new confirmed
miss is a new fixture file; nothing here is specific to one incident.
"""
from __future__ import annotations

import copy
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from ggongbab.config import Settings
from ggongbab.exporter import build_payload
from ggongbab.models import EventExtraction
from ggongbab.parsers.rule_parser import analyze
from ggongbab.parsers.validator import validate
from ggongbab.prefilter import classify

ROOT = Path(__file__).resolve().parents[2]
MISSES = sorted((ROOT / "tests/fixtures/ggongbab/misses").glob("MISS-*.json"))
CASES = [json.loads(p.read_text(encoding="utf-8")) for p in MISSES]
IDS = [c["id"] for c in CASES]

EXTRACTION_DEFAULTS = dict(summary=None, building=None, room=None, organizer=None, registration_deadline=None,
                           registration_url=None, confidence=0.9, needs_review=False, review_reason=None,
                           location_name=None, date_text=None, time_text=None, food_description=None)


def text_of(case):
    return f"{case['input']['subject']}\n{case['input']['body']}"


def received(case):
    return datetime.fromisoformat(case["input"]["received_at"])


def extraction(case, change=None):
    data = {**EXTRACTION_DEFAULTS, **copy.deepcopy(case["expected"]["extraction"])}
    for key, value in (change or {}).items():
        if key == "evidence":
            data["evidence"].update(value)
        else:
            data[key] = value
    return EventExtraction(**data)


def validated_row(case, change=None):
    facts = analyze(text_of(case), received(case))
    cand = validate(extraction(case, change), facts, text_of(case), source_type=case["source_class"].split("_")[0],
                    reference=received(case))
    return cand, {**cand.to_db_row(), "id": case["id"], "_sources": [{"type": "dooray"}]}


def test_registry_is_not_empty_and_ids_are_unique():
    assert CASES and len(set(IDS)) == len(IDS)
    for path, case in zip(MISSES, CASES):
        assert path.name.startswith(case["id"] + "-")


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_fixture_is_sanitized(case):
    blob = json.dumps(case, ensure_ascii=False)
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", blob), "e-mail address"
    assert not re.search(r"https?://", blob), "link"
    without_times = re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", "", blob)
    assert not re.search(r"\d{6,}", without_times), "long id"
    assert not re.search(r"(?<!\d)01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}", blob), "phone number"
    assert "dooray.com" not in blob and "mail_key" not in blob


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_prefilter_finds_it(case):
    want = case["expected"]["prefilter"]
    subject_only = classify(case["input"]["subject"], "", received(case))
    full = classify(case["input"]["subject"], case["input"]["body"], received(case))
    assert subject_only.candidate is want["subject_only_candidate"], subject_only.reason
    assert full.candidate is want["full_text_candidate"], full.reason
    assert full.urgency == want["urgency"]


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_rules_read_it(case):
    facts = analyze(text_of(case), received(case))
    for key, value in case["expected"]["rules"].items():
        assert getattr(facts, key) == value, key


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_validator_publishes_the_faithful_extraction(case):
    cand, row = validated_row(case)
    for key, value in case["expected"]["validated"].items():
        assert row[key] == value, (key, row[key], cand.review_reasons)


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_known_misreadings_do_not_change_the_public_facts(case):
    want = case["expected"]["validated"]
    for misreading in case["expected"]["ai_misreadings"]:
        cand, row = validated_row(case, misreading["change"])
        for key in ("status", "registration_required", "eligibility", "food_provided", "food_type"):
            assert row[key] == want[key], (misreading["name"], key, row[key], cand.review_reasons)


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_feed_and_page_keep_it_listed_while_it_may_be_running(case):
    _cand, row = validated_row(case)
    settings = Settings()
    public = case["expected"]["public"]
    times = public["listed_at"] + public["not_listed_at"]
    exported = {t: build_payload([row], settings, datetime.fromisoformat(t), food_only=True)["events"] for t in times}
    for t in public["listed_at"]:
        assert exported[t], ("feed", t)
    event = next(e for events in exported.values() for e in events)
    if public["food_bucket"] == "refreshment":
        assert event["food"]["type"] in {"beverage", "refreshment"}
    script = (
        "const fs=require('fs'),vm=require('vm');const c={window:{},Date};vm.createContext(c);"
        "vm.runInContext(fs.readFileSync('js/ggongbab-select.js','utf8'),c);const F=c.window.BabdodukFreeFood;"
        "const ev=JSON.parse(process.argv[1]);const out={};"
        "for(const t of JSON.parse(process.argv[2])){out[t]=F.todayUpcoming([ev],F.toKst(t)).length;}"
        "console.log(JSON.stringify(out));")
    result = subprocess.run(["node", "-e", script, json.dumps(event, ensure_ascii=False), json.dumps(times)],
                            cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr[-1000:]
    listed = json.loads(result.stdout)
    for t in public["listed_at"]:
        assert listed[t] == 1, ("page", t)
    for t in public["not_listed_at"]:
        assert listed[t] == 0, ("page", t)


def test_beverage_is_grouped_under_refreshment_on_the_page():
    script = (ROOT / "js/ggongbab.js").read_text(encoding="utf-8")
    assert "if (type === 'refreshment' || type === 'beverage') return 'refreshment';" in script
