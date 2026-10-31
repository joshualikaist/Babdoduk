# -*- coding: utf-8 -*-
"""The ops agent (scripts/ggongbab/ops_agent.py, docs/OPS_AGENT.md). Fakes only: no OpenAI, Telegram or systemd."""
from __future__ import annotations

import io
import json
import subprocess
from datetime import datetime

import pytest

from ggongbab import ops_agent as oa
from ggongbab.config import KST
from ggongbab.instagram import telegram_review as tr
from ggongbab.ops_policy import REASONS

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=KST).timestamp()
RADAR, PORTAL, IG = oa.UNITS["dooray-radar"], oa.UNITS["portal-worker"], oa.UNITS["ig-radar"]


def jpeg() -> bytes:
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (30, 30), (200, 100, 0)).save(buffer, "JPEG")
    return buffer.getvalue()


class Bot:
    chat_id = "42"

    def __init__(self):
        self.said, self.asked = [], []

    def say(self, text):
        self.said.append(text)

    def ask_agent(self, text, ask_id):
        self.asked.append((ask_id, text))
        return 1


class Run:
    """subprocess.run for systemctl, git, ops.sh and the worker runner; records every argv."""

    def __init__(self, active=(PORTAL, RADAR, IG), still_scanning=False):
        self.calls, self.active, self.still_scanning, self.fail = [], set(active), still_scanning, set()

    def __call__(self, argv, capture_output=True, text=True, timeout=None, cwd=None):
        self.calls.append(list(argv))
        out = ""
        if argv[:3] == ["systemctl", "--user", "is-active"]:
            out = "active" if argv[3] in self.active else "inactive"
        elif argv[0] == "git":
            out = "abc1234 11-02 11:00 content: generated data refresh"
        elif argv[-1] == "radar-stop" and not self.still_scanning:
            self.active.discard(RADAR)
        code = 1 if any(argv[-len(f):] == list(f) for f in self.fail) else 0
        return subprocess.CompletedProcess(argv, code, out, "")

    def did(self, *tail) -> bool:
        return any(call[-len(tail):] == list(tail) for call in self.calls)

    def restarts(self) -> list[str]:
        return [c[-1] for c in self.calls if c[:3] == ["systemctl", "--user", "restart"]]


def answer(reply="상태를 확인했습니다.", actions=(), later=""):
    return oa.Answer(reply=reply, actions=[oa.Action(**({"unit": None, "days": None, "why": "-"} | a)) for a in actions],
                     for_next_session=later)


@pytest.fixture
def ops(tmp_path):
    local = tmp_path / ".local"
    local.mkdir()
    (local / "ops-control.json").write_text(json.dumps({"enabled": True, "resume": NOW - 3600}))
    (local / "radar-control.json").write_text(json.dumps({"enabled": True, "changed_at": NOW - 3600}))

    def build(replies=None, run=None, clock=None):
        clock = clock if clock is not None else {"t": NOW}
        replies = list(replies or [])
        seen, logs, bot = [], [], Bot()

        def ask(content):
            seen.append(content)
            reply = replies.pop(0) if replies else answer()
            if isinstance(reply, Exception):
                raise reply
            return reply
        agent = oa.Agent(tmp_path, bot=bot, ask=ask, now=lambda: clock["t"], run=run or Run(), log=logs.append)
        return agent, bot, seen, logs, clock
    return tmp_path, build


def note(root, text, when=NOW, photo=None):
    return tr.keep_note(root / ".local", text, when, photo=photo)


def test_switching_on_answers_no_old_message_and_then_every_new_one(ops):
    root, build = ops
    note(root, "어제 쓴 메모")
    oa.set_enabled(root, True, NOW)
    agent, bot, seen, logs, _ = build([answer("레이더는 정상입니다.", later="")])
    agent.cycle()
    assert seen == [] and bot.said == []
    note(root, "메일 레이더 멈춘 것 같아", NOW + 60)
    agent.cycle()
    (content,) = seen
    assert "메일 레이더 멈춘 것 같아" in content[0]["text"] and "어제 쓴 메모" not in content[0]["text"].split("## 지난")[0]
    assert bot.said == ["🤖 자동 점검\n레이더는 정상입니다."] and logs == ["OPS_AGENT_ANSWERED"]
    agent.cycle()                                                   # nothing new: no second call
    assert len(seen) == 1
    (entry,) = agent.history(5)
    assert entry["notes"] == ["메일 레이더 멈춘 것 같아"] and entry["reply"] == "레이더는 정상입니다."


