# -*- coding: utf-8 -*-
"""Reader tips, reviewed by the owner on Telegram (docs/GGONGBAB_TIPS.md).

The tip page stores a tip through `ggongbab_submit_tip` (supabase/migrations/008_ggongbab_tips.sql)
and up to three photos in the private `ggongbab-tip-images` bucket (`<tip id>/<n>.<ext>`). Here, on
the operations PC, with the backend key and the Instagram radar's bot (one getUpdates reader per bot):

  * each new tip goes to the owner once, two minutes after it arrives (its photos have landed by
    then): the first photo, the fields and ✅ 게시판에 올리기 / ❌ 올리지 않음;
  * ✅ puts it on the public board (`ggongbab_tip_board`: title, place, date, time and food only, never
    the details, the link or a photo) and, while its date is still ahead, hands it to the collection
    project as a Dooray task (`[꽁밥 제보] <title>` with a `제보 ID: <uuid>` line), the way an
    Instagram post is handed over; the pipeline's own rules decide what reaches the 꽁밥 list;
  * ❌ only marks it rejected;
  * a tip's photos are deleted 14 days after the owner's answer.

Before the migration is applied the tables do not exist: one quiet TIP_REVIEW_NOT_READY a day.
"""
from __future__ import annotations

import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Callable, Optional

from .config import KST
from .db.supabase_client import SupabaseError

