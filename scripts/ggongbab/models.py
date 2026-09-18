# -*- coding: utf-8 -*-
"""Data models shared by collectors, parsers, validator, dedup and exporter."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

SourceType = Literal["dooray", "kaist_public", "manual", "portal"]
Tri = Literal["true", "false", "unknown"]
FoodType = Literal["meal", "lunchbox", "snack", "refreshment", "beverage", "coupon", "other", "unknown"]


# ---------------------------------------------------------------------------
# Collector output
# ---------------------------------------------------------------------------
@dataclass
class RawAttachment:
    external_file_id: str
    filename: str = ""
    mime_type: str = ""
    size: int = 0
    inline: bool = False
    data: Optional[bytes] = None  # populated only when download succeeded
    sha256: str = ""
    parse_status: str = "pending"

    def compute_sha(self) -> str:
        if self.data is not None and not self.sha256:
            self.sha256 = hashlib.sha256(self.data).hexdigest()
        return self.sha256


@dataclass
class RawItem:
    """Normalized unit of collected content. Same shape for every source."""

    source_type: SourceType
    external_id: str
    subject: str = ""
    sender_name: str = ""
    sender_email: str = ""
    raw_text: str = ""
    raw_html: str = ""
    source_url: str = ""
    source_created_at: Optional[datetime] = None
    source_updated_at: Optional[datetime] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    attachments: list[RawAttachment] = field(default_factory=list)

    @property
    def content_hash(self) -> str:
        basis = "\n".join([
            self.source_type,
            self.external_id,
            self.subject or "",
            re.sub(r"\s+", " ", self.raw_text or "").strip(),
            ",".join(sorted(a.external_file_id for a in self.attachments)),
        ])
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# AI structured output (OpenAI Structured Outputs - strict schema)
# All fields are required; None is expressed explicitly.
# ---------------------------------------------------------------------------
class Evidence(BaseModel):
    event_time: Optional[str] = Field(description="Verbatim quote from the text/poster that states the date/time, or null.")
    location: Optional[str] = Field(description="Verbatim quote that states the venue, or null.")
    food: Optional[str] = Field(description="Verbatim quote that explicitly says food/drink is PROVIDED, or null.")
    registration: Optional[str] = Field(description="Verbatim quote about registration/deadline/link, or null.")


class EventExtraction(BaseModel):
    is_event: bool
    title: Optional[str]
    summary: Optional[str]
    event_start: Optional[str] = Field(description="ISO 8601 with +09:00 offset when date and time are both explicit; else null.")
    event_end: Optional[str]
    date_text: Optional[str] = Field(description="Date as written in the source, e.g. '9월 25일(목)'.")
    time_text: Optional[str] = Field(description="Time as written in the source, e.g. '12:00~13:00'.")
    location_name: Optional[str]
    building: Optional[str] = Field(description="KAIST building code like N1, W1-3, E5, KI빌딩. Null if not stated.")
    room: Optional[str]
    food_provided: Tri
    food_type: FoodType
    food_description: Optional[str]
    organizer: Optional[str]
    eligibility: Optional[str]
    registration_required: Tri
    registration_deadline: Optional[str] = Field(description="ISO 8601 with +09:00 if explicit, else null.")
    registration_url: Optional[str]
    confidence: float = Field(description="0.0-1.0 overall confidence that the extraction is faithful to the source.")
    evidence: Evidence
    needs_review: bool
    review_reason: Optional[str]


# ---------------------------------------------------------------------------
# Rule parser output
# ---------------------------------------------------------------------------
@dataclass
class RuleFacts:
    dates: list[str] = field(default_factory=list)          # ISO dates YYYY-MM-DD found in text
    times: list[str] = field(default_factory=list)          # HH:MM found in text
    buildings: list[str] = field(default_factory=list)      # N1, W1-3, ...
    food_evidence: list[str] = field(default_factory=list)  # explicit "provided" phrases
    food_type_hint: FoodType = "unknown"
    lunch_time_only: bool = False                           # lunch-time words without provision words
    urls: list[str] = field(default_factory=list)
    deadline_dates: list[str] = field(default_factory=list)
    looks_like_event: bool = False

    @property
    def explicit_food(self) -> bool:
        return bool(self.food_evidence)


# ---------------------------------------------------------------------------
# Validated event candidate (goes into dedup and the DB)
# ---------------------------------------------------------------------------
@dataclass
class EventCandidate:
    title: str
    summary: Optional[str] = None
    event_start: Optional[datetime] = None
    event_end: Optional[datetime] = None
    registration_deadline: Optional[datetime] = None
    date_text: Optional[str] = None
    time_text: Optional[str] = None
    location_name: Optional[str] = None
    building: Optional[str] = None
    room: Optional[str] = None
    food_provided: Tri = "unknown"
    food_type: FoodType = "unknown"
    food_description: Optional[str] = None
    organizer: Optional[str] = None
    eligibility: Optional[str] = None
    registration_required: Tri = "unknown"
    registration_url: Optional[str] = None
    confidence: float = 0.0
    needs_review: bool = False
    review_reasons: list[str] = field(default_factory=list)
    is_event: bool = True
    source_type: SourceType = "manual"
    source_priority: int = 100

    @property
    def review_reason(self) -> Optional[str]:
        return "; ".join(self.review_reasons) if self.review_reasons else None

    def to_db_row(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "summary": self.summary,
            "event_start": self.event_start.isoformat() if self.event_start else None,
            "event_end": self.event_end.isoformat() if self.event_end else None,
            "registration_deadline": self.registration_deadline.isoformat() if self.registration_deadline else None,
            "date_text": self.date_text,
            "time_text": self.time_text,
            "location_name": self.location_name,
            "building": self.building,
            "room": self.room,
            "food_provided": self.food_provided,
            "food_type": self.food_type,
            "food_description": self.food_description,
            "organizer": self.organizer,
            "eligibility": self.eligibility,
            "registration_required": self.registration_required,
            "registration_url": self.registration_url,
            "confidence": round(float(self.confidence), 3),
            "needs_review": bool(self.needs_review),
            "review_reason": self.review_reason,
            "status": "review" if self.needs_review else "published",
        }


@dataclass
class ParseOutcome:
    """Result of running the AI (+fallback) and validator on one raw item."""

    candidate: Optional[EventCandidate]
    ai_calls: int = 0
    fallback_used: bool = False
    skipped_cached: bool = False
    error: Optional[str] = None