def test_while_off_messages_are_only_kept(ops):
    root, build = ops
    oa.set_enabled(root, True, NOW)
    oa.set_enabled(root, False, NOW + 1)
    agent, bot, seen, _, _ = build()
    note(root, "테스트")
    agent.cycle()
    assert seen == [] and bot.said == []
    oa.set_enabled(root, True, NOW + 2)                            # turning it on again answers nothing old
    agent.cycle()
    assert seen == []


def test_the_model_sees_masked_readable_state_and_the_photo_but_no_secret_file(ops):
    root, build = ops
    local = root / ".local"
    (root / ".env").write_text("OPENAI_API_KEY=sk-proj-SYNTHETICabcdefghijklmnop\n")
    (local / "easy-login.json").write_text(json.dumps({"enabled": True, "expected_id": "20261234"}))
    (local / "alert-push.json").write_text(json.dumps({"provider": "telegram", "chat_id": "987654321"}))
    (local / "ops-radar.json").write_text(json.dumps({"reason": "DOORAY_RADAR_RUNNING", "last_success": NOW - 120}))
    (local / oa.LATCH).write_text(json.dumps({"reason": "DOORAY_UNREAD_INVARIANT_BROKEN", "at": NOW - 7200,
                                              "requests": [["GET", "/v2/mail/<id>"]]}))
    (local / "ops-radar.log").write_text("".join(f"2026-11-02 11:{i:02d}:00,000 DOORAY_RADAR_RUNNING\n" for i in range(80)))
    oa.set_enabled(root, True, NOW)
    run = Run(active=(RADAR, IG))
    agent, _, seen, _, _ = build(run=run)
    note(root, "이 경고 뭐야? sb_secret_SYNTHETIC123456789", photo=jpeg())
    elsewhere = root / "outside.jpg"
    elsewhere.write_bytes(jpeg())
    with (local / tr.INBOX).open("a", encoding="utf-8") as inbox:     # a path outside the inbox folder is never read
        inbox.write(json.dumps({"at": "2026-11-02 12:00:05", "text": "두 번째", "photo": str(elsewhere)}) + "\n")
    agent.cycle()
    (content,) = seen
    text = content[0]["text"]
    assert "service portal-worker: inactive (control enabled)" in text and "service dooray-radar: active" in text
    assert "unread latch: SET" in text and "/v2/mail/<id>" in text and "abc1234" in text
    assert time_text(NOW - 120) in text                             # epoch seconds read as local time
    assert text.count("DOORAY_RADAR_RUNNING\n") <= oa.LOG_LINES
    for secret in ("sk-proj-SYNTHETIC", "20261234", "987654321", "sb_secret_SYNTHETIC", "expected_id"):
        assert secret not in text
    images = [part for part in content if part["type"] == "input_image"]
    assert len(images) == 1 and images[0]["image_url"].startswith("data:image/jpeg;base64,")


def time_text(ts):
    import time
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


def test_the_runbook_names_every_alert_action_with_the_linux_instruction():
    from ggongbab.alerts import ACTIONS
    from ggongbab.notify import LINUX_TOAST_ACTION
    prompt = oa.system_prompt()
    assert all(f"  {k}: " in prompt for k in ACTIONS)
    assert LINUX_TOAST_ACTION["review_unread"] in prompt and "ops.sh start" in prompt


