"""Structural diagnostics for a rejected Portal replay contract.

The live run rejected both contracts with UNSAFE_REQUEST_SHAPE and
DETAIL_BODY_PATH_AMBIGUOUS, and the counters could not say WHICH query key or
WHICH JSON path was responsible. These tests pin down the one thing that makes
that diagnosable safely: names and paths may be reported, values may not.

Every payload here is synthetic. The PRIVATE-* markers stand in for notice
content and must never appear in any diagnostic, log line or debug file.
"""
import json

import pytest

import portal_web_agent as agent
from ggongbab.portal_diagnostics import (MAX_KEYS, REDACTED, UNNAMEABLE, Diagnostics,
                                         capture_response, safe_json_path, safe_key_name)
from ggongbab.portal_discovery import (body_path_in_id_subtree, build_discovery,
                                       path_template, request_shape, structural_value_ok)

from .test_portal_agent import BASE, BODY, HOST, TITLE, listing, notice
from .test_portal_diagnostics import collect, opened, response

SECRETS = (TITLE, BODY, "PRIVATE-BOARD", "PRIVATE-TOKEN", "PRIVATE-ID-A", "PRIVATE-ID-B",
           "PRIVATE-CURSOR", "PRIVATE-SESSION")


def blob(*parts):
    return json.dumps(parts, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 1-5: unsafe query keys are nameable, values never are
# ---------------------------------------------------------------------------
def test_unsafe_non_sensitive_query_key_name_is_diagnosable():
    """The whole point: say which knob blocked the contract."""
    report, d = collect([response(url=BASE + "/api/notices?boardId=PRIVATE-BOARD")])
    assert "UNSAFE_REQUEST_SHAPE" in report["reasons"]
    assert d.unsafe_query_keys == ["boardId"]
    assert report["diagnostics"]["safe"]["unsafeQueryKeys"] == ["boardId"]


def test_unsafe_query_value_never_appears_anywhere():
    report, d = collect([response(url=BASE + "/api/notices?boardId=PRIVATE-BOARD")])
    assert "PRIVATE-BOARD" not in blob(report, d.export())


def test_sensitive_query_key_name_is_redacted():
    """A name like sso_token describes the auth scheme, so even it is withheld."""
    _, d = collect([response(url=BASE + "/api/notices?sessionToken=PRIVATE-SESSION")])
    assert d.unsafe_query_keys == [REDACTED]


@pytest.mark.parametrize("key", ["token", "authKey", "jwt", "PHPSESSID_cookie", "api_secret"])
def test_sensitive_names_are_redacted_by_shape(key):
    assert safe_key_name(key) == REDACTED


def test_sensitive_query_value_never_appears():
    report, d = collect([response(url=BASE + "/api/notices?sessionToken=PRIVATE-SESSION")])
    assert "PRIVATE-SESSION" not in blob(report, d.export())


@pytest.mark.parametrize("key", ["has space", "dotted.key", "", "x" * 80, "9leading"])
def test_keys_that_cannot_be_vouched_for_become_a_placeholder(key):
    assert safe_key_name(key) == UNNAMEABLE


def test_query_key_list_is_deduplicated_and_bounded():
    d = Diagnostics()
    for index in range(MAX_KEYS * 3):
        d.note_unsafe_query_key(f"key{index}")
    for _ in range(5):
        d.note_unsafe_query_key("key0")
    assert len(d.unsafe_query_keys) == MAX_KEYS
    assert len(set(d.unsafe_query_keys)) == MAX_KEYS


def test_duplicate_query_key_is_named_not_just_counted():
    _, d = collect([response(url=BASE + "/api/notices?boardId=A&boardId=B")])
    assert d.rejected["unsafe query key count"] >= 1
    assert d.unsafe_query_keys == ["boardId"]


# ---------------------------------------------------------------------------
# 2: list candidate metadata
# ---------------------------------------------------------------------------
def test_list_candidate_records_shape_without_values():
    report, d = collect([response(url=BASE + "/api/notices?boardId=PRIVATE-BOARD&page=0")])
    candidate = report["diagnostics"]["safe"]["listCandidate"]
    assert candidate["host"] == HOST
    assert candidate["templatedPath"] == "/api/notices"
    assert sorted(candidate["queryKeys"]) == ["boardId", "page"]
    assert candidate["method"] == "GET"
    assert candidate["resourceType"] == "xhr"
    assert "PRIVATE-BOARD" not in blob(candidate)


def test_unsafe_path_is_withheld_entirely():
    """A half-masked path still leaks its shape, so nothing is printed."""
    template, unsafe = path_template(BASE + "/api/9f3a8c1e2b/notices")
    assert unsafe == 1 and template == ""
    d = Diagnostics()
    d.note_list_candidate(host=HOST, path=template, query_keys=["page"],
                          method="GET", resource="xhr")
    assert d.list_candidate["templatedPath"] == ""


# ---------------------------------------------------------------------------
# 6-8: pagination and static structural candidates
# ---------------------------------------------------------------------------
def _two_list_calls(first_url, second_url):
    """Two pages of the same list, plus the two notices that were opened.

    The details are not decoration: pagination is only inferred once
    correlation has proved which endpoint is the notice list.
    """
    return collect([response(url=BASE + first_url),
                    response(url=BASE + second_url,
                             payload=listing([notice("PRIVATE-ID-C"), notice("PRIVATE-ID-D")]))]
                   + opened())


def test_static_structural_key_constant_across_calls_is_detectable():
    _, d = _two_list_calls("/api/notices?boardId=PRIVATE-BOARD&currentPage=1",
                           "/api/notices?boardId=PRIVATE-BOARD&currentPage=2")
    assert d.static_structural_keys == ["boardId"]
    assert "PRIVATE-BOARD" not in blob(d.export())


def test_changing_numeric_pagination_candidate_is_detectable():
    _, d = _two_list_calls("/api/notices?boardId=PRIVATE-BOARD&currentPage=1",
                           "/api/notices?boardId=PRIVATE-BOARD&currentPage=2")
    assert d.pagination_candidates == [
        {"key": "currentPage", "changesBetweenListCalls": True,
         "numericMonotonic": True, "opaqueChanging": False}]


def test_opaque_pagination_change_is_reported_but_not_authorized():
    """`currentPage` is not in PAGE, so naming it must not replay it."""
    report, d = _two_list_calls("/api/notices?currentPage=abc", "/api/notices?currentPage=def")
    entry = next(c for c in d.pagination_candidates if c["key"] == "currentPage")
    assert entry["changesBetweenListCalls"] and entry["opaqueChanging"]
    assert not entry["numericMonotonic"]
    # Named, yet still refused: the contract is not built from a key name.
    assert not report["listReplayable"]
    assert report["contract"] is None
    assert "abc" not in blob(d.export()) and "def" not in blob(d.export())


def test_a_named_numeric_candidate_is_still_not_authorized_automatically():
    """Observation proves the page increments it, not what it selects."""
    report, d = _two_list_calls("/api/notices?currentPage=1", "/api/notices?currentPage=2")
    assert d.pagination_candidates[0]["numericMonotonic"] is True
    assert not report["listReplayable"] and report["contract"] is None
    assert "UNSAFE_REQUEST_SHAPE" in report["reasons"]


def test_pagination_candidates_need_two_observed_calls():
    _, d = collect([response(url=BASE + "/api/notices?currentPage=1")])
    assert d.pagination_candidates == []
    assert d.static_structural_keys == []


# ---------------------------------------------------------------------------
# 15 / §4: structural params are authorized only by explicit opt-in
# ---------------------------------------------------------------------------
def test_structural_key_is_replayable_only_when_an_operator_opts_in():
    url = BASE + "/api/notices?boardId=notice01"
    assert request_shape(url) is None
    shape = request_shape(url, allow_structural={"boardId"})
    assert shape is not None and shape[2] == {"boardId": "notice01"}


@pytest.mark.parametrize("value", ["x" * 33, "has space", "a/b", "eyJhbGciOiJIUzI1NiJ9.abc"])
def test_opt_in_still_refuses_a_value_that_is_not_a_plain_identifier(value):
    assert not structural_value_ok("boardId", value)
    assert request_shape(f"{BASE}/api/notices?boardId={value}",
                         allow_structural={"boardId"}) is None


def test_opt_in_cannot_whitelist_a_credential_shaped_key():
    assert not structural_value_ok("sessionToken", "abc123")


# ---------------------------------------------------------------------------
# 9-13: detail body paths
# ---------------------------------------------------------------------------
def ambiguous_detail(identifier="PRIVATE-ID-A"):
    return {"result": {"id": identifier, "body": BODY, "content": BODY}}


def _ambiguous_flow():
    """Two opened notices whose payloads each offer two body fields."""
    return collect([response()] + [
        response(url=f"{BASE}/api/notices/{i}", payload=ambiguous_detail(i))
        for i in ("PRIVATE-ID-A", "PRIVATE-ID-B")])


def test_body_candidate_paths_are_recorded_without_values():
    report, d = _ambiguous_flow()
    paths = report["diagnostics"]["safe"]["detailBodyCandidatePaths"]
    assert sorted(paths) == ["result.body", "result.content"]
    assert BODY not in blob(report, d.export())


def test_body_value_is_never_persisted():
    report, d = _ambiguous_flow()
    assert BODY not in blob(report)
    assert "PRIVATE-BODY" not in blob(report, d.export())


def test_dynamic_json_key_never_reaches_a_recorded_path():
    """walk() refuses these, and safe_json_path refuses them again."""
    for path in ("result.some key.body", "result.auth_token.body", "result.9bad.body"):
        assert safe_json_path(path) == ""
    d = Diagnostics()
    d.note_body_candidate_path("result.session.content")
    assert d.detail_body_candidate_paths == []


def test_stable_id_subtree_yields_a_unique_body_path():
    """The body sharing the id's object is the notice's own body."""
    assert body_path_in_id_subtree(
        "result.id", ["result.content", "sidebar.content"]) == "result.content"


def test_ambiguous_subtree_remains_rejected():
    """Two candidates beside the id: choosing by name or length would be a guess."""
    assert body_path_in_id_subtree("result.id", ["result.body", "result.content"]) == ""


def test_subtree_widens_outward_only_until_it_finds_one():
    # Nothing beside the id itself, exactly one a level out.
    assert body_path_in_id_subtree(
        "result.meta.id", ["result.content"]) == "result.content"
    # Two a level out is still ambiguous.
    assert body_path_in_id_subtree(
        "result.meta.id", ["result.content", "result.body"]) == ""


def test_ambiguous_body_is_resolved_end_to_end_by_the_verified_id():
    """A payload the old code dropped now yields a detail candidate."""
    def resolvable(identifier):
        return {"result": {"id": identifier, "content": BODY},
                "sidebar": {"content": "unrelated promo text"}}

    report, d = collect([response()] + [
        response(url=f"{BASE}/api/notices/{i}", payload=resolvable(i))
        for i in ("PRIVATE-ID-A", "PRIVATE-ID-B")])
    safe = report["diagnostics"]["safe"]
    assert safe["bodyDisambiguatedByIdSubtree"] is True
    assert report["contract"]["detail_body_path"] == "result.content"
    # Observed as ambiguous, but resolved, so it is not reported as a blocker.
    assert d.rejected["body path ambiguous"] == 2
    assert d.body_ambiguity_unresolved == 0
    assert "DETAIL_BODY_PATH_AMBIGUOUS" not in report["reasons"]
    assert BODY not in blob(report)


def test_unresolvable_ambiguity_still_blocks():
    report, d = _ambiguous_flow()
    assert report["diagnostics"]["safe"]["bodyDisambiguatedByIdSubtree"] is False
    assert d.body_ambiguity_unresolved == 2
    assert "DETAIL_BODY_PATH_AMBIGUOUS" in report["reasons"]
    assert not report["detailReplayable"]


# ---------------------------------------------------------------------------
# 14: nothing notice-derived reaches the debug file or the terminal
# ---------------------------------------------------------------------------
def test_debug_file_and_staged_output_carry_no_notice_content(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(agent, "LOCAL_DIR", tmp_path)
    monkeypatch.setattr(agent, "DISCOVERY_FILE", tmp_path / "discovery.json")
    monkeypatch.setattr(agent, "DEBUG_FILE", tmp_path / "debug.json")
    monkeypatch.setattr(agent, "LOG_FILE", tmp_path / "log")
    d = Diagnostics()
    rows = []
    for r in (response(url=BASE + "/api/notices?boardId=PRIVATE-BOARD&sessionToken=PRIVATE-SESSION"),
              response(url=BASE + "/api/notices/PRIVATE-ID-A", payload=ambiguous_detail())):
        row = capture_response(r, HOST, d)
        if row:
            rows.append(row)
    report = agent.write_discovery(rows, d)
    agent.log_discovery(report)
    output = capsys.readouterr().out
    everything = output + agent.DEBUG_FILE.read_text(encoding="utf-8") \
        + agent.DISCOVERY_FILE.read_text(encoding="utf-8")
    for secret in SECRETS:
        assert secret not in everything, secret
    # ...while the diagnosis itself did survive.
    assert "boardId" in output
    assert REDACTED in output
    assert "result.content" in output


def test_staged_output_names_each_stage(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(agent, "LOG_FILE", tmp_path / "log")
    report, _ = collect([response(url=BASE + "/api/notices?boardId=PRIVATE-BOARD")])
    agent.log_discovery(report)
    output = capsys.readouterr().out
    for line in ("Interaction correlation:", "  correlated distinct ids: 0",
                 "Selected notice list:", "  correlated: no",
                 "  unsafe query keys: [boardId]", "Selected notice detail:",
                 "Pagination:"):
        assert line in output, line
    # Nothing correlated, so pagination was never even considered.
    assert "evaluated only after notice list correlation: not reached" in output


def test_diagnostics_do_not_authorize_unknown_structural_params():
    """Naming a key must never be the same act as trusting it."""
    report, d = collect([response(url=BASE + "/api/notices?boardId=PRIVATE-BOARD")])
    assert d.unsafe_query_keys == ["boardId"]
    assert report["contract"] is None
    assert not report["listReplayable"]
    # The default build authorizes no structural parameter at all.
    assert build_discovery([], BASE + "/")["contract"] is None
