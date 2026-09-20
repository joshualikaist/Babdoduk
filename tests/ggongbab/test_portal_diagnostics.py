"""Synthetic responses only: diagnostics must not disclose or authorize values."""
import json
from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import portal_web_agent as agent
from ggongbab.portal_diagnostics import Diagnostics, capture_response
from ggongbab.portal_discovery import build_discovery, request_shape
from ggongbab.portal_contract import contract_from_discovery
from ggongbab.portal_fetch import request_json
from ggongbab.web.exit_codes import AuthRequired
from .test_portal_agent import BASE, HOST, TITLE, BODY, listing, notice, detail, observations, Response


def response(*, url=BASE + "/api/notices", method="GET", resource="xhr", mime="application/json", payload=None):
    r = Response(payload if payload is not None else listing([notice("PRIVATE-ID-A"), notice("PRIVATE-ID-B")]), content_type=mime)
    r.url = url
    r.request = SimpleNamespace(method=method, resource_type=resource)
    return r


def opened(host=BASE, resource="xhr", mime="application/json",
           ids=("PRIVATE-ID-A", "PRIVATE-ID-B")):
    """The two notice details a person opened, matching the default listing.

    Correlation is now what selects an endpoint, so a list observation on its
    own can no longer produce a contract - the interaction has to be there.
    """
    return [response(url=f"{host}/api/notices/{i}", payload=detail(i),
                     resource=resource, mime=mime) for i in ids]


def collect(responses):
    d = Diagnostics()
    rows = [row for r in responses if (row := capture_response(r, HOST, d))]
    return build_discovery(rows, BASE + "/", d), d


def test_setup_list_like_evidence_does_not_imply_replay_success():
    report, d = collect([response(url=BASE + "/api/notices?boardId=PRIVATE-BOARD")])
    assert d.counts["list-schema candidates"] == 1
    assert report["listEndpointObserved"] and not report["listReplayable"]
    assert "UNSAFE_REQUEST_SHAPE" in report["reasons"]
    page = SimpleNamespace(url=BASE, locator=lambda _: SimpleNamespace(count=lambda: 0))
    assert agent.page_authenticated(page, HOST, notice_api_observed=True)
    assert contract_from_discovery(report) is None


def test_text_plain_json_is_parsed_only_in_discovery():
    r = response(mime="text/plain")
    report, d = collect([r] + opened(mime="text/plain"))
    assert d.counts["json-parsed responses"] == 3 and report["listReplayable"]
    request = Mock()
    request.get.return_value = r
    with pytest.raises(AuthRequired):
        request_json(request, HOST, "/api/notices", {})


def test_post_observed_but_not_authorized_or_body_inspected():
    r = response(method="POST")
    report, d = collect([r])
    assert d.counts["POST responses"] == 1
    assert d.counts["observed notice-like POST candidate"] == 1
    assert d.rejected["method unsupported"] == 1
    assert report["listEndpointObserved"] and report["contract"] is None
    assert "OBSERVATION_ONLY_LIST" in report["reasons"]


@pytest.mark.parametrize("host,same,kaist,observed", [
    (HOST, 1, 1, True), ("api.portal.kaist.ac.kr", 0, 1, True),
    ("kaist.ac.kr", 0, 1, True), ("kaist.ac.kr.attacker.test", 0, 0, False),
    ("evilkaist.ac.kr", 0, 0, False),
])
def test_host_observation_scope_does_not_expand_replay(host, same, kaist, observed):
    r = response(url="https://" + host + "/api/notices")
    r.json = Mock(wraps=r.json)
    report, d = collect([r] + opened(host="https://" + host))
    assert d.counts["same-host responses"] == same * 3
    assert d.counts["kaist-host responses"] == kaist * 3
    assert d.rejected["host mismatch"] == (1 - same) * 3
    assert report["listEndpointObserved"] == observed
    if not same:
        assert report["contract"] is None
    if kaist and not same:
        assert "CROSS_ORIGIN_LIST" in report["reasons"]
    if not kaist:
        r.json.assert_not_called()


@pytest.mark.parametrize("resource,bucket", [("fetch", "xhr/fetch"), ("document", "document"), ("other", "other")])
def test_resource_types_counted_and_non_xhr_is_diagnostic_only(resource, bucket):
    report, d = collect([response(resource=resource)] + opened(resource=resource))
    assert d.counts[bucket + " responses"] == 3
    assert report["listEndpointObserved"]
    assert report["listReplayable"] == (resource == "fetch")


def test_invalid_json_count_without_exception_values():
    r = response()
    r.json = Mock(side_effect=ValueError("PRIVATE-SECRET"))
    report, d = collect([r])
    assert d.rejected["json parse failed"] == 1
    assert "NO_LIST_CANDIDATE" in report["reasons"]
    assert "PRIVATE-SECRET" not in json.dumps(report)


