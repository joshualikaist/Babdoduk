# -*- coding: utf-8 -*-
"""Unattended agent: state, fail-closed contracts, task payload, exit codes.

Everything here runs without a browser. The parts that need a real authenticated
Dooray session (selectors, internal endpoints) are exactly the parts the agent
refuses to guess, and that refusal is what these tests pin down.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from ggongbab.config import KST
from ggongbab.web import exit_codes
from ggongbab.web.exit_codes import AuthRequired, ProjectNotFound, UiContractError
from ggongbab.web.mail_reader import MailHeader, _find_rows, _from_json_rows, parse_day, redact
from ggongbab.web.state import AgentState, digest
from ggongbab.web.task_writer import TASK_MARKER, MailPayload, TaskWriter
from ggongbab.web.ui_contract import DEFAULT_CONTRACT_FILE, UiContract, load_contract


# --- exit-code contract -------------------------------------------------------
def test_exit_codes_match_the_watchdog_contract():
    assert (exit_codes.SUCCESS, exit_codes.AUTH_REQUIRED, exit_codes.UI_CHANGED,
            exit_codes.PROJECT_NOT_FOUND, exit_codes.PIPELINE_FAILED) == (0, 10, 20, 30, 40)
    assert AuthRequired("x").code == 10
    assert UiContractError("x").code == 20
    assert ProjectNotFound("x").code == 30


# --- state file ---------------------------------------------------------------
def test_state_roundtrip_and_skip(tmp_path):
    state = AgentState.load(tmp_path / "s.json")
    assert not state.seen("mail-1")
    state.record("mail-1", "삼성전자 Tech Lunch Talk", date(2026, 9, 3), registered=True, outcome="candidate")
    state.mark_run(date(2026, 9, 19))
    state.save()

    again = AgentState.load(tmp_path / "s.json")
    assert again.seen("mail-1")
    assert not again.seen("mail-2")
    assert again.last_scanned_to == "2026-09-19"
    record = again.mails[digest("mail-1")]
    assert record.registered is True and record.received == "2026-09-03"


def test_state_holds_no_personal_information(tmp_path):
    state = AgentState.load(tmp_path / "s.json")
    state.record("<abc@kaist.ac.kr>", "삼성전자 Tech Lunch Talk", date(2026, 9, 3),
                 registered=True, outcome="candidate")
    state.save()
    blob = (tmp_path / "s.json").read_text(encoding="utf-8")
    for leak in ("kaist.ac.kr", "삼성전자", "Tech Lunch Talk", "abc@"):
        assert leak not in blob, leak
    data = json.loads(blob)
    assert set(data["mails"][0]) == {"id_hash", "subject_hash", "received", "processed_at",
                                     "registered", "outcome"}
    assert len(data["mails"][0]["id_hash"]) == 32


def test_corrupt_state_file_does_not_stop_the_agent(tmp_path):
    path = tmp_path / "s.json"
    path.write_text("{not json", encoding="utf-8")
    state = AgentState.load(path)
    assert state.mails == {} and state.last_run_at is None


def test_since_last_run_overlaps_by_a_day(tmp_path):
    state = AgentState.load(tmp_path / "s.json")
    state.last_run_at = datetime(2026, 9, 18, 12, 0, tzinfo=KST).isoformat()
    assert state.since_last_run() == date(2026, 9, 17)
    fresh = AgentState.load(tmp_path / "none.json")
    assert fresh.since_last_run(3) == (datetime.now(KST) - timedelta(days=3)).date()


def test_prune_drops_ancient_records(tmp_path):
    state = AgentState.load(tmp_path / "s.json")
    state.record("old", "s", date(2020, 1, 1), registered=False, outcome="filtered")
    state.record("new", "s", datetime.now(KST).date(), registered=False, outcome="filtered")
    assert state.prune(keep_days=30) == 1
    assert len(state.mails) == 1


# --- fail closed on an unrecorded UI ------------------------------------------
def test_shipped_contract_is_unverified_and_empty():
    """The repo must not ship guessed selectors."""
    data = json.loads(DEFAULT_CONTRACT_FILE.read_text(encoding="utf-8"))
    assert data["verified"] is False
    for key in ("mail_url", "row", "row_subject", "list_api", "logged_in_marker"):
        assert data[key] == "", key


def test_run_refuses_until_the_contract_is_recorded():
    with pytest.raises(UiContractError) as exc:
        load_contract().require_ready()
    assert "--setup" in (exc.value.hint or "")
    assert exc.value.code == 20


def test_incomplete_contract_is_rejected():
    contract = UiContract(verified=True, mail_url="https://x/mail", logged_in_marker=".app")
    with pytest.raises(UiContractError, match="incomplete"):
        contract.require_ready()


def test_json_endpoint_needs_no_selectors():
    contract = UiContract(verified=True, list_api="https://x/api/mails?page=1")
    contract.require_ready()          # must not raise


def test_local_override_wins(tmp_path):
    override = tmp_path / "dooray-ui.json"
    override.write_text(json.dumps({"verified": True, "list_api": "https://x/api"}), encoding="utf-8")
    contract = load_contract(override)
    assert contract.verified and contract.list_api == "https://x/api"


def test_login_url_detection():
    contract = UiContract()
    assert contract.looks_like_login("https://sso.kaist.ac.kr/login?next=/")
    assert contract.looks_like_login("https://idp.example/auth")
    assert not contract.looks_like_login("https://gov-dooray.com/mail/inbox")


# --- task writer: fail closed on the project ---------------------------------
class FakeWriter(TaskWriter):
    def __init__(self, settings, result=None, project_name="밥도둑-꽁밥-행사-수집함"):
        super().__init__(settings, project_name=project_name)
        self._result = result if result is not None else {"code": project_name, "state": "active"}
        self.posts: list[dict] = []

    def _request(self, method, path, body=None):
        if method == "GET":
            return {"result": self._result}
        self.posts.append({"path": path, "body": body})
        return {"result": {"id": "9001"}}


@pytest.fixture
def dooray_settings(settings):
    settings.dooray_token = "t"
    settings.dooray_project_id = "4424523215847914253"
    return settings


def test_project_verified_by_exact_name(dooray_settings):
    writer = FakeWriter(dooray_settings)
    assert writer.verify_project()["code"] == "밥도둑-꽁밥-행사-수집함"


@pytest.mark.parametrize("result", [
    {"code": "다른-프로젝트", "state": "active"},
    {"code": "밥도둑-꽁밥-행사-수집함 ", "state": "active"},   # trailing space is not a match
    {"code": "밥도둑-꽁밥-행사-수집함", "state": "archived"},
    {},
])
def test_wrong_project_is_refused(dooray_settings, result):
    writer = FakeWriter(dooray_settings, result=result)
    with pytest.raises(ProjectNotFound) as exc:
        writer.verify_project()
    assert exc.value.code == 30


def test_no_write_before_verification(dooray_settings):
    writer = FakeWriter(dooray_settings)
    with pytest.raises(ProjectNotFound, match="verify_project"):
        writer.create_task(MailPayload(mail_id="1", subject="s", body="b"))
    assert writer.posts == []


def test_mail_without_id_is_refused(dooray_settings):
    writer = FakeWriter(dooray_settings)
    writer.verify_project()
    with pytest.raises(ProjectNotFound, match="stable id"):
        writer.create_task(MailPayload(mail_id="", subject="s", body="b"))
    assert writer.posts == []


def test_task_body_is_readable_by_the_ingest_parser(dooray_settings):
    """The pipeline parses the Original Message block, so the agent must write one."""
    from ggongbab.parsers.dooray_mail import parse_original_message

    writer = FakeWriter(dooray_settings)
    writer.verify_project()
    mail = MailPayload(mail_id="m1", subject="삼성전자 Tech Lunch Talk",
                       body="9월 25일 12시 N1에서 진행합니다.\n점심 도시락을 제공합니다.",
                       received=date(2026, 9, 3))
    post_id = writer.create_task(mail)
    assert post_id == "9001" and len(writer.posts) == 1
    body = writer.posts[0]["body"]
    assert body["subject"] == "삼성전자 Tech Lunch Talk"
    parsed = parse_original_message(body["body"]["content"])
    assert parsed.found
    assert parsed.subject == "삼성전자 Tech Lunch Talk"
    assert "점심 도시락을 제공합니다" in parsed.body
    assert TASK_MARKER in body["body"]["content"]


def test_task_payload_carries_no_addresses(dooray_settings):
    writer = FakeWriter(dooray_settings)
    writer.verify_project()
    writer.create_task(MailPayload(mail_id="m1", subject="설명회", body="본문", received=date(2026, 9, 3)))
    blob = json.dumps(writer.posts[0], ensure_ascii=False)
    assert "From:" not in blob and "To:" not in blob and "Cc:" not in blob


def test_dry_run_creates_nothing(dooray_settings):
    writer = FakeWriter(dooray_settings)
    writer.verify_project()
    assert writer.create_task(MailPayload(mail_id="m1", subject="s", body="b"), dry_run=True) is None
    assert writer.posts == []


def test_selftest_subject_is_not_an_event(dooray_settings):
    """The write check must not turn into a fake ggongbab event."""
    from ggongbab.prefilter import classify

    writer = FakeWriter(dooray_settings)
    post_id = writer.selftest()
    assert post_id == "9001"
    subject = writer.posts[0]["body"]["subject"]
    assert not classify(subject, "Automated write check. Safe to delete.").candidate


# --- mail reader helpers ------------------------------------------------------
def test_discovery_urls_are_redacted():
    assert redact("https://x/api/mails?page=2&token=abc") == "https://x/api/mails?page=<v>&token=<v>"
    assert redact("https://x/u/someone@kaist.ac.kr/mail") == "https://x/u/[email]/mail"
    assert redact("https://x/api/mails") == "https://x/api/mails"


def test_json_rows_are_found_in_unknown_envelopes():
    rows = [{"id": 1, "subject": "a"}, {"id": 2, "subject": "b"}]
    for payload in (rows, {"result": rows}, {"data": {"items": rows}}, {"result": {"contents": rows}}):
        assert _find_rows(payload) == rows
    assert _find_rows({"result": {}}) == []


def test_mail_headers_from_varied_json_shapes():
    headers = _from_json_rows([
        {"id": 7, "subject": "설명회", "receivedAt": "2026-09-03T10:00:00+09:00", "unread": True},
        {"mailId": "x9", "title": "세미나", "sentAt": "2026-09-04", "isRead": True, "snippet": "요약"},
        {"subject": "no id"},
    ])
    assert [h.mail_id for h in headers] == ["7", "x9"]
    assert headers[0].received == date(2026, 9, 3) and headers[0].unread is True
    assert headers[1].unread is False and headers[1].preview == "요약"


def test_parse_day_formats():
    assert parse_day("2026-09-03T10:00:00+09:00") == date(2026, 9, 3)
    assert parse_day("2026.09.03") == date(2026, 9, 3)
    assert parse_day(1757208000) is not None
    assert parse_day("") is None and parse_day(None) is None


def test_header_filter_prefers_body_over_preview():
    header = MailHeader(mail_id="1", subject="s", preview="짧은 요약", body="전체 본문")
    assert header.text_for_filter == "전체 본문"


# --- the agent never handles credentials --------------------------------------
def _code_symbols(path: Path) -> tuple[set[str], set[str]]:
    """(identifiers, called attribute names) from real code, ignoring prose."""
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id.lower())
        elif isinstance(node, ast.Attribute):
            names.add(node.attr.lower())
        elif isinstance(node, ast.arg):
            names.add(node.arg.lower())
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            called.add(node.func.attr.lower())
    return names, called


def test_no_password_handling_anywhere_in_the_agent():
    """No code path may type, read or store a credential. Prose about it is fine."""
    from ggongbab.web import browser

    paths = [Path(browser.__file__),
             Path(__file__).resolve().parents[2] / "scripts" / "dooray_web_agent.py"]
    for path in paths:
        names, called = _code_symbols(path)
        for forbidden in ("password", "passwd", "credential", "keyring", "secret"):
            assert not any(forbidden in name for name in names), f"{path.name}: {forbidden}"
        # Playwright's text-entry calls: the agent must never fill a login form.
        for forbidden in ("fill", "press_sequentially", "set_input_files"):
            assert forbidden not in called, f"{path.name}: {forbidden}()"


def test_auth_required_is_raised_not_worked_around():
    from ggongbab.web.browser import Session

    class FakePage:
        url = "https://sso.kaist.ac.kr/login"

    session = Session(page=FakePage(), context=None, contract=UiContract(verified=True, list_api="x"))
    assert session.at_login_screen()
    with pytest.raises(AuthRequired) as exc:
        session.assert_authenticated()
    assert exc.value.code == 10 and "--setup" in (exc.value.hint or "")


# --- setup must not mistake Home for the inbox --------------------------------
class FakeResponse:
    """Minimal stand-in for a Playwright Response."""

    def __init__(self, url, payload=None, content_type="application/json",
                 status=200, resource_type="xhr", method="GET"):
        self.url = url
        self.status = status
        self._payload = payload
        self._headers = {"content-type": content_type}
        self.request = type("Req", (), {"method": method, "resource_type": resource_type})()

    def header_value(self, name):
        return self._headers.get(name.lower())

    def text(self):
        if self._payload is None:
            raise ValueError("no body")
        return json.dumps(self._payload, ensure_ascii=False)

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakePage:
    def __init__(self, landmarks=None):
        self._handlers = []
        self._landmarks = landmarks or {"repeated": [], "idAttrs": [], "title": ""}
        self.url = "https://kaist.gov-dooray.com/"
        self.reloads = 0

    def on(self, event, handler):
        self._handlers.append(handler)

    def remove_listener(self, event, handler):
        self._handlers = [h for h in self._handlers if h is not handler]

    def emit(self, response):
        for handler in list(self._handlers):
            handler(response)

    def evaluate(self, _js):
        return self._landmarks

    def wait_for_timeout(self, _ms):
        return None

    def reload(self, **_kw):
        self.reloads += 1

    @property
    def mouse(self):
        return type("M", (), {"wheel": lambda *_a, **_k: None})()


MAIL_ROWS = {"result": [
    {"id": 101, "subject": "삼성전자 Tech Lunch Talk", "receivedAt": "2026-09-03T10:00:00+09:00", "unread": True},
    {"id": 102, "subject": "연구 세미나", "receivedAt": "2026-09-04T09:00:00+09:00", "unread": False},
]}
HOME_ROWS = {"result": [{"id": 1, "name": "프로젝트", "type": "public"},
                        {"id": 2, "name": "다른 프로젝트", "type": "public"}]}


def _observer_with(page, *responses):
    from ggongbab.web.mail_reader import NetworkObserver

    observer = NetworkObserver(page)
    observer.start()
    for response in responses:
        page.emit(response)
    return observer


def test_home_page_calls_are_not_mail_list_candidates():
    """The exact bug: landing on Home must not look like the inbox."""
    page = FakePage()
    observer = _observer_with(page, FakeResponse("https://kaist.gov-dooray.com/v1/projects?page=1", HOME_ROWS))
    assert observer.list_candidates() == []


def test_inbox_call_is_recognised_with_reasons():
    page = FakePage()
    observer = _observer_with(page, FakeResponse("https://kaist.gov-dooray.com/v1/mails?page=1&size=50", MAIL_ROWS))
    observer.on_mail_screen = True
    page.emit(FakeResponse("https://kaist.gov-dooray.com/v1/mails?page=1&size=50", MAIL_ROWS))
    candidates = observer.list_candidates()
    assert len(candidates) == 1
    call = candidates[0]
    assert call["url"] == "https://kaist.gov-dooray.com/v1/mails?page=<v>&size=<v>"
    why = " ".join(call["why"])
    assert "subject-like key" in why and "date-like key" in why
    assert "called 2x" in why
    assert call["isJson"] is True


def test_detail_call_is_classified_separately():
    from ggongbab.web.mail_reader import classify_call

    call = {"contentType": "application/json", "hitCount": 1,
            "shape": {"kind": "object", "objectKeys": ["id", "subject", "body"], "longestTextLength": 4000}}
    category, why = classify_call(call)
    assert category == "mail-detail"
    assert any("body-like" in r for r in why)


def test_shape_records_key_names_but_never_values():
    from ggongbab.web.mail_reader import shape_of

    shape = shape_of(MAIL_ROWS)
    assert shape["kind"] == "rows" and shape["rowCount"] == 2
    assert "subject" in shape["rowKeys"] and "receivedAt" in shape["rowKeys"]
    blob = json.dumps(shape, ensure_ascii=False)
    assert "삼성전자" not in blob and "Tech Lunch Talk" not in blob


def test_discovery_report_holds_no_values(tmp_path):
    from ggongbab.web.mail_reader import write_discovery_report

    page = FakePage(landmarks={"repeated": [{"selector": ".mail-row", "count": 30}], "idAttrs": [], "title": "메일"})
    observer = _observer_with(page, FakeResponse(
        "https://kaist.gov-dooray.com/v1/mails?page=1&token=abc123", MAIL_ROWS))
    out = tmp_path / "discovery.json"
    row_evidence = {"repeatedContainers": 30, "mailRowGroups": [{"selector": "DIV.mail-row", "rowCount": 30}],
                    "strong": True, "groups": []}
    report = write_discovery_report(observer, row_evidence, out,
                                    page_url="https://kaist.gov-dooray.com/mail/inbox?u=someone@kaist.ac.kr",
                                    confirmed_by_user=True)
    blob = out.read_text(encoding="utf-8")
    for leak in ("삼성전자", "Tech Lunch Talk", "abc123", "someone@kaist.ac.kr"):
        assert leak not in blob, leak
    # A query value is redacted to <v>, which also swallows an address that sat there.
    assert "token=<v>" in blob and "page=<v>" in blob
    assert "u=<v>" in blob
    assert report["evidence"]["A_mailListCallObserved"] is True
    assert report["evidence"]["B_confirmedByUser"] is True
    assert report["evidence"]["C_mailRowGroups"] == 1
    assert report["observedReadStateKeys"] == ["unread"]


def test_read_state_keys_are_reported_only_when_present():
    page = FakePage()
    no_flag = {"result": [{"id": 1, "subject": "a", "receivedAt": "2026-09-03"},
                          {"id": 2, "subject": "b", "receivedAt": "2026-09-04"}]}
    observer = _observer_with(page, FakeResponse("https://x/v1/mails", no_flag))
    assert observer.observed_read_state_keys() == []
    assert observer.list_candidates(), "still a list candidate, just without a read flag"


def test_observer_ignores_non_xhr_and_unreadable_bodies():
    page = FakePage()
    observer = _observer_with(
        page,
        FakeResponse("https://x/app.js", None, content_type="application/javascript", resource_type="script"),
        FakeResponse("https://x/v1/thing", None, content_type="application/json"),
    )
    assert len(observer.calls) == 1               # the script was ignored
    only = next(iter(observer.calls.values()))
    assert only["shape"] is None                  # unreadable body left as unknown


def test_observe_reloads_to_trigger_the_list_call():
    from ggongbab.web.browser import Session
    from ggongbab.web.mail_reader import NetworkObserver, observe
    from ggongbab.web.ui_contract import UiContract

    page = FakePage()
    session = Session(page=page, context=None, contract=UiContract())
    observer = NetworkObserver(page)
    observe(session, observer, seconds=1, reload=True)
    assert page.reloads == 1 and observer.after_reload is True


def test_default_setup_url_is_the_real_tenant():
    from ggongbab.web.browser import DEFAULT_DOORAY_URL

    assert DEFAULT_DOORAY_URL == "https://kaist.gov-dooray.com/"
    assert not UiContract().looks_like_login(DEFAULT_DOORAY_URL)


def test_wait_for_login_only_proves_a_session_not_a_mailbox():
    """wait_for_login must not record any URL; that is a separate decision."""
    import inspect

    from ggongbab.web import browser

    source = inspect.getsource(browser.wait_for_login)
    assert "mail_url" not in source
    assert "save" not in source


# --- the reported production bug ----------------------------------------------
# Real report: the user reached https://kaist.gov-dooray.com/mail/systems/inbox and
# pressed Enter, but setup kept reading the launch page and saved the root URL,
# corroborated only by 25 generic repeated containers.
ROOT_URL = "https://kaist.gov-dooray.com/"
INBOX_URL = "https://kaist.gov-dooray.com/mail/systems/inbox"
LOGIN_URL = "https://sso.kaist.ac.kr/login"
HOST = "kaist.gov-dooray.com"


def generic_groups(count=25):
    """A home page: lots of repetition, no per-row dates or ids."""
    return {"groups": [{"selector": "DIV.card", "rowCount": count, "rowsWithText": count,
                        "rowsWithDate": 0, "rowsWithId": 0, "distinctIds": 0}], "title": "Dooray"}


def mail_row_groups(count=25):
    """An inbox: each row has readable text, a date/time and its own id."""
    return {"groups": [{"selector": "LI.row", "rowCount": count, "rowsWithText": count,
                        "rowsWithDate": count, "rowsWithId": count, "distinctIds": count}],
            "title": "받은메일함"}


class FakeFrame:
    def __init__(self, url, groups=None):
        self.url = url
        self._groups = groups or {"groups": [], "title": ""}
        self.gotos = 0

    def evaluate(self, _js):
        return self._groups

    def goto(self, url, **_kw):
        self.gotos += 1
        self.url = url


class FakeCtxPage:
    def __init__(self, *frames, closed=False, ready_state="interactive", text=0):
        self.frames = list(frames)
        self._closed = closed
        self._ready_state = ready_state
        self._text = text
        self.reloads = 0

    @property
    def url(self):
        return self.frames[0].url if self.frames else ""

    def evaluate(self, _js):
        return {"ready": self._ready_state, "body": True, "text": self._text}

    def is_closed(self):
        return self._closed

    def reload(self, **_kw):
        self.reloads += 1

    def wait_for_timeout(self, _ms):
        return None

    @property
    def mouse(self):
        return type("M", (), {"wheel": lambda *_a, **_k: None})()


class FakeContext:
    def __init__(self, *pages):
        self.pages = list(pages)
        self.handlers = []

    def on(self, _event, handler):
        self.handlers.append(handler)

    def remove_listener(self, _event, handler):
        self.handlers = [h for h in self.handlers if h is not handler]

    def emit(self, response):
        for handler in list(self.handlers):
            handler(response)


def test_inbox_page_is_selected_over_root():
    from ggongbab.web.page_select import select_mail_page

    context = FakeContext(FakeCtxPage(FakeFrame(ROOT_URL, generic_groups())),
                          FakeCtxPage(FakeFrame(INBOX_URL, mail_row_groups())))
    target = select_mail_page(context, HOST)
    assert target is not None and target.url == INBOX_URL
    assert target.location == INBOX_URL


def test_login_and_root_and_inbox_selects_inbox():
    from ggongbab.web.page_select import select_mail_page

    context = FakeContext(FakeCtxPage(FakeFrame(LOGIN_URL)),
                          FakeCtxPage(FakeFrame(ROOT_URL, generic_groups())),
                          FakeCtxPage(FakeFrame(INBOX_URL, mail_row_groups())))
    target = select_mail_page(context, HOST)
    assert target.url == INBOX_URL       # the other-host login page is filtered out entirely


def test_inbox_inside_a_frame_is_selected():
    """Dooray may host the mailbox in a frame of the shell page."""
    from ggongbab.web.page_select import select_mail_page

    shell = FakeCtxPage(FakeFrame(ROOT_URL, generic_groups()), FakeFrame(INBOX_URL, mail_row_groups()))
    target = select_mail_page(FakeContext(shell), HOST)
    assert target.url == INBOX_URL and target.is_main is False


def test_closed_pages_are_ignored():
    from ggongbab.web.page_select import select_mail_page

    context = FakeContext(FakeCtxPage(FakeFrame(INBOX_URL, mail_row_groups()), closed=True),
                          FakeCtxPage(FakeFrame(ROOT_URL, generic_groups())))
    assert select_mail_page(context, HOST) is None


def test_generic_repetition_is_not_mail_evidence():
    """25 elements sharing a class is not a mailbox. This is the C false positive."""
    from ggongbab.web.page_select import is_mail_row_group, summarise_rows

    summary = summarise_rows(generic_groups(25))
    assert summary["repeatedContainers"] == 25
    assert summary["strong"] is False
    assert summary["mailRowGroups"] == []
    assert not is_mail_row_group(generic_groups(25)["groups"][0])


def test_mail_row_structure_is_evidence():
    from ggongbab.web.page_select import is_mail_row_group, summarise_rows

    summary = summarise_rows(mail_row_groups(25))
    assert summary["strong"] is True and len(summary["mailRowGroups"]) == 1
    assert is_mail_row_group(mail_row_groups(8)["groups"][0])


@pytest.mark.parametrize("group,expected", [
    ({"rowCount": 4, "rowsWithText": 4, "rowsWithDate": 4, "rowsWithId": 4, "distinctIds": 4}, False),
    ({"rowCount": 20, "rowsWithText": 20, "rowsWithDate": 2, "rowsWithId": 20, "distinctIds": 20}, False),
    ({"rowCount": 20, "rowsWithText": 5, "rowsWithDate": 20, "rowsWithId": 20, "distinctIds": 20}, False),
    ({"rowCount": 20, "rowsWithText": 20, "rowsWithDate": 18, "rowsWithId": 0, "distinctIds": 0}, True),
    ({"rowCount": 20, "rowsWithText": 20, "rowsWithDate": 12, "rowsWithId": 20, "distinctIds": 20}, True),
])
def test_mail_row_thresholds(group, expected):
    from ggongbab.web.page_select import is_mail_row_group

    assert is_mail_row_group(group) is expected


def test_root_page_with_generic_repetition_is_refused(tmp_path):
    """home/root + 25 generic divs + user confirmed  ->  REFUSE, save nothing."""
    from ggongbab.web.mail_reader import NetworkObserver, write_discovery_report
    from ggongbab.web.page_select import select_mail_page, summarise_rows

    context = FakeContext(FakeCtxPage(FakeFrame(ROOT_URL, generic_groups(25))))
    assert select_mail_page(context, HOST) is None      # nothing qualifies

    observer = NetworkObserver(context)
    observer.start()
    context.emit(FakeResponse("https://kaist.gov-dooray.com/v1/projects?page=1", HOME_ROWS))
    report = write_discovery_report(observer, summarise_rows(generic_groups(25)),
                                    tmp_path / "report.json",
                                    page_url=ROOT_URL, confirmed_by_user=True)
    assert report["evidence"]["B_confirmedByUser"] is True
    assert report["evidence"]["A_mailListCallObserved"] is False
    assert report["evidence"]["C_strong"] is False
    # B alone must never be enough.
    corroborated = report["evidence"]["A_mailListCallObserved"] or report["evidence"]["C_strong"]
    assert corroborated is False


def test_observer_attaches_to_the_context_not_the_launch_page():
    """A mailbox opened in a second tab must still be observed."""
    from ggongbab.web.mail_reader import NetworkObserver

    context = FakeContext(FakeCtxPage(FakeFrame(ROOT_URL)))
    observer = NetworkObserver(context)
    observer.start()
    assert len(context.handlers) == 1
    context.emit(FakeResponse("https://kaist.gov-dooray.com/v1/mails?page=1", MAIL_ROWS))
    assert len(observer.list_candidates()) == 1
    observer.stop()
    assert context.handlers == []


def test_reload_targets_the_selected_page_not_the_launch_page():
    from ggongbab.web.browser import Session
    from ggongbab.web.mail_reader import NetworkObserver, observe
    from ggongbab.web.page_select import select_mail_page
    from ggongbab.web.ui_contract import UiContract

    launch = FakeCtxPage(FakeFrame(ROOT_URL, generic_groups()))
    inbox = FakeCtxPage(FakeFrame(INBOX_URL, mail_row_groups()))
    context = FakeContext(launch, inbox)
    target = select_mail_page(context, HOST)
    session = Session(page=launch, context=context, contract=UiContract())
    observe(session, NetworkObserver(context), seconds=1, reload=True, target=target)
    assert inbox.reloads == 1 and launch.reloads == 0


def test_frame_reload_uses_goto():
    from ggongbab.web.page_select import select_mail_page

    frame = FakeFrame(INBOX_URL, mail_row_groups())
    shell = FakeCtxPage(FakeFrame(ROOT_URL, generic_groups()), frame)
    target = select_mail_page(FakeContext(shell), HOST)
    target.reload()
    assert frame.gotos == 1 and shell.reloads == 0


def test_describe_shows_origin_and_path_only():
    from ggongbab.web.page_select import collect_targets, describe

    context = FakeContext(FakeCtxPage(FakeFrame(ROOT_URL, generic_groups())),
                          FakeCtxPage(FakeFrame(INBOX_URL + "?token=secret123", mail_row_groups())))
    lines = "\n".join(describe(collect_targets(context, HOST)))
    assert "secret123" not in lines and "?" not in lines
    assert "pages observed: 2" in lines
    assert "mailCandidate=yes" in lines and "mailCandidate=no" in lines


def test_recommended_list_api_when_exactly_one_clear_candidate():
    from ggongbab.web.mail_reader import recommend_list_api

    good = {"contentType": "application/json", "afterReload": True, "onMailScreen": True,
            "url": "https://kaist.gov-dooray.com/v1/mails?page=<v>",
            "shape": {"kind": "rows", "rowCount": 50, "rowKeys": ["id", "subject", "receivedAt"]}}
    assert recommend_list_api([good]) == "https://kaist.gov-dooray.com/v1/mails?page=<v>"
    assert recommend_list_api([good, dict(good, url="other")]) is None, "ambiguous -> report only"
    assert recommend_list_api([]) is None
    assert recommend_list_api([dict(good, afterReload=False)]) is None
    assert recommend_list_api([dict(good, shape={"kind": "rows", "rowCount": 50,
                                                 "rowKeys": ["id", "name"]})]) is None


def test_setup_overwrites_an_earlier_wrong_mail_url(tmp_path):
    """The stale root URL in .local must be replaced without hand editing."""
    path = tmp_path / "dooray-ui.json"
    path.write_text(json.dumps({"verified": False, "mail_url": ROOT_URL}), encoding="utf-8")
    contract = load_contract(path)
    assert contract.mail_url == ROOT_URL
    contract.mail_url = INBOX_URL
    contract.save(path)
    assert load_contract(path).mail_url == INBOX_URL


# --- calibration from the live discovery -------------------------------------
# Measured on the real inbox: Dooray serves its mail list WITHOUT "json" in the
# content-type, which is why the first classifier filed it under nonJsonCalls.
def _mail_page(rows, page_no=0):
    return {"totalCount": 137, "contents": rows}


def _rows(start, count, day=3, read_flags=None):
    out = []
    for i in range(count):
        out.append({"id": str(start + i), "subject": f"mail {start + i}",
                    "receivedAt": f"2026-09-{day:02d}T10:00:00+09:00",
                    "read": (read_flags[i] if read_flags else True)})
    return out


def test_non_json_content_type_is_still_sniffed():
    """The exact miss: content-type without 'json' must not hide a mail list."""
    from ggongbab.web.mail_reader import NetworkObserver

    page = FakePage()
    observer = NetworkObserver(page)
    observer.start()
    page.emit(FakeResponse("https://kaist.gov-dooray.com/v2/wapi/mails?folderName=1&page=0",
                           _mail_page(_rows(100, 3)), content_type="application/octet-stream"))
    call = next(iter(observer.calls.values()))
    assert call["isJson"] is True
    assert call["shape"]["kind"] == "rows" and call["shape"]["rowCount"] == 3
    assert len(observer.list_candidates()) == 1


def test_static_assets_are_never_sniffed():
    from ggongbab.web.mail_reader import NetworkObserver

    page = FakePage()
    observer = NetworkObserver(page)
    observer.start()
    page.emit(FakeResponse("https://x/app.js", {"a": 1}, content_type="application/javascript"))
    assert next(iter(observer.calls.values()))["shape"] is None


def test_endpoint_choice_prefers_real_mail_rows():
    from ggongbab.web.calibrate import choose_list_endpoint

    mails = {"rawUrl": "https://x/v2/wapi/mails?folderName=1&page=0&size=50", "isJson": True,
             "afterReload": True, "onMailScreen": True,
             "shape": {"kind": "rows", "rowCount": 50,
                       "rowKeys": ["id", "subject", "receivedAt", "read"]}}
    services = {"rawUrl": "https://x/v2/wapi/members/me/services", "isJson": True,
                "shape": {"kind": "rows", "rowCount": 118, "rowKeys": ["name", "use", "ipAcl"]}}
    folders = {"rawUrl": "https://x/v2/wapi/mail-folders?type=a", "isJson": True,
               "shape": {"kind": "rows", "rowCount": 8, "rowKeys": ["id", "name"]}}
    chosen = choose_list_endpoint([services, folders, mails])
    assert chosen is mails


def test_endpoint_choice_fails_closed_on_a_tie():
    from ggongbab.web.calibrate import choose_list_endpoint

    one = {"rawUrl": "https://x/a", "isJson": True,
           "shape": {"kind": "rows", "rowCount": 50, "rowKeys": ["id", "subject", "receivedAt"]}}
    two = dict(one, rawUrl="https://x/b")
    assert choose_list_endpoint([one, two]) is None


def test_endpoint_without_id_or_subject_is_rejected():
    from ggongbab.web.calibrate import choose_list_endpoint

    no_id = {"rawUrl": "https://x/a", "isJson": True,
             "shape": {"kind": "rows", "rowCount": 50, "rowKeys": ["subject", "receivedAt"]}}
    assert choose_list_endpoint([no_id]) is None


def test_query_helpers_find_real_param_names():
    from ggongbab.web.calibrate import query_param_named, set_query

    url = "https://x/v2/wapi/mails?folderName=1&preview=true&size=50&page=0&order=-receivedAt"
    assert query_param_named(url, ("page", "offset")) == "page"
    assert query_param_named(url, ("size", "limit")) == "size"
    assert query_param_named(url, ("cursor",)) == ""
    assert "page=3" in set_query(url, page=3) and "folderName=1" in set_query(url, page=3)


class FakeRequest:
    def __init__(self, pages):
        self.pages = pages
        self.urls = []

    def get(self, url, timeout=None):
        self.urls.append(url)
        from urllib.parse import parse_qsl, urlparse
        page = int(dict(parse_qsl(urlparse(url).query)).get("page", 0))
        payload = self.pages[page] if page < len(self.pages) else {"contents": []}
        return FakeResponse(url, payload, content_type="application/octet-stream")


class FakeApiPage:
    def __init__(self, pages):
        self.request = FakeRequest(pages)


def test_smoke_test_reports_without_pii(capsys):
    from ggongbab.web.calibrate import smoke_test

    page = FakeApiPage([_mail_page(_rows(100, 10, read_flags=[True] * 8 + [False] * 2))])
    result = smoke_test(page, "https://x/v2/wapi/mails?page=0")
    assert result.ok
    assert result.headers_parsed == 10 and result.unique_ids == 10 and result.dates_parsed == 10
    assert result.read_key == "read" and result.read_count == 8 and result.unread_count == 2
    text = "\n".join(result.lines())
    assert "mail 100" not in text and "subject" not in text.lower()
    assert "stable ids: 10/10" in text


def test_smoke_test_fails_closed_on_duplicate_ids():
    from ggongbab.web.calibrate import smoke_test

    dup = [{"id": "1", "subject": "a", "receivedAt": "2026-09-03T10:00:00+09:00"} for _ in range(10)]
    result = smoke_test(FakeApiPage([_mail_page(dup)]), "https://x/mails?page=0")
    assert not result.ok and any("unique" in e for e in result.errors)


def test_smoke_test_fails_closed_on_too_few_rows():
    from ggongbab.web.calibrate import smoke_test

    result = smoke_test(FakeApiPage([_mail_page(_rows(1, 2))]), "https://x/mails?page=0")
    assert not result.ok


def test_calibrate_sets_verified_only_after_a_clean_smoke_test():
    from ggongbab.web.calibrate import calibrate
    from ggongbab.web.mail_reader import NetworkObserver

    contract = UiContract(mail_url=INBOX_URL)
    observer = NetworkObserver(FakePage())
    observer.calls["k"] = {
        "rawUrl": "https://kaist.gov-dooray.com/v2/wapi/mails?folderName=1&page=0&size=50",
        "url": "https://kaist.gov-dooray.com/v2/wapi/mails?folderName=<v>&page=<v>&size=<v>",
        "isJson": True, "afterReload": True, "onMailScreen": True, "hitCount": 2,
        "shape": {"kind": "rows", "rowCount": 50, "rowKeys": ["id", "subject", "receivedAt", "read"]},
    }
    page = FakeApiPage([_mail_page(_rows(100, 10))])
    summary = calibrate(page, observer, contract, log=lambda *_a: None)
    assert summary["strategy"] == "api"
    assert contract.verified is True
    assert contract.list_page_param == "page" and contract.list_size_param == "size"
    assert contract.read_state_key == "read"
    assert "folderName=1" in contract.list_api, "the real query values are kept locally"


def test_calibrate_leaves_unverified_when_smoke_fails():
    from ggongbab.web.calibrate import calibrate
    from ggongbab.web.mail_reader import NetworkObserver

    contract = UiContract(mail_url=INBOX_URL)
    observer = NetworkObserver(FakePage())
    observer.calls["k"] = {
        "rawUrl": "https://x/v2/wapi/mails?page=0", "url": "https://x/v2/wapi/mails?page=<v>",
        "isJson": True, "afterReload": True, "onMailScreen": True, "hitCount": 2,
        "shape": {"kind": "rows", "rowCount": 50, "rowKeys": ["id", "subject", "receivedAt"]},
    }
    page = FakeApiPage([_mail_page(_rows(1, 2))])       # only 2 rows: below the floor
    calibrate(page, observer, contract, log=lambda *_a: None)
    assert contract.verified is False and contract.list_api == ""


def test_calibrate_reports_nothing_when_no_endpoint_seen():
    from ggongbab.web.calibrate import calibrate
    from ggongbab.web.mail_reader import NetworkObserver

    contract = UiContract(mail_url=INBOX_URL)
    summary = calibrate(FakeApiPage([]), NetworkObserver(FakePage()), contract, log=lambda *_a: None)
    assert summary["strategy"] == "none" and contract.verified is False


# --- paging -------------------------------------------------------------------
def _paged_session(pages, contract):
    from ggongbab.web.browser import Session

    page = FakeApiPage(pages)
    return Session(page=page, context=None, contract=contract), page


def test_paging_accumulates_unique_ids_across_pages():
    from ggongbab.web.mail_reader import list_mails

    contract = UiContract(verified=True, list_api="https://x/mails?page=0&size=50",
                          list_page_param="page")
    pages = [_mail_page(_rows(100, 50)), _mail_page(_rows(150, 50)), _mail_page(_rows(200, 50))]
    session, page = _paged_session(pages, contract)
    headers = list_mails(session, limit=120, max_pages=10)
    assert len(headers) == 120
    assert len({h.mail_id for h in headers}) == 120
    assert len(page.request.urls) >= 3


def test_paging_stops_at_the_date_cutoff():
    from ggongbab.web.mail_reader import list_mails

    contract = UiContract(verified=True, list_api="https://x/mails?page=0", list_page_param="page")
    pages = [_mail_page(_rows(100, 20, day=18)), _mail_page(_rows(200, 20, day=2))]
    session, page = _paged_session(pages, contract)
    headers = list_mails(session, limit=500, since=date(2026, 9, 10), max_pages=10)
    assert len(headers) == 40                 # the page that crossed the cutoff is still kept
    assert len(page.request.urls) == 2        # and then it stops


def test_paging_stops_when_no_new_ids_appear():
    from ggongbab.web.mail_reader import list_mails

    contract = UiContract(verified=True, list_api="https://x/mails?page=0", list_page_param="page")
    same = _mail_page(_rows(100, 10))
    session, page = _paged_session([same, same, same, same, same], contract)
    headers = list_mails(session, limit=500, max_pages=20)
    assert len(headers) == 10
    assert len(page.request.urls) <= 3, "must not spin on a repeating page"


def test_paging_without_a_page_param_reads_one_page():
    from ggongbab.web.mail_reader import list_mails

    contract = UiContract(verified=True, list_api="https://x/mails")
    session, page = _paged_session([_mail_page(_rows(100, 10))], contract)
    assert len(list_mails(session, limit=500)) == 10
    assert len(page.request.urls) == 1


def test_read_state_comes_from_the_calibrated_field():
    from ggongbab.web.mail_reader import list_mails

    contract = UiContract(verified=True, list_api="https://x/mails?page=0",
                          list_page_param="page", read_state_key="read")
    rows = _rows(100, 4, read_flags=[True, False, True, False])
    session, _page = _paged_session([_mail_page(rows)], contract)
    headers = list_mails(session, limit=10)
    assert [h.unread for h in headers] == [False, True, False, True]


# --- frame-aware DOM fallback --------------------------------------------------
class FakeDomFrame:
    """A frame holding mail rows; the top page holds none."""

    def __init__(self, url, rows):
        self.url = url
        self._rows = rows
        self.clicks = []

    def evaluate(self, _js):
        return mail_row_groups(len(self._rows))

    def wait_for_selector(self, _sel, **_kw):
        return True

    def query_selector_all(self, _sel):
        return self._rows

    def goto(self, url, **_kw):
        self.url = url


class FakeRow:
    def __init__(self, mail_id, subject, when):
        self._attrs = {"data-mail-id": mail_id}
        self._subject = subject
        self._when = when

    def get_attribute(self, name):
        return self._attrs.get(name)

    def query_selector(self, sel):
        text = {".s": self._subject, ".d": self._when}.get(sel)
        return type("El", (), {"inner_text": lambda _self, t=text: t})() if text else None

    def inner_text(self):
        return f"{self._subject} {self._when}"


def test_dom_rows_are_read_from_the_frame_not_the_top_page():
    """top page = /, mail frame = /mail/systems/inbox."""
    from ggongbab.web.browser import Session
    from ggongbab.web.mail_reader import list_mails
    from ggongbab.web.page_select import select_mail_page

    rows = [FakeRow(f"m{i}", f"설명회 {i}", "2026-09-03") for i in range(6)]
    frame = FakeDomFrame(INBOX_URL, rows)
    shell = FakeCtxPage(FakeFrame(ROOT_URL, generic_groups()), frame)
    context = FakeContext(shell)
    target = select_mail_page(context, HOST)
    assert target is not None and target.is_main is False

    contract = UiContract(verified=True, mail_url=INBOX_URL, logged_in_marker=".app",
                          row="li.row", row_subject=".s", row_date=".d", row_id_attr="data-mail-id")
    session = Session(page=shell, context=context, contract=contract)
    headers = list_mails(session, limit=10, target=target)
    assert [h.mail_id for h in headers] == [f"m{i}" for i in range(6)]
    assert headers[0].received == date(2026, 9, 3)


def test_dom_rows_without_a_stable_id_fail_closed():
    from ggongbab.web.browser import Session
    from ggongbab.web.mail_reader import list_mails
    from ggongbab.web.page_select import select_mail_page

    rows = [FakeRow(None, f"설명회 {i}", "2026-09-03") for i in range(6)]
    frame = FakeDomFrame(INBOX_URL, rows)
    context = FakeContext(FakeCtxPage(FakeFrame(ROOT_URL, generic_groups()), frame))
    target = select_mail_page(context, HOST)
    contract = UiContract(verified=True, mail_url=INBOX_URL, logged_in_marker=".app",
                          row="li.row", row_subject=".s", row_id_attr="data-mail-id")
    session = Session(page=context.pages[0], context=context, contract=contract)
    with pytest.raises(UiContractError, match="stable id"):
        list_mails(session, limit=10, target=target)


# --- session persistence -------------------------------------------------------
def test_session_restore_preference_is_written(tmp_path):
    """Measured: Dooray's auth cookie is a session cookie, so the profile must keep it."""
    from ggongbab.web.browser import ensure_session_restore

    profile = tmp_path / "profile"
    ensure_session_restore(profile)
    prefs = json.loads((profile / "Default" / "Preferences").read_text(encoding="utf-8"))
    assert prefs["session"]["restore_on_startup"] == 1
    assert prefs["profile"]["exit_type"] == "Normal"


