# -*- coding: utf-8 -*-
"""Easy Login assist (owner decision 2026-10-29, docs/PORTAL_EASY_LOGIN_ASSIST.md).
Synthetic pages behind a fake CDP client only: no browser, no SSO, no Telegram."""
from __future__ import annotations

import json
from unittest.mock import Mock

import pytest

from ggongbab import easy_login as el
from ggongbab.ops_policy import REASONS
from ggongbab.ops_storage import OpsError, atomic_json
from ggongbab.resident_ops import Files, Watchdog
import ggongbab.resident_ops as ops

NOW = 2_000_000_000.0
OWNER_ID = "synthetic-owner"
PORTAL = {"host": "portal.kaist.ac.kr", "path": "/common/login/login.do", "portal_button": True}
VIEW = {"host": "sso.kaist.ac.kr", "path": "/auth/kaist/user/login/view", "tab": "mfa", "id_filled": True,
        "id_matches": True, "easy_button": True, "error": False, "captcha": False, "digits": [], "timer": ""}
MFA = {"host": "sso.kaist.ac.kr", "path": "/auth/twofactor/mfa/login2Factor", "digits": ["6", "7"], "timer": "2:59"}
URL = {"portal": "https://portal.kaist.ac.kr/common/login/login.do",
       "view": "https://sso.kaist.ac.kr/auth/kaist/user/login/view?agt_id=kaist-prod-portal",
       "mfa": "https://sso.kaist.ac.kr/auth/twofactor/mfa/login2Factor",
       "dooray": "https://kaist.gov-dooray.com/mail/systems/inbox",
       "stuck": "https://sso.kaist.ac.kr/auth/user/login/view",          # where an expired verification ended
       "main": "https://portal.kaist.ac.kr/index.html"}
STUCK = {"host": "sso.kaist.ac.kr", "path": "/auth/user/login/view"}
BLANK = {"host": "", "path": "blank"}
DOORAY_HOST = "kaist.gov-dooray.com"


class Browser:
    """Pages in order; a click on the expected button moves to the next page. `stall` keeps the page."""

    def __init__(self, *pages, clicks_to=None, stall=False, answer=True):
        self.pages, self.index, self.clicks, self.expressions = list(pages), 0, [], []
        self.navigations, self.created = [], []
        self.clicks_to = clicks_to or {el.PORTAL_BUTTON: "portal", el.EASY_LOGIN_BUTTON: "view"}
        self.stall, self.answer, self.closed = stall, answer, False

    def __call__(self, port):
        assert port == 9224
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True

    def call(self, method, params=None, *, session=None, timeout=5):
        if method == "Target.attachToTarget":
            assert params["flatten"] is True
            return {"sessionId": "s1"}
        if method in ("Page.navigate", "Target.createTarget"):   # both lead to the next page
            if method == "Page.navigate":
                assert session == "s1"
                self.navigations.append(params["url"])
            else:
                self.created.append(params)
            self.index = min(self.index + 1, len(self.pages) - 1)
            return {"frameId": "f1", "targetId": "t-new"}
        assert method == "Runtime.evaluate" and session == "s1"
        expression = params["expression"]
        self.expressions.append(expression)
        if ".click()" in expression:
            selector = json.loads(expression.split("document.querySelector(")[1].split(");")[0])
            self.clicks.append(selector)
            if not self.stall:
                self.index = min(self.index + 1, len(self.pages) - 1)
            return {"result": {"value": True}}
        if not self.answer:
            return None
        page = self.pages[self.index]
        return {"result": {"value": page() if callable(page) else dict(page)}}


class Telegram:
    def __init__(self, result="PUSH_SENT"):
        self.result, self.messages, self.markups = result, [], []

    def send(self, text, markup=None):
        self.messages.append(text)
        self.markups.append(markup)
        return self.result


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


@pytest.fixture
def local(tmp_path):
    local = tmp_path / ".local"
    local.mkdir()
    atomic_json(local / el.CONFIG, {"enabled": True, "expected_id": OWNER_ID})
    return local