def test_a_restart_only_for_a_worker_left_on_and_at_most_once_an_hour(ops):
    root, build = ops
    (root / ".local" / "ops-control.json").write_text(json.dumps({"enabled": False, "resume": NOW}))
    oa.set_enabled(root, True, NOW)
    run = Run(active=(IG,))
    agent, bot, _, logs, clock = build([answer(actions=[{"do": "restart", "unit": "portal-worker"},
                                                        {"do": "restart", "unit": "dooray-radar"}]),
                                        answer(actions=[{"do": "restart", "unit": "dooray-radar"}])], run=run)
    note(root, "다 멈춘 것 같아")
    agent.cycle()
    assert run.restarts() == [RADAR] and run.did("reset-failed", RADAR)
    assert "꺼 두신 상태라 켜지 않았습니다" in bot.said[0] and "두레이 메일 레이더: 다시 시작했습니다" in bot.said[0]
    assert "OPS_AGENT_RESTART" in logs
    clock["t"] += 1800
    note(root, "아직도 멈췄어", clock["t"])
    agent.cycle()
    assert run.restarts() == [RADAR] and "1시간 안에 이미 다시 시작" in bot.said[1]


def test_a_recheck_stops_the_radar_reads_again_and_starts_it(ops):
    root, build = ops
    oa.set_enabled(root, True, NOW)
    run = Run()
    agent, bot, _, _, clock = build([answer(actions=[{"do": "recheck", "days": 9}]),
                                     answer(actions=[{"do": "recheck", "days": 2}])], run=run)
    note(root, "메일 놓친 것 같아")
    agent.cycle()
    tails = [c[-1] if c[-1] != "1" else " ".join(c[-3:]) for c in run.calls if c[0] != "systemctl" and c[0] != "git"]
    assert tails == ["radar-stop", "radar-recheck --days 1", "radar-start"]     # 9 days is out of range: 1
    assert "최근 1일 메일을 다시 읽었습니다" in bot.said[0]
    clock["t"] += 3600
    note(root, "한 번 더", clock["t"])
    agent.cycle()
    assert "6시간에 한 번만" in bot.said[1] and not run.did("radar-recheck", "--days", "2")


def test_a_recheck_waits_while_the_radar_is_still_scanning(ops):
    root, build = ops
    oa.set_enabled(root, True, NOW)
    run = Run(still_scanning=True)
    agent, bot, _, _, _ = build([answer(actions=[{"do": "recheck", "days": 1}])], run=run)
    note(root, "메일 다시 읽어 줘")
    agent.cycle()
    assert run.did("radar-enable") and not any("radar-recheck" in c for c in run.calls)
    assert "스캔을 끝내지 않아" in bot.said[0]


def test_a_recheck_while_the_owner_left_the_radar_off_does_not_switch_it_on(ops):
    root, build = ops
    (root / ".local" / "radar-control.json").write_text(json.dumps({"enabled": False}))
    oa.set_enabled(root, True, NOW)
    run = Run(active=(PORTAL, IG))
    agent, _, _, _, _ = build([answer(actions=[{"do": "recheck", "days": 3}])], run=run)
    note(root, "메일 확인")
    agent.cycle()
    assert run.did("radar-recheck", "--days", "3") and not run.did("radar-stop") and not run.did("radar-start")


