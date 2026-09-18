# -*- coding: utf-8 -*-
"""OpenAI structured extraction (Responses API + Structured Outputs).

Primary model (Luna) parses every new item. The fallback model (Terra) is
called only when the validator finds the primary result ambiguous.

The input the model sees is already sanitized (see sanitizer.py) and trimmed
to the fields needed for event analysis. Raw mail is never sent.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Optional, Protocol

from ..config import PROMPT_VERSION
from ..models import EventExtraction

SYSTEM_PROMPT = """You extract KAIST campus event information for a "free food events" feed.
You are an EXTRACTION engine, not a reasoning engine. Follow these rules strictly:

1. Report ONLY what the text or the poster image literally states. Never infer or guess
   a date, time, venue, deadline, URL, organizer or food. If it is not written, use null
   or "unknown". Leaving a field null is always better than inventing a value.
2. food_provided = "true" ONLY when the source explicitly says food/drink is PROVIDED to
   attendees (e.g. "점심 제공", "도시락 제공", "간식 제공", "다과 제공", "식권 지급",
   "lunch provided", "refreshments provided", "피자 제공").
   A time of day is NOT food: "12시", "점심시간에 설명회", "lunch session", "런치 토크"
   alone mean food_provided = "unknown" unless provision is stated. When food_provided is
   "true", `evidence.food` MUST quote the exact sentence that states the provision.
3. food_type: lunchbox for 도시락, meal for 점심/식사/피자/샌드위치/케이터링, snack for 간식,
   refreshment for 다과, beverage for 커피/음료, coupon for 식권/쿠폰, other, or unknown.
4. Dates: convert to ISO 8601 with the +09:00 (Asia/Seoul) offset only when both the date
   and the clock time are explicit. If the year is missing, use the year that makes the
   event fall shortly after the mail date given in the input. `date_text` and `time_text`
   copy the original wording. `evidence.event_time` quotes the sentence with the date/time.
5. building: KAIST building codes such as N1, W1-3, E5, KI빌딩, 창의학습관 only if written.
6. registration_url: must appear verbatim in the input. Never construct or shorten URLs.
7. is_event = false for newsletters, surveys, job postings without a session, or general
   notices. A cafeteria menu is not an event.
8. confidence reflects how completely and unambiguously the essential fields (title,
   date/time, venue, food) are supported by the source. Use needs_review = true and
   explain in review_reason whenever the text and poster disagree, the date is ambiguous,
   or food provision is implied but not stated.
9. Write title/summary in the language of the source (usually Korean). Summary: one or two
   sentences, no marketing fluff, no personal names, no e-mail addresses, no phone numbers.
"""


@dataclass
class AIUsage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class AIResult:
    extraction: Optional[EventExtraction]
    model: str
    usage: AIUsage = field(default_factory=AIUsage)
    input_kind: str = "text"
    error: Optional[str] = None
    prompt_version: str = PROMPT_VERSION


class Extractor(Protocol):
    def extract(self, text: str, images: list[tuple[str, bytes]], model: str) -> AIResult: ...


def build_user_text(subject: str, body: str, sent_at: str, source_label: str, attachments_note: str = "") -> str:
    parts = [
        f"SOURCE: {source_label}",
        f"MAIL_DATE: {sent_at or 'unknown'}",
        f"SUBJECT: {subject or '(none)'}",
        "",
        "BODY:",
        body or "(empty)",
    ]
    if attachments_note:
        parts += ["", attachments_note]
    return "\n".join(parts)


class OpenAIExtractor:
    """Real extractor using the official SDK: client.responses.parse(...)."""

    def __init__(self, api_key: str, timeout: float = 90.0):
        from openai import OpenAI  # imported lazily so tests run without the package configured

        self.client = OpenAI(api_key=api_key, timeout=timeout, max_retries=2)

    def extract(self, text: str, images: list[tuple[str, bytes]], model: str) -> AIResult:
        content: list[dict] = [{"type": "input_text", "text": text}]
        for mime, data in images:
            b64 = base64.b64encode(data).decode("ascii")
            content.append({"type": "input_image", "image_url": f"data:{mime};base64,{b64}", "detail": "auto"})
        input_kind = "text+image" if images else "text"
        try:
            response = self.client.responses.parse(
                model=model,
                instructions=SYSTEM_PROMPT,
                input=[{"role": "user", "content": content}],
                text_format=EventExtraction,
                metadata={"prompt_version": PROMPT_VERSION, "app": "babdoduk-ggongbab"},
            )
        except Exception as exc:  # noqa: BLE001 - recorded in ai_parse_runs, retried next run
            return AIResult(extraction=None, model=model, input_kind=input_kind, error=f"{exc.__class__.__name__}: {str(exc)[:200]}")
        usage = AIUsage()
        raw_usage = getattr(response, "usage", None)
        if raw_usage is not None:
            usage.input_tokens = int(getattr(raw_usage, "input_tokens", 0) or 0)
            usage.output_tokens = int(getattr(raw_usage, "output_tokens", 0) or 0)
        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            refusal = _find_refusal(response)
            return AIResult(extraction=None, model=model, usage=usage, input_kind=input_kind,
                            error=refusal or "no parsed output")
        return AIResult(extraction=parsed, model=model, usage=usage, input_kind=input_kind)


def _find_refusal(response) -> Optional[str]:
    for item in getattr(response, "output", None) or []:
        for part in getattr(item, "content", None) or []:
            if getattr(part, "type", "") == "refusal":
                return f"refusal: {getattr(part, 'refusal', '')[:120]}"
    return None