def run(local, browser, *, start="portal", telegram=None, now=NOW, extra_pages=()):
    clock = Clock()
    targets = [{"id": "t1", "url": URL[start]}, *({"id": f"x{i}", "url": URL[k]} for i, k in enumerate(extra_pages))]
    telegram = Telegram() if telegram is None else telegram
    code = el.attempt(local, 9224, notifier=telegram, targets=lambda port: targets, cdp=browser,
                      now=lambda: now, sleep=clock.sleep, clock=clock)
    return code, telegram


# --- the flow ------------------------------------------------------------------------------------
def test_two_clicks_then_the_code_goes_to_telegram_and_nowhere_else(local):
    browser = Browser(PORTAL, VIEW, MFA)
    code, telegram = run(local, browser)
    assert code == "EASY_LOGIN_CODE_SENT"
    assert browser.clicks == [el.PORTAL_BUTTON, el.EASY_LOGIN_BUTTON] and browser.closed
    (text,) = telegram.messages
    assert "67" in text and "2분 59초" in text and "거절하세요" in text
    assert telegram.markups[0]["inline_keyboard"][0][0]["callback_data"] == el.REQUEST_CALLBACK   # a new code later
    state = (local / el.STATE).read_text(encoding="utf-8")
    assert "67" not in state and OWNER_ID not in state
    assert json.loads(state)["last_sent"] == NOW and json.loads(state)["attempts"] == [NOW]


def test_only_the_probe_and_the_two_allowed_clicks_ever_run_in_the_page(local):
    browser = Browser(PORTAL, VIEW, MFA)
    run(local, browser)
    probe = el.PROBE % json.dumps(OWNER_ID)
    for expression in browser.expressions:
        if ".click()" in expression:
            assert any(json.dumps(s) in expression for s in el.CLICKABLE)
        else:
            assert expression == probe
    joined = "\n".join(browser.expressions)
    for forbidden in (".value =", ".value=", "login_pwd", "loginTab02", "#auth", "cookie", "localStorage", "fetch("):
        assert forbidden not in joined.replace("id.value || ''", "")


def test_the_owner_id_is_compared_inside_the_page_and_never_returned():
    assert "value === expected" in el.PROBE and "id_value" not in el.PROBE
    assert el.PROBE.count("return out") == 1


def test_it_can_start_on_an_open_sso_page_too(local):
    browser = Browser(VIEW, MFA)
    code, _ = run(local, browser, start="view")
    assert code == "EASY_LOGIN_CODE_SENT" and browser.clicks == [el.EASY_LOGIN_BUTTON]


def test_remember_id_gets_a_moment_to_fill_the_field(local):
    probes = iter([dict(VIEW, id_filled=False), dict(VIEW, id_filled=False)])
    browser = Browser(lambda: next(probes, dict(VIEW)), MFA)
    code, _ = run(local, browser, start="view")
    assert code == "EASY_LOGIN_CODE_SENT"


# --- it stops --------------------------------------------------------------------------------------
@pytest.mark.parametrize("page, reason", [
    (dict(VIEW, id_filled=False), "EASY_LOGIN_STOPPED_ID_EMPTY"),
    (dict(VIEW, id_matches=False), "EASY_LOGIN_STOPPED_ID_MISMATCH"),
    (dict(VIEW, tab="auth"), "EASY_LOGIN_STOPPED_NOT_EASY_LOGIN"),
    (dict(VIEW, error=True), "EASY_LOGIN_STOPPED_SSO_ERROR"),
    (dict(VIEW, captcha=True), "EASY_LOGIN_STOPPED_CAPTCHA"),
    (dict(VIEW, easy_button=False), "EASY_LOGIN_STOPPED_UNEXPECTED_PAGE"),
])
def test_a_login_page_that_is_not_exactly_right_stops_without_a_click(local, page, reason):
    browser = Browser(page)
    code, telegram = run(local, browser, start="view")
    assert code == reason and browser.clicks == [] and telegram.messages == []