TIP = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
BUCKET = "ggongbab-tip-images"
FIELDS = "id,created_at,title,place,event_date,time_text,food,details,link,status,dooray_post_id"
POLL_SECONDS = 300
SETTLE_SECONDS = 120            # photos are uploaded right after the tip itself
IMAGE_KEEP_SECONDS = 14 * 86400
MAX_PHOTOS = 3
NOT_READY = ("HTTP 404", "PGRST205", "42P01")


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Storage:
    """The private bucket, through the Storage REST API with the backend key (list, get, delete)."""

    def __init__(self, url: str, key: str, opener: Callable = urllib.request.urlopen, timeout: int = 30):
        self.base, self._key, self._opener, self.timeout = url.rstrip("/") + "/storage/v1", key, opener, timeout
        self._ctx = ssl.create_default_context()

    def _request(self, method: str, path: str, body=None) -> bytes:
        headers = {"apikey": self._key, "Authorization": f"Bearer {self._key}"}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        request = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with self._opener(request, timeout=self.timeout, context=self._ctx) as response:
                return response.read(10_000_001)
        except urllib.error.HTTPError as exc:
            raise SupabaseError(f"storage {method}: HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise SupabaseError(f"storage {method}: transport") from None

    def names(self, tip_id: str) -> list[str]:
        rows = json.loads(self._request("POST", f"/object/list/{BUCKET}", {"prefix": tip_id, "limit": 10}) or b"[]")
        return sorted(f"{tip_id}/{r['name']}" for r in rows if isinstance(r, dict)
                      and re.fullmatch(r"[1-3]\.(?:jpg|png|webp)", str(r.get("name") or "")))

    def get(self, name: str) -> bytes:
        return self._request("GET", f"/object/{BUCKET}/{urllib.parse.quote(name)}")

    def delete(self, names: list[str]) -> None:
        if names:
            self._request("DELETE", f"/object/{BUCKET}", {"prefixes": names})


def summary(row: dict, photos: int) -> str:
    created = row.get("created_at") or ""
    try:
        created = datetime.fromisoformat(created.replace("Z", "+00:00")).astimezone(KST).strftime("%m-%d %H:%M")
    except ValueError:
        pass
    lines = ["📮 꽁밥 제보", f"제목: {row.get('title') or '-'}", f"장소: {row.get('place') or '-'}",
             f"날짜: {row.get('event_date') or '-'} {row.get('time_text') or ''}".rstrip(),
             f"음식·경품: {row.get('food') or '-'}"]
    if row.get("details"):
        lines.append(f"내용: {row['details'][:400]}")
    if row.get("link"):
        lines.append(f"링크: {row['link']}")
    lines += [f"사진: {photos}장 · 받은 시각 {created}", "", "✅를 누르면 게시판에 올리고 수집함에 넘깁니다."]
    return "\n".join(lines)[:1000]


def task_body(row: dict, reviewed: datetime) -> str:
    lines = [row.get("title") or "", f"장소: {row.get('place') or '-'}",
             f"날짜: {row.get('event_date') or '-'} {row.get('time_text') or ''}".rstrip(),
             f"음식·경품: {row.get('food') or '-'}"]
    if row.get("details"):
        lines.append(f"내용: {row['details']}")
    if row.get("link"):
        lines.append(f"링크: {row['link']}")
    lines += ["", f"[독자 제보 · 운영자 확인 {reviewed.strftime('%Y-%m-%d %H:%M')} (KST)]", f"제보 ID: {row['id']}"]
    return "\n".join(lines)


class Tips:
    def __init__(self, db, storage, bot, writer, *, store, now: Callable, log: Callable):
        self.db, self.storage, self.bot, self.writer = db, storage, bot, writer
        self.store, self.now, self.log = store, now, log

    def today(self) -> str:
        return datetime.fromtimestamp(self.now(), KST).strftime("%Y-%m-%d")

    def failed(self, exc: Exception) -> None:
        if any(mark in str(exc) for mark in NOT_READY):
            if self.now() - float(self.store.get("tips_not_ready", 0)) >= 86400:
                self.store.put("tips_not_ready", self.now())
                self.log("TIP_REVIEW_NOT_READY")
        else:
            self.log("TIP_REVIEW_FAILED")

    def photos(self, tip_id: str, limit: int = MAX_PHOTOS) -> list[tuple[str, bytes]]:
        """Shrunk and re-encoded like an Instagram poster; a photo that cannot be read is skipped."""
        from .parsers.attachment_text import image_mime, normalize_image
        out = []
        for name in self.storage.names(tip_id)[:limit]:
            try:
                data = self.storage.get(name)
            except SupabaseError:
                continue
            mime = image_mime(data)
            if mime in ("image/jpeg", "image/png", "image/webp"):
                out.append(normalize_image(mime, data))
        return out

    # --- the resident loop ----------------------------------------------------------------------
    def poll(self) -> None:
        if self.now() - float(self.store.get("tips_polled", 0)) < POLL_SECONDS:
            return
        self.store.put("tips_polled", self.now())
        try:
            rows = self.db.select("ggongbab_tips", {"select": FIELDS, "status": "eq.new", "notified_at": "is.null",
                                                    "created_at": f"lt.{iso(self.now() - SETTLE_SECONDS)}",
                                                    "order": "created_at.asc", "limit": 10})
            for row in rows:
                if not TIP.fullmatch(str(row.get("id") or "")):
                    continue
                photos = self.photos(row["id"], 1)
                self.bot.ask_tip(summary(row, len(self.storage.names(row["id"]))), row["id"], photos[0] if photos else None)
                self.db.update("ggongbab_tips", {"id": f"eq.{row['id']}"}, {"notified_at": iso(self.now())})
            self.hand_over()
            self.purge()
        except SupabaseError as exc:
            self.failed(exc)

    def decide(self, action: str, tip_id: str, callback: str) -> None:
        try:
            rows = self.db.select("ggongbab_tips", {"select": FIELDS, "id": f"eq.{tip_id}"})
            if not rows:
                self.bot.answer(callback, "알 수 없는 제보입니다")
                return
            row = rows[0]
            if row["status"] != "new":
                self.bot.answer(callback, "이미 올렸습니다" if row["status"] == "accepted" else "이미 올리지 않기로 했습니다")
                return
            if action == "no":
                self.db.update("ggongbab_tips", {"id": f"eq.{tip_id}"}, {"status": "rejected", "reviewed_at": iso(self.now())})
                self.bot.answer(callback, "❌ 올리지 않습니다")
                return
            # The board first: a second ✅ after a failure finds the tip still new and writes it again.
            self.db.upsert("ggongbab_tip_board", {k: row.get(k) or "" for k in ("id", "title", "place", "time_text", "food")}
                           | {"event_date": row["event_date"]}, on_conflict="id")
            self.db.update("ggongbab_tips", {"id": f"eq.{tip_id}"}, {"status": "accepted", "reviewed_at": iso(self.now())})
            self.bot.answer(callback, "✅ 게시판에 올렸습니다")
            self.hand_over()
        except SupabaseError as exc:
            self.failed(exc)
            self.bot.answer(callback, "지금은 처리하지 못했습니다. 잠시 뒤 다시 눌러 주세요")

    def hand_over(self) -> None:
        """Accepted tips whose date is still ahead, once each, as collection tasks."""
        if self.writer is None:
            return
        from .web.task_writer import MailPayload
        rows = self.db.select("ggongbab_tips", {"select": FIELDS, "status": "eq.accepted", "dooray_post_id": "is.null",
                                                "event_date": f"gte.{self.today()}", "order": "created_at.asc", "limit": 10})
        for row in rows:
            if not TIP.fullmatch(str(row.get("id") or "")):
                continue
            created = datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00")).astimezone(KST)
            reviewed = datetime.fromtimestamp(self.now(), KST)
            try:
                post_id = self.writer.create_task(MailPayload(
                    mail_id=f"tip-{row['id']}", subject=f"[꽁밥 제보] {(row.get('title') or '').strip() or '제목 없는 제보'}"[:200],
                    body=task_body(row, reviewed), received_at=created, discovered_at=reviewed,
                    images=self.photos(row["id"])))
            except Exception:  # noqa: BLE001 - retried on the next poll
                self.log("TIP_DOORAY_FAILED")
                continue
            self.db.update("ggongbab_tips", {"id": f"eq.{row['id']}"}, {"dooray_post_id": str(post_id)})

    def purge(self) -> None:
        """Photos of tips answered more than 14 days ago; once a day, from where the last pass ended."""
        last = float(self.store.get("tips_purged_until", 0))
        until = self.now() - IMAGE_KEEP_SECONDS
        if until - last < 86400:
            return
        rows = self.db.select("ggongbab_tips", {"select": "id", "and": f"(reviewed_at.gt.{iso(last)},reviewed_at.lte.{iso(until)})",
                                                "limit": 1000})
        for row in rows:
            if TIP.fullmatch(str(row.get("id") or "")):
                self.storage.delete(self.storage.names(row["id"]))
        self.store.put("tips_purged_until", until)


def build(settings, bot, writer, *, store, now: Callable, log: Callable) -> Optional[Tips]:
    """None without the backend key or the bot: tips then simply wait in the table."""
    if bot is None or not settings.has_supabase:
        return None
    from .db.supabase_client import SupabaseClient
    return Tips(SupabaseClient(settings.supabase_url, settings.supabase_secret_key),
                Storage(settings.supabase_url, settings.supabase_secret_key), bot, writer, store=store, now=now, log=log)

