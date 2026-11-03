# -*- coding: utf-8 -*-
"""Held free-food events told to the owner (ggongbab/held.py, 2026-11-03). Fakes only: no Supabase or Telegram."""
from __future__ import annotations

from datetime import datetime

from ggongbab import held
from ggongbab.config import KST

NOW = datetime(2026, 11, 3, 16, 0, tzinfo=KST).timestamp()
BURGER = "8f65a362-a09c-4577-bc5c-d39338c5b7c1"
TALK = "20c80e0a-0000-4000-8000-000000000001"
TIP = "5e65e3b8-0000-4000-8000-000000000002"


def event(event_id, **extra):
    base = {"id": event_id, "title": "2026 망한과제 자랑대회", "event_start": "2026-11-04T09:00:00+00:00",
            "event_end": None, "building": "E9", "room": "5층 존해너홀", "location_name": None,
            "food_provided": "true", "food_description": "싸이버거+콜라 선착순 100명", "giveaway": "unknown",
            "review_reason": "병합 충돌 registration_deadline", "confidence": 0.99,
            "updated_at": "2026-11-02T18:45:14+00:00", "status": "review", "needs_review": True}
    return base | extra


class DB:
    def __init__(self, rows):
        self.rows, self.selects, self.updates = {r["id"]: dict(r) for r in rows}, [], []

    def select(self, table, params):
        assert table == "events"
        self.selects.append(params)
        if "id" in params:
            row = self.rows.get(params["id"].removeprefix("eq."))
            return [dict(row)] if row else []
        if params["status"] == "eq.published":
            day = params["and"].split("event_start.gte.")[1][:10]
            return [dict(r) for r in self.rows.values() if r["status"] == "published"
                    and r["event_start"][:10] == day]        # the fakes' events start in the KST morning
        assert params["status"] == "eq.review" and params["needs_review"] == "eq.true"
        return [dict(r) for r in self.rows.values() if r["status"] == "review" and r["needs_review"]]

    def update(self, table, match, values):
        self.updates.append((match, values))
        row = self.rows.get(match["id"])
        if row is None or row["status"] != match["status"] or str(row["needs_review"]).lower() != match["needs_review"]:
            return []
        row.update(values)
        return [dict(row)]


class Store(dict):
    def put(self, key, value):
        self[key] = value


class Bot:
    def __init__(self):
        self.asked, self.answered = [], []

    def ask_held(self, text, event_id, duplicate=False):
        self.asked.append((event_id, text))
        self.duplicates = getattr(self, "duplicates", []) + [duplicate]
        return 1

    def answer(self, callback, text):
        self.answered.append(text)


def make(rows):
    db, bot, published, logs = DB(rows), Bot(), [], []
    h = held.Held(db, bot, store=Store(), now=lambda: NOW, log=logs.append, on_publish=lambda: published.append(1))
    return h, db, bot, published, logs


def test_only_held_events_that_look_like_free_food_are_asked_once_each():
    h, db, bot, _, logs = make([
        event(BURGER),
        event(TALK, title="적외선 영상센서 세미나", food_provided="unknown", review_reason="병합 충돌 building"),
        event(TIP, title="NVIDIA Robotics Day", food_provided="unknown", confidence=0.6,
              review_reason="식사 제공 근거 없음 (시간 표현만 있을 수 있음)")])
    assert h.poll() == 2
    assert [a[0] for a in bot.asked] == [BURGER, TIP] and logs == ["HELD_EVENTS_ASKED"]
    text = bot.asked[0][1]
    assert "망한과제" in text and "11/04(수) 18:00" in text and "E9 5층 존해너홀" in text and "싸이버거" in text
    assert "⚠️" not in text
    assert h.poll() == 0                                    # asked already
    db.rows[BURGER]["updated_at"] = "2026-11-03T07:00:00+00:00"
    assert h.poll() == 1                                    # the pipeline changed it: asked again


def test_a_poll_asks_at_most_a_few_and_the_rest_come_next_time():
    rows = [event(f"{n:08x}-0000-4000-8000-000000000000") for n in range(held.PER_POLL + 2)]
    h, _, bot, _, _ = make(rows)
    assert h.poll() == held.PER_POLL and h.poll() == 2 and len(bot.asked) == held.PER_POLL + 2


