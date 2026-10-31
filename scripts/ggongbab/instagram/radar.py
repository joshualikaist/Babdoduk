# -*- coding: utf-8 -*-
"""Instagram 꽁밥 radar (owner request 2026-10-29, docs/INSTAGRAM_RADAR.md).

One cycle: check the token (daily) -> collect due accounts through Business Discovery (official
Graph API, GET only) -> analyze new posts (prefilter, primary model, review model) -> ask the owner
on Telegram when unsure -> hand confirmed posts to the existing pipeline as Dooray collection tasks
(the same path as the mail radar, so extraction, validation, dedup and publishing stay in one place).

No scraping, no unofficial API, no login automation; on a rate limit it waits. Secrets come from
the environment (.env) or this PC's credential store and are never logged or stored.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from . import analyze as an
from .meta_graph import REQUIRED_SCOPES, GraphClient, GraphError, usage_percent
from .store import Store

ACCOUNTS_FILE = Path("inputs/instagram/accounts.json")
STATE = "ops-ig-radar.json"
LOG = "ops-ig-radar.log"
LOCK = "ig-radar.lock"
PAGE = 10
FIRST_BACKFILL = 30           # most posts one first check takes, even within collect_since
SLOW_ABOVE = 80.0
RELAX_BELOW = 50.0
BACKOFF_BASE = 900            # 15 minutes, doubled per consecutive rate limit, up to 6 hours
BACKOFF_MAX = 6 * 3600
TOKEN_CHECK_EVERY = 24 * 3600
QUESTIONS_PER_DAY = 5
DIGEST_HOURS = (9, 18)        # KST
COST_ALERT_USD = 5.0
ACCOUNT_PAUSE = 2.0           # seconds between accounts: sequential, never a burst
LOOP_SECONDS = 300


@dataclass
class Config:
    version: str = field(default_factory=lambda: os.environ.get("META_GRAPH_VERSION", "v26.0"))
    ig_user_id: str = field(default_factory=lambda: os.environ.get("META_IG_USER_ID", ""))
    token: str = field(default_factory=lambda: os.environ.get("META_ACCESS_TOKEN", ""), repr=False)
    app_secret: str = field(default_factory=lambda: os.environ.get("META_APP_SECRET", ""), repr=False)
    primary: str = field(default_factory=lambda: os.environ.get("OPENAI_MODEL_PRIMARY", "gpt-6-luna"))
    review: str = field(default_factory=lambda: os.environ.get("OPENAI_MODEL_REVIEW", "gpt-6.1-terra"))

    def missing(self) -> list[str]:
        return [name for name, value in (("META_IG_USER_ID", self.ig_user_id), ("META_ACCESS_TOKEN", self.token))
                if not value]


def launch_login(root: Path):
    from ..easy_login import launch_request
    return launch_request(root)


class Radar:
    def __init__(self, root: Path, *, config: Config, graph, judge, bot=None, writer=None, log=None,
                 now: Callable = time.time, sleep: Callable = time.sleep, dry_run: bool = False):
        self.root, self.local = Path(root), Path(root) / ".local"
        self.store = Store(self.local)
        self.config, self.graph, self.judge, self.bot, self.writer = config, graph, judge, bot, writer
        self.log = log or (lambda code: None)
        self.now, self.sleep, self.dry_run = now, sleep, dry_run
        self.counts: dict = {}
        self.since = collect_since(self.root)
        self.tips = None        # ggongbab.tips.Tips: reader tips share this bot (cli.build)
        self.login_child = None     # the Easy Login attempt the owner asked for (request_login)
        self.launch_login = launch_login

    # --- alerts -------------------------------------------------------------------------------
    def alert(self, key: str, text: str, every: float = 24 * 3600) -> None:
        """A system notice through the same bot, at most once per `every` seconds per key."""
        last = self.store.get(f"alert:{key}", 0)
        if self.now() - float(last) < every or self.bot is None or self.dry_run:
            return
        try:
            self.bot.say("🛠 밥도둑 인스타 레이더: " + text)
            self.store.put(f"alert:{key}", self.now())
        except RuntimeError:
            self.log("IG_TELEGRAM_FAILED")

    # --- the token and the limits -------------------------------------------------------------
    def check_token(self) -> bool:
        if self.now() - float(self.store.get("token_checked", 0)) < TOKEN_CHECK_EVERY:
            return True
        try:
            status = self.graph.token_status()
        except GraphError as exc:
            self.log("IG_TOKEN_INVALID" if exc.kind == "auth" else "IG_ACCOUNT_ERROR")
            if exc.kind == "auth":
                self.alert("token", "Meta 액세스 토큰이 무효입니다. 새 토큰을 .env에 넣어 주세요.")
            return False
        missing = REQUIRED_SCOPES - status["scopes"]
        if not status["valid"] or missing:
            self.log("IG_SCOPE_MISSING")
            self.alert("scope", "토큰 권한이 부족합니다: " + ", ".join(sorted(missing)) if missing else "토큰이 무효입니다.")
            return False
        expires = status["expires_at"]
        if expires and expires - self.now() < 7 * 86400:
            days = max(0, int((expires - self.now()) // 86400))
            self.alert("expiry", f"Meta 토큰이 {days}일 뒤 만료됩니다. 새 토큰을 발급해 주세요.")
        self.store.put("token_checked", self.now())
        return True

    def record_usage(self, endpoint: str, outcome: str, headers: Optional[dict]) -> None:
        percent = usage_percent(headers or {})
        self.store.log_usage(endpoint, outcome, headers, percent, self.now())
        factor = int(self.store.get("slow_factor", 1))
        if percent > SLOW_ABOVE and factor == 1:
            self.store.put("slow_factor", 2)
            self.log("IG_SLOWED_DOWN")
            self.alert("usage", f"Graph API 사용률 {percent:.0f}% - 조회 주기를 2배로 늘렸습니다.")
        elif percent < RELAX_BELOW and factor > 1 and outcome == "ok":
            self.store.put("slow_factor", 1)

    def backing_off(self) -> bool:
        return self.now() < float(self.store.get("backoff_until", 0))

    def rate_limited(self, headers: Optional[dict]) -> None:
        step = int(self.store.get("backoff_step", 0))
        self.store.put("backoff_until", self.now() + min(BACKOFF_BASE * 2 ** step, BACKOFF_MAX))
        self.store.put("backoff_step", step + 1)
        self.record_usage("business_discovery", "rate_limit", headers)
        self.log("IG_RATE_LIMITED")

    # --- collect --------------------------------------------------------------------------------
    def due(self) -> list:
        factor = int(self.store.get("slow_factor", 1))
        rows = []
        for account in self.store.accounts():
            if account["status"] == "unsupported":
                continue
            interval = account["interval_minutes"] * 60 * factor
            if account["last_checked"] is None or self.now() - account["last_checked"] >= interval:
                rows.append(account)
        return rows

    def collect(self) -> int:
        """New posts of every due account; stops the whole round on a rate limit or a bad token."""
        added = 0
        for n, account in enumerate(self.due()):
            if self.backing_off():
                break
            if n:
                self.sleep(ACCOUNT_PAUSE)
            try:
                added += self.collect_account(account)
            except GraphError as exc:
                if exc.kind == "rate_limit":
                    self.rate_limited(getattr(exc, "headers", None))
                    break
                if exc.kind == "auth":
                    self.store.put("token_checked", 0)
                    self.log("IG_TOKEN_INVALID")
                    self.alert("token", "Meta 액세스 토큰이 거부되었습니다. 새 토큰을 .env에 넣어 주세요.")
                    break
                if exc.kind == "unsupported":
                    self.store.update_account(account["username"], status="unsupported", last_checked=self.now())
                    self.log("IG_ACCOUNT_UNSUPPORTED")
                    if not account["status_notified"]:
                        self.store.update_account(account["username"], status_notified=1)
                        self.alert(f"unsupported:{account['username']}",
                                   f"@{account['username']}는 비즈니스/크리에이터 계정이 아니거나 찾을 수 없어 건너뜁니다.", every=0)
                    continue
                self.store.update_account(account["username"], status="error", last_checked=self.now())
                self.log("IG_ACCOUNT_ERROR")
        return added

    def collect_account(self, account) -> int:
        username = account["username"]
        first = account["last_media_id"] is None
        cap = FIRST_BACKFILL
        new, after = [], ""
        while True:
            found, headers = self.graph.discover(username, limit=PAGE, after=after)
            self.record_usage("business_discovery", "ok", headers)
            media = (found.get("media") or {})
            known = old = False
            for item in media.get("data") or []:
                # Skipped, not a stop: a pinned post can sit above newer ones.
                if self.store.has_post(str(item["id"])):
                    known = True
                    continue
                if an.posted_kst(item["timestamp"]).timestamp() < self.since:
                    old = True
                    continue
                new.append(item)
                if len(new) >= cap:
                    break
            after = ((media.get("paging") or {}).get("cursors") or {}).get("after") or ""
            # One page is the usual case. Keep paging only while every post was new and recent enough
            # (a first check or a busy account), up to FIRST_BACKFILL, and only if there is a next page.
            if known or old or len(new) >= cap or not after or len(media.get("data") or []) < PAGE:
                break
            self.sleep(ACCOUNT_PAUSE)
        newest = max(new, key=lambda item: item["timestamp"]) if new else None
        for item in sorted(new, key=lambda item: item["timestamp"]):   # oldest first
            self.store.add_post(username, item, self.now())
            self.save_images(item)
        if newest:
            self.store.update_account(username, last_media_id=str(newest["id"]))
        self.store.update_account(username, status="ok", last_checked=self.now(), last_success=self.now())
        self.counts["collected"] = self.counts.get("collected", 0) + len(new)
        if first:
            self.counts["backfill"] = self.counts.get("backfill", 0) + len(new)
        return len(new)

    def save_images(self, item: dict) -> None:
        """Download at once: media_url is a signed, expiring CDN link. A carousel keeps every image,
        a video its thumbnail."""
        from ..parsers.attachment_text import image_mime
        sources = []
        children = (item.get("children") or {}).get("data") or []
        for child in children or [item]:
            url = child.get("thumbnail_url") if child.get("media_type") == "VIDEO" else child.get("media_url")
            url = url or child.get("thumbnail_url")
            if url:
                sources.append(url)
        for position, url in enumerate(sources):
            try:
                data = self.graph.download(url)
            except GraphError:
                self.counts["image_failed"] = self.counts.get("image_failed", 0) + 1
                continue
            mime = image_mime(data)
            ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}.get(mime, "bin")
            self.store.save_image(str(item["id"]), position, data, ext)

    # --- analyze --------------------------------------------------------------------------------
    def load_images(self, media_id: str) -> list[tuple[str, bytes]]:
        from ..parsers.attachment_text import image_mime, normalize_image
        out = []
        for row in self.store.images(media_id)[:an.MAX_IMAGES]:
            try:
                data = Path(row["path"]).read_bytes()
            except OSError:
                continue
            out.append(normalize_image(image_mime(data), data))
        return out

    def analyze(self) -> None:
        errors = 0
        for post in self.store.unanalyzed():
            images = self.load_images(post["media_id"])
            if not an.prefilter(post["caption"], len(images)):
                self.store.set_prefilter(post["media_id"], "skip")
                self.store.upsert_candidate(post["media_id"], "auto_rejected", post["media_id"], {},
                                            decided_by="prefilter", now=self.now())
                self.counts["prefiltered"] = self.counts.get("prefiltered", 0) + 1
                continue
            content = an.user_content(post["caption"], post["timestamp"], images, self.store.recent_labels())
            primary = self.run_model(post["media_id"], "primary", self.config.primary, content)
            if primary is None:
                errors += 1
                continue
            verdict, by = an.decide(primary, None)
            review = None
            if verdict == "review":
                review = self.run_model(post["media_id"], "review", self.config.review, content)
                if review is None:
                    errors += 1
                    continue
                verdict, by = an.decide(primary, review)
            chosen = review if by == "review" or (verdict == "ask" and review is not None) else primary
            if verdict == "confirm" and an.undated(chosen):
                verdict, by = "ask", ""
            extraction = chosen.model_dump() | {"_verdicts": self.verdicts(primary, review)}
            status = {"confirm": "auto_confirmed", "reject": "auto_rejected", "ask": "pending_human"}[verdict]
            if status != "auto_rejected" and an.is_past(extraction, post["timestamp"], self.now_kst()):
                status = "expired"
            group = self.merge_group(post, extraction) if verdict != "reject" else post["media_id"]
            self.store.upsert_candidate(post["media_id"], status, group, extraction, decided_by=by, now=self.now())
            self.counts[status] = self.counts.get(status, 0) + 1
            if errors >= 3:
                break
        if errors >= 3:
            self.log("IG_OPENAI_ERRORS")
            self.alert("openai", "OpenAI 분석 오류가 연달아 났습니다. 다음 주기에 다시 시도합니다.", every=6 * 3600)

    def run_model(self, media_id: str, stage: str, model: str, content: list):
        try:
            result, tokens_in, tokens_out = self.judge(model, content)
        except Exception as exc:  # noqa: BLE001 - recorded with a class name only; the post is retried next cycle
            self.store.add_run(media_id, stage, model, error=type(exc).__name__, now=self.now())
            return None
        self.store.add_run(media_id, stage, model, input_tokens=tokens_in, output_tokens=tokens_out,
                           cost=an.cost(model, tokens_in, tokens_out), result=result.model_dump(), now=self.now())
        return result

    @staticmethod
    def verdicts(primary, review) -> str:
        line = lambda name, j: f"{name}: {'꽁밥' if j.is_free_food_event else '아님'} {j.confidence:.2f}"  # noqa: E731
        return line("1차", primary) + (" / " + line("2차", review) if review is not None else "")

    def merge_group(self, post, extraction: dict) -> str:
        posted = an.posted_kst(post["timestamp"])
        since = (posted - an.MERGE_WINDOW).astimezone(an.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+0000")
        for other in self.store.recent_confirmed(post["username"], since):
            if other["media_id"] != post["media_id"] and an.same_event(extraction, other["extraction"]):
                return other["merge_group"]
        return post["media_id"]

    # --- the owner --------------------------------------------------------------------------------
    def review(self, wait: int = 0) -> None:
        if self.bot is None or self.dry_run:
            return
        try:
            self.ask_pending()
            if self.tips is not None:
                self.tips.poll()
            self.handle_updates(wait)
        except RuntimeError:
            self.log("IG_TELEGRAM_FAILED")

    def now_kst(self) -> datetime:
        return datetime.fromtimestamp(self.now(), an.KST)

    def expire(self, row) -> bool:
        """An event that is over stays here as `expired` and is never asked about or handed over."""
        post = self.store.post(row["media_id"])
        if not an.is_past(json.loads(row["extraction_json"]), post["timestamp"], self.now_kst()):
            return False
        self.store.update_candidate(row["media_id"], status="expired", updated_at=self.now())
        self.counts["expired"] = self.counts.get("expired", 0) + 1
        return True

    def ask_pending(self) -> None:
        today = datetime.fromtimestamp(self.now(), an.KST).strftime("%Y-%m-%d")
        sent = self.store.get(f"asked:{today}", 0)
        for row in self.store.candidates("pending_human"):
            if row["question_sent"] or self.expire(row):
                continue
            if sent >= QUESTIONS_PER_DAY:
                self.store.update_candidate(row["media_id"], status="queued_digest", updated_at=self.now())
                continue
            post = self.store.post(row["media_id"])
            extraction = json.loads(row["extraction_json"])
            from .telegram_review import summary
            text = summary(post, extraction, extraction.get("_verdicts", ""), an.posted_kst(post["timestamp"]).strftime("%m-%d %H:%M"))
            images = self.load_images(row["media_id"])
            message_id = self.bot.ask(text, row["media_id"], images[0] if images else None)
            self.store.update_candidate(row["media_id"], question_sent=self.now(), telegram_message_id=message_id,
                                        updated_at=self.now())
            sent += 1
            self.store.put(f"asked:{today}", sent)
        hour = datetime.fromtimestamp(self.now(), an.KST)
        slot = hour.strftime("%Y-%m-%d") + f"@{hour.hour}"
        queued = [row for row in self.store.candidates("queued_digest") if not self.expire(row)]
        if queued and hour.hour in DIGEST_HOURS and self.store.get("digest_slot") != slot:
            items = []
            for row in queued:
                post, extraction = self.store.post(row["media_id"]), json.loads(row["extraction_json"])
                items.append((row["media_id"], f"@{post['username']} {extraction.get('event_title') or post['caption'][:40]} "
                                               f"({extraction.get('_verdicts', '')}) {post['permalink']}"))
            self.bot.digest(items)
            for row in queued:
                self.store.update_candidate(row["media_id"], status="pending_human", question_sent=self.now(),
                                            updated_at=self.now())
            self.store.put("digest_slot", slot)

    def handle_updates(self, wait: int) -> None:
        from .telegram_review import EDITABLE, parse_edit
        offset = int(self.store.get("telegram_offset", 0))
        updates = self.bot.updates(offset, wait)
        if updates:
            self.store.put("telegram_offset", max(int(u.get("update_id", 0)) for u in updates) + 1)
        for event in self.bot.events(updates):
            if event[0] == "tip":
                _, action, tip_id, callback = event
                if self.tips is None:
                    self.bot.answer(callback, "제보 검토가 아직 켜져 있지 않습니다")
                else:
                    self.tips.decide(action, tip_id, callback)
            elif event[0] == "login":
                self.request_login(event[1])
            elif event[0] == "agent":
                from ..ops_agent import record_answer
                _, action, ask_id, callback = event
                record_answer(self.local, action, ask_id, self.now())
                self.bot.answer(callback, "확인했습니다. 곧 처리합니다")
            elif event[0] == "photo":
                self.note(event[2], event[1])
            elif event[0] == "button":
                _, action, media_id, callback = event
                row = self.store.candidate(media_id)
                if row is None:
                    self.bot.answer(callback, "알 수 없는 게시물입니다")
                    continue
                if action == "ok":
                    self.store.update_candidate(media_id, status="human_confirmed", decided_by="human")
                    self.store.add_review(media_id, "confirm", now=self.now())
                    self.bot.answer(callback, "✅ 꽁밥으로 등록합니다")
                elif action == "no":
                    self.store.update_candidate(media_id, status="human_rejected", decided_by="human")
                    self.store.add_review(media_id, "reject", now=self.now())
                    self.bot.answer(callback, "❌ 꽁밥 아님으로 기록했습니다")
                else:
                    self.bot.answer(callback, "✏️ 답장으로 고쳐 주세요")
                    prompt = self.bot._call("sendMessage", {
                        "chat_id": self.bot.chat_id, "reply_markup": {"force_reply": True},
                        "text": "✏️ 이 메시지에 답장으로 고칠 내용을 '필드: 값' 줄로 보내 주세요.\n"
                                "필드: 제목, 음식(쉼표로), 시작, 종료, 장소, 대상, 인원, 준비물, 신청\n"
                                "예) 시작: 2026-10-06T17:30+09:00"})
                    self.store.put(f"edit:{prompt.get('message_id')}", media_id)
            else:
                _, text, reply_to = event
                media_id = self.store.get(f"edit:{reply_to}") if reply_to else None
                if not media_id or self.store.candidate(media_id) is None:
                    from ..easy_login import is_request
                    if is_request(text):
                        self.request_login()
                    else:
                        self.note(text)
                    continue
                changes = {k: v for k, v in parse_edit(text).items() if k in EDITABLE}
                if not changes:
                    self.bot.say("고칠 필드를 찾지 못했습니다. '필드: 값' 형식으로 보내 주세요.")
                    continue
                row = self.store.candidate(media_id)
                extraction = json.loads(row["extraction_json"]) | changes | {"is_free_food_event": True}
                self.store.update_candidate(media_id, status="human_confirmed", decided_by="human",
                                            extraction_json=json.dumps(extraction, ensure_ascii=False))
                self.store.add_review(media_id, "edit", json.dumps(changes, ensure_ascii=False), now=self.now())
                self.bot.say("✏️ 고친 내용으로 꽁밥 등록합니다: " + ", ".join(changes))

    def request_login(self, callback: Optional[str] = None) -> None:
        """The owner asks for a KAIST login now: the 🔑 button or a message that is only "로그인" (owner
        2026-10-31: "로그인이라고 말하거나, 로그인 버튼이 있으면 누를게. 그러면 다시 너가 승인 요청하도록까지
        창 만들어줘"). One Easy Login attempt starts at once in its own process, which opens the login
        page again and sends the new code or says why not (easy_login.run_assist(requested=True))."""
        from ..easy_login import enabled as easy_login_on
        if not easy_login_on(self.local)[0]:
            text = "간편 로그인 도우미가 이 PC에서 꺼져 있습니다. 원격 데스크톱으로 운영 Chrome에서 직접 로그인해 주세요."
        elif self.login_child is not None and self.login_child.poll() is None:
            text = "⏳ 로그인 화면을 여는 중입니다. 승인 번호가 곧 옵니다."
        else:
            try:
                self.login_child = self.launch_login(self.root)
                text = "🔑 로그인 화면을 다시 열고 승인 번호를 보내겠습니다. 30초쯤 걸립니다."
            except OSError:
                self.log("EASY_LOGIN_REQUEST_NOT_STARTED")
                text = "⚠️ 로그인 요청을 시작하지 못했습니다. 원격 데스크톱으로 직접 로그인해 주세요."
        if callback:
            self.bot.answer(callback, text)
        else:
            self.bot.say(text)

    def note(self, text: str, photo: str = "") -> None:
        """Anything the owner writes that answers no question is kept for Claude (keep_note) and, while
        the ops agent is on, answered by it a few minutes later (ops_agent: the inbox starts it)."""
        from ..ops_agent import enabled
        from .telegram_review import keep_note
        data = None
        if photo:
            try:
                data = self.bot.download(photo)
            except RuntimeError:
                self.log("IG_TELEGRAM_FAILED")
        keep_note(self.local, text, self.now(), photo=data)
        if enabled(self.local):
            self.bot.say("📝 받았습니다. 상태를 확인하고 몇 분 안에 답할게요.")
        else:
            self.bot.say("📝 메모로 저장했습니다. 다음에 Claude와 작업할 때 \"텔레그램 메모 확인해 줘\"라고 하시면 읽어 봅니다.")

    # --- hand over to the pipeline ----------------------------------------------------------------
    def bridge(self) -> None:
        """Each confirmed event once as a Dooray collection task (the leader of its merge group);
        the other posts of the group keep their permalinks here and in the task's comment line."""
        if self.writer is None or self.dry_run:
            return
        from ..web.task_writer import MailPayload
        for row in self.store.candidates("auto_confirmed", "human_confirmed"):
            if row["dooray_post_id"] or self.expire(row):
                continue
            current = self.store.candidate(row["media_id"])     # the owner may have answered meanwhile
            if current is None or current["status"] not in ("auto_confirmed", "human_confirmed") or current["dooray_post_id"]:
                continue
            members = self.store.group_members(row["merge_group"])
            leader = next((m for m in members if m["dooray_post_id"] and not m["dooray_post_id"].startswith("merged:")), None)
            if leader is not None:
                self.store.update_candidate(row["media_id"], dooray_post_id=f"merged:{leader['dooray_post_id']}")
                continue
            post = self.store.post(row["media_id"])
            account = self.store.account(post["username"])
            extraction = json.loads(row["extraction_json"])
            posted = an.posted_kst(post["timestamp"])
            links = [self.store.post(m["media_id"])["permalink"] for m in members]
            body = (f"{post['caption']}\n\n[인스타그램 @{post['username']}"
                    f"{' (' + account['display_name'] + ')' if account and account['display_name'] else ''} 게시물]\n"
                    f"게시: {posted.strftime('%Y-%m-%d %H:%M')} (KST)\n" + "\n".join(f"원본: {link}" for link in links))
            title = extraction.get("event_title") or (post["caption"].splitlines() or [""])[0][:60]
            try:
                post_id = self.writer.create_task(MailPayload(
                    mail_id=f"instagram-{post['media_id']}", subject=f"[인스타 @{post['username']}] {title}"[:200],
                    body=body, received_at=posted, discovered_at=datetime.fromtimestamp(self.now(), an.KST),
                    images=self.load_images(post["media_id"])))
            except Exception:  # noqa: BLE001 - retried next cycle
                self.log("IG_DOORAY_FAILED")
                continue
            self.store.update_candidate(row["media_id"], dooray_post_id=str(post_id))
            self.counts["handed_over"] = self.counts.get("handed_over", 0) + 1

    # --- costs and one cycle ------------------------------------------------------------------------
    def cost_check(self) -> None:
        start = datetime.fromtimestamp(self.now(), an.KST).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        spent = self.store.month_cost(start.timestamp())
        self.counts["month_cost_usd"] = round(spent, 4)
        if spent > COST_ALERT_USD:
            self.alert(f"cost:{start:%Y-%m}", f"이번 달 OpenAI 추정 비용이 ${spent:.2f}로 ${COST_ALERT_USD:.0f}를 넘었습니다.",
                       every=40 * 86400)

    def cycle(self) -> str:
        self.counts = {}
        if not self.check_token():
            return "IG_TOKEN_INVALID"
        if self.backing_off():
            self.log("IG_RATE_LIMITED")
        else:
            self.collect()
            if not self.backing_off():
                self.store.put("backoff_step", 0)
        self.analyze()
        self.review()
        self.bridge()
        self.cost_check()
        purged = self.store.purge_images(self.now())
        if purged:
            self.counts["images_purged"] = purged
        self.log("IG_RADAR_CYCLE_OK")
        return "IG_RADAR_CYCLE_OK"


def collect_since(root: Path) -> float:
    """`collect_since` of the accounts file (a KST date): posts before it are never collected or
    analyzed (owner decision 2026-10-29: start from that week's Monday). 0 without one."""
    try:
        value = json.loads((Path(root) / ACCOUNTS_FILE).read_text(encoding="utf-8")).get("collect_since")
    except (OSError, ValueError):
        return 0.0
    if not value:
        return 0.0
    return datetime.strptime(str(value), "%Y-%m-%d").replace(tzinfo=an.KST).timestamp()


def load_accounts(root: Path) -> list[dict]:
    data = json.loads((Path(root) / ACCOUNTS_FILE).read_text(encoding="utf-8"))
    from .meta_graph import USERNAME
    rows = [row for row in data.get("accounts") or [] if USERNAME.fullmatch(str(row.get("username", "")))]
    if not rows:
        raise ValueError("no accounts")
    return rows


def check_models(client, config: Config) -> list[str]:
    """Problems with the configured models: missing from the account, or refusing an image."""
    import base64
    import io
    problems = []
    available = {m.id for m in client.models.list()}
    try:
        from PIL import Image
        buffer = io.BytesIO()
        Image.new("RGB", (8, 8), (255, 255, 255)).save(buffer, "PNG")
        probe = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
    except ImportError:
        probe = ""
    for model in (config.primary, config.review):
        if model not in available:
            problems.append(f"{model}: not available to this OpenAI account")
            continue
        if probe:
            try:
                client.responses.create(model=model, max_output_tokens=16, input=[{"role": "user", "content": [
                    {"type": "input_text", "text": "OK?"}, {"type": "input_image", "image_url": probe}]}])
            except Exception as exc:  # noqa: BLE001
                problems.append(f"{model}: image input refused ({type(exc).__name__})")
    return problems