@pytest.mark.parametrize("query", ["token=PRIVATE", "session=PRIVATE", "auth=PRIVATE", "boardId=PRIVATE", "category=PRIVATE"])
def test_query_values_never_persist_and_no_speculative_whitelist(query):
    report, d = collect([response(url=BASE + "/api/notices?" + query)])
    assert "UNSAFE_REQUEST_SHAPE" in report["reasons"]
    assert d.rejected["unsafe query key count"] == 1
    assert d.rejected["unsafe request shape"] == 1
    assert report["contract"] is None and "PRIVATE" not in json.dumps(report)


def test_path_rejection_count():
    d = Diagnostics()
    assert request_shape(BASE + "/api/123456/notices", diagnostics=d) is None
    assert d.rejected["unsafe path component count"] == 1


def test_ambiguous_list_reason():
    """Two equally plausible arrays are no longer ranked by field names.

    Nothing was opened, so nothing correlates and neither array is chosen.
    """
    payload = {"first": [notice("one"), notice("two")], "second": [notice("three"), notice("four")]}
    report, d = collect([response(payload=payload)])
    assert d.rejected["schema ambiguous"] == 1
    assert "LIST_DETAIL_ID_NOT_CORRELATED" in report["reasons"]
    assert report["contract"] is None
    assert report["listEndpointObserved"] and report["contract"] is None


def test_multiple_list_identity_reason():
    report, d = collect([response(), response(url=BASE + "/other/notices")])
    assert "LIST_DETAIL_ID_NOT_CORRELATED" in report["reasons"]
    assert d.rejected["list detail not correlated"] == 1


def test_page_parameter_and_progression_are_separate():
    report, d = collect([response(url=BASE + "/api/notices?page=0")] + opened())
    assert report["paginationParameterObserved"] and not report["paginationVerified"]
    assert d.counts["pagination parameter observed"] == 1
    assert d.counts["pagination progression observed"] == 0
    assert "PAGINATION_NOT_VERIFIED" in report["reasons"]
    assert report["listEndpointObserved"]


def test_no_pagination_is_allowed_and_no_detail_is_reported():
    report, d = collect([response()] + opened())
    assert report["listReplayable"] and not report["paginationParameterObserved"]
    assert report["contract"]["pagination"] == "none"
    # A list nobody clicked through has no contract at all any more.
    alone, _ = collect([response()])
    assert "NO_DETAIL_CANDIDATE" in alone["reasons"]
    assert alone["contract"] is None


def test_cursor_parameter_on_second_request_is_reported():
    report = build_discovery(observations("cursor"), BASE + "/")
    assert report["paginationParameterObserved"] and report["paginationVerified"]
    assert report["diagnostics"]["counts"]["pagination parameter observed"] == 1


def test_same_id_twice_is_not_two_details():
    rows = observations()
    rows[-1] = deepcopy(rows[-2])
    report = build_discovery(rows, BASE + "/")
    assert "NOT_ENOUGH_DISTINCT_DETAILS" in report["reasons"]
    assert report["diagnostics"]["rejected"]["same id repeated"] == 1
    assert not report["detailReplayable"]


@pytest.mark.parametrize("failure,reason", [
    ("host", "CROSS_ORIGIN_DETAIL"), ("template", "MULTIPLE_DETAIL_SHAPES"),
    ("id", "DETAIL_ID_PATH_AMBIGUOUS"),
])
def test_detail_rejections_are_distinguishable(failure, reason):
    rows = observations()
    if failure == "host":
        rows[-1]["_url"] = rows[-1]["_url"].replace(HOST, "api.portal.kaist.ac.kr")
    elif failure == "template":
        rows[-1]["_url"] = rows[-1]["_url"].replace("/api/", "/other/")
    else:
        rows[-1]["_payload"]["id"] = "private-id-b"
    report = build_discovery(rows, BASE + "/")
    assert reason in report["reasons"] and not report["detailReplayable"]


def test_ambiguous_body_reason_and_count():
    ambiguous = [response(url=f"{BASE}/api/notices/{i}",
                          payload={"result": {"id": i, "body": BODY, "content": BODY}})
                 for i in ("PRIVATE-ID-A", "PRIVATE-ID-B")]
    report, d = collect([response()] + ambiguous)
    assert "DETAIL_BODY_PATH_AMBIGUOUS" in report["reasons"]
    assert d.rejected["body path ambiguous"] == 2