def test_session_restore_keeps_other_preferences(tmp_path):
    from ggongbab.web.browser import ensure_session_restore

    profile = tmp_path / "profile"
    (profile / "Default").mkdir(parents=True)
    (profile / "Default" / "Preferences").write_text(
        json.dumps({"profile": {"name": "keep me"}, "other": 1}), encoding="utf-8")
    ensure_session_restore(profile)
    prefs = json.loads((profile / "Default" / "Preferences").read_text(encoding="utf-8"))
    assert prefs["other"] == 1 and prefs["profile"]["name"] == "keep me"
    assert prefs["session"]["restore_on_startup"] == 1


def test_cookie_summary_reports_names_only(tmp_path):
    import sqlite3

    from ggongbab.web.browser import dooray_cookie_summary

    db = tmp_path / "Default" / "Network" / "Cookies"
    db.parent.mkdir(parents=True)
    con = sqlite3.connect(db)
    con.execute("create table cookies (host_key text, name text, value text, is_persistent int)")
    con.execute("insert into cookies values ('.kaist.gov-dooray.com','SESSION','secret-value',0)")
    con.execute("insert into cookies values ('.kaist.gov-dooray.com','SCOUTER','x',1)")
    con.execute("insert into cookies values ('.other.com','A','y',1)")
    con.commit()
    con.close()
    summary = dooray_cookie_summary(tmp_path)
    assert summary["host"] == 2 and summary["persistent"] == 1
    assert summary["names"] == ["SCOUTER", "SESSION"]
    assert "secret-value" not in json.dumps(summary)


