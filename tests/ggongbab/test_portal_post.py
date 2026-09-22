"""POST discovery/replay tests. All transports and notice values are synthetic."""
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import urlencode

import pytest
import portal_web_agent as agent
from ggongbab.portal_contract import PortalContract, contract_from_discovery
from ggongbab.portal_diagnostics import Diagnostics, capture_response
from ggongbab.portal_discovery import build_discovery
from ggongbab.portal_fetch import fetch_detail, iter_notices
from ggongbab.portal_post import body_template
from ggongbab.web.exit_codes import UiContractError
from .test_portal_agent import BASE, HOST, BODY, TITLE, Response, notice, listing, install, args

IDS = ("90000123", "90000456")


def call(path, payload, *, body=None, encoding="json", method=None, diagnostics=None):
    method = method or ("POST" if body is not None else "GET")
    response = Response(payload)
    response.url = BASE + path
    req = SimpleNamespace(method=method, resource_type="xhr")
    req.header_value = Mock(return_value="application/json" if encoding == "json" else "application/x-www-form-urlencoded")
    req.post_data = json.dumps(body) if encoding == "json" else urlencode(body or {})
    response.request = req
    return capture_response(response, HOST, diagnostics or Diagnostics())


def payload(identifier):
    return {"result": {"notice": {"id": identifier, "body": BODY}}}


def fixture(*, list_post=True, encoding="json", nested=False, static=None, pagination=False, diagnostics=None):
    d = diagnostics or Diagnostics()
    list_body = {"pageNo": 0} if pagination else {}
    first = call("/api/notices", listing([notice(IDS[0]), notice(IDS[1])]),
                 body=list_body if list_post else None, diagnostics=d)
    rows = [first]
    if pagination:
        rows.append(call("/api/notices", listing([notice("90000789"), notice("90000890")]),
                         body={"pageNo": 1}, diagnostics=d))
    for identifier in IDS:
        body = {"request": {"nttId": identifier}} if nested else {"nttId": identifier}
        body.update(static or {})
        rows.append(call("/api/detail", payload(identifier), body=body, encoding=encoding, diagnostics=d))
    return rows, d


def make_contract(**kwargs):
    rows, d = fixture(**kwargs)
    report = build_discovery(rows, BASE + "/", d)
    c = contract_from_discovery(report)
    assert c and c.list_ready() and c.detail_ready(), report["reasons"]
    c.verified = True
    return c, report


@pytest.mark.parametrize("encoding", ["json", "form"])
@pytest.mark.parametrize("list_post", [True, False])
def test_json_form_request_body_correlation_and_per_endpoint_methods(encoding, list_post):
    c, report = make_contract(encoding=encoding, list_post=list_post)
    assert c.list_method == ("POST" if list_post else "GET")
    assert c.detail_method == "POST" and c.detail_body_type == encoding
    assert c.detail_request_id_path == "nttId" and c.detail_id_path == "result.notice.id"
    assert c.detail_body == {"nttId": "{id}"}
    assert report["diagnostics"]["counts"]["correlated via POST body"] == 2
    assert report["diagnostics"]["counts"]["correlated via URL"] == 0
    assert c.detail_verified_count == 2


@pytest.mark.parametrize("nested,encoding", [(False, "json"), (True, "json"), (False, "form")])
def test_exact_id_injection_and_transport(nested, encoding):
    c, _ = make_contract(nested=nested, encoding=encoding)
    request = Mock()
    request.post.return_value = Response(payload("another-id"))
    before = deepcopy(c.detail_body)
    assert fetch_detail(request, c, "another-id") == BODY
    fields = request.post.call_args.kwargs["data" if encoding == "json" else "form"]
    assert fields == ({"request": {"nttId": "another-id"}} if nested else {"nttId": "another-id"})
    assert c.detail_body == before
    request.get.assert_not_called()