def test_ok_publishes_with_the_public_floor_and_asks_for_a_refresh():
    h, db, bot, published, logs = make([event(TIP, food_provided="unknown", confidence=0.6,
                                              review_reason="식사 제공 근거 없음")])
    h.decide("ok", TIP, "cb")
    match, values = db.updates[0]
    assert match == {"id": TIP, "status": "review", "needs_review": "true"}
    assert values == {"status": "published", "needs_review": False, "review_reason": None,
                      "confidence": held.OWNER_CONFIDENCE, "food_provided": "true"}
    assert published == [1] and logs == ["HELD_EVENT_PUBLISHED"] and bot.answered[0].startswith("✅")


def test_ok_keeps_a_high_confidence_and_the_food_as_they_are():
    h, db, _, _, _ = make([event(BURGER)])
    h.decide("ok", BURGER, "cb")
    assert db.updates[0][1] == {"status": "published", "needs_review": False, "review_reason": None}


def test_no_rejects_and_a_settled_event_is_left_alone():
    h, db, bot, published, _ = make([event(BURGER), event(TIP, status="published", needs_review=False)])
    h.decide("no", BURGER, "cb")
    assert db.rows[BURGER]["status"] == "rejected" and db.rows[BURGER]["needs_review"] is False
    h.decide("ok", TIP, "cb2")
    h.decide("ok", "ffffffff-0000-4000-8000-000000000000", "cb3")
    assert len(db.updates) == 1 and published == [] and bot.answered[1:] == ["이미 처리된 행사입니다"] * 2


def test_without_the_backend_key_or_the_bot_nothing_is_built():
    class Settings:
        has_supabase, supabase_url, supabase_secret_key = False, "", ""
    assert held.build(Settings(), Bot(), store=Store(), now=lambda: NOW, log=print, on_publish=print) is None


def test_every_log_code_is_a_registered_reason():
    import re
    from pathlib import Path
    from ggongbab.ops_policy import REASONS
    source = (Path(__file__).resolve().parents[2] / "scripts/ggongbab/held.py").read_text(encoding="utf-8")
    codes = set(re.findall(r'"(HELD_[A-Z_]+)"', source))
    assert codes and codes <= REASONS


def test_a_held_copy_of_a_published_event_carries_a_duplicate_warning():
    copy = event(TALK, title="기계공학과 학과설명회", event_start="2026-11-09T07:10:00+00:00")
    live = event(TIP, title="2026 기계공학과 학과설명회", event_start="2026-11-09T07:10:00+00:00",
                 status="published", needs_review=False)
    other = event(BURGER, title="2026 전산학부 학과설명회", event_start="2026-11-09T08:00:00+00:00",
                  status="published", needs_review=False)
    h, _, bot, _, _ = make([copy, live, other])
    h.poll()
    [(_, text)] = bot.asked
    assert "⚠️ 이미 공개된 비슷한 행사: 2026 기계공학과 학과설명회 (11/09(월) 16:10)" in text and "전산학부" not in text
    assert bot.duplicates == [True]


def test_a_duplicate_question_puts_reject_first():
    from ggongbab.instagram.telegram_review import Bot as Real
    sent = []
    real = Real("x", "42")
    real._question = lambda text, markup, image: sent.append(markup) or 1
    real.ask_held("t", BURGER, duplicate=True)
    real.ask_held("t", BURGER)
    assert [b["text"] for b in sent[0]["inline_keyboard"][0]] == ["❌ 중복이라 버림", "✅ 그래도 공개"]
    assert [b["text"] for b in sent[1]["inline_keyboard"][0]] == ["✅ 공개", "❌ 버림"]


def test_titles_written_twice_are_the_same_event_but_two_departments_are_not():
    assert held.same_event("기계공학과 학과설명회", "2026 기계공학과 학과설명회")
    assert not held.same_event("2026 전산학부 학과설명회", "2026 기계공학과 학과설명회")
    assert not held.same_event("", "2026 기계공학과 학과설명회")
