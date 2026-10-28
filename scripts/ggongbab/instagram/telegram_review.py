# -*- coding: utf-8 -*-
"""The owner in the loop, on Telegram (docs/INSTAGRAM_RADAR.md).

A question is the representative poster with a summary, both models' verdicts and the permalink,
and three buttons: ✅ 꽁밥 맞음 / ❌ 아님 / ✏️ 정보 수정. ✏️ asks for "필드: 값" lines in a reply.
Only the allowed chat is ever read; anything else is ignored. Long polling (getUpdates), because
the operations PC has no public address. The bot is the existing Babdoduk ops bot unless
TELEGRAM_BOT_TOKEN / TELEGRAM_ALLOWED_CHAT_ID are set.
"""
from __future__ import annotations

import json
import os
import re
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
        markup = keyboard(media_id)
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

    def answer(self, callback_id: str, text: str) -> None:
        try:
            self._call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})
        except RuntimeError:
            pass

    def events(self, updates: list[dict]) -> list[tuple]:
        """("button", action, media_id, callback_id) and ("text", text, reply_to_message_id), from the
        allowed chat only."""
        out = []
        for update in updates:
            callback = update.get("callback_query")
            if callback:
                chat = ((callback.get("message") or {}).get("chat") or {}).get("id")
                match = re.fullmatch(r"ig:(ok|no|edit):([A-Za-z0-9_]{1,40})", str(callback.get("data") or ""))
                if str(chat) == self.chat_id and match:
                    out.append(("button", match.group(1), match.group(2), callback.get("id")))
                continue
            message = update.get("message") or {}
            if str((message.get("chat") or {}).get("id")) == self.chat_id and message.get("text"):
                reply = (message.get("reply_to_message") or {}).get("message_id")
                out.append(("text", message["text"], reply))
        return out