@pytest.mark.parametrize("repeat", [False, True])
def test_two_distinct_post_details_required(repeat):
    rows, d = fixture()
    rows.pop()
    if repeat:
        rows.append(deepcopy(rows[-1]))
    report = build_discovery(rows, BASE + "/", d)
    assert not report["detailReplayable"]
    assert "NOT_ENOUGH_DISTINCT_DETAILS" in report["reasons"]
    assert report["diagnostics"]["counts"]["correlated distinct ids"] == 1


def test_uncorrelated_codes_get_loses_to_post_notice_list():
    rows, d = fixture()
    rows.insert(0, call("/wz/api/admin/codes", listing([notice("codeA"), notice("codeB")]), diagnostics=d))
    report = build_discovery(rows, BASE + "/", d)
    assert report["contract"]["list_path"] == "/api/notices"
    assert report["diagnostics"]["safe"]["selectedList"]["method"] == "POST"


def test_localization_response_does_not_correlate():
    rows, d = fixture()
    rows = rows[:1] + [call("/api/messages", {"content": "localized text"}, body={"nttId": IDS[0]}, diagnostics=d)]
    report = build_discovery(rows, BASE + "/", d)
    assert "LIST_DETAIL_ID_NOT_CORRELATED" in report["reasons"]
    assert report["contract"] is None


def test_static_body_fields_need_explicit_approval_and_stay_out_of_reports(monkeypatch, tmp_path, capsys):
    rows, d = fixture(static={"boardId": "NOTICE"})
    rejected = build_discovery(rows, BASE + "/", d)
    assert not rejected["detailReplayable"]
    assert "NOTICE" not in json.dumps(rejected)
    for name in ("DISCOVERY_FILE", "DEBUG_FILE", "CONTRACT_FILE", "LOG_FILE"):
        monkeypatch.setattr(agent, name, tmp_path / name)
    monkeypatch.setattr(agent, "LOCAL_DIR", tmp_path)
    report = agent.write_discovery(rows, d, approve_post=["detail:boardId"])
    agent.log_discovery(report)
    assert report["detailReplayable"]
    contract = PortalContract.load(agent.CONTRACT_FILE)
    assert contract.detail_body["boardId"] == "NOTICE" and not contract.verified
    assert agent.cmd_calibrate(args()) == 0
    assert PortalContract.load(agent.CONTRACT_FILE).verified
    public = agent.DISCOVERY_FILE.read_text() + agent.DEBUG_FILE.read_text() + capsys.readouterr().out
    for secret in (*IDS, "NOTICE", "PRIVATE-TITLE", "PRIVATE-BODY"):
        assert secret not in public
    assert "boardId" in public


@pytest.mark.parametrize("value", ["private@example.com", "Bearer-abc", "a" * 100, "abcdef1234567890"])
def test_credential_shaped_static_value_rejected_even_with_approval(value):
    rows, d = fixture(static={"boardId": value})
    report = build_discovery(rows, BASE + "/", d, approve_post=["detail:boardId"])
    assert not report["detailReplayable"]
    assert value not in json.dumps(report)


def test_static_value_changes_rejected_even_when_key_approved():
    rows, d = fixture(static={"boardId": "NOTICE"})
    rows[-1]["_request_body"]["boardId"] = "OTHER"
    report = build_discovery(rows, BASE + "/", d, approve_post=["detail:boardId"])
    assert not report["detailReplayable"]


def test_sensitive_keys_redacted_and_dynamic_keys_omitted():
    d = Diagnostics()
    row = call("/api/detail", payload(IDS[0]), body={"nttId": IDS[0], "authToken": "RAW-TOKEN",
                                                    "user@example.com": "PRIVATE-VALUE"}, diagnostics=d)
    safe = json.dumps(d.export())
    assert "<sensitive>" in safe and "nttId" in safe
    for value in (IDS[0], "authToken", "RAW-TOKEN", "user@example.com", "PRIVATE-VALUE"):
        assert value not in safe
    assert row["_body_type"] == "json"
    assert body_template([row, deepcopy(row)], id_path="nttId", approved=["authToken"]) is None


