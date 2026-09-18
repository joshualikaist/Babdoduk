# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from ggongbab.config import KST, Settings  # noqa: E402
from ggongbab.models import EventExtraction, Evidence  # noqa: E402
from ggongbab.parsers.ai_parser import AIResult, AIUsage  # noqa: E402

REFERENCE = datetime(2026, 9, 19, 9, 0, tzinfo=KST)

POSITIVE_TEXT = "9월 25일 12시 N1에서 기업 설명회를 진행합니다.\n참석자에게 점심 도시락을 제공합니다."
NEGATIVE_TEXT = "9월 25일 12시 점심시간에 기업 설명회를 진행합니다."


def make_extraction(**overrides) -> EventExtraction:
    base = dict(
        is_event=True,
        title="기업 설명회",
        summary="9월 25일 12시 N1에서 열리는 기업 설명회.",
        event_start="2026-09-25T12:00:00+09:00",
        event_end=None,
        date_text="9월 25일",
        time_text="12시",
        location_name="N1",
        building="N1",
        room=None,
        food_provided="true",
        food_type="lunchbox",
        food_description="점심 도시락 제공",
        organizer=None,
        eligibility=None,
        registration_required="unknown",
        registration_deadline=None,
        registration_url=None,
        confidence=0.9,
        evidence=Evidence(event_time="9월 25일 12시", location="N1에서", food="참석자에게 점심 도시락을 제공합니다", registration=None),
        needs_review=False,
        review_reason=None,
    )
    base.update(overrides)
    return EventExtraction(**base)


class FakeExtractor:
    """Scripted extractor: maps model -> function(text) -> EventExtraction | None."""

    def __init__(self, primary: Callable[[str], Optional[EventExtraction]],
                 fallback: Optional[Callable[[str], Optional[EventExtraction]]] = None):
        self.primary = primary
        self.fallback = fallback or primary
        self.calls: list[tuple[str, str, int]] = []

    def extract(self, text: str, images, model: str) -> AIResult:
        self.calls.append((model, text, len(images)))
        fn = self.fallback if "terra" in model else self.primary
        extraction = fn(text)
        if extraction is None:
            return AIResult(extraction=None, model=model, error="simulated failure")
        return AIResult(extraction=extraction, model=model, usage=AIUsage(120, 40),
                        input_kind="text+image" if images else "text")


@pytest.fixture
def settings(tmp_path) -> Settings:
    s = Settings()
    s.dooray_token = ""
    s.supabase_url = ""
    s.supabase_service_key = ""
    s.openai_api_key = ""
    s.ai_model = "gpt-5.6-luna"
    s.ai_fallback_model = "gpt-5.6-terra"
    s.manual_path = tmp_path / "manual.json"
    s.kaist_public_enabled = False
    return s