def test_the_unread_latch_is_cleared_only_after_the_owner_taps_ok(ops):
    root, build = ops
    local = root / ".local"
    (local / oa.LATCH).write_text(json.dumps({"reason": "DOORAY_UNREAD_INVARIANT_BROKEN", "at": NOW - 30 * 3600,
                                              "requests": [["GET", "/v2/mail/<id>"]]}))
    oa.set_enabled(root, True, NOW)
    run = Run()
    why = "잠금을 건 요청이 메일 열기 한 건이라, 운영 Chrome에서 메일을 직접 연 것으로 보입니다."
    agent, bot, _, logs, clock = build([answer("메일 잠금이 걸려 있습니다.", actions=[{"do": "allow_unread", "why": why}]),
                                        answer(actions=[{"do": "allow_unread", "why": why}])], run=run)
    note(root, "잠금 알림 왔어")
    agent.cycle()
    (ask_id, question), = bot.asked
    assert why in question and not run.did("radar-allow-unread")
    assert bot.said[0].startswith("🤖 자동 점검\n메일 잠금이 걸려 있습니다.") and "버튼으로 여쭤봤습니다" in bot.said[0]

    oa.record_answer(local, "no", ask_id, clock["t"])
    agent.cycle()
    assert bot.said[-1] == "🤖 잠금을 그대로 둡니다." and not run.did("radar-allow-unread")
    oa.record_answer(local, "ok", ask_id, clock["t"])              # the question was already answered
    agent.cycle()
    assert "이미 처리했거나" in bot.said[-1] and not run.did("radar-allow-unread")

    note(root, "다시 확인해 줘", clock["t"] + 60)
    agent.cycle()
    second = bot.asked[-1][0]
    oa.record_answer(local, "ok", second, clock["t"] + 120)
    agent.cycle()
    assert run.did("radar-allow-unread") and run.did("radar-recheck", "--days", "2")   # 30 hours locked: 2 days
    assert bot.said[-1].startswith("🔓 안 읽은 메일도 다시 수집합니다.") and "OPS_AGENT_UNREAD_ALLOWED" in logs


def test_a_question_older_than_a_day_is_not_carried_out(ops):
    root, build = ops
    (root / ".local" / oa.LATCH).write_text(json.dumps({"reason": "X", "at": NOW}))
    oa.set_enabled(root, True, NOW)
    run = Run()
    agent, bot, _, _, clock = build([answer(actions=[{"do": "allow_unread"}])], run=run)
    note(root, "잠금")
    agent.cycle()
    ask_id = bot.asked[0][0]
    clock["t"] += oa.ASK_EXPIRES + 1
    oa.record_answer(root / ".local", "ok", ask_id, clock["t"])
    agent.cycle()
    assert "하루가 지난 질문" in bot.said[-1] and not run.did("radar-allow-unread")


def test_a_failed_model_call_is_reported_once_and_the_message_is_not_retried(ops):
    root, build = ops
    oa.set_enabled(root, True, NOW)
    agent, bot, seen, logs, _ = build([RuntimeError("openai down")])
    note(root, "오류 났어")
    agent.cycle()
    agent.cycle()
    assert len(seen) == 1 and logs == ["OPS_AGENT_FAILED"]
    assert bot.said == ["🤖 자동 점검이 실패했습니다. 메시지는 저장돼 있으니 다음 Claude 작업 때 확인합니다."]


def test_the_daily_limit_keeps_messages_without_calling_the_model(ops, monkeypatch):
    root, build = ops
    monkeypatch.setattr(oa, "DAILY_RUNS", 2)
    oa.set_enabled(root, True, NOW)
    agent, bot, seen, logs, clock = build()
    for i in range(4):
        note(root, f"메모 {i}", NOW + i)
        clock["t"] = NOW + i
        agent.cycle()
    assert len(seen) == 2 and logs.count("OPS_AGENT_LIMIT") == 2
    assert sum("자동 점검을 2번 다 했습니다" in t for t in bot.said) == 1


def test_the_reply_is_masked_and_what_is_left_for_claude_is_kept(ops):
    root, build = ops
    oa.set_enabled(root, True, NOW)
    agent, bot, _, _, _ = build([answer("키는 sk-proj-abcdefghijklmnopqrstuvwxyz 입니다", later="포털 UI 보정 필요")])
    note(root, "포털 오류")
    agent.cycle()
    assert "sk-proj" not in bot.said[0] and "[가림]" in bot.said[0] and "다음 Claude 작업 때 처리할 일" in bot.said[0]
    assert agent.history(1)[0]["for_next_session"] == "포털 UI 보정 필요"


def test_a_second_run_waits_for_the_first(ops, monkeypatch):
    root, _ = ops
    from ggongbab.portal_list_state import poller_lock
    oa.set_enabled(root, True, NOW)
    monkeypatch.setattr(tr, "credentials", lambda local: ("token", "42"))
    monkeypatch.setattr(oa, "ask_model", lambda model: pytest.fail("no model call while another run holds the lock"))
    with poller_lock(root / ".local" / oa.HOME / oa.LOCK):
        assert oa.run(root) == 0


