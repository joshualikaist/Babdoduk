# -*- coding: utf-8 -*-
"""OpenAI structured extraction (Responses API + Structured Outputs).

The primary model parses every new item. A fallback model is called only when
one is explicitly configured AND the validator finds the primary result
ambiguous; production leaves it unset, so an ambiguous source becomes
needs_review instead of a second, pricier guess.

The input the model sees is already sanitized (see sanitizer.py) and trimmed
to the fields needed for event analysis. Raw mail is never sent.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Optional, Protocol

from ..config import PROMPT_VERSION
from .ai_errors import classify_exception, classify_message
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
6a. registration_required = "true" only with explicit wording (사전 신청, 신청 필수, 등록 필요,
   선착순, RSVP, a registration link/form/deadline). "false" ONLY when the source explicitly
   says none is needed (신청 없이, 별도 신청 불필요, 현장 참여 가능, no registration needed,
   walk-ins welcome). If the source says nothing about registration, answer "unknown".
   Quote the deciding sentence in `evidence.registration`.
6b. eligibility: ONLY an actual restriction on who may attend, e.g. "KAIST 학부생 대상",
   "기계공학과 학생", "석·박사 과정 학생", "신입생만", "외국인 학생 대상", "선착순 50명".
   Words that merely refer to whoever shows up - "참석자에게", "참가자", "방문자", "attendees",
   "everyone" - are NOT eligibility; use null. If no restriction is stated, eligibility = null.
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
    # Safe-to-log category. The `error` string may quote the request, so only
    # this field is ever printed or aggregated.
    error_category: str = ""
    prompt_version: str = PROMPT_VERSION

    @property
    def category(self) -> str:
        if self.error_category:
            return self.error_category
        return classify_message(self.error) if self.error else ""


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
                # This is literal extraction into a fixed schema - dates, venue,
                # food wording, registration - and the deterministic validator
                # is what decides truth afterwards. Chain-of-thought buys nothing
                # here and is billed as output tokens.
                reasoning={"effort": "none"},
                metadata={"prompt_version": PROMPT_VERSION, "app": "babdoduk-ggongbab"},
            )
        except Exception as exc:  # noqa: BLE001 - recorded in ai_parse_runs, retried next run
            return AIResult(extraction=None, model=model, input_kind=input_kind,
                            error=f"{exc.__class__.__name__}: {str(exc)[:200]}",
                            error_category=classify_exception(exc))
        usage = AIUsage()
        raw_usage = getattr(response, "usage", None)
        if raw_usage is not None:
            usage.input_tokens = int(getattr(raw_usage, "input_tokens", 0) or 0)
            usage.output_tokens = int(getattr(raw_usage, "output_tokens", 0) or 0)
        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            refusal = _find_refusal(response)
            message = refusal or "no parsed output"
            return AIResult(extraction=None, model=model, usage=usage, input_kind=input_kind,
                            error=message, error_category=classify_message(message))
        return AIResult(extraction=parsed, model=model, usage=usage, input_kind=input_kind)


def _find_refusal(response) -> Optional[str]:
    for item in getattr(response, "output", None) or []:
        for part in getattr(item, "content", None) or []:
            if getattr(part, "type", "") == "refusal":
                return f"refusal: {getattr(part, 'refusal', '')[:120]}"
    return None