# --- login detection across tabs ----------------------------------------------
# Real report: --setup printed its banner and then sat there. wait_for_login held
# the launch page, which stayed parked on the identity provider while the signed-in
# app lived in another tab, so it waited out the whole timeout.
IDP_URL = "https://kaist.gov-dooray.com/idp/multi"
APP_URL = "https://kaist.gov-dooray.com/home"


class FakeLoginPage:
    """A page whose URL can change between polls, like a real redirect chain."""

    def __init__(self, *urls, ready=True, closed=False, ready_state=None,
                 text=50, frame_urls=()):
        self._urls = list(urls)
        self._ready = ready
        self._closed = closed
        self._ready_state = ready_state or ("complete" if ready else "loading")
        self._text = text if ready else 0
        self._frame_urls = list(frame_urls)
        self.url = self._urls[0]
        self.evaluations = 0

    @property
    def frames(self):
        return [type("F", (), {"url": u})() for u in [self.url] + self._frame_urls]

    def advance(self):
        if len(self._urls) > 1:
            self._urls.pop(0)
            self.url = self._urls[0]

    def is_closed(self):
        return self._closed

    def evaluate(self, _js):
        self.evaluations += 1
        return {"ready": self._ready_state, "body": bool(self._ready), "text": self._text}


class SteppingContext:
    """Advances every page one step per poll."""

    def __init__(self, *pages):
        self._pages = list(pages)

    @property
    def pages(self):
        for page in self._pages:
            page.advance()
        return list(self._pages)


