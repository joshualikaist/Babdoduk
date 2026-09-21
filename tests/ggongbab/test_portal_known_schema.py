"""Pinned DevTools schema: synthetic responses only, no browser or Dooray writes."""
import json
from contextlib import nullcontext
from copy import deepcopy
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, urlparse

import pytest
import portal_web_agent as agent
import ggongbab.portal_known_schema as known
from ggongbab.portal_contract import PortalContract, ID_KEYS, TITLE_KEYS, BODY_KEYS
from ggongbab.portal_discovery import notice_date, notice_timestamp
from ggongbab.portal_diagnostics import Diagnostics, capture_response
from ggongbab.portal_fetch import fetch_detail, fetch_list, iter_notices
from ggongbab.portal_queue import PortalQueue
from ggongbab.web.exit_codes import UiContractError
from ggongbab.ingest_marker import portal_external_key
from .test_portal_agent import Response, TITLE, BODY, args, install
from .test_portal_post import fixture as post_fixture

BASE = "https://" + known.KNOWN_HOST


def row(identifier="test-notice-a", board="test-board-a", public="Y", stamp="2026.09.20 13:07:30", title=TITLE):
    return {"pstNo": identifier, "pstTtl": title, "regDt": stamp, "boardNo": board,
            "publicYn": public, "loginId": "example-user", "writerEmail": "example@example.invalid"}


def listing(index, rows=None):
    return {"data": rows if rows is not None else [row()], "page": {
        "pageIndex": index, "recordCountPerPage": 10, "totalPage": 5600, "totalRecord": 56000}}


def detail(r, **changes):
    return {**r, "pstCn": BODY, **changes}


def detail_response(r, **changes):
    from urllib.parse import urlencode
    response = Response(detail(r, **changes))
    response.url = BASE + known.KNOWN_LIST_PATH + "/" + str(r["pstNo"]) + "?" + urlencode({
        "boardNo": r["boardNo"], "boardNos": "", "menuNo": "21"})
    response.request = SimpleNamespace(method="GET", resource_type="xhr")
    return response


def reviewed_contract():
    # Hypothetical future side-effect review used only to exercise runtime gates.
    c = known.known_contract()
    c.known_schema_verified = c.detail_side_effect_reviewed = c.verified = True
    c.potential_view_side_effect = False
    c.detail_id_hashes = [portal_external_key("a"), portal_external_key("b")]
    c.detail_verified_count = 2
    return c