@pytest.mark.parametrize("digits", [[], ["6"], ["6", "7", "8"], ["6", "x"]])
def test_a_verification_page_without_exactly_two_digits_sends_nothing(local, digits):
    browser = Browser(VIEW, dict(MFA, digits=digits))
    code, telegram = run(local, browser, start="view")
    assert code in {"EASY_LOGIN_STOPPED_UNEXPECTED_PAGE", "EASY_LOGIN_STOPPED_NO_PROGRESS"}
    assert telegram.messages == []


def test_a_click_that_leads_somewhere_else_stops(local):
    browser = Browser(PORTAL, {"host": "evil.example", "path": "/"})
    code, telegram = run(local, browser)
    assert code == "EASY_LOGIN_STOPPED_UNEXPECTED_PAGE" and telegram.messages == []


def test_a_page_that_never_moves_or_never_answers_stops(local):
    stuck = Browser(PORTAL, VIEW, stall=True)
    assert run(local, stuck)[0] == "EASY_LOGIN_STOPPED_NO_PROGRESS"
    (local / el.STATE).unlink()
    silent = Browser(PORTAL, answer=False)          # for example an alert() dialog holds the page
    assert run(local, silent)[0] == "EASY_LOGIN_STOPPED_UNRESPONSIVE" and silent.clicks == []


def test_an_open_verification_page_is_never_touched(local):
    browser = Browser(MFA)
    code, telegram = run(local, browser, start="mfa")
    assert code == "EASY_LOGIN_MFA_ALREADY_OPEN" and browser.expressions == [] and telegram.messages == []


def test_no_login_page_means_nothing_to_do_and_no_attempt_counted(local):
    browser = Browser(PORTAL)
    code, _ = run(local, browser, start="dooray")
    assert code == "EASY_LOGIN_NO_LOGIN_PAGE" and browser.expressions == []
    assert not (local / el.STATE).exists()


def test_off_without_the_owner_opt_in_or_without_telegram(local):
    browser = Browser(PORTAL, VIEW, MFA)
    clock = Clock()
    assert el.attempt(local, 9224, notifier=None, targets=lambda p: [{"id": "t", "url": URL["portal"]}],
                      cdp=browser, now=lambda: NOW, sleep=clock.sleep, clock=clock) == "EASY_LOGIN_NO_PUSH"
    atomic_json(local / el.CONFIG, {"enabled": False, "expected_id": OWNER_ID})
    assert run(local, browser)[0] == "EASY_LOGIN_DISABLED"
    (local / el.CONFIG).unlink()
    assert run(local, browser)[0] == "EASY_LOGIN_DISABLED" and browser.expressions == []


def test_a_failed_telegram_send_is_not_a_sent_code(local):
    code, _ = run(local, Browser(PORTAL, VIEW, MFA), telegram=Telegram("PUSH_TRANSPORT_FAILED"))
    assert code == "EASY_LOGIN_PUSH_FAILED"
    assert json.loads((local / el.STATE).read_text(encoding="utf-8"))["last_sent"] is None


# --- the limits ----------------------------------------------------------------------------------
def test_at_most_one_attempt_per_thirty_minutes_and_four_a_day(local):
    assert run(local, Browser(PORTAL, VIEW, MFA))[0] == "EASY_LOGIN_CODE_SENT"
    atomic_json(local / "ops-portal.json", {"last_success": NOW + 60})            # the owner approved
    assert run(local, Browser(PORTAL, VIEW, MFA), now=NOW + 600)[0] == "EASY_LOGIN_RATE_LIMITED"
    for i in range(1, 4):
        now = NOW + i * el.MIN_GAP_SECONDS
        atomic_json(local / "ops-portal.json", {"last_success": now - 1})
        assert run(local, Browser(PORTAL, VIEW, MFA), now=now)[0] == "EASY_LOGIN_CODE_SENT"
        atomic_json(local / "ops-portal.json", {"last_success": now + 60})
    assert run(local, Browser(PORTAL, VIEW, MFA), now=NOW + 4 * el.MIN_GAP_SECONDS)[0] == "EASY_LOGIN_RATE_LIMITED"
    assert run(local, Browser(PORTAL, VIEW, MFA), now=NOW + 86400 + 1)[0] == "EASY_LOGIN_CODE_SENT"