def _session(context, page=None):
    from ggongbab.web.browser import Session

    return Session(page=page or (context.pages[0] if context.pages else None),
                   context=context, contract=UiContract())


def _wait(session, **kw):
    from ggongbab.web.browser import wait_for_login

    kw.setdefault("poll_seconds", 0)
    kw.setdefault("stable_polls", 2)
    kw.setdefault("timeout_seconds", 5)
    kw.setdefault("log", lambda *_a: None)
    kw.setdefault("host", HOST)
    return wait_for_login(session, **kw)


def test_case1_same_tab_redirect_chain():
    """root -> idp -> signed-in app, all in one tab."""
    page = FakeLoginPage(ROOT_URL, IDP_URL, IDP_URL, APP_URL, APP_URL, APP_URL)
    context = SteppingContext(page)
    session = _session(context, page)
    assert _wait(session) == APP_URL
    assert session.page is page


def test_case2_app_opens_in_a_second_tab():
    """The launch page stays on the identity provider; the app is elsewhere."""
    stuck = FakeLoginPage(IDP_URL)
    app = FakeLoginPage(APP_URL)
    context = SteppingContext(stuck, app)
    session = _session(context, stuck)
    assert _wait(session) == APP_URL
    assert session.page is app, "session.page must be repointed at the signed-in tab"


