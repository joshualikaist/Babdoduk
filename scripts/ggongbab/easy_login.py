# -*- coding: utf-8 -*-
"""Easy Login assist (owner decision 2026-10-29, docs/PORTAL_EASY_LOGIN_ASSIST.md).

When the KAIST SSO session has ended, start a KAIST SSO **Easy Login** in the Babdoduk Ops Chrome
and send the two-digit verification code to the owner's Telegram, so a login is one approval on the
owner's phone instead of a remote-desktop session. The approval itself stays human.

What it does, and nothing else, on the loopback CDP endpoint of the Ops Chrome:
  1. portal.kaist.ac.kr/common/login/login.do  -> click `#btn-sso-login`;
  2. sso.kaist.ac.kr/auth/kaist/user/login/view -> with the Easy Login tab on (`li#mfa.on`) and the
     ID field already filled by Remember ID (and equal to the owner's configured ID), click
     `#loginTab01 a.btn_login`;
  3. sso.kaist.ac.kr/auth/twofactor/mfa/login2Factor -> read the two visible one-digit boxes and
     the countdown, send one Telegram message, and leave. The watchdog's existing resume path
     notices the SSO page closing once the owner has approved.

It never types into a field, never selects ID/PW Login, never reads or stores a password, cookie
or token, never approves anything, and stops on any page, error text, dialog or CAPTCHA it does
not expect. The page probe returns fixed facts only (booleans, the two digits, the countdown);
the code goes into the one Telegram message and nowhere else: logs hold fixed reason codes and
the state file holds timestamps and counts.

On the owner's request (owner 2026-10-31: "로그인이라고 말하거나, 로그인 버튼이 있으면 누를게. 그러면 다시
너가 승인 요청하도록까지 창 만들어줘"): the Telegram button 🔑 or a message such as "로그인" starts one attempt
at once (run_assist(requested=True)). It has its own limits instead of the automatic ones, and when no
login page is open it first sends the Portal's tab back to the Portal's login page (one fixed URL,
PORTAL_LOGIN_URL), for example from a verification page that expired unanswered. It tells the owner
the outcome either way.

Opt-in per PC: `.local/easy-login.json` = {"enabled": true, "expected_id": "<the owner's KAIST ID>"}.
Without it, or without a configured Telegram push (notify.local_notifier), nothing runs.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from .ops_storage import OpsError, SafeLog, atomic_json, read_json

CONFIG = "easy-login.json"
STATE = "easy-login-state.json"
LOCK = "easy-login.lock"
LOG = "ops-easy-login.log"

MIN_GAP_SECONDS = 1800        # at most one attempt per 30 minutes ...
DAILY_MAX = 4                 # ... and four per day
UNANSWERED_MAX = 2            # two unanswered codes in a row pause it until a person logs in
CODE_LIFETIME_SECONDS = 300   # the page offers 3 minutes (extendable); past this a code is unanswered
STEP_WAIT_SECONDS = 20        # how long one click may take to reach the next page
MAX_STEPS = 4
ID_SETTLE_SECONDS = 3      # Remember ID fills the field just after the SSO page loads
REQUEST_GAP_SECONDS = 60      # the owner's own request: a double tap is one request ...
REQUEST_DAILY_MAX = 10        # ... and at most ten a day

PORTAL_LOGIN = ("portal.kaist.ac.kr", "/common/login/login.do")
SSO_VIEW = ("sso.kaist.ac.kr", "/auth/kaist/user/login/view")
SSO_MFA = ("sso.kaist.ac.kr", "/auth/twofactor/mfa/login2Factor")
PORTAL_LOGIN_URL = "https://portal.kaist.ac.kr/common/login/login.do"   # the only address it ever opens
PORTAL_BUTTON = "#btn-sso-login"
EASY_LOGIN_BUTTON = "#loginTab01 a.btn_login"
CLICKABLE = frozenset({PORTAL_BUTTON, EASY_LOGIN_BUTTON})

CODES = frozenset({
    "EASY_LOGIN_CODE_SENT", "EASY_LOGIN_DISABLED", "EASY_LOGIN_NO_PUSH", "EASY_LOGIN_RATE_LIMITED",
    "EASY_LOGIN_PAUSED_UNANSWERED", "EASY_LOGIN_NO_LOGIN_PAGE", "EASY_LOGIN_MFA_ALREADY_OPEN",
    "EASY_LOGIN_BUSY", "EASY_LOGIN_BROWSER_UNAVAILABLE", "EASY_LOGIN_PUSH_FAILED",
    "EASY_LOGIN_STOPPED_UNEXPECTED_PAGE", "EASY_LOGIN_STOPPED_NOT_EASY_LOGIN", "EASY_LOGIN_STOPPED_ID_EMPTY",
    "EASY_LOGIN_STOPPED_ID_MISMATCH", "EASY_LOGIN_STOPPED_SSO_ERROR", "EASY_LOGIN_STOPPED_CAPTCHA",
    "EASY_LOGIN_STOPPED_UNRESPONSIVE", "EASY_LOGIN_STOPPED_NO_PROGRESS",
    "EASY_LOGIN_REQUESTED", "EASY_LOGIN_REQUEST_NOT_STARTED", "EASY_LOGIN_REQUEST_TOO_SOON",
    "EASY_LOGIN_REQUEST_DAILY_MAX", "EASY_LOGIN_NOT_NEEDED", "EASY_LOGIN_STOPPED_TABS_UNCLEAR",
})

# The owner's request: this button (telegram_review.Bot.events -> ("login", callback)) or a short
# message that is only the request ("로그인", "다시 로그인", "로그인 해줘", "/login"; never a question).
REQUEST_CALLBACK = "login:go"
REQUEST_WORDS = re.compile(r"(다시)?(로그인|login)(다시)?(할게|할께|해|해줘|해주세요|해줄래|하자|요청|시작|부탁해?)?요?",
                           re.IGNORECASE)


def is_request(text: str) -> bool:
    compact = re.sub(r"\s+", "", text or "").rstrip(".!~ㅎㅋ").lstrip("/")
    return bool(REQUEST_WORDS.fullmatch(compact))


def request_markup(label: str = "🔑 로그인 요청") -> dict:
    return {"inline_keyboard": [[{"text": label, "callback_data": REQUEST_CALLBACK}]]}

# The probe reads only fixed facts. `expected` is compared inside the page so the ID never
# leaves it; the digits are the only page text returned.
PROBE = r"""(() => {
  const expected = %s;
  const q = (s) => document.querySelector(s);
  const visible = (e) => !!(e && (e.offsetWidth || e.offsetHeight || e.getClientRects().length));
  const out = {host: location.hostname, path: location.pathname};
  out.portal_button = visible(q('#btn-sso-login'));
  const on = q('.login_tab li.on');
  out.tab = on ? on.id : '';
  const id = q('#login_id_mfa');
  const value = id ? (id.value || '').trim() : '';
  out.id_filled = value.length > 0;
  out.id_matches = expected === '' || value === expected;
  out.easy_button = visible(q('#loginTab01 a.btn_login'));
  const msg = q('#mfaResultMsg');
  out.error = !!(msg && msg.textContent.trim());
  out.captcha = !!q('iframe[src*="captcha" i], [id*="captcha" i], [class*="captcha" i], .g-recaptcha');
  const root = q('.box02') || document.body;
  const digits = [], timers = [];
  for (const e of root.querySelectorAll('*')) {
    if (e.children.length || !visible(e)) continue;
    const t = (e.textContent || '').trim();
    if (/^\d$/.test(t)) digits.push(t);
    else if (/^\d{1,2}:\d{2}$/.test(t)) timers.push(t);
  }
  out.digits = digits.slice(0, 4);
  out.timer = timers.length ? timers[0] : '';
  return out;
})()"""


def page_kind(url: str) -> str:
    """'portal_login', 'sso_view', 'sso_mfa' or '' for any other page. Exact https host and path."""
    try:
        parts = urlsplit(url or "")
    except ValueError:
        return ""
    if parts.scheme != "https":
        return ""
    where = ((parts.hostname or "").lower(), parts.path.rstrip("/") or "/")
    return {PORTAL_LOGIN: "portal_login", SSO_VIEW: "sso_view", SSO_MFA: "sso_mfa"}.get(where, "")


def decide(probe: dict) -> tuple:
    """("click", selector) | ("code", "NN", seconds) | ("stop", REASON). Pure."""
    kind = {PORTAL_LOGIN: "portal_login", SSO_VIEW: "sso_view", SSO_MFA: "sso_mfa"}.get(
        (str(probe.get("host") or "").lower(), (str(probe.get("path") or "").rstrip("/") or "/")), "")
    if probe.get("captcha"):
        return ("stop", "EASY_LOGIN_STOPPED_CAPTCHA")
    if kind == "portal_login":
        return ("click", PORTAL_BUTTON) if probe.get("portal_button") else ("stop", "EASY_LOGIN_STOPPED_UNEXPECTED_PAGE")
    if kind == "sso_view":
        if probe.get("error"):
            return ("stop", "EASY_LOGIN_STOPPED_SSO_ERROR")
        if probe.get("tab") != "mfa":
            return ("stop", "EASY_LOGIN_STOPPED_NOT_EASY_LOGIN")
        if not probe.get("id_filled"):
            return ("stop", "EASY_LOGIN_STOPPED_ID_EMPTY")
        if not probe.get("id_matches"):
            return ("stop", "EASY_LOGIN_STOPPED_ID_MISMATCH")
        return ("click", EASY_LOGIN_BUTTON) if probe.get("easy_button") else ("stop", "EASY_LOGIN_STOPPED_UNEXPECTED_PAGE")
    if kind == "sso_mfa":
        digits = probe.get("digits") or []
        if len(digits) != 2 or not all(isinstance(d, str) and re.fullmatch(r"\d", d) for d in digits):
            return ("stop", "EASY_LOGIN_STOPPED_UNEXPECTED_PAGE")
        match = re.fullmatch(r"(\d{1,2}):(\d{2})", str(probe.get("timer") or ""))
        seconds = int(match.group(1)) * 60 + int(match.group(2)) if match else None
        return ("code", "".join(digits), seconds)
    return ("stop", "EASY_LOGIN_STOPPED_UNEXPECTED_PAGE")


def message(code: str, seconds: Optional[int]) -> str:
    left = f"남은 시간: 약 {seconds // 60}분 {seconds % 60:02d}초\n" if seconds else ""
    return ("🔐 밥도둑 운영: KAIST 로그인 승인 요청\n\n"
            f"휴대폰 KAIST 인증 앱 알림에서 {code} 을(를) 선택하세요.\n{left}\n"
            "이 메시지 없이 온 승인 요청은 밥도둑이 보낸 것이 아니니 거절하세요.\n"
            "시간 안에 못 하셨으면 아래 버튼을 누르거나 \"로그인\"이라고 보내 주세요. 새 번호를 보냅니다.")


# What the owner is told when their own request ends without a code. Fixed wording per reason.
REMOTE = "원격 데스크톱으로 이 PC의 운영 Chrome에서 직접 로그인해 주세요."
OUTCOME = {
    "EASY_LOGIN_NOT_NEEDED": "✅ 지금은 로그인이 필요하지 않습니다. 포털과 메일 수집 모두 로그인을 기다리지 않습니다.",
    "EASY_LOGIN_REQUEST_TOO_SOON": "⏳ 방금 요청을 처리했습니다. 1분 뒤에 다시 눌러 주세요.",
    "EASY_LOGIN_REQUEST_DAILY_MAX": f"⛔ 오늘 로그인 요청을 {REQUEST_DAILY_MAX}번 다 썼습니다. " + REMOTE,
    "EASY_LOGIN_BUSY": "⏳ 다른 로그인 시도가 진행 중입니다. 잠시 뒤 다시 눌러 주세요.",
    "EASY_LOGIN_BROWSER_UNAVAILABLE": "⚠️ 운영 Chrome에 연결하지 못했습니다. 몇 분 뒤 다시 누르거나, " + REMOTE,
    "EASY_LOGIN_PUSH_FAILED": "⚠️ 승인 번호를 텔레그램으로 보내지 못했습니다. 다시 눌러 주세요.",
    "EASY_LOGIN_STOPPED_TABS_UNCLEAR": "⚠️ 운영 Chrome의 탭이 예상과 달라 손대지 않았습니다. " + REMOTE,
    "EASY_LOGIN_STOPPED_ID_EMPTY": "⚠️ 로그인 화면의 아이디 칸이 비어 있습니다(아이디 기억이 풀림). 한 번은 " + REMOTE,
    "EASY_LOGIN_STOPPED_ID_MISMATCH": "⚠️ 로그인 화면에 다른 아이디가 들어 있어 멈췄습니다. " + REMOTE,
    "EASY_LOGIN_STOPPED_NOT_EASY_LOGIN": "⚠️ 로그인 화면이 간편 로그인(Easy Login) 탭이 아니어서 멈췄습니다. " + REMOTE,
    "EASY_LOGIN_STOPPED_CAPTCHA": "⚠️ 로그인 화면에 보안 문자가 나와 멈췄습니다. " + REMOTE,
    "EASY_LOGIN_STOPPED_SSO_ERROR": "⚠️ 로그인 화면에 오류 문구가 있어 멈췄습니다. 잠시 뒤 다시 누르거나, " + REMOTE,
}
STOPPED = "⚠️ 로그인 화면이 예상대로 넘어가지 않아 멈췄습니다. 잠시 뒤 다시 누르거나, " + REMOTE


def outcome(code: str) -> tuple[str, Optional[dict]]:
    """The message for an owner's request that ended without a code, and its button (none when
    pressing again would not help yet)."""
    text = OUTCOME.get(code, STOPPED)
    quiet = {"EASY_LOGIN_NOT_NEEDED", "EASY_LOGIN_REQUEST_TOO_SOON", "EASY_LOGIN_REQUEST_DAILY_MAX"}
    return text, None if code in quiet else request_markup("🔑 다시 요청")


# --- the limits ------------------------------------------------------------------------------
def normalize(state: dict, now: float, last_success: Optional[float]) -> dict:
    """Account for what happened since the last code: answered (a scan succeeded after it), or
    unanswered once its lifetime passed. A successful scan after the last unanswered code means a
    person has logged in, which lifts the pause."""
    state = {"attempts": [float(t) for t in state.get("attempts") or [] if now - float(t) < 86400],
             "requests": [float(t) for t in state.get("requests") or [] if now - float(t) < 86400],
             "last_sent": state.get("last_sent"), "unanswered": int(state.get("unanswered") or 0),
             "last_unanswered": state.get("last_unanswered")}
    sent = state["last_sent"]
    if sent is not None and last_success is not None and last_success > float(sent):
        state.update(last_sent=None, unanswered=0, last_unanswered=None)
    elif sent is not None and now - float(sent) > CODE_LIFETIME_SECONDS:
        state.update(last_sent=None, unanswered=state["unanswered"] + 1, last_unanswered=float(sent))
    if (state["unanswered"] and state["last_unanswered"] is not None and last_success is not None
            and last_success > float(state["last_unanswered"])):
        state.update(unanswered=0, last_unanswered=None)
    return state


def gate(state: dict, now: float) -> Optional[str]:
    """None when an attempt may start now, else the reason it may not (state already normalized)."""
    if state["unanswered"] >= UNANSWERED_MAX:
        return "EASY_LOGIN_PAUSED_UNANSWERED"
    if state["last_sent"] is not None:
        return "EASY_LOGIN_RATE_LIMITED"          # a code is still waiting for the owner
    attempts = state["attempts"]
    started = attempts + state["requests"]          # an owner's request also restarts the 30 minutes
    if started and now - max(started) < MIN_GAP_SECONDS:
        return "EASY_LOGIN_RATE_LIMITED"
    if len(attempts) >= DAILY_MAX:
        return "EASY_LOGIN_RATE_LIMITED"
    return None


def request_gate(state: dict, now: float) -> Optional[str]:
    """The owner's own request: none of the automatic limits (the owner is there and asked), only
    REQUEST_GAP_SECONDS and REQUEST_DAILY_MAX."""
    requests = state["requests"]
    if requests and now - max(requests) < REQUEST_GAP_SECONDS:
        return "EASY_LOGIN_REQUEST_TOO_SOON"
    if len(requests) >= REQUEST_DAILY_MAX:
        return "EASY_LOGIN_REQUEST_DAILY_MAX"
    return None


def login_waits(local: Path) -> dict:
    """Which collector reports that it waits for a login: the Portal (the watchdog's login latch)
    and the Dooray Radar (DOORAY_AUTH_REQUIRED). For request_target."""
    from .ops_policy import LOGIN
    local = Path(local)
    return {"portal_wait": read_json(local / "ops-watchdog.json", {}).get("latched") in LOGIN,
            "mail_wait": read_json(local / "ops-radar.json", {}).get("reason") == "DOORAY_AUTH_REQUIRED"}


def last_success(local: Path) -> Optional[float]:
    """The newest successful scan of the Portal worker or the Dooray Radar."""
    values = []
    for name in ("ops-portal.json", "ops-radar.json"):
        value = read_json(Path(local) / name, {}).get("last_success")
        if isinstance(value, (int, float)):
            values.append(float(value))
    return max(values) if values else None


def enabled(local: Path) -> tuple[bool, str]:
    config = read_json(Path(local) / CONFIG, {})
    expected = config.get("expected_id") if isinstance(config.get("expected_id"), str) else ""
    return config.get("enabled") is True, expected.strip()


def may_start(local: Path, now: float) -> bool:
    """Cheap check for the watchdog before it launches the assist process."""
    if not enabled(Path(local))[0]:
        return False
    state = normalize(read_json(Path(local) / STATE, {}), now, last_success(local))
    return gate(state, now) is None


# --- one attempt -------------------------------------------------------------------------------
class Page:
    """One page target of the Ops Chrome, attached through the loopback CDP client."""

    def __init__(self, client, target_id: str):
        self.client = client
        attached = client.call("Target.attachToTarget", {"targetId": target_id, "flatten": True})
        if not (attached or {}).get("sessionId"):
            raise OpsError("EASY_LOGIN_BROWSER_UNAVAILABLE")
        self.session = attached["sessionId"]

    def navigate(self, url: str) -> None:
        if url != PORTAL_LOGIN_URL:
            raise OpsError("EASY_LOGIN_STOPPED_UNEXPECTED_PAGE")
        self.client.call("Page.navigate", {"url": url}, session=self.session, timeout=10)

    def evaluate(self, expression: str, timeout: float = 5):
        """The value, or None when the page did not answer (an open dialog, a navigation)."""
        try:
            result = self.client.call("Runtime.evaluate", {"expression": expression, "returnByValue": True},
                                      session=self.session, timeout=timeout)
        except OpsError:
            return None
        if not result or "exceptionDetails" in result:
            return None
        return (result.get("result") or {}).get("value")


def choose_target(targets: list[dict]) -> tuple[Optional[dict], Optional[str]]:
    """The page to start from, or a reason not to start. An open verification page is a login a
    person (or an earlier attempt) is already in: never touched."""
    kinds = [(page_kind(t.get("url", "")), t) for t in targets]
    if any(kind == "sso_mfa" for kind, _ in kinds):
        return None, "EASY_LOGIN_MFA_ALREADY_OPEN"
    for wanted in ("sso_view", "portal_login"):
        for kind, target in kinds:
            if kind == wanted:
                return target, None
    return None, "EASY_LOGIN_NO_LOGIN_PAGE"


def request_target(targets: list[dict], *, mail_host: str, mail_tab: bool, portal_wait: bool,
                   mail_wait: bool) -> tuple[Optional[dict], str]:
    """Where the owner's request starts: (page, "here") on a login page to use as it is; (page,
    "reset") for the Portal's tab, sent back to the Portal's login page first; (None, "open") when
    the Portal has no tab at all; or (None, REASON). `mail_tab`: the Dooray tab lives in this
    browser too (unified mode), so a lone SSO page is the Portal's only while the Dooray tab is open.
    `portal_wait` / `mail_wait`: the watchdog's login latch / the Radar's DOORAY_AUTH_REQUIRED."""
    from .ops_browser import role_of
    roles = {"portal": [], "sso": [], "dooray": []}
    for target in targets:
        role = role_of(target.get("url", ""), mail_host)
        if role in roles:
            roles[role].append(target)
    portal, sso, dooray = roles["portal"], roles["sso"], roles["dooray"]
    portal_login = any(page_kind(t.get("url", "")) == "portal_login" for t in portal)
    if not (sso or portal_login or portal_wait or mail_wait):
        return None, "EASY_LOGIN_NOT_NEEDED"
    if len(sso) == 1 and not portal and (dooray or not mail_tab):
        # The Portal's login on an SSO page, perhaps a verification page that expired unanswered
        # (2026-10-31) or a stale login page: start it afresh from the Portal's login page.
        return sso[0], "reset"
    if (len(sso) == 1 and len(portal) == 1 and mail_tab and not dooray
            and page_kind(sso[0].get("url", "")) == "sso_view"):
        return sso[0], "here"       # Dooray's own SSO login page, as the automatic attempt takes it
    if len(portal) == 1 and not sso and (portal_login or portal_wait):
        return portal[0], ("here" if portal_login else "reset")
    if not portal and not sso and portal_wait:
        return None, "open"
    return None, "EASY_LOGIN_STOPPED_TABS_UNCLEAR"


def attempt(local: Path, port: int, *, notifier, targets, cdp, now=time.time, sleep=time.sleep,
            clock=time.monotonic, requested: bool = False, mail_host: str = "", mail_tab: bool = True,
            portal_wait: bool = False, mail_wait: bool = False) -> str:
    """One bounded attempt. Returns a reason code; the code itself never leaves this function
    except inside the Telegram message. `requested`: the owner asked for it (request_gate,
    request_target), whose other arguments describe the browser for that case."""
    local = Path(local)
    is_on, expected = enabled(local)
    if not is_on:
        return "EASY_LOGIN_DISABLED"
    if notifier is None:
        return "EASY_LOGIN_NO_PUSH"
    state = normalize(read_json(local / STATE, {}), now(), last_success(local))
    blocked = request_gate(state, now()) if requested else gate(state, now())
    if blocked:
        atomic_json(local / STATE, state)
        return blocked
    try:
        pages = targets(port)
    except OpsError:
        return "EASY_LOGIN_BROWSER_UNAVAILABLE"
    if requested:
        target, how = request_target(pages, mail_host=mail_host, mail_tab=mail_tab, portal_wait=portal_wait,
                                     mail_wait=mail_wait)
        if target is None and how != "open":
            return how
        # A code still waiting is replaced: the owner asked for a new one.
        state["requests"].append(now())
        state["last_sent"] = None
    else:
        target, reason = choose_target(pages)
        if target is None:
            return reason
        how = "here"
        state["attempts"].append(now())
    # The attempt counts from here, whatever happens next.
    atomic_json(local / STATE, state)
    probe_js = PROBE % json.dumps(expected)
    try:
        with cdp(port) as client:
            last_kind = None
            if how == "open":
                created = client.call("Target.createTarget", {"url": PORTAL_LOGIN_URL, "background": True})
                if not (created or {}).get("targetId"):
                    return "EASY_LOGIN_BROWSER_UNAVAILABLE"
                target, last_kind = {"id": created["targetId"], "url": ""}, ""
            page = Page(client, target["id"])
            if how == "reset":
                page.navigate(PORTAL_LOGIN_URL)
                last_kind = page_kind(target.get("url", ""))    # wait until the page has left it
            for _ in range(MAX_STEPS):
                probe = _wait_for_next_page(page, probe_js, last_kind, sleep=sleep, clock=clock)
                if probe is None:
                    return "EASY_LOGIN_STOPPED_UNRESPONSIVE" if last_kind is None else "EASY_LOGIN_STOPPED_NO_PROGRESS"
                action = decide(probe)
                if action[0] == "stop":
                    return action[1]
                if action[0] == "code":
                    result = notifier.send(message(action[1], action[2]), markup=request_markup("🔁 새 승인 번호 받기"))
                    if result != "PUSH_SENT":
                        return "EASY_LOGIN_PUSH_FAILED"
                    state["last_sent"] = now()
                    atomic_json(local / STATE, state)
                    return "EASY_LOGIN_CODE_SENT"
                selector = action[1]
                if selector not in CLICKABLE:
                    return "EASY_LOGIN_STOPPED_UNEXPECTED_PAGE"
                last_kind = page_kind(f"https://{probe['host']}{probe['path']}")
                page.evaluate(f"(() => {{ const e = document.querySelector({json.dumps(selector)}); "
                              f"if (e) e.click(); return !!e; }})()")
    except OpsError:
        return "EASY_LOGIN_BROWSER_UNAVAILABLE"
    return "EASY_LOGIN_STOPPED_NO_PROGRESS"


def _wait_for_next_page(page, probe_js, last_kind, *, sleep, clock):
    """The probe of the page once it is no longer `last_kind` (the first call takes the current
    page), or None if nothing answered or nothing moved within STEP_WAIT_SECONDS."""
    deadline = clock() + STEP_WAIT_SECONDS
    seen_at = {}
    while True:
        probe = page.evaluate(probe_js)
        if isinstance(probe, dict):
            kind = page_kind(f"https://{probe.get('host', '')}{probe.get('path', '')}")
            first = seen_at.setdefault(kind, clock())
            # Both SSO pages fill in after load: Remember ID writes the ID field, and the
            # verification page renders its digits. Give each a moment before judging it.
            if kind == "sso_view":
                settled = probe.get("id_filled") or clock() - first >= ID_SETTLE_SECONDS
            elif kind == "sso_mfa":
                settled = len(probe.get("digits") or []) >= 2
            else:
                settled = True
            if (last_kind is None or kind != last_kind) and settled:
                return probe
        if clock() >= deadline:
            return None
        sleep(1)


def run_assist(root: Path, *, requested: bool = False) -> int:
    """The `easy-login` worker action: one attempt under its own lock, logged as a fixed code. The
    watchdog launches it; `requested` (`easy-login --requested`) is the owner's request from
    Telegram (launch_request), whose outcome the owner is told even when no code was sent."""
    from .cdp_lite import LoopbackCdp
    from .notify import local_notifier
    from .ops_browser import dooray_host, page_targets, read_mode, slot_for
    from .portal_list_state import ListStateError, poller_lock

    local = Path(root).resolve() / ".local"
    log = SafeLog(local / LOG)
    notifier = None
    try:
        notifier = local_notifier(local)
        if requested:
            log("EASY_LOGIN_REQUESTED")
            where = dict(mail_host=dooray_host(local / "dooray-ui.json"), mail_tab=read_mode(local) == "unified",
                         **login_waits(local))
        else:
            where = {}
        with poller_lock(local / LOCK):
            code = attempt(local, slot_for(root, "portal").port, notifier=notifier,
                           targets=page_targets, cdp=LoopbackCdp, requested=requested, **where)
    except ListStateError:
        code = "EASY_LOGIN_BUSY"
    except OpsError:
        code = "EASY_LOGIN_BROWSER_UNAVAILABLE"
    log(code)
    log.close()
    if requested and code != "EASY_LOGIN_CODE_SENT" and notifier is not None:
        text, markup = outcome(code)
        notifier.send(text, markup=markup)
    print(code)
    return 0 if code == "EASY_LOGIN_CODE_SENT" else 1


def launch_request(root: Path):
    """The owner's request from Telegram (the radar's bot or the ops agent): one attempt at once, in
    its own process, so the bot never waits on a page."""
    import subprocess
    import sys
    root = Path(root).resolve()
    return subprocess.Popen([sys.executable, str(root / "scripts/windows/ggongbab_workers.py"), "easy-login", "--requested"],
                            cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True)
