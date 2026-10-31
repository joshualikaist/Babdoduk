# -*- coding: utf-8 -*-
"""Reader tips reviewed on Telegram (scripts/ggongbab/tips.py). Fakes only: no Supabase, Telegram or Dooray."""
from __future__ import annotations

import io
import json
import re
from datetime import datetime, timezone

import pytest

from ggongbab import tips
from ggongbab.config import KST
from ggongbab.db.supabase_client import SupabaseError
from ggongbab.instagram.store import Store
from ggongbab.instagram.telegram_review import Bot as RealBot

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=KST).timestamp()
TIP_A = "0b6f4c3e-1d2a-4f5b-8c9d-0123456789ab"
TIP_B = "1c7f4c3e-1d2a-4f5b-8c9d-0123456789ab"


def jpeg() -> bytes:
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (30, 30), (200, 100, 0)).save(buffer, "JPEG")
    return buffer.getvalue()


def row(tip_id, **extra):
    base = {"id": tip_id, "created_at": tips.iso(NOW - 600), "title": "학과설명회 피자", "place": "창의학습관 1층",
            "event_date": "2026-11-03", "time_text": "18:00", "food": "피자, 경품 추첨", "details": "참석자 전원 피자",
            "link": "https://example.org/form", "status": "new", "dooray_post_id": None, "notified_at": None,
            "reviewed_at": None}
    base.update(extra)
    return base


class DB:
    """Enough PostgREST for the module: eq/is.null/lt/gte filters, update, upsert, and an `and` range."""

    def __init__(self, rows=(), missing=False):
        self.rows = {r["id"]: dict(r) for r in rows}
        self.board, self.missing, self.calls = {}, missing, []

    def _match(self, r, params):
        for key, cond in params.items():
            if key in ("select", "order", "limit"):
                continue
            if key == "and":
                lo, hi = re.findall(r"reviewed_at\.(?:gt|lte)\.([^,)]+)", cond)
                if not (r.get("reviewed_at") and lo < r["reviewed_at"] <= hi):
                    return False
                continue
            op, _, value = cond.partition(".")
            have = r.get(key)
            if op == "eq" and str(have) != value or op == "is" and have is not None:
                return False
            if op == "lt" and not str(have) < value or op == "gte" and not str(have) >= value:
                return False
        return True

    def select(self, table, params):
        self.calls.append(("select", table, params))
        if self.missing:
            raise SupabaseError("GET ggongbab_tips: HTTP 404 {\"code\":\"PGRST205\"}")
        assert table == "ggongbab_tips"
        return [dict(r) for r in self.rows.values() if self._match(r, params)]

    def update(self, table, match, values):
        self.calls.append(("update", table, match, values))
        self.rows[match["id"].split(".", 1)[1]].update(values)
        return []

    def upsert(self, table, rows, on_conflict):
        assert table == "ggongbab_tip_board" and on_conflict == "id"
        assert set(rows) == {"id", "title", "place", "event_date", "time_text", "food"}   # nothing private
        self.board[rows["id"]] = rows
        return []


class Storage:
    def __init__(self, files=None):
        self.files, self.deleted = dict(files or {}), []

    def names(self, tip_id):
        return sorted(n for n in self.files if n.startswith(tip_id + "/"))

    def get(self, name):
        return self.files[name]

    def delete(self, names):
        self.deleted += names
        for n in names:
            self.files.pop(n, None)


class Bot:
    chat_id = "42"

    def __init__(self):
        self.asked, self.answered = [], []

    def ask_tip(self, text, tip_id, image=None):
        self.asked.append((tip_id, text, image is not None))
        return 1

    def answer(self, callback, text):
        self.answered.append(text)


class Writer:
    def __init__(self, fail=False):
        self.tasks, self.fail = [], fail

    def create_task(self, mail):
        if self.fail:
            raise RuntimeError("dooray down")
        self.tasks.append(mail)
        return f"task-{len(self.tasks)}"


@pytest.fixture
def make(tmp_path):
    def build(rows=(), files=None, writer=None, missing=False, clock=None):
        clock = clock or {"t": NOW}
        logs = []
        db, storage, bot = DB(rows, missing), Storage(files), Bot()
        t = tips.Tips(db, storage, bot, writer if writer is not None else Writer(), store=Store(tmp_path),
                      now=lambda: clock["t"], log=logs.append)
        return t, db, storage, bot, logs, clock
    return build


def test_a_new_tip_is_asked_once_with_its_photo_after_it_settles(make):
    fresh = row(TIP_B, created_at=tips.iso(NOW - 30))           # photos may still be uploading
    t, db, storage, bot, _, clock = make([row(TIP_A), fresh], files={f"{TIP_A}/1.jpg": jpeg(), f"{TIP_A}/2.jpg": jpeg()})
    t.poll()
    (asked,) = bot.asked
    assert asked[0] == TIP_A and asked[2] is True
    assert "학과설명회 피자" in asked[1] and "경품" in asked[1] and "사진: 2장" in asked[1]
    assert db.rows[TIP_A]["notified_at"] and db.rows[TIP_B]["notified_at"] is None
    t.poll()                                                    # within five minutes: no call at all
    assert len(bot.asked) == 1
    clock["t"] += 301
    t.poll()
    assert [a[0] for a in bot.asked] == [TIP_A, TIP_B]          # never the same tip twice


