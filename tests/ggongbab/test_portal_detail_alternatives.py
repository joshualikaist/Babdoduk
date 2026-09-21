"""Passive synthetic responses; never execute live discovery or Portal requests."""
import json
from contextlib import contextmanager, nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import portal_web_agent as agent
from ggongbab import portal_detail_alternatives as alt
from ggongbab.portal_known_schema import known_contract, KNOWN_HOST, KNOWN_LIST_PATH
from ggongbab.web import resident
from ggongbab.web.exit_codes import AuthRequired, UiContractError
from ggongbab.web.ui_contract import UiContract

BASE = "https://" + KNOWN_HOST
ID = "private-notice-8844"
TEXT = "PRIVATE-NOTICE-BODY"
PAGE = object()


def response(path="/wz/api/board/content", *, payload=None, html=None, method="GET", status=200, resource="fetch", page=PAGE):
    r = Mock()
    r.url = BASE + path
    r.status = status
    r.request = SimpleNamespace(method=method, resource_type=resource, frame=SimpleNamespace(page=page))
    r.json.return_value = payload if payload is not None else {"data": {"pstNo": ID, "pstCn": TEXT}}
    if html is not None:
        r.json.side_effect = ValueError("Not JSON PRIVATE")
        r.text.return_value = html
    return r


def anchor(*, identifier=ID, public="Y", page=PAGE):
    return response(KNOWN_LIST_PATH + "/" + identifier, page=page,
                    payload={"pstNo": identifier, "publicYn": public, "pstCn": TEXT, "inqCnt": 123})


def observer():
    return alt.AlternativeObserver(clock=lambda: 100)


@pytest.mark.parametrize("before", [True, False])
def test_json_candidate_correlates_before_or_after_manual_detail_response(before):
    o = observer()
    sequence = [response(), anchor()] if before else [anchor(), response()]
    for r in sequence:
        o.capture(r)
    report = o.report()
    assert report["JSON candidates"] == 1 and report["exact known-detail endpoint seen"]
    candidate = report["candidates"][0]
    assert candidate["body-like field path"] == "data.pstCn"
    assert candidate["id-like field path"] == "data.pstNo"
    assert candidate["clicked-id correlated"] and not candidate["view-counter field present"]
    assert len(report["candidates"]) == 1  # known endpoint is never a candidate


@pytest.mark.parametrize("path", [
    "/thumb/notice", "/image/notice", "/wz/api/admin/codes", "/api/collegePlan",
    "/localization/messages", "/i18n/ko", "/assets/ui-bundle", "/analytics/content",
    "/api/view-count", "/api/readCount", "/api/increaseCount", "/api/markRead",
    "/api/content?action=incrementViewCount", "/api/content?viewCount=1",
])
def test_excluded_endpoints_never_read_or_reported(path):
    o = observer()
    o.capture(anchor())
    r = response(path)
    o.capture(r)
    assert not o.report()["candidates"]
    r.json.assert_not_called()
    r.text.assert_not_called()


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
def test_mutating_methods_never_read_or_reported(method):
    o = observer()
    o.capture(anchor())
    r = response(method=method)
    o.capture(r)
    assert not o.report()["candidates"]
    r.json.assert_not_called()


@pytest.mark.parametrize("case", ["subdomain", "external", "status", "resource", "tab", "identifier", "private", "missing-public"])
def test_scope_status_and_click_identity_fail_closed(case):
    o = observer()
    base = anchor()
    r = response()
    if case == "subdomain":
        r.url = r.url.replace(KNOWN_HOST, "api.portal.kaist.ac.kr")
    elif case == "external":
        r.url = r.url.replace(KNOWN_HOST, KNOWN_HOST + ".attacker.test")
    elif case == "status":
        r.status = 404
    elif case == "resource":
        r.request.resource_type = "image"
    elif case == "tab":
        r.request.frame.page = object()
    elif case == "identifier":
        r.json.return_value["data"]["pstNo"] = "different"
    elif case == "private":
        base = anchor(public="N")
    else:
        base.json.return_value.pop("publicYn")
    o.capture(base)
    o.capture(r)
    assert not o.report()["candidates"]


def test_time_window_does_not_associate_unrelated_later_requests():
    times = iter([100, 200])
    o = alt.AlternativeObserver(clock=lambda: next(times))
    o.capture(anchor())
    o.capture(response())
    assert not o.report()["candidates"]


def test_document_with_explicit_notice_container_and_hidden_id():
    o = observer()
    o.capture(anchor())
    markup = f'<input name="pstNo" value="{ID}"><div id="pstCn"><p>{TEXT}</p></div>'
    o.capture(response("/board/document", html=markup, resource="document"))
    report = o.report()
    assert report["document candidates"] == 1
    assert report["candidates"][0]["id-like field path"] == "html.input.pstNo"
    assert TEXT not in json.dumps(report) and ID not in json.dumps(report)


def test_document_embedded_json_is_parsed_without_js_execution():
    o = observer()
    o.capture(anchor())
    data = json.dumps({"notice": {"pstNo": ID, "pstCn": TEXT}})
    o.capture(response("/board/document", html=f'<script type="application/json">{data}</script>', resource="document"))
    assert o.report()["document candidates"] == 1


def test_generic_shell_and_localization_payload_are_not_body_evidence():
    o = observer()
    o.capture(anchor())
    o.capture(response("/board/document?pstNo=" + ID, html="<main><h1>UI title</h1><p>UI text</p></main>", resource="document"))
    o.capture(response(payload={"content": "UI text", "locale": "ko"}))
    assert not o.report()["candidates"]