def test_two_unanswered_codes_pause_it_until_a_person_logs_in(local):
    assert run(local, Browser(PORTAL, VIEW, MFA))[0] == "EASY_LOGIN_CODE_SENT"
    later = NOW + el.MIN_GAP_SECONDS
    assert run(local, Browser(PORTAL, VIEW, MFA), now=later)[0] == "EASY_LOGIN_CODE_SENT"
    third = later + el.MIN_GAP_SECONDS
    assert run(local, Browser(PORTAL, VIEW, MFA), now=third)[0] == "EASY_LOGIN_PAUSED_UNANSWERED"
    assert el.may_start(local, third) is False
    atomic_json(local / "ops-radar.json", {"last_success": third + 5})          # a person logged in
    assert el.may_start(local, third + 10) is True


def test_a_code_still_waiting_blocks_a_second_one():
    state = el.normalize({"attempts": [NOW], "last_sent": NOW}, NOW + 60, None)
    assert el.gate(state, NOW + 60) == "EASY_LOGIN_RATE_LIMITED"


# --- the watchdog launches it ----------------------------------------------------------------------
def dog(tmp_path, *, enabled=True, now=1000.0):
    files = Files(tmp_path)
    files.set_enabled(True, 1000)
    if enabled:
        atomic_json(files.local / el.CONFIG, {"enabled": True, "expected_id": OWNER_ID})
    clock = {"t": now}
    host = Mock()
    host.inspect.return_value = ("verified", None)
    host.port = 9224
    easy = Mock(side_effect=lambda *a: Mock(poll=Mock(return_value=None)))
    wd = Watchdog(files, host=host, launch=Mock(), now=lambda: clock["t"], launch_easy=easy,
                  targets=lambda port: [{"id": "t", "url": URL["view"]}])
    wd.state.update(latched="PORTAL_LIST_AUTH_REQUIRED", resume=1000)
    wd.save()
    return wd, easy, clock, files


def test_the_watchdog_starts_one_attempt_after_the_quick_retry_had_its_chance(tmp_path):
    wd, easy, clock, files = dog(tmp_path)
    wd.tick()
    assert easy.call_count == 0                                   # the quick retry comes first
    clock["t"] += ops.QUICK_RETRY_SECONDS + 30
    wd.tick()
    assert easy.call_count == 1
    assert "EASY_LOGIN_STARTED" in (files.local / "ops-watchdog.log").read_text(encoding="utf-8")
    clock["t"] += 15
    wd.tick()
    assert easy.call_count == 1                                   # one at a time, not every tick
    wd.easy_child.poll.return_value = 1
    clock["t"] += ops.EASY_LOGIN_CHECK_SECONDS
    atomic_json(files.local / el.STATE, {"attempts": [clock["t"] - 60], "last_sent": None, "unanswered": 0})
    wd.tick()
    assert easy.call_count == 1                                   # its own 30-minute limit holds


def test_the_watchdog_never_starts_it_without_the_opt_in(tmp_path):
    wd, easy, clock, _ = dog(tmp_path, enabled=False)
    for _ in range(3):
        clock["t"] += ops.EASY_LOGIN_CHECK_SECONDS
        wd.tick()
    easy.assert_not_called()