def test_accepting_puts_public_fields_on_the_board_and_hands_the_tip_over(make):
    writer = Writer()
    t, db, storage, bot, _, _ = make([row(TIP_A, notified_at="x")], files={f"{TIP_A}/1.jpg": jpeg()}, writer=writer)
    t.decide("ok", TIP_A, "cb")
    assert db.rows[TIP_A]["status"] == "accepted" and db.rows[TIP_A]["reviewed_at"]
    assert db.board[TIP_A] == {"id": TIP_A, "title": "학과설명회 피자", "place": "창의학습관 1층", "event_date": "2026-11-03",
                               "time_text": "18:00", "food": "피자, 경품 추첨"}
    (task,) = writer.tasks
    assert task.subject == "[꽁밥 제보] 학과설명회 피자" and task.mail_id == f"tip-{TIP_A}"
    assert re.search(rf"^제보 ID: {TIP_A}$", task.body, re.M) and "https://example.org/form" in task.body
    assert len(task.images) == 1 and db.rows[TIP_A]["dooray_post_id"] == "task-1"
    t.decide("ok", TIP_A, "cb")                                 # a second tap changes nothing
    assert len(writer.tasks) == 1 and bot.answered[-1] == "이미 올렸습니다"


def test_rejecting_only_marks_the_tip(make):
    writer = Writer()
    t, db, _, bot, _, _ = make([row(TIP_A)], writer=writer)
    t.decide("no", TIP_A, "cb")
    assert db.rows[TIP_A]["status"] == "rejected" and db.board == {} and writer.tasks == []


def test_a_tip_without_a_title_still_carries_the_marker_subject(make):
    writer = Writer()
    t, _, _, _, _, _ = make([row(TIP_A, title="  ")], writer=writer)
    t.decide("ok", TIP_A, "cb")
    assert writer.tasks[0].subject == "[꽁밥 제보] 제목 없는 제보"     # the source check needs a title


def test_a_past_tip_goes_on_the_board_but_not_to_the_collection_project(make):
    writer = Writer()
    t, db, _, _, _, _ = make([row(TIP_A, event_date="2026-11-01")], writer=writer)
    t.decide("ok", TIP_A, "cb")
    assert TIP_A in db.board and writer.tasks == []


def test_a_failed_handover_is_retried_on_the_next_poll(make):
    writer = Writer(fail=True)
    t, db, _, _, logs, clock = make([row(TIP_A, notified_at="x")], writer=writer)
    t.decide("ok", TIP_A, "cb")
    assert db.rows[TIP_A]["status"] == "accepted" and db.rows[TIP_A]["dooray_post_id"] is None
    assert "TIP_DOORAY_FAILED" in logs
    writer.fail = False
    t.poll()
    assert len(writer.tasks) == 1 and db.rows[TIP_A]["dooray_post_id"] == "task-1"


def test_photos_are_deleted_fourteen_days_after_the_answer(make):
    reviewed = tips.iso(NOW - 15 * 86400)
    recent = tips.iso(NOW - 3 * 86400)
    files = {f"{TIP_A}/1.jpg": jpeg(), f"{TIP_B}/1.jpg": jpeg()}
    t, _, storage, _, _, clock = make([row(TIP_A, status="rejected", reviewed_at=reviewed, notified_at="x"),
                                       row(TIP_B, status="accepted", reviewed_at=recent, notified_at="x",
                                           dooray_post_id="task-9")], files=files)
    t.poll()
    assert storage.deleted == [f"{TIP_A}/1.jpg"] and f"{TIP_B}/1.jpg" in storage.files
    clock["t"] += 12 * 86400
    t.store.put("tips_polled", 0)
    t.poll()
    assert storage.deleted == [f"{TIP_A}/1.jpg", f"{TIP_B}/1.jpg"]


def test_before_the_migration_the_review_is_one_quiet_line_a_day(make):
    t, _, _, bot, logs, clock = make(missing=True)
    t.poll()
    clock["t"] += 600
    t.poll()
    assert logs == ["TIP_REVIEW_NOT_READY"] and bot.asked == []


def test_tip_buttons_are_read_only_from_the_owners_chat_and_only_with_a_uuid():
    bot = RealBot("x", "42")
    def cb(data, chat=42):
        return {"update_id": 1, "callback_query": {"id": "c", "data": data, "message": {"chat": {"id": chat}}}}
    events = bot.events([cb(f"tip:ok:{TIP_A}"), cb(f"tip:no:{TIP_A}", chat=7), cb("tip:ok:../../etc"),
                         cb(f"tip:delete:{TIP_A}")])
    assert events == [("tip", "ok", TIP_A, "c")]


def test_the_storage_client_lists_only_tip_photos_and_never_leaks_the_key():
    calls = []

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def opener(request, timeout=None, context=None):
        calls.append(request)
        return Response(json.dumps([{"name": "1.jpg"}, {"name": "../x.jpg"}, {"name": "4.gif"}]).encode())

    storage = tips.Storage("https://abc.supabase.co", "sb_secret_SYNTHETIC", opener=opener)
    assert storage.names(TIP_A) == [f"{TIP_A}/1.jpg"]
    (request,) = calls
    assert request.full_url == f"https://abc.supabase.co/storage/v1/object/list/{tips.BUCKET}"
    assert request.get_method() == "POST" and "sb_secret" not in request.full_url


def test_the_task_body_carries_the_marker_line_the_pipeline_trusts():
    body = tips.task_body(row(TIP_A), datetime(2026, 11, 2, 12, 0, tzinfo=KST))
    assert body.splitlines()[-1] == f"제보 ID: {TIP_A}"
    assert datetime.fromisoformat(row(TIP_A)["created_at"].replace("Z", "+00:00")).tzinfo == timezone.utc
