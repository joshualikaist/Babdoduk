# -*- coding: utf-8 -*-
"""The owner's Telegram messages, answered on the operations PC (docs/OPS_AGENT.md).

Owner 2026-10-31: "너가 받아서 확인한 다음에 진짜 모르겠는거만 지금처럼 나한테 물어보면 되지", with the
Instagram radar's classifier model ("우리 기존에 쓰던 분류기 모델도 그거로 하면 되는거 아니야?").

The Instagram radar keeps each message in .local/telegram-inbox.jsonl (telegram_review.keep_note) and
each tap on one of the questions below in .local/ops-agent/answers.jsonl; a systemd path unit starts
this one-shot run on either (scripts/linux/ops.sh agent-install). It:

  * builds a masked summary of the operations state: the services, the control files, the unread
    latch, the alerts and the last lines of each worker log (reason codes only, by SafeLog's design);
  * asks the radar's primary model (OPENAI_MODEL_PRIMARY, gpt-6-luna; never swapped here) for a reply
    in Korean, the actions it proposes and what it leaves for the next Claude session. The model sees
    only that summary, the message and its photo; it has no tools and changes nothing itself;
  * sends the reply and carries out only what this module allows:
      restart       a worker the owner left switched on, at most once an hour per worker;
      recheck       the Dooray mail of the last 1-3 days read again, at most once every six hours;
      allow_unread  never on its own: a ✅/❌ question, and only ✅ clears the latch (it protects
                    unread mail); the days the latch skipped are then read again.
    A login, a code or site fix, a deployment or a database change stays with the owner or the next
    Claude session, which reads .local/ops-agent/history.jsonl (`ops.sh agent-status`).
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Callable, Literal, Optional

from pydantic import BaseModel, ConfigDict

from .ops_storage import atomic_json, read_json

HOME = "ops-agent"                      # .local/ops-agent/
CONTROL = "ops-agent.json"              # .local/ops-agent.json: {"enabled": bool}
ANSWERS, STATE, HISTORY, LOCK = "answers.jsonl", "state.json", "history.jsonl", "run.lock"
LOG = "ops-agent.log"
DAILY_RUNS = 30                         # model calls in any 24 hours; then messages are only kept
SEEN_KEEP, ANSWERS_KEEP, HISTORY_KEEP = 400, 100, 200
LOG_LINES = 60
REPLY_MAX = 3500
RESTART_EVERY, RECHECK_EVERY, ASK_EXPIRES = 3600, 6 * 3600, 86400
UNITS = {"portal-worker": "babdoduk-portal-worker.service", "dooray-radar": "babdoduk-dooray-radar.service",
         "ig-radar": "babdoduk-ig-radar.service"}
LABELS = {"portal-worker": "포털 공지 수집", "dooray-radar": "두레이 메일 레이더", "ig-radar": "인스타 레이더"}
LOGS = ("ops-portal.log", "ops-watchdog.log", "ops-radar.log", "ops-ig-radar.log", "ops-easy-login.log", LOG)
# State files whose values are timestamps, counts and reason codes; never easy-login.json (a Portal ID)
# or alert-push.json (the chat).
STATE_FILES = ("ops-control.json", "ops-portal.json", "ops-watchdog.json", "ops-alerts.json", "radar-control.json",
               "ops-radar.json", "radar-unread-disabled.json", "ops-ig-radar.json", "easy-login-state.json")
LATCH = "radar-unread-disabled.json"


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid")
    do: Literal["restart", "recheck", "allow_unread", "login"]
    unit: Optional[Literal["portal-worker", "dooray-radar", "ig-radar"]]
    days: Optional[int]
    why: str


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reply: str
    actions: list[Action]
    for_next_session: str


SYSTEM = """You are the operations assistant of Babdoduk, a KAIST free-food site, on the owner's operations PC.
The owner is Korean and not a developer. They wrote to you on Telegram, usually because something looks
broken (an alert on their phone, a missing event, a screenshot). You get their message(s) and photos, your
last answers, and a summary of the operations state: the services, the control files, the unread-mail
latch, the alerts and the last lines of each worker log. The logs hold reason codes only.