def test_request_bound_body_does_not_emit_query_values():
    o = observer()
    o.capture(anchor())
    o.capture(response("/api/board/content?pstNo=" + ID + "&loginId=example-user&token=PRIVATE-TOKEN",
                       payload={"pstCn": TEXT}))
    report = o.report()
    assert report["JSON candidates"] == 1
    blob = "\n".join(alt.report_lines(report))
    assert all(s not in blob for s in (ID, TEXT, "example-user", "PRIVATE-TOKEN", "loginId", "token="))
    assert "request.query.pstNo" in blob


def test_opaque_path_segments_and_payload_keys_cannot_leak_identifiers():
    o = observer()
    o.capture(anchor())
    o.capture(response("/api/example-user/PRIVATE-TITLE/" + ID,
                       payload={"privateParent": {"pstNo": ID, "pstCn": TEXT}}))
    blob = json.dumps(o.report())
    assert o.report()["JSON candidates"] == 1
    assert all(s not in blob for s in (ID, TEXT, "example-user", "PRIVATE-TITLE", "privateParent"))
    assert "{id}" in blob and "{segment}" in blob and "{key}" in blob


def test_view_counter_is_flagged_not_an_approval():
    o = observer()
    o.capture(anchor())
    o.capture(response(payload={"pstNo": ID, "pstCn": TEXT, "inqCnt": 555}))
    assert o.report()["candidates"][0]["view-counter field present"]
    lines = "\n".join(alt.report_lines(o.report()))
    assert "no safe alternative observed" in lines and "555" not in lines
    assert "Automatic detail replay remains blocked" in lines


def test_no_candidate_is_an_explicit_result():
    o = observer()
    o.capture(anchor())
    assert "no safe alternative observed" in alt.report_lines(o.report())


def test_attachment_only_session_does_not_start_browser(monkeypatch, tmp_path):
    monkeypatch.setattr(resident, "is_running", lambda _: None)
    start = Mock(side_effect=AssertionError("must not start"))
    monkeypatch.setattr(resident, "start_chrome", start)
    with pytest.raises(AuthRequired):
        with resident.resident_session(tmp_path, UiContract(), attach_only=True):
            pass
    start.assert_not_called()


def test_attach_only_does_not_navigate_or_create_tabs(monkeypatch, tmp_path):
    page = Mock()
    page.url = BASE + "/"
    page.is_closed.return_value = False
    page.frames = []
    context = Mock(pages=[page])
    browser = Mock(contexts=[context])
    @contextmanager
    def playwright():
        yield SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=lambda *_a, **_kw: browser))
    monkeypatch.setattr(resident, "_playwright", lambda: playwright)
    monkeypatch.setattr(resident, "is_running", lambda _: {"Browser": "Chrome"})
    with resident.resident_session(tmp_path, UiContract(), start_url=BASE, attach_only=True, log=lambda _: None):
        pass
    page.goto.assert_not_called()
    context.new_page.assert_not_called()
    browser.new_context.assert_not_called()


def test_cli_does_not_write_contract_queue_or_discovery(monkeypatch, tmp_path, capsys):
    for name in ("CONTRACT_FILE", "STATE_FILE", "DISCOVERY_FILE", "DEBUG_FILE", "LOG_FILE"):
        monkeypatch.setattr(agent, name, tmp_path / name)
    monkeypatch.setattr(agent, "LOCAL_DIR", tmp_path)
    c = known_contract()
    c.save(agent.CONTRACT_FILE)
    agent.STATE_FILE.write_bytes(b'{"notices": {}}\n')
    before = {p: p.read_bytes() for p in (agent.CONTRACT_FILE, agent.STATE_FILE)}
    connect = Mock(return_value=nullcontext(object()))
    monkeypatch.setattr(agent, "resident_session", connect)
    o = observer()
    o.capture(anchor())
    o.capture(response())
    monkeypatch.setattr(alt, "observe", lambda *_: o.report())
    writer = Mock(side_effect=AssertionError("writer forbidden"))
    monkeypatch.setattr(agent, "TaskWriter", writer)
    assert agent.main(["--discover-detail-alternatives", "--cdp"]) == 0
    assert connect.call_args.kwargs["attach_only"] is True
    assert connect.call_args.kwargs["start_url"] == ""
    assert all(p.read_bytes() == data for p, data in before.items())
    assert not agent.DISCOVERY_FILE.exists() and not agent.DEBUG_FILE.exists()
    assert not c.detail_side_effect_reviewed and c.potential_view_side_effect
    for mode in ("--run", "--dry-run"):
        assert agent.main([mode, "--cdp"]) == 20
    writer.assert_not_called()
    output = capsys.readouterr().out + agent.LOG_FILE.read_text()
    assert ID not in output and TEXT not in output


def test_passive_event_loop_uses_callbacks_only_and_removes_listener(monkeypatch):
    page = Mock()
    page.url = BASE
    events = [anchor(page=page), response(page=page)]
    callbacks = {}
    page.wait_for_timeout = lambda _: callbacks["response"](events.pop(0)) if events else None
    context = SimpleNamespace(pages=[page], on=lambda e, cb: callbacks.update({e: cb}),
                              remove_listener=lambda e, cb: callbacks.pop(e))
    ticks = iter(range(20))
    monkeypatch.setattr(alt, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    report = alt.observe(SimpleNamespace(context=context), lambda _: None, seconds=4)
    assert report["JSON candidates"] == 1 and not callbacks
    page.goto.assert_not_called()
    page.evaluate.assert_not_called()