def test_a_dooray_login_wait_also_starts_it(tmp_path):
    wd, easy, clock, files = dog(tmp_path)
    wd.state.update(latched="")
    wd.save()
    atomic_json(files.local / "ops-radar.json", {"reason": "DOORAY_AUTH_REQUIRED", "last_success": None})
    assert wd.login_needed(clock["t"]) is True
    atomic_json(files.local / "ops-radar.json", {"reason": "DOORAY_RADAR_RUNNING", "last_success": None})
    assert wd.login_needed(clock["t"]) is False


def test_every_reason_it_logs_is_a_declared_fixed_code():
    assert el.CODES | {"EASY_LOGIN_STARTED"} <= REASONS


def logged_out(tmp_path, last_success=None):
    """The worker exits at once (2026-10-29: the LIST answered a 5xx after the Portal's dawn outage)
    while the Portal tab sits on the Portal's login page."""
    wd, easy, clock, files = dog(tmp_path)
    wd.state.update(latched="", launches=1, launched_at=1000)
    wd.save()
    wd.targets = lambda port: [{"id": "t", "url": URL["portal"]}]
    row = files.runtime_state()
    row.update(started=1000, observed=clock["t"], reason="PORTAL_LIST_TRANSPORT_UNAVAILABLE", running=False,
               last_success=last_success)
    atomic_json(files.runtime, row)
    return wd, easy, clock, files


def test_a_logged_out_portal_page_becomes_a_login_wait_that_starts_it(tmp_path):
    wd, easy, clock, files = logged_out(tmp_path)
    wd.tick()
    assert wd.state["latched"] == "PORTAL_LIST_AUTH_REQUIRED"
    wd.launch.assert_not_called()                                 # no more restarts against a dead session
    clock["t"] += ops.QUICK_RETRY_SECONDS + 30
    wd.tick()
    assert files.control_state()["resume"] == 1000                # no quick retry on a login page
    assert easy.call_count == 1


def test_a_healthy_worker_is_not_stopped_by_a_stray_login_page(tmp_path):
    wd, easy, clock, files = logged_out(tmp_path, last_success=1000.0 - 30)
    wd.tick()
    assert wd.state["latched"] == ""
    easy.assert_not_called()


# --- the owner's request from Telegram (owner 2026-10-31) -------------------------------------------
def ask(local, browser, *pages, telegram=None, now=NOW, mail_tab=True, **waits):
    clock = Clock()
    targets = [{"id": f"t{i}", "url": URL[k]} for i, k in enumerate(pages)]
    telegram = Telegram() if telegram is None else telegram
    code = el.attempt(local, 9224, notifier=telegram, targets=lambda port: targets, cdp=browser, now=lambda: now,
                      sleep=clock.sleep, clock=clock, requested=True, mail_host=DOORAY_HOST, mail_tab=mail_tab,
                      **({"portal_wait": False, "mail_wait": False} | waits))
    return code, telegram


def test_on_request_an_expired_login_goes_back_to_the_portal_login_page_and_a_new_code_follows(local):
    """The live case of 2026-10-31: the code expired unanswered and the Portal's tab stayed on an SSO
    page the automatic attempt does not start from (EASY_LOGIN_NO_LOGIN_PAGE every 5 minutes)."""
    atomic_json(local / el.STATE, {"attempts": [NOW - 600], "last_sent": None, "unanswered": 2,
                                   "last_unanswered": NOW - 600})
    browser = Browser(STUCK, PORTAL, VIEW, MFA)
    code, telegram = ask(local, browser, "dooray", "stuck", portal_wait=True)
    assert code == "EASY_LOGIN_CODE_SENT"
    assert browser.navigations == [el.PORTAL_LOGIN_URL] and browser.clicks == [el.PORTAL_BUTTON, el.EASY_LOGIN_BUTTON]
    (text,), (markup,) = telegram.messages, telegram.markups
    assert "67" in text and markup == el.request_markup("🔁 새 승인 번호 받기")
    state = json.loads((local / el.STATE).read_text(encoding="utf-8"))
    assert state["requests"] == [NOW] and state["attempts"] == [NOW - 600] and state["last_sent"] == NOW
    assert state["unanswered"] == 2               # the automatic pause still waits for a real login
    assert el.may_start(local, NOW + el.MIN_GAP_SECONDS) is False