The workers: portal-worker (KAIST Portal notices, in the Ops Chrome; needs the owner's Portal login),
dooray-radar (Dooray mail in the same Chrome; it skips unread mail while the unread latch is set),
ig-radar (Instagram accounts through the official API; it also runs this Telegram bot and the reader tips).
Standing states that need nothing from the owner (mention them only if asked): CANDIDATE_WAITING while the
radar's dispatch is off (ops-radar.json "dispatch": "DISPATCH_OFF"; the scheduled refresh still publishes
the candidate within hours), and an occasional IG_TELEGRAM_FAILED (a dropped connection; the bot retries).

Answer in Korean, plainly and briefly (at most 8 short lines): what happened, why, and what is being done
or what the owner should do. Separate what the state shows from what you infer. Never say something is
fixed or working unless the state shows it. If the message is not about a problem (a test, thanks), answer
in one line and propose nothing. Never repeat tokens, passwords, IDs or cookies.

Actions, run by the program with its own limits; propose one only when the state shows the need:
  restart (unit): the worker is meant to run (its control is enabled) but its service is not active, or
    its log shows it stuck. Never for a login wait (a login latch in ops-watchdog.json such as
    PORTAL_LIST_AUTH_REQUIRED, or DOORAY_AUTH_REQUIRED): a restart does not log in.
  recheck (days 1-3): Dooray mail was missed (the radar was stopped or failed, or skipped unread mail)
    and must be read again.
  allow_unread: the unread latch is set. The program asks the owner first, with buttons. Explain in `why`
    what tripped it (its requests) and whether it looks like the owner opening a mail in the Ops Chrome's
    Dooray tab or something else.
  login: the owner asks in this message for a KAIST login now (they can approve on their phone). The PC
    opens the login page again and sends a new approval number to Telegram (Easy Login). Not when they
    report that they approved or logged in, and never on your own initiative: when a login is needed but
    not asked for, tell them to tap 🔑 로그인 요청 or send "로그인".
    How a login ends: once the owner approves on the phone the SSO page closes and the watchdog restarts
    the Portal worker by itself (OPS_AUTO_RESUMED in its log); nothing else is needed. If the owner says
    they approved but the login wait is still there, the approval did not go through (easy-login-state.json
    "last_sent" is the last code's time; a code lasts about 3 minutes): suggest 🔑 or "로그인" for a new code.
Nothing else can be done here. The approval itself (the owner's phone), a login by hand over remote desktop,
a code or site fix, a deployment, a database change or a Meta/Instagram setting is for the owner or the
next Claude session: say so, and put a short task description in for_next_session. That field is only
for work a developer must do (a fault you cannot explain counts); leave it empty otherwise, and never use
it to ask the owner something.

Alert actions (ops-alerts.json), what each means, and what the owner is told:
"""


def system_prompt() -> str:
    from .alerts import ACTIONS
    from .notify import LINUX_TOAST_ACTION
    return SYSTEM + "\n".join(f"  {k}: {v}" + (f" / 안내: {LINUX_TOAST_ACTION[k]}" if k in LINUX_TOAST_ACTION else "")
                              for k, v in ACTIONS.items())


def mask(text: str) -> str:
    from .instagram.telegram_review import SECRETISH
    return SECRETISH.sub("[가림]", text)


def enabled(local: Path) -> bool:
    try:
        return read_json(Path(local) / CONTROL, {}).get("enabled") is True
    except Exception:  # noqa: BLE001 - an unreadable switch is off
        return False


def _digest(line: str) -> str:
    return hashlib.sha256(line.encode("utf-8")).hexdigest()[:12]


def _lines(path: Path) -> list[str]:
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


def _readable(value):
    """Epoch seconds as local time, so the model reads "2026-10-31 13:52" instead of 1793422320.5."""
    if isinstance(value, dict):
        return {k: _readable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_readable(v) for v in value]
    if isinstance(value, (int, float)) and not isinstance(value, bool) and 1.6e9 < value < 2.2e9:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(value))
    return value


def record_answer(local: Path, action: str, ask_id: str, now: float) -> None:
    """The radar's half: the owner's ✅/❌ on one of these questions, for the next run to carry out."""
    path = Path(local) / HOME / ANSWERS
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    line = json.dumps({"action": action, "id": ask_id, "at": round(now, 3)})
    path.write_text("\n".join((_lines(path) + [line])[-ANSWERS_KEEP:]) + "\n", encoding="utf-8")
    path.chmod(0o600)


def baseline(local: Path) -> dict:
    """Everything already in the inbox counts as seen: switching the agent on answers no old message."""
    from .instagram.telegram_review import INBOX
    local = Path(local)
    return {"notes": [_digest(l) for l in _lines(local / INBOX)][-SEEN_KEEP:],
            "answers": [_digest(l) for l in _lines(local / HOME / ANSWERS)][-SEEN_KEEP:],
            "runs": [], "last": {}, "pending": {}, "limit_day": ""}


def set_enabled(root: Path, on: bool, now: float) -> None:
    local = Path(root) / ".local"
    home = local / HOME
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    if on:
        atomic_json(home / STATE, baseline(local))
    atomic_json(local / CONTROL, {"enabled": bool(on), "changed_at": round(now, 3)})


class Agent:
    def __init__(self, root: Path, *, bot, ask: Callable[[list], Answer], now: Callable = time.time,
                 run: Callable = subprocess.run, log: Callable = lambda code: None):
        self.root = Path(root).resolve()
        self.local = self.root / ".local"
        self.home = self.local / HOME
        self.bot, self.ask, self.now, self.run, self.log = bot, ask, now, run, log
        self.asked_login = self.login_wanted = False   # handle(): the owner asked for a login

    # --- commands ---------------------------------------------------------------------------------
    def _run(self, argv: list[str], timeout: int) -> tuple[int, str]:
        try:
            done = self.run(argv, capture_output=True, text=True, timeout=timeout, cwd=str(self.root))
        except (OSError, subprocess.TimeoutExpired):
            return 1, ""
        return done.returncode, (done.stdout or "").strip()

    def systemctl(self, *args: str) -> tuple[int, str]:
        return self._run(["systemctl", "--user", *args], 60)

    def workers(self, *args: str, timeout: int = 120) -> int:
        return self._run([sys.executable, str(self.root / "scripts" / "windows" / "ggongbab_workers.py"), *args], timeout)[0]

    def ops(self, *args: str, timeout: int = 180) -> int:
        return self._run(["bash", str(self.root / "scripts" / "linux" / "ops.sh"), *args], timeout)[0]

    def active(self, name: str) -> bool:
        return self.systemctl("is-active", UNITS[name])[1] == "active"

    def switched_on(self, name: str) -> bool:
        control = {"portal-worker": "ops-control.json", "dooray-radar": "radar-control.json"}.get(name)
        if control is None:
            return True
        try:
            return read_json(self.local / control, {}).get("enabled") is True
        except Exception:  # noqa: BLE001
            return False

    # --- state ------------------------------------------------------------------------------------
    def load(self) -> dict:
        try:
            state = read_json(self.home / STATE, None)
        except Exception:  # noqa: BLE001 - a broken state file starts over without replaying the inbox
            state = None
        return state if isinstance(state, dict) and {"notes", "answers", "runs", "last", "pending"} <= set(state) \
            else baseline(self.local)

    def save(self, state: dict) -> None:
        atomic_json(self.home / STATE, state)

    def unseen(self, state: dict, key: str, path: Path) -> list[tuple[str, dict]]:
        out = []
        for line in _lines(path):
            digest = _digest(line)
            if digest in state[key]:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                entry = None
            out.append((digest, entry if isinstance(entry, dict) else {}))
        return out

    def seen(self, state: dict, key: str, digests: list[str]) -> None:
        state[key] = (state[key] + digests)[-SEEN_KEEP:]

    # --- the run ----------------------------------------------------------------------------------
    def cycle(self) -> int:
        """Taps first (the owner may have answered meanwhile), then new messages; again while more arrive."""
        from .instagram.telegram_review import INBOX
        self.home.mkdir(mode=0o700, parents=True, exist_ok=True)
        state = self.load()
        for _ in range(5):
            answers = self.unseen(state, "answers", self.home / ANSWERS)
            notes = self.unseen(state, "notes", self.local / INBOX)
            if not answers and not notes:
                break
            for digest, entry in answers:
                self.seen(state, "answers", [digest])
                self.save(state)
                self.apply(state, entry)
            if notes:
                self.seen(state, "notes", [d for d, _ in notes])
                self.save(state)
                self.handle(state, [e for _, e in notes])
            self.save(state)
        return 0

    def say(self, text: str) -> None:
        try:
            self.bot.say(mask(text)[:REPLY_MAX])
        except RuntimeError:
            self.log("OPS_AGENT_TELEGRAM_FAILED")

    def handle(self, state: dict, notes: list[dict]) -> None:
        if not enabled(self.local):
            return
        now = self.now()
        runs = [t for t in state["runs"] if t > now - 86400]
        if len(runs) >= DAILY_RUNS:
            day = time.strftime("%Y-%m-%d", time.localtime(now))
            if state.get("limit_day") != day:
                state["limit_day"] = day
                self.say(f"🤖 오늘 자동 점검을 {DAILY_RUNS}번 다 했습니다. 이후 메시지는 저장만 하고, 다음 Claude 작업 때 확인합니다.")
            self.log("OPS_AGENT_LIMIT")
            return
        state["runs"] = runs + [now]
        self.asked_login = any(re.search(r"로그인|login", str(n.get("text") or ""), re.IGNORECASE) for n in notes)
        self.login_wanted = False
        try:
            answer = self.ask(self.content(state, notes))
        except Exception:  # noqa: BLE001 - the message stays in the inbox for the next Claude session
            self.log("OPS_AGENT_FAILED")
            self.say("🤖 자동 점검이 실패했습니다. 메시지는 저장돼 있으니 다음 Claude 작업 때 확인합니다.")
            return
        lines, questions = [], []
        for action in answer.actions[:3]:
            line, question = self.act(state, action)
            lines.append(line)
            if question:
                questions.append(question)
        text = "🤖 자동 점검\n" + answer.reply.strip()
        if any(lines):
            text += "\n\n" + "\n".join(l for l in lines if l)
        if answer.for_next_session.strip():
            text += "\n\n🗒️ 다음 Claude 작업 때 처리할 일로 남겼습니다."
        self.say(text)
        for question, ask_id in questions:
            try:
                self.bot.ask_agent(mask(question)[:REPLY_MAX], ask_id)
            except RuntimeError:
                self.log("OPS_AGENT_TELEGRAM_FAILED")
        self.remember(notes, answer, lines)
        self.log("OPS_AGENT_ANSWERED")
        if self.login_wanted:
            # Waited for here: this one-shot service's processes end with it. The attempt tells the
            # owner its outcome itself (easy_login.run_assist(requested=True)).
            self._run([sys.executable, str(self.root / "scripts" / "windows" / "ggongbab_workers.py"),
                       "easy-login", "--requested"], 300)

    def remember(self, notes: list[dict], answer: Answer, lines: list[str]) -> None:
        path = self.home / HISTORY
        entry = {"at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.now())),
                 "notes": [mask(str(n.get("text") or ""))[:500] + (" [사진]" if n.get("photo") else "") for n in notes],
                 "reply": mask(answer.reply)[:REPLY_MAX], "actions": [a.model_dump() for a in answer.actions[:3]],
                 "results": [l for l in lines if l], "for_next_session": mask(answer.for_next_session)[:2000]}
        path.write_text("\n".join((_lines(path) + [json.dumps(entry, ensure_ascii=False)])[-HISTORY_KEEP:]) + "\n",
                        encoding="utf-8")
        path.chmod(0o600)

    def history(self, limit: int) -> list[dict]:
        out = []
        for line in _lines(self.home / HISTORY)[-limit:]:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out

    # --- what the model sees ----------------------------------------------------------------------
    def content(self, state: dict, notes: list[dict]) -> list[dict]:
        from .instagram.telegram_review import INBOX_PHOTOS
        from .parsers.attachment_text import image_mime
        text = ["## 운영자 메시지"]
        images = []
        folder = (self.local / INBOX_PHOTOS).resolve()
        for note in notes:
            text.append(f"- {note.get('at', '')}: {note.get('text') or '(글 없음)'}" + (" [사진 첨부]" if note.get("photo") else ""))
            photo = Path(str(note.get("photo") or ""))
            if note.get("photo") and photo.resolve().parent == folder and photo.is_file() and len(images) < 3:
                data = photo.read_bytes()
                mime = image_mime(data)
                if mime in ("image/jpeg", "image/png", "image/webp"):
                    images.append({"type": "input_image", "image_url": f"data:{mime};base64,{base64.b64encode(data).decode()}"})
        past = self.history(3)
        if past:
            text.append("\n## 지난 대화 (최근 것이 아래)")
            text += [f"- {p['at']} 운영자: {' / '.join(p['notes'])}\n  답: {p['reply'][:400]}" for p in past]
        text.append(f"\n## 운영 상태 ({time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.now()))})")
        text.append(self.snapshot())
        return [{"type": "input_text", "text": mask("\n".join(text))[:60000]}] + images

    def snapshot(self) -> str:
        rows = []
        for name, unit in UNITS.items():
            rows.append(f"service {name}: {self.systemctl('is-active', unit)[1] or 'unknown'}"
                        + ("" if name == "ig-radar" else f" (control {'enabled' if self.switched_on(name) else 'disabled'})"))
        _, head = self._run(["git", "-C", str(self.root), "log", "-1", "--format=%h %cd %s", "--date=format:%m-%d %H:%M"], 10)
        rows.append(f"ops checkout: {head or 'unknown'}")
        rows.append("unread latch: " + ("SET" if (self.local / LATCH).exists() else "not set"))
        for name in STATE_FILES:
            path = self.local / name
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8")[:200000])
            except (OSError, ValueError):
                rows.append(f"\n### {name}\n(unreadable)")
                continue
            body = json.dumps(_readable(data), ensure_ascii=False)
            rows.append(f"\n### {name}\n{body[:3000]}")
        for name in LOGS:
            path = self.local / name
            if path.exists():
                tail = path.read_text(encoding="utf-8", errors="replace").splitlines()[-LOG_LINES:]
                rows.append(f"\n### {name} (last {len(tail)} lines)\n" + "\n".join(tail))
        return "\n".join(rows)

    # --- what the program does --------------------------------------------------------------------
    def act(self, state: dict, action: Action) -> tuple[str, Optional[tuple[str, str]]]:
        now = self.now()
        if action.do == "restart":
            name = action.unit
            if name not in UNITS:
                return "", None
            label = LABELS[name]
            if not self.switched_on(name):
                return f"⏸️ {label}: 꺼 두신 상태라 켜지 않았습니다.", None
            key = f"restart:{name}"
            if now - float(state["last"].get(key, 0)) < RESTART_EVERY:
                return f"⏭️ {label}: 1시간 안에 이미 다시 시작해서 이번에는 하지 않았습니다.", None
            state["last"][key] = now
            self.save(state)
            self.systemctl("reset-failed", UNITS[name])
            code, _ = self.systemctl("restart", "--no-block", UNITS[name])
            self.log("OPS_AGENT_RESTART")
            return (f"🔄 {label}: 다시 시작했습니다." if code == 0 else f"⚠️ {label}: 다시 시작하지 못했습니다."), None
        if action.do == "recheck":
            return self.recheck(state, action.days if action.days in (1, 2, 3) else 1), None
        if action.do == "login":
            from .easy_login import enabled as easy_login_on
            if not self.asked_login:
                return "", None             # only when the owner's own message asks for a login
            if not easy_login_on(self.local)[0]:
                return "🔑 간편 로그인 도우미가 꺼져 있어 로그인 요청을 보내지 않았습니다.", None
            self.login_wanted = True        # started after the reply (handle), so it comes first
            return "🔑 로그인 화면을 다시 열고 승인 번호를 곧 보냅니다.", None
        if action.do == "allow_unread":
            if not (self.local / LATCH).exists():
                return "🔓 읽지 않은 메일 잠금은 이미 풀려 있습니다.", None
            state["pending"] = {k: v for k, v in state["pending"].items() if now - float(v.get("at", 0)) < ASK_EXPIRES}
            ask_id = uuid.uuid4().hex[:12]
            state["pending"][ask_id] = {"do": "allow_unread", "at": now}
            self.save(state)
            question = ("🔒 읽지 않은 메일 잠금을 풀까요?\n" + action.why.strip()[:600]
                        + "\n\n✅를 누르면 안 읽은 메일도 다시 수집하고, 잠긴 동안의 메일을 다시 읽습니다.")
            return "❓ 잠금을 풀지 버튼으로 여쭤봤습니다.", (question, ask_id)
        return "", None

    def recheck(self, state: dict, days: int) -> str:
        now = self.now()
        if now - float(state["last"].get("recheck", 0)) < RECHECK_EVERY:
            return "⏭️ 메일 다시 읽기는 6시간에 한 번만 합니다. 이번에는 하지 않았습니다."
        state["last"]["recheck"] = now
        self.save(state)
        was_on = self.switched_on("dooray-radar")
        if was_on:
            self.ops("radar-stop")
            if self.active("dooray-radar"):     # still finishing a scan: leave it running
                self.workers("radar-enable")
                return "⚠️ 메일 레이더가 스캔을 끝내지 않아 다시 읽기를 미뤘습니다."
        code = self.workers("radar-recheck", "--days", str(days), timeout=1200)
        if was_on:
            self.ops("radar-start")
        self.log("OPS_AGENT_RECHECK")
        if code == 0:
            return f"📬 최근 {days}일 메일을 다시 읽었습니다."
        return "⚠️ 메일 다시 읽기가 실패했습니다." + (" 레이더는 원래대로 다시 켰습니다." if was_on else "")

    def apply(self, state: dict, entry: dict) -> None:
        pending = state["pending"].pop(str(entry.get("id") or ""), None)
        self.save(state)
        if not pending or self.now() - float(pending.get("at", 0)) >= ASK_EXPIRES:
            self.say("🤖 이미 처리했거나 하루가 지난 질문입니다.")
            return
        if entry.get("action") != "ok":
            self.say("🤖 잠금을 그대로 둡니다.")
            return
        latch = self.local / LATCH
        since = None
        try:
            since = float(read_json(latch, {}).get("at") or 0) or None
        except Exception:  # noqa: BLE001
            pass
        if self.workers("radar-allow-unread") != 0:
            self.say("🤖 잠금을 풀지 못했습니다. 다음 Claude 작업 때 확인합니다.")
            return
        self.log("OPS_AGENT_UNREAD_ALLOWED")
        days = min(3, max(1, math.ceil((self.now() - since) / 86400))) if since else 1
        self.say("🔓 안 읽은 메일도 다시 수집합니다.\n" + self.recheck(state, days))


def ask_model(model: str) -> Callable[[list], Answer]:
    from openai import OpenAI
    from .config import load_settings
    client = OpenAI(api_key=load_settings().openai_api_key, timeout=120, max_retries=2)

    def ask(content: list) -> Answer:
        response = client.responses.parse(
            model=model, input=[{"role": "system", "content": system_prompt()}, {"role": "user", "content": content}],
            text_format=Answer, max_output_tokens=3000)
        if response.output_parsed is None:
            raise ValueError("no structured output")
        return response.output_parsed
    return ask


def run(root: Path) -> int:
    """`ggongbab_workers.py ops-agent`: the one-shot run the path unit starts."""
    from .instagram.radar import Config
    from .instagram.telegram_review import Bot, credentials
    from .ops_storage import SafeLog
    from .portal_list_state import ListStateError, poller_lock
    root = Path(root).resolve()
    local = root / ".local"
    if not enabled(local):
        return 0
    token, chat = credentials(local)
    if not (token and chat):
        return 1
    (local / HOME).mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        with poller_lock(local / HOME / LOCK):
            return Agent(root, bot=Bot(token, chat), ask=ask_model(Config().primary), log=SafeLog(local / LOG)).cycle()
    except ListStateError:
        return 0        # another run is busy and picks this message up in its next round


def status(root: Path, limit: int = 5) -> int:
    root = Path(root).resolve()
    local = root / ".local"
    agent = Agent(root, bot=None, ask=None)
    state = agent.load()
    runs = [t for t in state["runs"] if t > time.time() - 86400]
    print(f"Ops agent    : {'on' if enabled(local) else 'off'}, {len(runs)}/{DAILY_RUNS} model calls in 24 h,"
          f" {len(state['pending'])} question(s) waiting")
    for entry in agent.history(limit):
        print(f"\n{entry['at']}  {' / '.join(entry['notes'])}\n  답: {entry['reply'][:300]}")
        for line in entry.get("results") or []:
            print(f"  {line}")
        if entry.get("for_next_session"):
            print(f"  다음 Claude 작업: {entry['for_next_session']}")
    return 0
