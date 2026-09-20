"""Endpoint selection by interaction, not by field names.

The live run selected /wz/api/widget/collegePlan as the notice list and
kaist.lbl.content as a notice body. Both are false positives that satisfy every
name heuristic: a calendar widget has rows with an id, a title and a date, and a
localization bundle has fields called content and text.

What tells them apart from the real thing is what the person did. Someone
looking for notices opens two of them, so two row values must reappear inside
two fetched detail payloads. A widget nobody clicked correlates with nothing.

All payloads here are synthetic. PRIVATE-* markers stand in for notice content
and must never reach a log, a debug file or a contract.
"""
import json

import portal_web_agent as agent
from ggongbab.portal_contract import contract_from_discovery
from ggongbab.portal_diagnostics import Diagnostics, capture_response
from ggongbab.portal_discovery import correlate_interactions

from .test_portal_agent import BASE, BODY, HOST, TITLE
from .test_portal_diagnostics import collect, response

# ---------------------------------------------------------------------------
# The two false positives from the live run, reproduced
# ---------------------------------------------------------------------------
PLAN_ROWS = [{"id": "PLAN-1", "title": "PRIVATE-PLAN-A", "date": "2026-03-02"},
             {"id": "PLAN-2", "title": "PRIVATE-PLAN-B", "date": "2026-06-20"}]
LOCALIZATION = {"kaist": {"lbl": {"content": "PRIVATE-LABEL-ONE"}},
                "label": {"text": "PRIVATE-LABEL-TWO"}}


def college_plan(bgng="20260101", end="20261231"):
    """The academic-calendar widget: generic schema, never opened by anyone."""
    return response(url=f"{BASE}/wz/api/widget/collegePlan?bgngDt={bgng}&endDt={end}",
                    payload={"result": {"list": PLAN_ROWS}})


def localization():
    return response(url=BASE + "/wz/api/i18n/messages", payload=LOCALIZATION)


# ---- the real thing, with field names no whitelist knows --------------------
def notice_row(identifier, subject="PRIVATE-SUBJECT", reg="2026-09-20"):
    return {"nttId": identifier, "nttSj": subject, "regDt": reg}


def notice_list(identifiers, page=None):
    """A page of the notice board. `currentPage` is deliberately left off by
    default: it is not a key request_shape can replay, so including it would
    reject the contract before the parts under test are reached."""
    query = f"?currentPage={page}" if page is not None else ""
    return response(url=f"{BASE}/api/board/notices{query}",
                    payload={"result": {"resultList": [notice_row(i) for i in identifiers]}})


def notice_detail(identifier):
    return response(url=f"{BASE}/api/board/notices/{identifier}",
                    payload={"result": {"nttId": identifier, "nttCont": BODY}})


def real_flow(identifiers=("NOTICE-A", "NOTICE-B"), extra=()):
    return list(extra) + [notice_list(identifiers)] + [notice_detail(i) for i in identifiers]


# ---- the same flow with field names the whitelists DO know ------------------
def known_list(identifiers):
    rows = [{"noticeId": i, "subject": "PRIVATE-SUBJECT", "regDate": "2026-09-20"}
            for i in identifiers]
    return response(url=BASE + "/api/board/notices",
                    payload={"result": {"resultList": rows}})


def known_detail(identifier):
    return response(url=f"{BASE}/api/board/notices/{identifier}",
                    payload={"result": {"noticeId": identifier, "noticeBody": BODY}})


def known_flow(identifiers=("NOTICE-A", "NOTICE-B"), extra=()):
    return list(extra) + [known_list(identifiers)] + [known_detail(i) for i in identifiers]