def test_case3_root_flash_is_not_mistaken_for_login():
    """The tenant root shows briefly before the redirect to the identity provider."""
    page = FakeLoginPage(ROOT_URL, IDP_URL, IDP_URL, IDP_URL)
    context = SteppingContext(page)
    session = _session(context, page)
    with pytest.raises(AuthRequired):
        _wait(session, stable_polls=3, timeout_seconds=1)


def test_root_alone_needs_to_hold_still():
    """A root URL that does persist is accepted, but only after several polls."""
    page = FakeLoginPage(ROOT_URL)
    context = SteppingContext(page)
    session = _session(context, page)
    assert _wait(session, stable_polls=3) == ROOT_URL


def test_closed_popup_is_ignored():
    closed = FakeLoginPage(APP_URL, closed=True)
    stuck = FakeLoginPage(IDP_URL)
    session = _session(SteppingContext(closed, stuck), stuck)
    with pytest.raises(AuthRequired):
        _wait(session, timeout_seconds=1)


def test_unrendered_page_is_ignored():
    """A document that has not painted anything is not proof of a session."""
    blank = FakeLoginPage(APP_URL, ready=False)
    session = _session(SteppingContext(blank), blank)
    with pytest.raises(AuthRequired):
        _wait(session, timeout_seconds=1)


