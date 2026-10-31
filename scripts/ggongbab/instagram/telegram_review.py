# -*- coding: utf-8 -*-
"""The owner in the loop, on Telegram (docs/INSTAGRAM_RADAR.md).

A question is the representative poster with a summary, both models' verdicts and the permalink,
and three buttons: ✅ 꽁밥 맞음 / ❌ 아님 / ✏️ 정보 수정. ✏️ asks for "필드: 값" lines in a reply.
The same bot asks about reader tips (ggongbab/tips.py: tip:ok / tip:no). Anything else the owner
writes or sends as a photo is kept for Claude to read (keep_note, owner 2026-10-31: "텔레그램에서 내가
친 내용을 너가 다시 볼 수 있게") and, while the ops agent is on, answered by it (ggongbab/ops_agent.py),
whose questions come back as agent:ok / agent:no. The 🔑 button under a login alert or code (login:go) and
a message that is only "로그인" ask for a new KAIST login (ggongbab/easy_login.py, owner 2026-10-31).
Only the allowed chat is ever read; anything else is ignored. Long polling (getUpdates), because
the operations PC has no public address. The bot is the existing Babdoduk ops bot unless
TELEGRAM_BOT_TOKEN / TELEGRAM_ALLOWED_CHAT_ID are set.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Callable, Optional

API = "https://api.telegram.org"
EDITABLE = ("event_title", "food_items", "start_at", "end_at", "location", "eligibility", "quantity_limit",
            "requirements", "registration")
FIELD_NAMES = {"제목": "event_title", "음식": "food_items", "시작": "start_at", "종료": "end_at", "장소": "location",
               "대상": "eligibility", "인원": "quantity_limit", "준비물": "requirements", "신청": "registration"}
TIP_ID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
ASK_ID = r"[0-9a-f]{12}"                # an ops agent question (ops_agent.Agent.act)
LOGIN_CALLBACK = "login:go"             # easy_login.REQUEST_CALLBACK: the owner asks for a login
INBOX = "telegram-inbox.jsonl"          # .local/: the owner's notes, newest last
INBOX_PHOTOS = "telegram-inbox"         # .local/telegram-inbox/<time>.<ext>
INBOX_KEEP, PHOTO_KEEP = 300, 50
PHOTO_MAX_BYTES = 10_000_000
# Masked before a note is kept: API keys, bot tokens, Meta tokens and any other long opaque string.
SECRETISH = re.compile(r"sk-[A-Za-z0-9_-]{16,}|sb_(?:secret|publishable)_[A-Za-z0-9_-]{8,}|EAA[A-Za-z0-9]{20,}"
                       r"|\d{8,10}:[A-Za-z0-9_-]{30,}|[A-Za-z0-9_\-]{40,}")


def credentials(local: Path) -> tuple[str, str]:
    """(token, chat id): the environment first, then the ops bot of this PC (ops_credentials)."""
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(), os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", "").strip()
    if token and chat:
        return token, chat
    from ..notify import TOKEN_TARGET
    from ..ops_credentials import read_credential
    from ..ops_storage import read_json
    config = read_json(Path(local) / "alert-push.json", {})
    return (read_credential(TOKEN_TARGET) or "", str(config.get("chat_id") or "")) if config.get("provider") == "telegram" else ("", "")


def summary(post, extraction: dict, verdicts: str, kst_time: str) -> str:
    foods = ", ".join(extraction.get("food_items") or []) or "-"
    rows = [f"🍱 꽁밥 판단 요청 · @{post['username']}", f"게시: {kst_time}", "",
            f"제목: {extraction.get('event_title') or '-'}", f"음식: {foods}",
            f"시작: {extraction.get('start_at') or '-'}", f"장소: {extraction.get('location') or '-'}",
            f"대상: {extraction.get('eligibility') or '-'}", f"인원: {extraction.get('quantity_limit') or '-'}",
            "", verdicts, post["permalink"]]
    return "\n".join(rows)[:1000]


def keep_note(local: Path, text: str, now: float, photo: Optional[bytes] = None) -> dict:
    """Keep one message of the owner's for Claude: a line of .local/telegram-inbox.jsonl (at most
    INBOX_KEEP, oldest dropped) and its photo under .local/telegram-inbox/ (at most PHOTO_KEEP).
    Token-like strings are masked first; the files are readable by this user only."""
    local = Path(local)
    entry = {"at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)), "text": SECRETISH.sub("[가림]", text or "")[:4000]}
    if photo:
        from ..parsers.attachment_text import image_mime
        ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}.get(image_mime(photo))
        if ext:
            folder = local / INBOX_PHOTOS
            folder.mkdir(mode=0o700, exist_ok=True)
            path = folder / f"{time.strftime('%Y%m%d-%H%M%S', time.localtime(now))}-{uuid.uuid4().hex[:6]}.{ext}"
            path.write_bytes(photo)
            os.chmod(path, 0o600)
            entry["photo"] = str(path)
            for old in sorted(folder.iterdir())[:-PHOTO_KEEP]:
                old.unlink()
    inbox = local / INBOX
    lines = inbox.read_text(encoding="utf-8").splitlines() if inbox.exists() else []
    lines = (lines + [json.dumps(entry, ensure_ascii=False)])[-INBOX_KEEP:]
    inbox.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(inbox, 0o600)
    return entry


def read_notes(local: Path, limit: int = 20) -> list[dict]:
    inbox = Path(local) / INBOX
    if not inbox.exists():
        return []
    out = []
    for line in inbox.read_text(encoding="utf-8").splitlines()[-limit:]:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def keyboard(media_id: str) -> dict:
    return {"inline_keyboard": [[{"text": "✅ 꽁밥 맞음", "callback_data": f"ig:ok:{media_id}"},
                                 {"text": "❌ 아님", "callback_data": f"ig:no:{media_id}"}],
                                [{"text": "✏️ 정보 수정", "callback_data": f"ig:edit:{media_id}"}]]}


def parse_edit(text: str) -> dict:
    """"필드: 값" lines -> {field: value}. Unknown fields are ignored; 음식 is a comma list."""
    out = {}
    for line in (text or "").splitlines():
        if ":" not in line:
            continue
        name, value = (part.strip() for part in line.split(":", 1))
        key = FIELD_NAMES.get(name, name if name in EDITABLE else None)
        if key:
            out[key] = [v.strip() for v in re.split(r"[,，]", value) if v.strip()] if key == "food_items" else (value or None)
    return out


class Bot:
    def __init__(self, token: str, chat_id: str, opener: Callable = urllib.request.urlopen, timeout: float = 35):
        self._token, self.chat_id, self._opener, self.timeout = token, str(chat_id), opener, timeout

    def _call(self, method: str, payload: dict, files: Optional[dict] = None) -> dict:
        url = f"{API}/bot{self._token}/{method}"
        if files:
            boundary = uuid.uuid4().hex
            body = b""
            for key, value in payload.items():
                body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n"
                         f"{value if isinstance(value, str) else json.dumps(value)}\r\n").encode()
            for key, (name, mime, data) in files.items():
                body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"; filename=\"{name}\"\r\n"
                         f"Content-Type: {mime}\r\n\r\n").encode() + data + b"\r\n"
            body += f"--{boundary}--\r\n".encode()
            request = urllib.request.Request(url, data=body, method="POST",
                                             headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        else:
            request = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                             headers={"Content-Type": "application/json"})
        try:
            with self._opener(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise RuntimeError("TELEGRAM_TRANSPORT_FAILED") from None   # never the URL: it holds the token
        if not data.get("ok"):
            raise RuntimeError("TELEGRAM_REJECTED")
        return data.get("result") or {}

    def say(self, text: str) -> None:
        self._call("sendMessage", {"chat_id": self.chat_id, "text": text[:4000], "disable_web_page_preview": True})

    def ask(self, text: str, media_id: str, image: Optional[tuple[str, bytes]] = None) -> int:
        return self._question(text, keyboard(media_id), image)

    def ask_tip(self, text: str, tip_id: str, image: Optional[tuple[str, bytes]] = None) -> int:
        markup = {"inline_keyboard": [[{"text": "✅ 게시판에 올리기", "callback_data": f"tip:ok:{tip_id}"},
                                       {"text": "❌ 올리지 않음", "callback_data": f"tip:no:{tip_id}"}]]}
        return self._question(text, markup, image)

    def ask_agent(self, text: str, ask_id: str) -> int:
        markup = {"inline_keyboard": [[{"text": "✅ 풀기", "callback_data": f"agent:ok:{ask_id}"},
                                       {"text": "❌ 그대로 두기", "callback_data": f"agent:no:{ask_id}"}]]}
        return self._question(text, markup, None)

    def _question(self, text: str, markup: dict, image: Optional[tuple[str, bytes]]) -> int:
        if image:
            mime, data = image
            result = self._call("sendPhoto", {"chat_id": self.chat_id, "caption": text[:1000], "reply_markup": markup},
                                files={"photo": ("poster.jpg", mime, data)})
        else:
            result = self._call("sendMessage", {"chat_id": self.chat_id, "text": text, "reply_markup": markup,
                                                "disable_web_page_preview": True})
        return int(result.get("message_id") or 0)

    def digest(self, items: list[tuple[str, str]]) -> None:
        """Several questions in one message: one line and one row of buttons per post."""
        lines, rows = ["🍱 꽁밥 판단 요청 묶음"], []
        for n, (media_id, line) in enumerate(items, start=1):
            lines.append(f"{n}. {line}")
            rows.append([{"text": f"{n} ✅", "callback_data": f"ig:ok:{media_id}"},
                         {"text": f"{n} ❌", "callback_data": f"ig:no:{media_id}"},
                         {"text": f"{n} ✏️", "callback_data": f"ig:edit:{media_id}"}])
        self._call("sendMessage", {"chat_id": self.chat_id, "text": "\n".join(lines)[:4000],
                                   "reply_markup": {"inline_keyboard": rows}, "disable_web_page_preview": True})

    def updates(self, offset: int, wait: int = 25) -> list[dict]:
        return self._call("getUpdates", {"offset": offset, "timeout": wait,
                                         "allowed_updates": ["callback_query", "message"]}) or []

    def download(self, file_id: str) -> bytes:
        """A photo the owner sent (getFile, then the file URL, which holds the token: never logged)."""
        path = str(self._call("getFile", {"file_id": file_id}).get("file_path") or "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}/[A-Za-z0-9_.-]{1,120}", path) or ".." in path:
            raise RuntimeError("TELEGRAM_REJECTED")
        try:
            with self._opener(urllib.request.Request(f"{API}/file/bot{self._token}/{path}"), timeout=self.timeout) as response:
                data = response.read(PHOTO_MAX_BYTES + 1)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise RuntimeError("TELEGRAM_TRANSPORT_FAILED") from None
        if len(data) > PHOTO_MAX_BYTES:
            raise RuntimeError("TELEGRAM_REJECTED")
        return data

    def answer(self, callback_id: str, text: str) -> None:
        try:
            self._call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})
        except RuntimeError:
            pass

    def events(self, updates: list[dict]) -> list[tuple]:
        """("button", action, media_id, callback_id), ("tip", action, tip_id, callback_id),
        ("agent", action, ask_id, callback_id), ("login", callback_id), ("text", text,
        reply_to_message_id) and ("photo", file_id, caption), from the allowed chat only."""
        out = []
        for update in updates:
            callback = update.get("callback_query")
            if callback:
                chat = ((callback.get("message") or {}).get("chat") or {}).get("id")
                data = str(callback.get("data") or "")
                match = re.fullmatch(r"ig:(ok|no|edit):([A-Za-z0-9_]{1,40})", data)
                tip = re.fullmatch(rf"tip:(ok|no):({TIP_ID})", data)
                agent = re.fullmatch(rf"agent:(ok|no):({ASK_ID})", data)
                if str(chat) == self.chat_id and match:
                    out.append(("button", match.group(1), match.group(2), callback.get("id")))
                elif str(chat) == self.chat_id and tip:
                    out.append(("tip", tip.group(1), tip.group(2), callback.get("id")))
                elif str(chat) == self.chat_id and agent:
                    out.append(("agent", agent.group(1), agent.group(2), callback.get("id")))
                elif str(chat) == self.chat_id and data == LOGIN_CALLBACK:
                    out.append(("login", callback.get("id")))
                continue
            message = update.get("message") or {}
            if str((message.get("chat") or {}).get("id")) != self.chat_id:
                continue
            if message.get("text"):
                reply = (message.get("reply_to_message") or {}).get("message_id")
                out.append(("text", message["text"], reply))
            elif message.get("photo"):
                out.append(("photo", str(message["photo"][-1].get("file_id") or ""), message.get("caption") or ""))
        return out