def test_on_request_only_the_probe_the_two_clicks_and_the_one_fixed_address_ever_run(local):
    browser = Browser(STUCK, PORTAL, VIEW, MFA)
    ask(local, browser, "dooray", "stuck", portal_wait=True)
    probe = el.PROBE % json.dumps(OWNER_ID)
    assert all(e == probe or any(json.dumps(s) in e for s in el.CLICKABLE) for e in browser.expressions)
    assert browser.navigations == [el.PORTAL_LOGIN_URL] and el.page_kind(el.PORTAL_LOGIN_URL) == "portal_login"
    page = el.Page.__new__(el.Page)
    page.client, page.session = Mock(), "s1"
    with pytest.raises(OpsError):
        page.navigate("https://sso.kaist.ac.kr/auth/kaist/user/login/view")
    page.client.call.assert_not_called()


def test_a_missing_portal_tab_is_opened_in_the_background_at_the_login_page(local):
    browser = Browser(BLANK, PORTAL, VIEW, MFA)
    code, _ = ask(local, browser, "dooray", portal_wait=True)
    assert code == "EASY_LOGIN_CODE_SENT"
    assert browser.created == [{"url": el.PORTAL_LOGIN_URL, "background": True}] and browser.navigations == []


@pytest.mark.parametrize("pages, extra, expected", [
    (("dooray", "stuck"), {}, ("t1", "reset")),          # the Portal's login on an expired page
    (("dooray", "mfa"), {}, ("t1", "reset")),            # an open verification page: the owner wants a new code
    (("dooray", "view"), {}, ("t1", "reset")),           # even a login page starts afresh (it may be stale)
    (("dooray", "portal"), {}, ("t1", "here")),
    (("dooray", "main"), {"portal_wait": True}, ("t1", "reset")),
    (("dooray", "main"), {}, (None, "EASY_LOGIN_NOT_NEEDED")),
    (("dooray", "main"), {"mail_wait": True}, (None, "EASY_LOGIN_STOPPED_TABS_UNCLEAR")),
    (("dooray",), {"portal_wait": True}, (None, "open")),
    (("main", "view"), {"mail_wait": True}, ("t1", "here")),   # Dooray's own SSO login page
    (("main", "stuck"), {"mail_wait": True}, (None, "EASY_LOGIN_STOPPED_TABS_UNCLEAR")),
    (("stuck", "view"), {"portal_wait": True}, (None, "EASY_LOGIN_STOPPED_TABS_UNCLEAR")),
    (("stuck",), {"portal_wait": True}, (None, "EASY_LOGIN_STOPPED_TABS_UNCLEAR")),   # whose SSO page is it?
    (("stuck",), {"portal_wait": True, "mail_tab": False}, ("t0", "reset")),          # separate browsers
])
def test_where_an_owner_request_starts(pages, extra, expected):
    targets = [{"id": f"t{i}", "url": URL[k]} for i, k in enumerate(pages)]
    options = {"portal_wait": False, "mail_wait": False, "mail_tab": True} | extra
    target, how = el.request_target(targets, mail_host=DOORAY_HOST, **options)
    assert ((target or {}).get("id"), how) == expected


def test_nothing_is_touched_when_no_login_is_needed(local):
    browser = Browser(PORTAL)
    code, telegram = ask(local, browser, "dooray", "main")
    assert code == "EASY_LOGIN_NOT_NEEDED" and browser.expressions == [] and browser.navigations == []
    assert telegram.messages == [] and not (local / el.STATE).exists()