def test_other_host_is_ignored():
    other = FakeLoginPage("https://accounts.google.com/o/oauth2")
    session = _session(SteppingContext(other), other)
    with pytest.raises(AuthRequired):
        _wait(session, timeout_seconds=1)


def test_deeper_path_wins_over_bare_root():
    root = FakeLoginPage(ROOT_URL)
    app = FakeLoginPage(APP_URL)
    session = _session(SteppingContext(root, app), root)
    assert _wait(session) == APP_URL


def test_progress_is_logged_only_when_the_state_changes():
    stuck = FakeLoginPage(IDP_URL)
    app = FakeLoginPage(APP_URL)
    lines = []
    session = _session(SteppingContext(stuck, app), stuck)
    _wait(session, log=lines.append)
    joined = "\n".join(lines)
    assert "[setup] waiting for SSO login..." in joined
    assert "authenticated Dooray page detected" in joined
    # the same message must not repeat on every poll
    assert len(lines) == len(set(lines)), lines


def test_login_logs_never_carry_query_values():
    app = FakeLoginPage(APP_URL + "?token=secret123&u=someone@kaist.ac.kr")
    lines = []
    session = _session(SteppingContext(app), app)
    _wait(session, log=lines.append)
    joined = "\n".join(lines)
    assert "secret123" not in joined and "someone@kaist.ac.kr" not in joined


