# -*- coding: utf-8 -*-
"""Held free-food events, told to the owner on Telegram (owner 2026-11-03: "지금 많은 부분을 서로서로
놓치고 있는거 같아").

The cloud pipeline holds an event for review (status review, needs_review) whenever the validator or a
merge finds a doubt, and nothing told anyone: on 2026-11-03 a burger giveaway for the next day and a
department info session sat off the site until the owner looked by chance. Each radar cycle reads the
upcoming held events that look like free food and asks once per event (again only after the pipeline
changed the row), with two buttons:

  ✅ 공개   status published, needs_review off, no reason; food marked provided and confidence raised to
            the public floor when the validator had lowered them (the owner has just confirmed both),
            then the cloud refresh is asked for at once
  ❌ 버림   status rejected

Both writes match on the row still being held, so a row the pipeline or an SQL edit already settled is
left alone. Reads and writes go through the backend key of this PC (.env), like the tip board.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Callable, Optional

from .config import KST

PER_POLL = 5                   # questions sent in one cycle; the rest come in the next ones
PUBLIC_FLOOR = 0.7             # config.Settings.min_confidence: the exporter's confidence floor
OWNER_CONFIDENCE = 0.9
NO_FOOD_EVIDENCE = "식사 제공 근거 없음"
FIELDS = ("id,title,event_start,event_end,building,room,location_name,food_provided,food_description,"
          "giveaway,giveaway_description,review_reason,confidence,updated_at,status,needs_review")
WEEKDAYS = "월화수목금토일"
SIMILAR_RATIO = 0.75


def looks_like_free_food(row: dict) -> bool:
    """Food or a giveaway already, or held only because the validator could not quote the food."""
    return (str(row.get("food_provided")) == "true" or str(row.get("giveaway")) == "true"
            or NO_FOOD_EVIDENCE in str(row.get("review_reason") or ""))


def when(value: Optional[str]) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(KST) if value else None
    except ValueError:
        return None


def kst(value: Optional[str]) -> str:
    moment = when(value)
    if moment is None:
        return str(value or "-")
    return f"{moment:%m/%d}({WEEKDAYS[moment.weekday()]}) {moment:%H:%M}"


def same_event(a: str, b: str) -> bool:
    """Titles of one event written twice ("기계공학과 학과설명회" / "2026 기계공학과 학과설명회")."""
    a, b = (re.sub(r"\b20\d\d\b|[\s\W_]+", "", t or "").lower() for t in (a, b))
    return bool(a and b) and (a in b or b in a or SequenceMatcher(None, a, b).ratio() >= SIMILAR_RATIO)


def message(row: dict, similar: tuple = ()) -> str:
    place = " ".join(str(row.get(k) or "") for k in ("building", "room")).strip() or str(row.get("location_name") or "-")
    food = row.get("food_description") or ("확인 필요" if str(row.get("food_provided")) != "true" else "제공")
    rows = ["⏸ 사이트에 안 보이는 꽁밥 (검토 대기)", "",
            f"제목: {row.get('title') or '-'}", f"일시: {kst(row.get('event_start'))}", f"장소: {place}",
            f"음식: {food}"]
    if str(row.get("giveaway")) == "true":
        rows.append(f"경품: {row.get('giveaway_description') or '있음'}")
    rows.append(f"사유: {str(row.get('review_reason') or '-')[:300]}")
    for other in similar:
        rows.append(f"⚠️ 이미 공개된 비슷한 행사: {other.get('title')} ({kst(other.get('event_start'))}). 같은 행사면 ❌")
    rows += ["", "✅ 공개하면 10~15분 뒤 사이트에 나옵니다."]
    return "\n".join(rows)[:1000]


class Held:
    """`db` is a SupabaseClient (select takes PostgREST filters, update a plain match)."""

    def __init__(self, db, bot, *, store, now: Callable, log: Callable, on_publish: Callable[[], None]):
        self.db, self.bot, self.store, self.now, self.log, self.on_publish = db, bot, store, now, log, on_publish

    def held(self) -> list[dict]:
        since = datetime.fromtimestamp(self.now() - 6 * 3600, timezone.utc).isoformat()
        rows = self.db.select("events", {"select": FIELDS, "status": "eq.review", "needs_review": "eq.true",
                                         "event_start": f"gte.{since}", "order": "event_start.asc", "limit": 200})
        return [row for row in rows if looks_like_free_food(row)]

    def similar(self, row: dict) -> tuple:
        """Published events of the same KST day with nearly the same title: a ✅ would list it twice."""
        moment = when(row.get("event_start"))
        if moment is None:
            return ()
        day = moment.replace(hour=0, minute=0, second=0, microsecond=0)
        rows = self.db.select("events", {"select": "id,title,event_start", "status": "eq.published",
                                         "and": f"(event_start.gte.{day.isoformat()},event_start.lt.{(day + timedelta(days=1)).isoformat()})"})
        return tuple(r for r in rows if r.get("id") != row.get("id") and same_event(r.get("title"), row.get("title")))

    def poll(self) -> int:
        """Ask about held events not asked about yet (or changed since). Returns the number asked."""
        asked = 0
        for row in self.held():
            key = f"held:{row['id']}"
            if self.store.get(key) == row.get("updated_at"):
                continue
            if asked >= PER_POLL:
                break
            self.bot.ask_held(message(row, self.similar(row)), row["id"])
            self.store.put(key, row.get("updated_at"))
            asked += 1
        if asked:
            self.log("HELD_EVENTS_ASKED")
        return asked

    def decide(self, action: str, event_id: str, callback: str) -> None:
        rows = self.db.select("events", {"select": FIELDS, "id": f"eq.{event_id}"})
        row = rows[0] if rows else None
        if row is None or row.get("status") != "review" or not row.get("needs_review"):
            self.bot.answer(callback, "이미 처리된 행사입니다")
            return
        match = {"id": event_id, "status": "review", "needs_review": "true"}
        if action == "no":
            done = self.db.update("events", match, {"status": "rejected", "needs_review": False})
            self.bot.answer(callback, "❌ 버렸습니다" if done else "이미 처리된 행사입니다")
            if done:
                self.log("HELD_EVENT_REJECTED")
            return
        values = {"status": "published", "needs_review": False, "review_reason": None}
        if float(row.get("confidence") or 0) < PUBLIC_FLOOR:
            values["confidence"] = OWNER_CONFIDENCE
        if str(row.get("food_provided")) != "true" and str(row.get("giveaway")) != "true":
            values["food_provided"] = "true"
        done = self.db.update("events", match, values)
        if not done:
            self.bot.answer(callback, "이미 처리된 행사입니다")
            return
        self.log("HELD_EVENT_PUBLISHED")
        self.bot.answer(callback, "✅ 공개합니다. 10~15분 뒤 사이트에 나옵니다")
        self.on_publish()


def build(settings, bot, *, store, now: Callable, log: Callable, on_publish: Callable[[], None]) -> Optional[Held]:
    if bot is None or not settings.has_supabase:
        return None
    from .db.supabase_client import SupabaseClient
    return Held(SupabaseClient(settings.supabase_url, settings.supabase_secret_key), bot, store=store, now=now,
                log=log, on_publish=on_publish)