def test_the_owners_requests_have_their_own_limits_instead_of_the_automatic_ones(local):
    for i in range(el.REQUEST_DAILY_MAX):
        now = NOW + i * el.REQUEST_GAP_SECONDS
        assert ask(local, Browser(PORTAL, VIEW, MFA), "portal", now=now)[0] == "EASY_LOGIN_CODE_SENT"
    assert ask(local, Browser(PORTAL, VIEW, MFA), "portal", now=now + 30)[0] == "EASY_LOGIN_REQUEST_TOO_SOON"
    later = now + el.REQUEST_GAP_SECONDS
    assert ask(local, Browser(PORTAL, VIEW, MFA), "portal", now=later)[0] == "EASY_LOGIN_REQUEST_DAILY_MAX"
    assert ask(local, Browser(PORTAL, VIEW, MFA), "portal", now=NOW + 86400 + 1)[0] == "EASY_LOGIN_CODE_SENT"


def test_an_owner_request_also_restarts_the_automatic_thirty_minutes(local):
    assert ask(local, Browser(PORTAL, VIEW, MFA), "portal")[0] == "EASY_LOGIN_CODE_SENT"
    atomic_json(local / "ops-portal.json", {"last_success": NOW + 60})            # the owner approved
    assert run(local, Browser(PORTAL, VIEW, MFA), now=NOW + 600)[0] == "EASY_LOGIN_RATE_LIMITED"
    assert run(local, Browser(PORTAL, VIEW, MFA), now=NOW + el.MIN_GAP_SECONDS)[0] == "EASY_LOGIN_CODE_SENT"


def test_the_owner_is_told_every_outcome_in_fixed_words():
    for code in el.CODES - {"EASY_LOGIN_CODE_SENT", "EASY_LOGIN_REQUESTED"}:
        text, markup = el.outcome(code)
        assert text and markup in (None, el.request_markup("🔑 다시 요청"))
    for quiet in ("EASY_LOGIN_NOT_NEEDED", "EASY_LOGIN_REQUEST_TOO_SOON", "EASY_LOGIN_REQUEST_DAILY_MAX"):
        assert el.outcome(quiet)[1] is None                  # pressing again would not help yet
    assert "아이디 칸이 비어" in el.outcome("EASY_LOGIN_STOPPED_ID_EMPTY")[0]


def test_a_request_reports_its_outcome_on_telegram_and_an_automatic_run_does_not(tmp_path, monkeypatch):
    from ggongbab import notify, ops_browser
    local = tmp_path / ".local"
    local.mkdir()
    atomic_json(local / el.CONFIG, {"enabled": True, "expected_id": OWNER_ID})
    telegram = Telegram()
    monkeypatch.setattr(notify, "local_notifier", lambda path: telegram)
    monkeypatch.setattr(ops_browser, "page_targets",
                        lambda port, **kw: [{"id": "d", "url": URL["dooray"]}, {"id": "p", "url": URL["main"]}])
    monkeypatch.setattr(ops_browser, "slot_for", lambda root, role: Mock(port=9224))
    monkeypatch.setattr(ops_browser, "read_mode", lambda path: "unified")
    monkeypatch.setattr(ops_browser, "dooray_host", lambda path: DOORAY_HOST)
    assert el.run_assist(tmp_path, requested=True) == 1
    assert telegram.messages == [el.OUTCOME["EASY_LOGIN_NOT_NEEDED"]] and telegram.markups == [None]
    log = (local / el.LOG).read_text(encoding="utf-8")
    assert "EASY_LOGIN_REQUESTED" in log and "EASY_LOGIN_NOT_NEEDED" in log
    assert el.run_assist(tmp_path) == 1 and len(telegram.messages) == 1      # EASY_LOGIN_NO_LOGIN_PAGE, quietly


@pytest.mark.parametrize("text, wanted", [
    ("로그인", True), ("로그인 다시 할게", True), ("다시 로그인", True), ("로그인 해줘", True), ("/login", True),
    ("로그인할게요", True), ("로그인!", True), ("Login", True), ("로그인 요청", True),
    ("로그인?", False), ("로그인 됐어?", False), ("왜 로그인 풀렸어", False), ("포털 로그인 상태 알려줘", False), ("", False),
])
def test_only_a_message_that_is_just_the_request_counts(text, wanted):
    assert el.is_request(text) is wanted