def test_debug_file_and_terminal_export_only_fixed_counts_and_reasons(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(agent, "LOCAL_DIR", tmp_path)
    monkeypatch.setattr(agent, "DISCOVERY_FILE", tmp_path / "discovery.json")
    monkeypatch.setattr(agent, "DEBUG_FILE", tmp_path / "debug.json")
    monkeypatch.setattr(agent, "LOG_FILE", tmp_path / "log")
    d = Diagnostics()
    r = response(url=BASE + "/api/notices?token=PRIVATE-TOKEN")
    row = capture_response(r, HOST, d)
    report = agent.write_discovery([row], d)
    agent.log_discovery(report)
    output = capsys.readouterr().out
    blob = output + agent.DEBUG_FILE.read_text() + agent.DISCOVERY_FILE.read_text()
    for value in (TITLE, BODY, "PRIVATE-ID-A", "PRIVATE-ID-B", "PRIVATE-TOKEN"):
        assert value not in blob
    debug = json.loads(agent.DEBUG_FILE.read_text())
    assert set(debug) == {"diagnostics", "reasons"}
    assert set(debug["diagnostics"]) == {"counts", "rejected", "safe"}
    for section in ("counts", "rejected"):
        assert all(type(v) is int for v in debug["diagnostics"][section].values())
    # The structural section carries names and paths, never values. This URL
    # had ?token=PRIVATE-TOKEN, so the key name itself must be redacted too.
    safe = debug["diagnostics"]["safe"]
    assert set(safe) == {"unsafeQueryKeys", "listCandidate", "paginationCandidates",
                         "staticStructuralKeys", "detailBodyCandidatePaths",
                         "bodyDisambiguatedByIdSubtree", "selectedList", "selectedDetail",
                         "rowKeys"}
    assert "token" not in json.dumps(safe)


def test_observer_callback_uses_relaxed_mime_and_detaches(monkeypatch):
    d = Diagnostics()
    callbacks = {}
    r = response(mime="text/plain")
    page = Mock()
    page.url = BASE
    page.locator.return_value.count.return_value = 0
    r.request.frame = SimpleNamespace(page=page)
    page.wait_for_timeout = lambda _: callbacks["response"](r)
    context = SimpleNamespace(pages=[page], on=lambda event, cb: callbacks.update({event: cb}),
                              remove_listener=lambda event, cb: callbacks.pop(event))
    rows = agent.observe_network(SimpleNamespace(context=context), stop_on_auth=True, diagnostics=d)
    assert len(rows) == 1 and not callbacks
    assert d.counts["json-parsed responses"] == 1


def test_discover_command_reports_candidate_and_rejection_separately(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(agent, "LOCAL_DIR", tmp_path)
    monkeypatch.setattr(agent, "DISCOVERY_FILE", tmp_path / "discovery.json")
    monkeypatch.setattr(agent, "DEBUG_FILE", tmp_path / "debug.json")
    monkeypatch.setattr(agent, "LOG_FILE", tmp_path / "log")
    monkeypatch.setattr(agent, "open_session", lambda *_: nullcontext(object()))
    def observe(_session, seconds, diagnostics):
        seen = [response(url=BASE + "/api/notices?page=0")] + opened()
        return [capture_response(r, HOST, diagnostics) for r in seen]
    monkeypatch.setattr(agent, "observe_network", observe)
    assert agent.cmd_discover(SimpleNamespace()) == 20
    output = capsys.readouterr().out
    assert "list endpoint: candidate found" in output
    assert "list replay contract: rejected" in output
    assert "PAGINATION_NOT_VERIFIED" in output
    assert "total responses: 3" in output


def test_setup_message_does_not_claim_replay_verification(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(agent, "LOG_FILE", tmp_path / "log")
    monkeypatch.setattr(agent, "open_session", lambda *_: nullcontext(object()))
    monkeypatch.setattr(agent, "wait_for_portal", Mock())
    assert agent.cmd_setup(SimpleNamespace()) == 0
    output = capsys.readouterr().out
    assert "authenticated list-like Portal response observed" in output
    assert "setup success does not mean replay contract verified" in output


def test_successful_debug_report_has_no_contract_values(monkeypatch, tmp_path):
    monkeypatch.setattr(agent, "LOCAL_DIR", tmp_path)
    monkeypatch.setattr(agent, "DISCOVERY_FILE", tmp_path / "discovery.json")
    monkeypatch.setattr(agent, "DEBUG_FILE", tmp_path / "debug.json")
    report = agent.write_discovery(observations())
    assert report["detailReplayable"]
    saved = json.loads(agent.DEBUG_FILE.read_text())
    assert set(saved) == {"diagnostics", "reasons"}
    for value in ("PRIVATE-TITLE", "PRIVATE-BODY", "private-id-a", "private-id-b", "list_query", "detail_id_hashes"):
        assert value not in agent.DEBUG_FILE.read_text()
