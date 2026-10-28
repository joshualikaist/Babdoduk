# -*- coding: utf-8 -*-
"""Is an Instagram post a 꽁밥 (free food for students)? A free keyword prefilter, then the primary
model, then the review model when unsure, then the owner on Telegram (docs/INSTAGRAM_RADAR.md).

Decision (decide()):
  * primary confidence >= 0.8: its verdict stands;
  * otherwise the review model: >= 0.75 and the same verdict, or >= 0.75 on its own -> its verdict;
  * anything else (both unsure, or they disagree without a confident review) -> ask the owner.
A question is never shown on the site before the owner answers.
"""
from __future__ import annotations

import base64
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

KST = timezone(timedelta(hours=9))
PRIMARY_CONFIRM = 0.8
REVIEW_CONFIRM = 0.75
MAX_IMAGES = 6
MERGE_WINDOW = timedelta(hours=48)
KEYWORDS = ("간식", "피자", "치킨", "도시락", "커피", "음료", "무료", "선착순", "배부", "나눔", "증정", "샌드위치",
            "햄버거", "떡", "과자", "빵", "식사", "밥", "음식", "디저트", "아이스크림", "snack", "free", "food",
            "pizza", "coffee", "drink", "lunch", "dinner", "giveaway")
# USD per 1M tokens (input, output); a model missing here is costed with the review model's price.
PRICES = {"gpt-6-luna": (0.10, 0.50), "gpt-6.1-terra": (1.00, 5.00)}


class Judgement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_free_food_event: bool
    confidence: float = Field(ge=0, le=1)
    event_title: str
    food_items: list[str]
    start_at: Optional[str]
    end_at: Optional[str]
    location: str
    eligibility: str
    quantity_limit: Optional[str]
    requirements: Optional[str]
    registration: Optional[str]
    language: str
    evidence: list[str]
    reason: str


SYSTEM = """You judge whether an Instagram post by a KAIST student council or department account announces a
꽁밥: an event where students can get food or drinks for free (snacks, meals, coffee, a food giveaway, food at a
talk or study session). Not a 꽁밥: paid sales, a restaurant or cafe promotion, a general notice that only
mentions food, recruiting, open labs, results announcements.

Rules:
- Read the caption and every image (posters often carry the date, time, place and food).
- Dates without a year: take the nearest date on or after the post time (Asia/Seoul). Write times as
  YYYY-MM-DDTHH:MM+09:00. Unknown values are null or "" - never guess a value the post does not support.
- eligibility: who may come, as written (for example "과비 납부한 전자과 주/복/부전공 학부생").
- evidence: short quotes from the caption or poster that support the verdict.
- confidence: how sure you are of is_free_food_event, 0 to 1.
- language: ko, en or mixed (the caption's language)."""


def prefilter(caption: str, image_count: int, keywords=KEYWORDS) -> bool:
    """True when the post deserves a model call: a food keyword in the caption, or a poster that
    may carry the details (two or more images)."""
    text = (caption or "").lower()
    return image_count >= 2 or any(k.lower() in text for k in keywords)


def posted_kst(timestamp: str) -> datetime:
    """Graph timestamps look like 2026-10-05T08:30:00+0000."""
    return datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S%z").astimezone(KST)


def user_content(caption: str, timestamp: str, images: list[tuple[str, bytes]], examples: list[dict]) -> list[dict]:
    lines = []
    for ex in examples:
        verdict = {"confirm": "꽁밥 맞음", "reject": "꽁밥 아님", "edit": "꽁밥 맞음 (운영자가 정보를 고침)"}[ex["action"]]
        lines.append(f"[운영자 판정 예시: {verdict}] {(ex.get('caption') or '')[:300]}")
    header = ("\n".join(lines) + "\n\n" if lines else "") + f"Posted at (KST): {posted_kst(timestamp).isoformat(timespec='minutes')}\n"
    content = [{"type": "input_text", "text": header + "Caption:\n" + (caption or "(no caption)")[:4000]}]
    for mime, data in images[:MAX_IMAGES]:
        content.append({"type": "input_image", "image_url": f"data:{mime};base64,{base64.b64encode(data).decode()}"})
    return content


def cost(model: str, input_tokens: int, output_tokens: int) -> float:
    price_in, price_out = PRICES.get(model, PRICES["gpt-6.1-terra"])
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


class Judge:
    """The OpenAI call. `client` is an openai.OpenAI (or a fake with .responses.parse)."""

    def __init__(self, client, *, timeout_note: str = ""):
        self.client = client

    def __call__(self, model: str, content: list[dict]) -> tuple[Judgement, int, int]:
        response = self.client.responses.parse(
            model=model, input=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}],
            text_format=Judgement, max_output_tokens=4000)
        parsed = response.output_parsed
        if parsed is None:
            raise ValueError("no structured output")
        usage = getattr(response, "usage", None)
        return parsed, int(getattr(usage, "input_tokens", 0) or 0), int(getattr(usage, "output_tokens", 0) or 0)


def decide(primary: Judgement, review: Optional[Judgement]) -> tuple[str, str]:
    """("confirm" | "reject" | "ask", decided_by)."""
    if primary.confidence >= PRIMARY_CONFIRM:
        return ("confirm" if primary.is_free_food_event else "reject"), "primary"
    if review is None:
        return "review", ""
    if review.confidence >= REVIEW_CONFIRM:
        return ("confirm" if review.is_free_food_event else "reject"), "review"
    return "ask", ""


def _norm(value) -> str:
    if isinstance(value, list):
        return "|".join(sorted(_norm(v) for v in value))
    return re.sub(r"[\s·,./()\-]+", "", str(value or "")).lower()


def same_event(a: dict, b: dict) -> bool:
    """Same event (the caller already limits it to one account and 48 hours): the same start time,
    and, in one language, the same place and food. A Korean and an English post of one event name
    the place and the food in two languages, so across languages the start time decides, unless both
    give a different head count."""
    if not a.get("start_at") or a.get("start_at") != b.get("start_at"):
        return False
    if a.get("language") != b.get("language"):
        qa, qb = _digits(a.get("quantity_limit")), _digits(b.get("quantity_limit"))
        return not (qa and qb and qa != qb)
    return _norm(a.get("location")) == _norm(b.get("location")) and _norm(a.get("food_items")) == _norm(b.get("food_items"))


def _digits(value) -> str:
    return "".join(re.findall(r"\d+", str(value or "")))