def blob(*parts):
    return json.dumps(parts, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 1-3: the false positives are rejected, and not by a path blacklist
# ---------------------------------------------------------------------------
def test_college_plan_widget_is_rejected_for_lack_of_correlation():
    """Nobody opened a calendar entry, so nothing points back at those rows."""
    report, d = collect([college_plan()])
    assert "LIST_DETAIL_ID_NOT_CORRELATED" in report["reasons"]
    assert report["contract"] is None
    assert not report["listReplayable"]
    assert d.counts["correlated distinct ids"] == 0


def test_college_plan_is_rejected_even_while_real_notices_are_opened():
    """The decisive fact is correlation, not the widget's path or its name."""
    report, _ = collect(real_flow(extra=[college_plan()]))
    contract = report["contract"]
    assert contract["list_path"] == "/api/board/notices"
    assert contract["list_array_path"] == "result.resultList"
    assert "collegePlan" not in blob(report)


def test_widget_date_range_keys_are_not_notice_pagination():
    """bgngDt/endDt change between widget calls, but that is not our list."""
    report, d = collect([college_plan("20260101", "20260630"),
                         college_plan("20260701", "20261231")])
    named = {entry["key"] for entry in d.pagination_candidates}
    assert "bgngDt" not in named and "endDt" not in named
    assert d.pagination_candidates == []
    assert not report["paginationParameterObserved"]


def test_localization_json_is_not_a_notice_detail():
    """content/text abound in a message bundle; none of them is a notice body."""
    report, d = collect([localization()])
    assert report["contract"] is None
    assert d.selected_detail.get("correlated") in (False, None)
    for marker in ("PRIVATE-LABEL-ONE", "PRIVATE-LABEL-TWO"):
        assert marker not in blob(report, d.export())


def test_localization_beside_a_real_flow_is_ignored():
    report, _ = collect(real_flow(extra=[localization(), college_plan()]))
    contract = report["contract"]
    assert contract["detail_body_path"] == "result.nttCont"
    assert report["detailReplayable"]
    assert "lbl" not in blob(report)


# ---------------------------------------------------------------------------
# 4, 11-13: unknown field names, and the order inference happens in
# ---------------------------------------------------------------------------
def test_unknown_id_field_is_inferred_from_the_interaction():
    """nttId is in no whitelist; the click is what identifies it."""
    report, d = collect(real_flow())
    contract = report["contract"]
    assert contract["list_id_key"] == "nttId"
    assert contract["detail_id_path"] == "result.nttId"
    assert d.selected_list["idKey"] == "nttId"


def test_row_keys_are_reported_so_unknown_schemas_can_be_supported():
    report, d = collect(real_flow())
    assert d.selected_list["rowKeys"] == ["nttId", "nttSj", "regDt"]
    assert report["diagnostics"]["safe"]["rowKeys"] == ["nttId", "nttSj", "regDt"]


def test_title_inference_runs_only_after_the_list_is_selected():
    """nttSj is not in TITLE_KEYS, so the run says so instead of guessing."""
    report, d = collect(real_flow())
    assert "NOTICE_LIST_CORRELATED_BUT_TITLE_FIELD_UNKNOWN" in report["reasons"]
    assert report["contract"]["list_title_key"] == ""
    assert d.selected_list["titleKey"] == "unknown"
    # Uncorrelated widget rows DO have a field called "title"; it was never used.
    assert "PRIVATE-PLAN-A" not in blob(report)


def test_date_inference_runs_only_after_the_list_is_selected():
    """The widget has parseable dates; they must not become notice dates."""
    report, _ = collect([college_plan()])
    assert report["contract"] is None
    # The widget's own "date" column parses cleanly, yet is never adopted.
    correlated, d = collect(real_flow(extra=[college_plan()]))
    assert correlated["contract"]["list_date_key"] == "regDt"
    assert d.selected_list["dateKey"] == "regDt"
    assert correlated["contract"]["list_array_path"] == "result.resultList"


def test_pagination_is_evaluated_only_for_the_correlated_list():
    report, d = collect([college_plan("20260101", "20260630")]
                        + [notice_list(("NOTICE-A", "NOTICE-B"), page=1),
                           notice_list(("NOTICE-C", "NOTICE-D"), page=2)]
                        + [notice_detail("NOTICE-A"), notice_detail("NOTICE-B")])
    named = {entry["key"] for entry in d.pagination_candidates}
    assert named == {"currentPage"}
    assert "bgngDt" not in named


# ---------------------------------------------------------------------------
# 5-8: how much evidence is enough, and choosing among unrelated candidates
# ---------------------------------------------------------------------------
def test_two_distinct_ids_are_required():
    report, _ = collect(real_flow())
    assert report["contract"]["detail_verified_count"] == 2
    assert report["detailReplayable"]


def test_one_opened_notice_identifies_the_list_but_not_the_detail():
    report, _ = collect([notice_list(("NOTICE-A", "NOTICE-B")), notice_detail("NOTICE-A")])
    assert "NOT_ENOUGH_DISTINCT_DETAILS" in report["reasons"]
    assert not report["detailReplayable"]
    # One correlation is still enough to say which array is the notice list.
    assert report["contract"]["list_array_path"] == "result.resultList"


def test_the_same_notice_opened_twice_is_one_id():
    report, d = collect([notice_list(("NOTICE-A", "NOTICE-B")),
                         notice_detail("NOTICE-A"), notice_detail("NOTICE-A")])
    assert d.counts["correlated distinct ids"] == 1
    assert "NOT_ENOUGH_DISTINCT_DETAILS" in report["reasons"]
    assert not report["detailReplayable"]


def test_the_correlated_list_wins_against_unrelated_list_candidates():
    """Three plausible arrays; only one has rows anybody opened."""
    other = response(url=BASE + "/wz/api/widget/menu",
                     payload={"items": [{"id": "M1", "title": "a"}, {"id": "M2", "title": "b"}]})
    report, d = collect(real_flow(extra=[college_plan(), other]))
    assert d.counts["list-like JSON candidates"] >= 3
    assert report["contract"]["list_path"] == "/api/board/notices"
    assert d.selected_list["correlated"] is True


def test_the_correlated_detail_wins_against_unrelated_json():
    config = response(url=BASE + "/wz/api/config",
                      payload={"theme": {"content": "PRIVATE-THEME"}})
    report, _ = collect(real_flow(extra=[localization(), config]))
    assert report["contract"]["detail_path"] == "/api/board/notices/{id}"
    assert "PRIVATE-THEME" not in blob(report)


# ---------------------------------------------------------------------------
# 9-10: the body is searched inside the correlated id's subtree
# ---------------------------------------------------------------------------
def test_body_search_starts_inside_the_correlated_id_subtree():
    def payload(identifier):
        return {"result": {"nttId": identifier, "nttCont": BODY},
                "layout": {"content": "PRIVATE-SIDEBAR"}}

    rows = [notice_list(("NOTICE-A", "NOTICE-B"))] + [
        response(url=f"{BASE}/api/board/notices/{i}", payload=payload(i))
        for i in ("NOTICE-A", "NOTICE-B")]
    report, d = collect(rows)
    assert report["contract"]["detail_body_path"] == "result.nttCont"
    assert d.body_disambiguated_by_id is True
    assert "PRIVATE-SIDEBAR" not in blob(report, d.export())


def test_two_body_fields_beside_the_id_stay_ambiguous():
    """Choosing by name or by length would be a guess; a wrong guess publishes
    the wrong text."""
    def payload(identifier):
        return {"result": {"nttId": identifier, "nttCont": BODY, "content": BODY}}

    rows = [notice_list(("NOTICE-A", "NOTICE-B"))] + [
        response(url=f"{BASE}/api/board/notices/{i}", payload=payload(i))
        for i in ("NOTICE-A", "NOTICE-B")]
    report, _ = collect(rows)
    assert "DETAIL_BODY_PATH_AMBIGUOUS" in report["reasons"]
    assert not report["detailReplayable"]
    assert report["contract"]["detail_body_path"] == ""


# ---------------------------------------------------------------------------
# 14-16: correlation values stay in memory
# ---------------------------------------------------------------------------
def test_raw_correlation_values_are_never_persisted():
    report, d = collect(real_flow(extra=[college_plan(), localization()]))
    everything = blob(report, d.export())
    for secret in ("NOTICE-A", "NOTICE-B", "PRIVATE-SUBJECT", "PRIVATE-PLAN-A",
                   "PRIVATE-LABEL-ONE", BODY, TITLE):
        assert secret not in everything, secret


def test_correlation_evidence_is_hashed_not_stored():
    rows = [r for r in (capture_response(x, HOST, Diagnostics()) for x in real_flow()) if r]
    lists = [r for r in rows if r["kind"] == "list"]
    details = [r for r in rows if r["kind"] == "detail"]
    groups = correlate_interactions(lists, details)
    assert len(groups) == 1
    (entry,) = groups.values()
    assert len(entry["hashes"]) == 2
    for hashed in entry["hashes"]:
        assert "NOTICE-A" not in hashed and "NOTICE-B" not in hashed


def test_raw_correlation_values_are_never_logged(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(agent, "LOCAL_DIR", tmp_path)
    monkeypatch.setattr(agent, "DISCOVERY_FILE", tmp_path / "discovery.json")
    monkeypatch.setattr(agent, "DEBUG_FILE", tmp_path / "debug.json")
    monkeypatch.setattr(agent, "LOG_FILE", tmp_path / "log")
    d = Diagnostics()
    observed = [r for r in (capture_response(x, HOST, d)
                            for x in real_flow(extra=[college_plan(), localization()])) if r]
    report = agent.write_discovery(observed, d)
    agent.log_discovery(report)
    everything = (capsys.readouterr().out
                  + agent.DEBUG_FILE.read_text(encoding="utf-8")
                  + agent.DISCOVERY_FILE.read_text(encoding="utf-8"))
    for secret in ("NOTICE-A", "NOTICE-B", "PRIVATE-SUBJECT", "PRIVATE-PLAN-A",
                   "PRIVATE-LABEL-ONE", BODY, TITLE, "20260101"):
        assert secret not in everything, secret
    # The structural diagnosis did survive.
    assert "nttId" in everything and "result.nttCont" in everything


def test_debug_file_holds_only_names_paths_and_counts(monkeypatch, tmp_path):
    monkeypatch.setattr(agent, "LOCAL_DIR", tmp_path)
    monkeypatch.setattr(agent, "DISCOVERY_FILE", tmp_path / "discovery.json")
    monkeypatch.setattr(agent, "DEBUG_FILE", tmp_path / "debug.json")
    d = Diagnostics()
    observed = [r for r in (capture_response(x, HOST, d) for x in real_flow()) if r]
    agent.write_discovery(observed, d)
    debug = json.loads(agent.DEBUG_FILE.read_text(encoding="utf-8"))
    assert set(debug) == {"diagnostics", "reasons"}
    for section in ("counts", "rejected"):
        assert all(type(v) is int for v in debug["diagnostics"][section].values())
    safe = debug["diagnostics"]["safe"]
    assert safe["selectedList"]["idKey"] == "nttId"
    assert safe["selectedDetail"]["idPath"] == "result.nttId"
    assert all(isinstance(r, str) for r in safe["rowKeys"])


# ---------------------------------------------------------------------------
# 17: the whole positive flow
# ---------------------------------------------------------------------------
def test_positive_notice_flow_builds_a_replayable_contract():
    report, d = collect(known_flow(extra=[college_plan(), localization()]))
    contract = report["contract"]
    assert report["listReplayable"] and report["detailReplayable"]
    assert contract["list_path"] == "/api/board/notices"
    assert contract["list_array_path"] == "result.resultList"
    assert contract["list_id_key"] == "noticeId"
    assert contract["list_title_key"] == "subject"
    assert contract["list_date_key"] == "regDate"
    assert contract["detail_path"] == "/api/board/notices/{id}"
    assert contract["detail_id_path"] == "result.noticeId"
    assert contract["detail_body_path"] == "result.noticeBody"
    assert contract["detail_verified_count"] == 2
    assert d.counts["correlated distinct ids"] == 2
    assert contract_from_discovery(report) is not None
    for secret in ("NOTICE-A", "PRIVATE-SUBJECT", BODY, "PRIVATE-LABEL-ONE"):
        assert secret not in blob(report)


def test_an_unknown_title_field_blocks_calibration_instead_of_guessing():
    """The detail side is proven, but a list with no known title is not usable."""
    report, _ = collect(real_flow())
    assert report["detailReplayable"]
    assert not report["listReplayable"]
    assert contract_from_discovery(report) is None