def session(monkeypatch, first=None, second=None, responses=None):
    a, b = row(), row("test-notice-b", "test-board-b", stamp="2026.09.19 10:00:00")
    request = Mock()
    request.get.side_effect = [Response(first or listing(1, [a])), Response(second or listing(2, [b]))]
    page = Mock()
    page.url = BASE + "/"
    page.context.request = request
    callbacks = {}
    pending = list(responses if responses is not None else [detail_response(a), detail_response(b)])
    def pump(_):
        if pending:
            callbacks["response"](pending.pop(0))
    page.wait_for_timeout = pump
    context = SimpleNamespace(pages=[page], on=lambda e, cb: callbacks.update({e: cb}),
                              remove_listener=lambda e, cb: callbacks.pop(e))
    ticks = iter(range(10000))
    monkeypatch.setattr(known, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    return SimpleNamespace(context=context), request, callbacks


@pytest.mark.parametrize("value,expected", [
    ("2026.09.20 13:07:30", date(2026, 9, 20)), ("2026.09.20", date(2026, 9, 20)),
    ("2026-09-20", date(2026, 9, 20)), ("2026-09-20T23:30:00Z", date(2026, 9, 21)),
    ("2026.13.20 13:07:30", None), ("bad", None),
])
def test_known_and_iso_dates(value, expected):
    assert notice_date(value) == expected
    if value == "2026.09.20 13:07:30":
        assert notice_timestamp(value).utcoffset().total_seconds() == 9 * 3600


def test_pinned_shape_and_canonical_keys():
    c = known.known_contract()
    assert c.list_path == "/wz/api/board/recents" and c.detail_path == "/wz/api/board/recents/{id}"
    assert (c.list_array_path, c.list_id_key, c.list_title_key, c.list_date_key) == ("data", "pstNo", "pstTtl", "regDt")
    assert (c.detail_id_path, c.detail_body_path) == ("pstNo", "pstCn")
    assert "pstno" in ID_KEYS and "pstttl" in TITLE_KEYS and "pstcn" in BODY_KEYS
    assert known.pinned_shape_valid(c)


@pytest.mark.parametrize("field,value", [("pstNo", True), ("pstNo", ""), ("pstTtl", ""),
                                        ("boardNo", False), ("boardNo", None), ("regDt", "bad"),
                                        ("publicYn", None)])
def test_list_row_validation_fail_closed(field, value):
    data = listing(1)
    data["data"][0][field] = value
    with pytest.raises(UiContractError):
        known.validate_list(data, 1)


@pytest.mark.parametrize("field,value", [("pageIndex", 2), ("pageIndex", True),
                                        ("recordCountPerPage", 100), ("totalPage", "2"), ("totalRecord", None)])
def test_page_metadata_strict(field, value):
    data = listing(1)
    data["page"][field] = value
    with pytest.raises(UiContractError):
        known.validate_list(data, 1)


@pytest.mark.parametrize("payload", [{}, {"data": {}, "page": {}}, {"data": [], "page": []}])
def test_list_root_array_and_page_required(payload):
    with pytest.raises(UiContractError):
        known.validate_list(payload, 1)


def test_duplicate_ids_within_page_rejected():
    with pytest.raises(UiContractError):
        known.validate_list(listing(1, [row(), row()]), 1)


def test_calibration_requests_exact_two_pages_without_account_and_only_passive_details(monkeypatch):
    browser, request, callbacks = session(monkeypatch)
    c = known.calibrate(browser, known.known_contract(), lambda _: None, seconds=5)
    assert c.known_schema_verified and c.detail_verified_count == 2 and c.list_date_descending
    assert not c.verified and c.potential_view_side_effect and not callbacks
    urls = [call.args[0] for call in request.get.call_args_list]
    assert len(urls) == 2
    for index, url in enumerate(urls, 1):
        parsed = urlparse(url)
        query = parse_qs(parsed.query, keep_blank_values=True)
        assert parsed.path == known.KNOWN_LIST_PATH
        assert query["pageIndex"] == [str(index)] and query["recordCountPerPage"] == ["10"]
        assert query["boardVO.fnctnStng.secretUseYn"] == ["N"]
        assert "loginId" not in query


def test_omitted_account_failure_does_not_retry_with_account(monkeypatch):
    browser, request, _ = session(monkeypatch)
    request.get.side_effect = [Response({}, status=403)]
    with pytest.raises(UiContractError, match="LOGIN_ID_RUNTIME_REQUIRED"):
        known.calibrate(browser, known.known_contract(), lambda _: None, seconds=5)
    assert request.get.call_count == 1
    assert "loginId" not in request.get.call_args.args[0]


@pytest.mark.parametrize("first_stamps,second_stamps", [
    (["2026.09.19", "2026.09.20"], ["2026.09.18"]),
    (["2026.09.20"], ["2026.09.21"]),
    (["2026.09.20 10:00:00", "2026.09.20 11:00:00"], ["2026.09.19"]),
])
def test_unsorted_dates_disable_cutoff(monkeypatch, first_stamps, second_stamps):
    rows = [row(f"id-{i}", stamp=s) for i, s in enumerate(first_stamps + second_stamps)]
    first = listing(1, rows[:len(first_stamps)])
    second = listing(2, rows[len(first_stamps):])
    browser, _, _ = session(monkeypatch, first, second, [detail_response(r) for r in rows[:2]])
    c = known.calibrate(browser, known.known_contract(), lambda _: None, seconds=5)
    assert c.known_schema_verified and not c.list_date_descending


@pytest.mark.parametrize("board", [None, "", True, [], {}])
def test_invalid_row_board_fails_before_request(board):
    c, request = reviewed_contract(), Mock()
    r = row(board=board)
    with pytest.raises(UiContractError):
        fetch_detail(request, c, r["pstNo"], r)
    request.get.assert_not_called()


def test_each_detail_uses_its_own_board_and_static_query():
    c, request = reviewed_contract(), Mock()
    a, b = row(), row("test-notice-b", "test-board-b")
    request.get.side_effect = [Response(detail(a)), Response(detail(b))]
    for r in (a, b):
        assert fetch_detail(request, c, r["pstNo"], r) == BODY
    for call, r in zip(request.get.call_args_list, (a, b)):
        query = parse_qs(urlparse(call.args[0]).query, keep_blank_values=True)
        assert query == {"boardNo": [r["boardNo"]], "boardNos": [""], "menuNo": ["21"]}
    assert c.detail_query == known.DETAIL_QUERY


@pytest.mark.parametrize("mapping", [{"boardNo": "loginId"}, {"loginId": "loginId"}, {}, {"boardNo": "boardNo", "writer": "writerName"}])
def test_arbitrary_row_mapping_rejected(mapping):
    c, request = reviewed_contract(), Mock()
    c.detail_query_from_row = mapping
    with pytest.raises(UiContractError):
        fetch_detail(request, c, row()["pstNo"], row())
    request.get.assert_not_called()


@pytest.mark.parametrize("changes", [{"pstNo": "wrong"}, {"boardNo": "wrong"}, {"pstCn": ""}, {"publicYn": "N"}])
def test_detail_response_must_match_request_and_public_gate(changes):
    c, request, r = reviewed_contract(), Mock(), row()
    request.get.return_value = Response(detail(r, **changes))
    with pytest.raises(UiContractError):
        fetch_detail(request, c, r["pstNo"], r)


def test_same_detail_twice_not_sufficient(monkeypatch):
    browser, _, _ = session(monkeypatch, responses=[detail_response(row()), detail_response(row())])
    c = known.known_contract()
    with pytest.raises(UiContractError, match="TWO_DISTINCT"):
        known.calibrate(browser, c, lambda _: None, seconds=4)
    assert c.detail_verified_count == 1 and not c.known_schema_verified


def test_observed_board_query_mismatch_fails():
    r = row()
    response = detail_response(r)
    response.url = response.url.replace("test-board-a", "other-board")
    with pytest.raises(UiContractError, match="BOARD_QUERY"):
        known.observe_detail(response, {r["pstNo"]: r}, known.known_contract())


def test_counter_observed_but_not_proven_side_effect_and_no_replay(monkeypatch, tmp_path, capsys):
    a, b = row(), row("test-notice-b", "test-board-b", stamp="2026.09.19")
    browser, request, _ = session(monkeypatch, responses=[detail_response(a, inqCnt=12), detail_response(b, inqCnt=15)])
    monkeypatch.setattr(agent, "open_session", lambda *_: nullcontext(browser))
    monkeypatch.setattr(agent, "CONTRACT_FILE", tmp_path / "portal-ui.json")
    monkeypatch.setattr(agent, "LOG_FILE", tmp_path / "log")
    assert agent.cmd_calibrate_known(args()) == 20
    c = PortalContract.load(agent.CONTRACT_FILE)
    assert c.view_counter_observed and c.known_schema_verified and not c.verified
    assert c.potential_view_side_effect and not c.detail_ready()
    output = capsys.readouterr().out + agent.CONTRACT_FILE.read_text(encoding="utf-8")
    for private in ("loginId", "example-user", "PRIVATE-TITLE", "PRIVATE-BODY", "test-notice-a", "test-board-a"):
        assert private not in output
    assert "CALIBRATION BLOCKED" in output and "potential view counter field observed: yes" in output
    writer = Mock(side_effect=AssertionError("writer forbidden"))
    monkeypatch.setattr(agent, "TaskWriter", writer)
    for dry in (True, False):
        options = args()
        options.dry_run = dry
        with pytest.raises(UiContractError, match="view-count"):
            agent.cmd_run(options)
    assert request.get.call_count == 2
    writer.assert_not_called()


def test_no_counter_in_response_still_does_not_prove_no_side_effect(monkeypatch):
    browser, _, _ = session(monkeypatch)
    c = known.calibrate(browser, known.known_contract(), lambda _: None, seconds=5)
    assert not c.view_counter_observed and c.potential_view_side_effect and not c.verified


def test_public_gate_and_prefilter_precede_detail_and_dry_run_does_not_mutate(monkeypatch, tmp_path, capsys):
    c, request = reviewed_contract(), Mock()
    public, private, irrelevant = row(), row("private", public="N"), row("irrelevant", title="비밀번호 변경 안내")
    request.get.side_effect = [Response(listing(1, [public, private, irrelevant])), Response(detail(public)), Response(listing(2, []))]
    state = install(monkeypatch, tmp_path, request, c)
    state.write_bytes(b'{"notices": {}}\n')
    before = state.read_bytes()
    writer = Mock(side_effect=AssertionError("writer forbidden"))
    monkeypatch.setattr(agent, "TaskWriter", writer)
    monkeypatch.setattr(PortalQueue, "record", Mock(side_effect=AssertionError("record forbidden")))
    monkeypatch.setattr(PortalQueue, "save", Mock(side_effect=AssertionError("save forbidden")))
    assert agent.cmd_run(args()) == 0
    assert state.read_bytes() == before
    writer.assert_not_called()
    assert request.get.call_count == 3
    assert "candidates: 1" in capsys.readouterr().out


def test_missing_public_flag_fails_before_detail(monkeypatch, tmp_path):
    c, request, r = reviewed_contract(), Mock(), row()
    del r["publicYn"]
    request.get.return_value = Response(listing(1, [r]))
    install(monkeypatch, tmp_path, request, c)
    with pytest.raises(UiContractError):
        agent.cmd_run(args())
    assert request.get.call_count == 1


@pytest.mark.parametrize("limit", ["max_pages", "max_items"])
def test_bounds_preserved(limit):
    c, request = reviewed_contract(), Mock()
    request.get.return_value = Response(listing(1, [row(), row("other")]))
    rows = list(iter_notices(request, c, **{limit: 1}))
    assert len(rows) == (1 if limit == "max_items" else 2)
    assert request.get.call_count == 1


def test_duplicate_only_page_stops_and_page_index_mismatch_fails():
    c, request = reviewed_contract(), Mock()
    request.get.side_effect = [Response(listing(1)), Response(listing(2))]
    assert len(list(iter_notices(request, c))) == 1
    assert request.get.call_count == 2
    request.get.side_effect = [Response(listing(1)), Response(listing(1))]
    with pytest.raises(UiContractError, match="PAGE_INDEX"):
        list(iter_notices(request, c))


def test_verified_oldest_date_cutoff():
    c, request = reviewed_contract(), Mock()
    c.list_date_descending = True
    request.get.return_value = Response(listing(1, [row(stamp="2026.09.19")]))
    assert len(list(iter_notices(request, c, date_from=date(2026, 9, 20)))) == 1
    assert request.get.call_count == 1


def test_generic_discovery_and_calibration_cannot_overwrite_known(monkeypatch, tmp_path):
    for name in ("CONTRACT_FILE", "DISCOVERY_FILE", "DEBUG_FILE", "LOG_FILE"):
        monkeypatch.setattr(agent, name, tmp_path / name)
    monkeypatch.setattr(agent, "LOCAL_DIR", tmp_path)
    reviewed_contract().save(agent.CONTRACT_FILE)
    before = agent.CONTRACT_FILE.read_bytes()
    rows, d = post_fixture()
    agent.write_discovery(rows, d)
    assert agent.CONTRACT_FILE.read_bytes() == before
    assert agent.cmd_calibrate(args()) == 20
    assert agent.CONTRACT_FILE.read_bytes() == before


def test_generic_diagnostics_redacts_account_key_and_value():
    from .test_portal_diagnostics import response
    d = Diagnostics()
    r = response(url=BASE + "/api/notices?loginId=example-user")
    captured = capture_response(r, known.KNOWN_HOST, d)
    from ggongbab.portal_discovery import build_discovery
    output = json.dumps(build_discovery([captured], BASE + "/", d))
    assert "loginId" not in output and "example-user" not in output


def test_privacy_payload_projection_for_queue(monkeypatch, tmp_path):
    c, request, r = reviewed_contract(), Mock(), row()
    request.get.side_effect = [Response(listing(1, [r])), Response(detail(r)), Response(listing(2, []))]
    install(monkeypatch, tmp_path, request, c)
    writer = Mock()
    writer.create_portal_task.return_value = "synthetic-created-task"
    monkeypatch.setattr(agent, "TaskWriter", lambda _: writer)
    monkeypatch.setattr(agent, "load_settings", lambda: object())
    options = args()
    options.dry_run = False
    assert agent.cmd_run(options) == 0
    payload = writer.create_portal_task.call_args.args[0]
    serialized = json.dumps(vars(payload))
    assert all(value not in serialized for value in ("loginId", "example-user", "example@example.invalid", "test-board-a", "test-notice-a"))
    assert payload.title == TITLE and payload.body == BODY
    assert payload.source_created_at == "2026-09-20T13:07:30+09:00"


def test_known_query_rejects_extra_fields_before_request():
    c, request = reviewed_contract(), Mock()
    with pytest.raises(UiContractError):
        fetch_list(request, c, {**known.LIST_QUERY, "loginId": "example-user"}, {})
    request.get.assert_not_called()


def test_known_dry_run_creates_no_state_file(monkeypatch, tmp_path):
    c, request, r = reviewed_contract(), Mock(), row()
    request.get.side_effect = [Response(listing(1, [r])), Response(detail(r)), Response(listing(2, []))]
    state = install(monkeypatch, tmp_path, request, c)
    monkeypatch.setattr(agent, "TaskWriter", Mock(side_effect=AssertionError("writer forbidden")))
    assert agent.cmd_run(args()) == 0
    assert not state.exists()


def test_known_cli_dispatch_avoids_generic_discovery(monkeypatch):
    known_command = Mock(return_value=20)
    monkeypatch.setattr(agent, "cmd_calibrate_known", known_command)
    monkeypatch.setattr(agent, "cmd_discover", Mock(side_effect=AssertionError("generic forbidden")))
    assert agent.main(["--calibrate-known", "--cdp"]) == 20
    known_command.assert_called_once()


@pytest.mark.parametrize("change", ["method", "endpoint", "host"])
def test_passive_observer_ignores_non_exact_detail_endpoints(change):
    r = row()
    response = detail_response(r)
    if change == "method":
        response.request.method = "POST"
    elif change == "endpoint":
        response.url = response.url.replace("/board/recents/", "/admin/codes/")
    else:
        response.url = response.url.replace(known.KNOWN_HOST, "other.kaist.ac.kr")
    c = known.known_contract()
    assert not known.observe_detail(response, {r["pstNo"]: r}, c)
    assert c.detail_verified_count == 0