def test_setup_timeout_is_short_enough_to_surface_bugs():
    from ggongbab.web.browser import SETUP_TIMEOUT_SECONDS

    assert SETUP_TIMEOUT_SECONDS <= 300


def test_wait_for_login_rereads_the_context_every_poll():
    """Guards against the regression: no fixed page reference."""
    import inspect

    from ggongbab.web import browser

    source = inspect.getsource(browser.wait_for_login)
    assert "session.context" in source
    assert "page = session.page" not in source


# --- the mail screen must not be called an identity provider ------------------
# Real report: the user was logged in and looking at /mail/systems/inbox, and the
# terminal still said "still on the identity provider".
MAIL_URL = "https://kaist.gov-dooray.com/mail/systems/inbox"


def _observe(page, host=HOST):
    from ggongbab.web.browser import observe_page

    return observe_page(page, UiContract(), host)


def test_A_mail_page_with_interactive_ready_state_is_authenticated():
    page = FakeLoginPage(MAIL_URL, ready_state="interactive")
    obs = _observe(page)
    assert obs.classification == "authenticated-mail"
    assert obs.authenticated and obs.ready == "interactive"


def test_B_mail_page_passes_even_when_the_old_strict_check_would_fail():
    """Empty body text and a non-complete readyState: the old rule rejected this."""
    page = FakeLoginPage(MAIL_URL, ready_state="interactive", text=0)
    obs = _observe(page)
    assert obs.classification == "authenticated-mail"
    session = _session(SteppingContext(page), page)
    assert _wait(session) == MAIL_URL


def test_C_mail_in_a_child_frame_selects_the_parent_page():
    page = FakeLoginPage(ROOT_URL, ready_state="interactive", text=0, frame_urls=[MAIL_URL])
    obs = _observe(page)
    assert obs.classification == "authenticated-mail-frame"
    assert obs.frame_url == MAIL_URL
    session = _session(SteppingContext(page), page)
    assert _wait(session) == ROOT_URL
    assert session.page is page


def test_D_identity_provider_still_blocks():
    page = FakeLoginPage(IDP_URL)
    assert _observe(page).classification == "identity-provider"
    session = _session(SteppingContext(page), page)
    with pytest.raises(AuthRequired):
        _wait(session, timeout_seconds=1)


def test_E_root_flash_then_idp_is_not_a_login():
    page = FakeLoginPage(ROOT_URL, IDP_URL, IDP_URL, IDP_URL)
    session = _session(SteppingContext(page), page)
    with pytest.raises(AuthRequired):
        _wait(session, stable_polls=3, timeout_seconds=1)


def test_F_log_never_claims_identity_provider_when_mail_is_visible():
    page = FakeLoginPage(MAIL_URL, ready_state="interactive")
    lines = []
    session = _session(SteppingContext(page), page)
    _wait(session, log=lines.append)
    joined = "\n".join(lines)
    assert "identity provider" not in joined.lower()
    assert "/mail/systems/inbox" in joined
    assert "classification: authenticated-mail" in joined


def test_log_shows_the_observed_path_and_ready_state():
    page = FakeLoginPage(MAIL_URL, ready_state="interactive")
    lines = []
    _wait(_session(SteppingContext(page), page), log=lines.append)
    joined = "\n".join(lines)
    assert "[setup] observed:" in joined
    assert "page: /mail/systems/inbox" in joined
    assert "readyState: interactive" in joined