def test_the_bot_starts_a_request_on_the_button_or_on_login_and_keeps_questions_for_the_agent(tmp_path):
    from ggongbab.instagram import telegram_review as tr
    from ggongbab.instagram.radar import Config, Radar

    class RadarBot:
        chat_id = "42"

        def __init__(self):
            self.pending, self.said, self.answered = [], [], []

        def updates(self, offset, wait=25):
            out, self.pending = self.pending, []
            return out

        def events(self, updates):
            return tr.Bot("x", self.chat_id).events(updates)

        def say(self, text):
            self.said.append(text)

        def answer(self, callback, text):
            self.answered.append(text)

    local = tmp_path / ".local"
    local.mkdir()
    bot = RadarBot()
    config = Config(version="v26.0", ig_user_id="1", token="t", primary="gpt-6-luna", review="gpt-6.1-terra")
    radar = Radar(tmp_path, config=config, graph=None, judge=None, bot=bot, now=lambda: NOW, sleep=lambda s: None)
    launched = []
    radar.launch_login = lambda root: launched.append(root) or Mock(poll=Mock(return_value=None))

    def message(uid, text):
        return {"update_id": uid, "message": {"chat": {"id": 42}, "text": text}}

    def tap(uid, chat=42):
        return {"update_id": uid, "callback_query": {"id": f"c{uid}", "data": el.REQUEST_CALLBACK,
                                                      "message": {"chat": {"id": chat}}}}
    assert tr.LOGIN_CALLBACK == el.REQUEST_CALLBACK
    bot.pending = [message(1, "로그인")]
    radar.handle_updates(0)
    assert launched == [] and "꺼져 있습니다" in bot.said[-1]          # Easy Login is off on this PC
    atomic_json(local / el.CONFIG, {"enabled": True, "expected_id": OWNER_ID})
    bot.pending = [tap(2, chat=99)]                                    # another chat: ignored
    radar.handle_updates(0)
    assert launched == [] and bot.answered == []
    bot.pending = [tap(3)]
    radar.handle_updates(0)
    assert launched == [tmp_path] and bot.answered[-1].startswith("🔑")
    bot.pending = [message(4, "로그인 다시 할게")]                    # the first one still runs
    radar.handle_updates(0)
    assert len(launched) == 1 and "여는 중" in bot.said[-1]
    radar.login_child.poll.return_value = 0
    bot.pending = [message(5, "다시 로그인")]
    radar.handle_updates(0)
    assert len(launched) == 2 and not (local / tr.INBOX).exists()      # a request is not a note
    bot.pending = [message(6, "로그인 왜 풀렸어?")]
    radar.handle_updates(0)
    assert len(launched) == 2 and "왜 풀렸어" in (local / tr.INBOX).read_text(encoding="utf-8")


def test_no_automatic_resume_while_the_portal_tab_is_back_on_its_login_page(tmp_path):
    """The request's first step shows the Portal's login page after an SSO page: that is not a login."""
    wd, _, clock, _ = dog(tmp_path)
    tabs = {"now": [{"id": "d", "url": URL["dooray"]}, {"id": "s", "url": URL["stuck"]}]}
    wd.targets = lambda port: tabs["now"]
    assert wd.may_resume("verified", clock["t"]) is None and wd.sso_seen
    for step in ("portal", "view", "mfa"):
        tabs["now"] = [{"id": "d", "url": URL["dooray"]}, {"id": "s", "url": URL[step]}]
        assert wd.may_resume("verified", clock["t"]) is None
    tabs["now"] = [{"id": "d", "url": URL["dooray"]}, {"id": "s", "url": URL["main"]}]    # approved
    assert wd.may_resume("verified", clock["t"]) == "login"