def test_agent_buttons_are_read_only_from_the_owners_chat():
    bot = tr.Bot("x", "42")

    def cb(data, chat=42):
        return {"update_id": 1, "callback_query": {"id": "c", "data": data, "message": {"chat": {"id": chat}}}}
    events = bot.events([cb("agent:ok:0123456789ab"), cb("agent:no:0123456789ab", chat=7), cb("agent:ok:../../x"),
                         cb("agent:run:0123456789ab")])
    assert events == [("agent", "ok", "0123456789ab", "c")]


def test_the_radar_hands_a_tap_to_the_agent_and_says_who_answers_a_note(tmp_path):
    from ggongbab.instagram.radar import Config, Radar

    class RadarBot(Bot):
        def __init__(self):
            super().__init__()
            self.pending, self.answered = [], []

        def updates(self, offset, wait=25):
            out, self.pending = self.pending, []
            return out

        def events(self, updates):
            return tr.Bot("x", self.chat_id).events(updates)

        def answer(self, callback, text):
            self.answered.append(text)

    (tmp_path / ".local").mkdir()
    bot = RadarBot()
    config = Config(version="v26.0", ig_user_id="1", token="t", primary="gpt-6-luna", review="gpt-6.1-terra")
    radar = Radar(tmp_path, config=config, graph=None, judge=None, bot=bot, now=lambda: NOW, sleep=lambda s: None)
    bot.pending = [{"update_id": 1, "message": {"chat": {"id": 42}, "text": "첫 메모"}}]
    radar.handle_updates(0)
    assert "메모로 저장했습니다" in bot.said[-1]
    oa.set_enabled(tmp_path, True, NOW)
    bot.pending = [{"update_id": 2, "message": {"chat": {"id": 42}, "text": "둘째 메모"}},
                   {"update_id": 3, "callback_query": {"id": "c9", "data": "agent:ok:0123456789ab",
                                                       "message": {"chat": {"id": 42}}}}]
    radar.handle_updates(0)
    assert bot.said[-1] == "📝 받았습니다. 상태를 확인하고 몇 분 안에 답할게요."
    assert bot.answered == ["확인했습니다. 곧 처리합니다"]
    line = (tmp_path / ".local" / oa.HOME / oa.ANSWERS).read_text().splitlines()[-1]
    assert json.loads(line) | {"at": 0} == {"action": "ok", "id": "0123456789ab", "at": 0}


def test_every_code_the_agent_logs_is_an_allowed_reason():
    import re
    from pathlib import Path
    text = Path(oa.__file__).read_text(encoding="utf-8")
    codes = set(re.findall(r'"(OPS_AGENT_[A-Z_]+)"', text))
    assert codes and codes <= REASONS


def test_the_agent_units_watch_the_inbox_and_run_once_per_message():
    from pathlib import Path
    import shutil
    if not shutil.which("bash"):
        pytest.skip("bash not available")
    script = Path(__file__).resolve().parents[2] / "scripts" / "linux" / "ops.sh"
    text = script.read_text(encoding="utf-8")
    start = text.index("agent_text() {")
    body = text[start:text.index("\n}\n", start) + 3]
    out = lambda kind: subprocess.run(["bash", "-c", body + '\nROOT=/r; RUNNER=/r/w.py; AGENT_UNIT=a.service; agent_text "$@"',
                                       "_", kind, "/py"], capture_output=True, text=True, check=True).stdout
    service, path = out("service"), out("path")
    assert "Type=oneshot\n" in service and "ExecStart=/py /r/w.py ops-agent\n" in service and "Restart" not in service
    assert "PathChanged=/r/.local/telegram-inbox.jsonl\n" in path and "PathChanged=/r/.local/ops-agent/answers.jsonl\n" in path
    assert "Unit=a.service\n" in path