def test_sensitive_body_field_does_not_hide_id_evidence_but_blocks_replay():
    rows, d = fixture(static={"authToken": "PRIVATE-TOKEN"})
    report = build_discovery(rows, BASE + "/", d, approve_post=["detail:authToken"])
    assert report["diagnostics"]["counts"]["correlated via POST body"] == 2
    assert not report["detailReplayable"]
    assert "PRIVATE-TOKEN" not in json.dumps(report)


def test_observed_post_method_and_evidence_required():
    c, _ = make_contract()
    c.detail_post_evidence = []
    request = Mock()
    with pytest.raises(UiContractError):
        fetch_detail(request, c, IDS[0])
    request.post.assert_not_called()
    # Changing an old GET method cannot accidentally opt into POST.
    from .test_portal_agent import contract
    old = contract()
    old.detail_method = "POST"
    assert not old.detail_ready()


def test_post_list_body_pagination_is_observed_and_replayed():
    c, report = make_contract(pagination=True)
    assert c.pagination == "page" and c.pagination_location == "body" and c.list_page_param == "pageNo"
    assert report["diagnostics"]["safe"]["postPaginationCandidates"] == [{"path": "pageNo", "numericMonotonic": True}]
    request = Mock()
    request.post.side_effect = [Response(listing([notice("one"), notice("two")])), Response(listing([]))]
    # Copy arguments since requests receive a mutable body which advances between pages.
    bodies = []
    def post(*_, **kwargs):
        bodies.append(deepcopy(kwargs["data"]))
        return Response(listing([notice("one"), notice("two")]) if len(bodies) == 1 else listing([]))
    request.post.side_effect = post
    assert len(list(iter_notices(request, c))) == 2
    assert bodies == [{"pageNo": 0}, {"pageNo": 1}]
    assert c.list_body == {"pageNo": 0}


def test_post_list_single_page_parameter_not_authorized():
    rows, d = fixture(pagination=True)
    del rows[1]
    report = build_discovery(rows, BASE + "/", d)
    assert not report["listReplayable"] and "PAGINATION_NOT_VERIFIED" in report["reasons"]


def test_date_range_pair_is_filter_not_pagination():
    rows, d = fixture(pagination=True)
    rows[0]["_request_body"] = {"bgngDt": "2026-09-01", "endDt": "2026-09-20"}
    rows[1]["_request_body"] = {"bgngDt": "2026-09-02", "endDt": "2026-09-21"}
    report = build_discovery(rows, BASE + "/", d, approve_post=["list:bgngDt", "list:endDt"])
    assert not report["paginationVerified"]
    assert not report["diagnostics"]["safe"].get("postPaginationCandidates")
    assert set(report["diagnostics"]["safe"]["postFilterPaths"]) == {"bgngDt", "endDt"}


def test_unapproved_static_list_field_blocks_list_replay():
    rows, d = fixture()
    rows[0]["_request_body"] = {"boardId": "NOTICE"}
    report = build_discovery(rows, BASE + "/", d)
    assert not report["listReplayable"]
    assert "NOTICE" not in json.dumps(report)


def test_dry_run_post_replay_performs_zero_dooray_writes(monkeypatch, tmp_path):
    c, _ = make_contract()
    request = Mock()
    request.post.side_effect = [Response(listing([notice(IDS[0])])), Response(payload(IDS[0]))]
    state = install(monkeypatch, tmp_path, request, c)
    writer = Mock(side_effect=AssertionError("Dooray writer forbidden"))
    monkeypatch.setattr(agent, "TaskWriter", writer)
    assert agent.cmd_run(args()) == 0
    writer.assert_not_called()
    assert not state.exists()


def test_wrong_body_field_never_receives_identifier():
    rows, d = fixture(static={"boardId": "NOTICE"})
    c = contract_from_discovery(build_discovery(rows, BASE + "/", d, approve_post=["detail:boardId"]))
    request = Mock()
    request.post.return_value = Response(payload("new-id"))
    fetch_detail(request, c, "new-id")
    assert request.post.call_args.kwargs["data"] == {"nttId": "new-id", "boardId": "NOTICE"}