def test_log_reports_the_identity_provider_only_from_a_real_url():
    page = FakeLoginPage(IDP_URL)
    lines = []
    with pytest.raises(AuthRequired):
        _wait(_session(SteppingContext(page), page), log=lines.append, timeout_seconds=1)
    joined = "\n".join(lines)
    assert "classification: identity-provider" in joined
    assert "page: /idp/multi" in joined


def test_timeout_message_says_what_was_last_seen():
    page = FakeLoginPage(IDP_URL)
    with pytest.raises(AuthRequired) as exc:
        _wait(_session(SteppingContext(page), page), timeout_seconds=1)
    assert "/idp/multi" in str(exc.value) and "identity-provider" in str(exc.value)


def test_priority_order_mail_beats_frame_beats_app_beats_root():
    from ggongbab.web.browser import observe_pages

    root = FakeLoginPage(ROOT_URL)
    app = FakeLoginPage("https://kaist.gov-dooray.com/project/1")
    framed = FakeLoginPage("https://kaist.gov-dooray.com/home", frame_urls=[MAIL_URL])
    mail = FakeLoginPage(MAIL_URL)
    ranked = observe_pages(SteppingContext(root, app, framed, mail), UiContract(), HOST)
    assert [o.classification for o in ranked] == [
        "authenticated-mail", "authenticated-mail-frame", "authenticated-app", "app-root"]


def test_unreachable_mail_page_is_not_ready():
    class Dead(FakeLoginPage):
        def evaluate(self, _js):
            raise RuntimeError("execution context destroyed")

    obs = _observe(Dead(MAIL_URL))
    assert obs.classification == "not-ready" and not obs.authenticated


def test_root_still_needs_complete_and_text():
    assert _observe(FakeLoginPage(ROOT_URL, ready_state="interactive")).classification == "not-ready"
    assert _observe(FakeLoginPage(ROOT_URL, ready_state="complete", text=0)).classification == "not-ready"
    assert _observe(FakeLoginPage(ROOT_URL, ready_state="complete", text=20)).classification == "app-root"


def test_deep_app_page_accepts_interactive():
    page = FakeLoginPage("https://kaist.gov-dooray.com/project/123", ready_state="interactive")
    assert _observe(page).classification == "authenticated-app"


def test_mail_frame_on_another_host_is_ignored():
    page = FakeLoginPage(ROOT_URL, ready_state="interactive", text=0,
                         frame_urls=["https://evil.example/mail/systems/inbox"])
    assert _observe(page).classification == "not-ready"


# --- the mailbox lives in a frame under an /idp/ shell -------------------------
# Real report: the user was reading the inbox while the terminal insisted on
# "identity-provider". observe_page returned on the login URL before it ever
# looked at the frames.
def test_A_idp_shell_with_a_mail_frame_is_authenticated():
    page = FakeLoginPage(IDP_URL, ready_state="interactive", text=0, frame_urls=[MAIL_URL])
    obs = _observe(page)
    assert obs.classification == "authenticated-mail-frame"
    assert obs.frame_url == MAIL_URL and obs.authenticated


def test_B_idp_shell_without_a_mail_frame_is_still_the_identity_provider():
    page = FakeLoginPage(IDP_URL)
    assert _observe(page).classification == "identity-provider"


def test_C_root_shell_with_a_mail_frame_is_authenticated():
    page = FakeLoginPage(ROOT_URL, ready_state="interactive", text=0, frame_urls=[MAIL_URL])
    assert _observe(page).classification == "authenticated-mail-frame"


def test_frames_are_checked_before_the_login_url():
    """Guards the ordering itself, which is what the bug was."""
    import inspect

    from ggongbab.web import browser

    source = inspect.getsource(browser.observe_page)
    assert source.index("_mail_frame_url") < source.index("looks_like_login"), \
        "frame inspection must come first"


def test_streak_key_includes_the_frame_and_classification():
    import inspect

    from ggongbab.web import browser

    source = inspect.getsource(browser.wait_for_login)
    assert "best.frame_url" in source and "best.classification" in source


# --- setup gates on the mailbox, not on a generic auth check -------------------
AGENT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "dooray_web_agent.py"


def test_D_setup_does_not_call_wait_for_login():
    source = AGENT_PATH.read_text(encoding="utf-8")
    start = source.index("def cmd_setup(")
    end = source.index("def cmd_discover(")
    assert "wait_for_login" not in source[start:end]


def test_F_setup_does_not_wait_for_enter():
    source = AGENT_PATH.read_text(encoding="utf-8")
    start = source.index("def cmd_setup(")
    end = source.index("def cmd_discover(")
    body = source[start:end]
    assert "input(" not in body and "_confirm" not in body


def test_E_setup_polls_select_mail_page_until_the_mailbox_appears():
    """The mailbox only shows up on the third poll; setup must keep looking."""
    import sys

    sys.path.insert(0, str(AGENT_PATH.parent))
    import dooray_web_agent as agent
    from ggongbab.web.browser import Session

    shell_no_frame = FakeLoginPage(IDP_URL)
    calls = {"n": 0}

    class LateContext:
        """Frames appear only after a few polls, like a user clicking [메일]."""

        def __init__(self):
            self.shell = FakeCtxPage(FakeFrame(IDP_URL, generic_groups()))

        @property
        def pages(self):
            calls["n"] += 1
            if calls["n"] >= 3 and len(self.shell.frames) == 1:
                self.shell.frames.append(FakeFrame(MAIL_URL, mail_row_groups()))
            return [self.shell]

    context = LateContext()
    session = Session(page=context.pages[0], context=context, contract=UiContract())
    target = agent.wait_for_mailbox(session, HOST, timeout_seconds=5, log=lambda *_a: None,
                                    poll_seconds=0, stable_polls=2)
    assert target is not None and target.url == MAIL_URL
    assert calls["n"] >= 3


def test_G_mailbox_must_hold_still_before_setup_accepts_it():
    import sys

    sys.path.insert(0, str(AGENT_PATH.parent))
    import dooray_web_agent as agent
    from ggongbab.web.browser import Session

    shell = FakeCtxPage(FakeFrame(ROOT_URL, generic_groups()), FakeFrame(MAIL_URL, mail_row_groups()))
    context = FakeContext(shell)
    session = Session(page=shell, context=context, contract=UiContract())
    polls = {"n": 0}

    def counting_log(*_a):
        polls["n"] += 1

    target = agent.wait_for_mailbox(session, HOST, timeout_seconds=5, log=counting_log,
                                    poll_seconds=0, stable_polls=3)
    assert target.url == MAIL_URL


def test_setup_timeout_lists_what_was_seen():
    import sys

    sys.path.insert(0, str(AGENT_PATH.parent))
    import dooray_web_agent as agent
    from ggongbab.web.browser import Session

    context = FakeContext(FakeCtxPage(FakeFrame(IDP_URL, generic_groups())))
    session = Session(page=context.pages[0], context=context, contract=UiContract())
    lines = []
    with pytest.raises(AuthRequired) as exc:
        agent.wait_for_mailbox(session, HOST, timeout_seconds=1, log=lines.append,
                               poll_seconds=0, stable_polls=2)
    joined = "\n".join(lines)
    assert "open pages:" in joined and "/idp/multi" in joined
    assert "받은메일함" in (exc.value.hint or "")


def test_H_setup_logs_carry_no_query_or_content():
    import sys

    sys.path.insert(0, str(AGENT_PATH.parent))
    import dooray_web_agent as agent
    from ggongbab.web.browser import Session

    secret_url = MAIL_URL + "?token=secret123&u=someone@kaist.ac.kr"
    shell = FakeCtxPage(FakeFrame(ROOT_URL, generic_groups()), FakeFrame(secret_url, mail_row_groups()))
    context = FakeContext(shell)
    session = Session(page=shell, context=context, contract=UiContract())
    lines = []
    agent.wait_for_mailbox(session, HOST, timeout_seconds=5, log=lines.append,
                           poll_seconds=0, stable_polls=2)
    joined = "\n".join(lines)
    assert "secret123" not in joined and "someone@kaist.ac.kr" not in joined
    assert "?" not in joined