@pytest.mark.parametrize("mismatch", ["request", "response", "endpoint"])
def test_distinct_ids_with_incompatible_shapes_not_authorized(mismatch):
    rows, d = fixture()
    if mismatch == "request":
        rows[-1]["_request_body"] = {"otherId": IDS[1]}
    elif mismatch == "response":
        rows[-1]["_payload"] = {"different": {"id": IDS[1], "body": BODY}}
    else:
        rows[-1]["_url"] = BASE + "/api/other"
    report = build_discovery(rows, BASE + "/", d)
    assert not report["detailReplayable"]


def test_integer_identifier_type_preserved():
    rows, d = fixture()
    for row in rows[1:]:
        row["_request_body"]["nttId"] = int(row["_request_body"]["nttId"])
    c = contract_from_discovery(build_discovery(rows, BASE + "/", d))
    request = Mock()
    request.post.return_value = Response(payload("42"))
    fetch_detail(request, c, "42")
    assert request.post.call_args.kwargs["data"] == {"nttId": 42}


def test_post_list_get_details_keep_methods_independent():
    rows, d = fixture()
    rows = rows[:1] + [call("/api/detail/" + identifier, payload(identifier), diagnostics=d) for identifier in IDS]
    report = build_discovery(rows, BASE + "/", d)
    c = contract_from_discovery(report)
    assert c.list_method == "POST" and c.detail_method == "GET" and c.detail_ready()
    assert report["diagnostics"]["counts"]["correlated POST endpoints"] == 1


def test_form_list_pagination_replays_form_with_observed_string_types():
    rows, d = fixture(pagination=True)
    for row in rows[:2]:
        row["_body_type"] = "form"
        row["_request_body"]["pageNo"] = str(row["_request_body"]["pageNo"])
    c = contract_from_discovery(build_discovery(rows, BASE + "/", d))
    request = Mock()
    request.post.return_value = Response(listing([]))
    assert list(iter_notices(request, c)) == []
    assert request.post.call_args.kwargs["form"] == {"pageNo": "0"}
    assert "data" not in request.post.call_args.kwargs


@pytest.mark.parametrize("encoding,raw", [("multipart/form-data", "secret file"),
                                         ("application/json", '{"nttId":"one","nttId":"two"}'),
                                         ("application/x-www-form-urlencoded", "nttId=one&nttId=two"),
                                         ("application/json", "not-json")])
def test_unsupported_or_ambiguous_request_body_cannot_authorize(encoding, raw):
    d = Diagnostics()
    req = SimpleNamespace(method="POST", resource_type="xhr", header_value=lambda _: encoding, post_data=raw)
    response = Response(payload(IDS[0]))
    response.url, response.request = BASE + "/api/detail", req
    row = capture_response(response, HOST, d)
    assert row["_body_type"] == "" and row["_request_body"] is None
    assert d.rejected["POST body unsupported"] == 1
    assert raw not in json.dumps(d.export())


def test_body_cursor_progression_uses_response_link_only():
    rows, d = fixture(pagination=True)
    rows[0]["_request_body"] = {"cursor": ""}
    rows[0]["_payload"]["result"]["nextCursor"] = "PRIVATE-CURSOR"
    rows[1]["_request_body"] = {"cursor": "PRIVATE-CURSOR"}
    report = build_discovery(rows, BASE + "/", d)
    c = contract_from_discovery(report)
    assert c.pagination == "cursor" and c.cursor_path == "result.nextCursor"
    assert c.list_body == {"cursor": ""}
    assert "PRIVATE-CURSOR" not in json.dumps(report)


def test_repeated_approved_static_list_field_persistable_only_after_evidence():
    rows, d = fixture()
    rows[0]["_request_body"] = {"boardId": "NOTICE"}
    rows.insert(1, deepcopy(rows[0]))
    report = build_discovery(rows, BASE + "/", d, approve_post=["list:boardId"])
    assert report["listReplayable"] and report["detailReplayable"]
    assert report["contract"]["list_body"] == {"boardId": "NOTICE"}
