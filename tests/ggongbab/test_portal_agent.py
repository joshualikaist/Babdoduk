"""Portal correctness tests use synthetic APIs only; no SSO or live writes."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import date
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from unittest.mock import Mock
import json

import pytest
import portal_web_agent as agent
from ggongbab.portal_contract import PortalContract, contract_from_discovery
from ggongbab.portal_discovery import build_discovery, classify_observed
from ggongbab.portal_fetch import exact_rows, fetch_detail, iter_notices, request_context
from ggongbab.portal_queue import PortalQueue
from ggongbab.web.exit_codes import AuthRequired, UiContractError

HOST = "portal.kaist.ac.kr"
BASE = "https://" + HOST
TITLE = "기업 설명회 안내 PRIVATE-TITLE"
BODY = "9월 25일 12시 N1에서 설명회를 진행합니다. 참석자에게 점심 도시락을 제공합니다. PRIVATE-BODY"


def notice(identifier, day="2026-09-20"):
    return dict(id=identifier, title=TITLE, createdAt=day)


def listing(rows, cursor=None):
    return {"irrelevant": [{"wrong": True}], "result": {"contents": rows, "nextCursor": cursor}}


def detail(identifier, body=BODY):
    return {"result": {"id": identifier, "content": {"body": {"content": body}}}}


def observation(url, payload):
    result = classify_observed("GET", BASE + url, 200, payload)
    assert result
    return result


def observations(mode="page"):
    first = listing([notice("private-id-a"), notice("private-id-b", "2026-09-19")])
    second = listing([notice("private-id-c", "2026-09-18"), notice("private-id-d", "2026-09-17")])
    if mode == "cursor":
        first["result"]["nextCursor"] = "PRIVATE-CURSOR"
        urls = ("/api/notices?limit=2", "/api/notices?limit=2&cursor=PRIVATE-CURSOR")
    elif mode == "offset":
        urls = ("/api/notices?offset=0&limit=2", "/api/notices?offset=2&limit=2")
    else:
        urls = ("/api/notices?page=0&size=2", "/api/notices?page=1&size=2")
    return [observation(urls[0], first), observation(urls[1], second),
            observation("/api/notices/private-id-a", detail("private-id-a")),
            observation("/api/notices/private-id-b", detail("private-id-b"))]


def contract(mode="page"):
    c = contract_from_discovery(build_discovery(observations(mode), BASE + "/"))
    assert c and c.list_ready() and c.detail_ready()
    c.verified = True
    return c


class Response:
    def __init__(self, payload, status=200, content_type="application/json"):
        self.payload, self.status = payload, status
        self.headers = {"content-type": content_type}
        self.disposed = False

    def json(self):
        return self.payload

    def dispose(self):
        self.disposed = True


class Request:
    def __init__(self, pages, bodies=None):
        self.pages, self.bodies, self.calls = list(pages), bodies or {}, []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        parsed = urlparse(url)
        if parsed.path == "/api/notices":
            assert self.pages, "unexpected extra list fetch"
            value = self.pages.pop(0)
        else:
            identifier = parsed.path.rsplit("/", 1)[-1]
            value = self.bodies.get(identifier, detail(identifier))
        return value if isinstance(value, Response) else Response(value)


def args(**kwargs):
    return SimpleNamespace(dry_run=True, date_from=None, date_to=None,
                           max_pages=20, max_items=500, port=9223, **kwargs)


def install(monkeypatch, tmp_path, request, c=None):
    state = tmp_path / "state.json"
    monkeypatch.setattr(agent, "STATE_FILE", state)
    monkeypatch.setattr(agent, "LOG_FILE", tmp_path / "agent.log")
    monkeypatch.setattr(agent, "LOCAL_DIR", tmp_path)
    monkeypatch.setattr(agent, "_require_contract", lambda: c or contract())
    page = SimpleNamespace(url=BASE + "/", context=SimpleNamespace(request=request))
    @contextmanager
    def session(*_):
        yield SimpleNamespace(context=SimpleNamespace(pages=[page]))
    monkeypatch.setattr(agent, "open_session", session)
    monkeypatch.setattr(agent, "observe_network", Mock(side_effect=AssertionError("passive run")))
    monkeypatch.setattr(agent, "wait_for_portal", Mock(side_effect=AssertionError("passive auth")))
    return state


@pytest.mark.parametrize("existing", [False, True])
def test_dry_run_has_candidates_without_writer_or_any_queue_mutation(monkeypatch, tmp_path, capsys, existing):
    request = Request([listing([notice("private-id-a")]), listing([])])
    state = install(monkeypatch, tmp_path, request)
    if existing:
        state.write_bytes(b'{"notices": {}}\n')
    before = state.read_bytes() if existing else None
    writer = Mock(side_effect=AssertionError("dry run must not construct writer"))
    monkeypatch.setattr(agent, "TaskWriter", writer)
    monkeypatch.setattr(agent, "load_settings", Mock(side_effect=AssertionError("settings unnecessary")))
    monkeypatch.setattr(PortalQueue, "record", Mock(side_effect=AssertionError("queue mutation")))
    monkeypatch.setattr(PortalQueue, "save", Mock(side_effect=AssertionError("queue save")))
    assert agent.cmd_run(args()) == 0
    assert (state.read_bytes() if state.exists() else None) == before
    output = capsys.readouterr().out
    assert "candidates: 1" in output and "registered: 0 (dry run)" in output
    assert "new: 1" in output and "detail fetched: 1" in output
    assert all(value not in output for value in (TITLE, BODY, "private-id-a"))
    writer.assert_not_called()


@pytest.mark.parametrize("result", ["created-task", None, RuntimeError("SECRET error")])
def test_real_run_advances_queue_only_after_confirmed_creation(monkeypatch, tmp_path, result):
    state = install(monkeypatch, tmp_path, Request([listing([notice("private-id-a")]), listing([])]))
    state.write_bytes(b'{"notices": {}}\n')
    before = state.read_bytes()
    writer = Mock()
    if isinstance(result, Exception):
        writer.create_portal_task.side_effect = result
    else:
        writer.create_portal_task.return_value = result
    monkeypatch.setattr(agent, "TaskWriter", lambda _: writer)
    monkeypatch.setattr(agent, "load_settings", lambda: object())
    options = args()
    options.dry_run = False
    if result == "created-task":
        assert agent.cmd_run(options) == 0
        assert state.read_bytes() != before
        assert len(PortalQueue(state).hashes) == 1
    else:
        with pytest.raises(agent.ProjectNotFound):
            agent.cmd_run(options)
        assert state.read_bytes() == before
    writer.verify_project.assert_called_once()


@pytest.mark.parametrize("mode,expected", [("page", "1"), ("offset", "2"), ("cursor", "PRIVATE-CURSOR")])
def test_active_pagination_uses_observed_progression(mode, expected):
    c = contract(mode)
    request = Request([listing([notice("one"), notice("two")], "PRIVATE-CURSOR"), listing([])])
    assert len(list(iter_notices(request, c))) == 2
    assert parse_qs(urlparse(request.calls[1][0]).query)[c.list_page_param] == [expected]
    assert all(opts["max_redirects"] == 0 for _, opts in request.calls)


def test_no_pagination_is_invented():
    rows = observations()[0:1] + observations()[2:]
    rows[0]["_url"] = BASE + "/api/notices"
    c = contract_from_discovery(build_discovery(rows, BASE + "/"))
    assert c.pagination == "none"
    req = Request([listing([notice("one"), notice("two")])])
    assert len(list(iter_notices(req, c))) == 2 and len(req.calls) == 1
    assert "?" not in req.calls[0][0]


def test_unverified_pagination_is_rejected():
    rows = observations()
    del rows[1]
    assert contract_from_discovery(build_discovery(rows, BASE + "/")) is None


def test_exact_array_path_never_uses_first_unrelated_array():
    c = contract()
    assert c.list_array_path == "result.contents"
    assert exact_rows(listing([notice("one")]), c)[0]["id"] == "one"
    with pytest.raises(UiContractError):
        exact_rows({"different": [notice("one")]}, c)


def test_exact_nested_body_path_never_falls_back():
    c = contract()
    assert c.detail_body_path == "result.content.body.content"
    assert fetch_detail(Request([]), c, "private-id-a") == BODY
    bad = {"body": BODY, "result": {"id": "private-id-a"}}
    with pytest.raises(UiContractError):
        fetch_detail(Request([], {"private-id-a": bad}), c, "private-id-a")


def test_detail_must_match_exact_stable_id():
    with pytest.raises(UiContractError):
        fetch_detail(Request([], {"private-id-a": detail("private-id-aa")}), contract(), "private-id-a")


def test_duplicate_ids_and_duplicate_only_page_stop():
    req = Request([listing([notice("one"), notice("one"), notice("two")]),
                   listing([notice("one"), notice("two")])])
    assert [r["id"] for r in iter_notices(req, contract())] == ["one", "two"]
    assert len(req.calls) == 2


def test_verified_descending_date_cutoff():
    req = Request([listing([notice("one"), notice("two", "2026-09-18")])])
    assert len(list(iter_notices(req, contract(), date_from=date(2026, 9, 19)))) == 2
    assert len(req.calls) == 1


def test_unverified_order_does_not_stop_at_old_row():
    c = contract()
    c.list_date_descending = False
    req = Request([listing([notice("old", "2026-01-01")]), listing([notice("new")]), listing([])])
    assert len(list(iter_notices(req, c, date_from=date(2026, 9, 19)))) == 2
    assert len(req.calls) == 3


@pytest.mark.parametrize("limit", ["max_items", "max_pages"])
def test_configured_limits_stop_requests(limit):
    req = Request([listing([notice("one"), notice("two")])])
    rows = list(iter_notices(req, contract(), **{limit: 1}))
    assert len(rows) == (1 if limit == "max_items" else 2)
    assert len(req.calls) == 1


def test_date_window_skips_missing_invalid_and_outside_dates_before_detail(monkeypatch, tmp_path, capsys):
    c = contract()
    c.list_date_descending = False
    req = Request([listing([notice("missing", ""), notice("invalid", "bad"),
                            notice("old", "2026-09-18"), notice("future", "2026-09-22"), notice("included")]), listing([])])
    install(monkeypatch, tmp_path, req, c)
    options = args()
    options.date_from, options.date_to = date(2026, 9, 19), date(2026, 9, 21)
    assert agent.cmd_run(options) == 0
    assert len([u for u, _ in req.calls if urlparse(u).path != "/api/notices"]) == 1
    output = capsys.readouterr().out
    assert "date matched: 1" in output and "loaded rows: 5" in output


def test_two_distinct_details_and_private_values_never_saved():
    report = build_discovery(observations(), BASE + "/")
    c = contract_from_discovery(report)
    assert c.detail_verified_count == 2 and c.detail_ready()
    blob = json.dumps(report)
    assert all(value not in blob for value in (TITLE, BODY, "private-id-a", "private-id-b"))
    cursor_report = build_discovery(observations("cursor"), BASE + "/")
    assert "PRIVATE-CURSOR" not in json.dumps(cursor_report)


def test_same_id_twice_does_not_verify_and_calibration_invalidates_old_contract(monkeypatch, tmp_path, capsys):
    rows = observations()
    rows[-1] = deepcopy(rows[-2])
    report = build_discovery(rows, BASE + "/")
    c = contract_from_discovery(report)
    assert c.detail_verified_count == 1 and not c.detail_ready()
    monkeypatch.setattr(agent, "CONTRACT_FILE", tmp_path / "contract.json")
    monkeypatch.setattr(agent, "DISCOVERY_FILE", tmp_path / "discovery.json")
    monkeypatch.setattr(agent, "LOG_FILE", tmp_path / "log")
    contract().save(agent.CONTRACT_FILE)
    agent.DISCOVERY_FILE.write_text(json.dumps(report), encoding="utf-8")
    assert agent.cmd_calibrate(args()) == 20
    assert "need two distinct notice details" in capsys.readouterr().out
    assert not PortalContract.load(agent.CONTRACT_FILE).verified


@pytest.mark.parametrize("change", ["template", "body", "id", "empty"])
def test_incompatible_or_empty_details_do_not_verify(change):
    rows = observations()
    if change == "template":
        rows[-1]["_url"] = BASE + "/other/private-id-b"
    elif change == "body":
        rows[-1] = observation("/api/notices/private-id-b", {"id": "private-id-b", "body": BODY})
    elif change == "id":
        rows[-1]["_payload"]["result"]["id"] = "wrong"
    else:
        # An empty body is admitted as a correlation candidate - correlation is
        # about identity, not text - but it yields no body path, so it can never
        # authorize a detail contract.
        rows[-1] = observation("/api/notices/private-id-b", detail("private-id-b", ""))
        assert rows[-1]["_bodies"] == []
    c = contract_from_discovery(build_discovery(rows, BASE + "/"))
    assert not c.detail_ready()


@pytest.mark.parametrize("suffix", ["&token=PRIVATE-TOKEN", "&search=PRIVATE-TITLE", "&memberId=PRIVATE-ID"])
def test_secret_or_unknown_query_values_make_contract_unreplayable(suffix):
    rows = observations()
    rows[0]["_url"] += suffix
    report = build_discovery(rows, BASE + "/")
    assert report["contract"] is None
    assert "PRIVATE" not in json.dumps(report)


def test_read_state_semantics_block_detail_authorization():
    rows = observations()
    rows[-1]["_payload"]["result"]["isRead"] = False
    c = contract_from_discovery(build_discovery(rows, BASE + "/"))
    assert c.detail_state == "requires-semantics-review" and not c.detail_ready()
    with pytest.raises(UiContractError):
        exact_rows({**listing([notice("one")]), "readCount": 1}, contract())


def test_generic_landing_page_is_not_authenticated():
    page = SimpleNamespace(url=BASE + "/", locator=lambda _: SimpleNamespace(count=lambda: 0))
    assert not agent.page_authenticated(page, HOST)
    assert agent.page_authenticated(page, HOST, notice_api_observed=True)
    page.url = BASE + ".attacker.test/"
    assert not agent.page_authenticated(page, HOST, notice_api_observed=True)
    page.url = BASE + "/login"
    assert not agent.page_authenticated(page, HOST, notice_api_observed=True)


@pytest.mark.parametrize("status,ctype", [(302, "application/json"), (401, "application/json"), (200, "text/html")])
def test_active_fetch_rejects_auth_redirect_and_html(status, ctype):
    req = Request([Response({}, status, ctype)])
    with pytest.raises(AuthRequired):
        list(iter_notices(req, contract()))


def test_legacy_contract_never_authorizes_active_fetch(tmp_path):
    path = tmp_path / "old.json"
    path.write_text(json.dumps({"verified": True, "list_path": "/old"}), encoding="utf-8")
    assert not PortalContract.load(path).verified


def test_calibration_saves_verified_exact_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(agent, "CONTRACT_FILE", tmp_path / "contract.json")
    monkeypatch.setattr(agent, "DISCOVERY_FILE", tmp_path / "discovery.json")
    monkeypatch.setattr(agent, "LOG_FILE", tmp_path / "log")
    agent.DISCOVERY_FILE.write_text(json.dumps(build_discovery(observations(), BASE + "/")), encoding="utf-8")
    assert agent.cmd_calibrate(args()) == 0
    c = PortalContract.load(agent.CONTRACT_FILE)
    assert c.verified and c.list_ready() and c.detail_ready()


def test_cli_rejects_invalid_limits_and_reversed_window():
    for values in (("--max-items", "0"), ("--max-pages", "-1"),
                   ("--from", "2026-09-20", "--to", "2026-09-19")):
        with pytest.raises(SystemExit):
            agent.main(["--dry-run", "--cdp", *values])


def test_request_context_probes_all_cdp_contexts_and_reuses_successful_first_page():
    stale = Request([Response({}, 401)])
    good = Request([listing([notice("one")]), listing([])])
    pages = [SimpleNamespace(url=BASE + "/", context=SimpleNamespace(request=r)) for r in (stale, good)]
    session = SimpleNamespace(context=SimpleNamespace(pages=pages))
    c = contract()
    chosen, initial = request_context(session, c)
    assert chosen is good
    assert len(list(iter_notices(chosen, c, initial_payload=initial))) == 1
    assert len(stale.calls) == 1 and len(good.calls) == 2


def test_cursor_loop_stops_without_persisting_cursor():
    req = Request([listing([notice("one")], "PRIVATE-CURSOR"),
                   listing([notice("two")], "PRIVATE-CURSOR")])
    assert len(list(iter_notices(req, contract("cursor")))) == 2
    assert len(req.calls) == 2


def test_unknown_date_field_rejects_window_before_any_fetch(monkeypatch, tmp_path):
    c = contract()
    c.list_date_key = ""
    req = Request([])
    install(monkeypatch, tmp_path, req, c)
    options = args()
    options.date_from = date(2026, 9, 1)
    with pytest.raises(UiContractError):
        agent.cmd_run(options)
    assert req.calls == []


def test_dry_run_counts_new_update_skip_and_keeps_state_bytes(monkeypatch, tmp_path, capsys):
    req = Request([listing([notice("new"), notice("updated"), notice("same")]), listing([])])
    state = install(monkeypatch, tmp_path, req)
    queue = PortalQueue(state)
    queue.record(queue.decide("updated", TITLE, BODY + " old"))
    queue.record(queue.decide("same", TITLE, BODY))
    queue.save()
    before = state.read_bytes()
    assert agent.cmd_run(args()) == 0
    assert state.read_bytes() == before
    output = capsys.readouterr().out
    assert "new: 1" in output and "updated: 1" in output and "already queued: 1" in output
    assert "registered: 0 (dry run)" in output


def test_partial_real_failure_records_only_confirmed_tasks(monkeypatch, tmp_path):
    req = Request([listing([notice("one"), notice("two")])])
    state = install(monkeypatch, tmp_path, req)
    writer = Mock()
    writer.create_portal_task.side_effect = ["created-task", RuntimeError("PRIVATE-TITLE")]
    monkeypatch.setattr(agent, "TaskWriter", lambda _: writer)
    monkeypatch.setattr(agent, "load_settings", lambda: object())
    options = args()
    options.dry_run = False
    with pytest.raises(agent.ProjectNotFound):
        agent.cmd_run(options)
    queue = PortalQueue(state)
    assert queue.decide("one", TITLE, BODY).outcome == "skip"
    assert queue.decide("two", TITLE, BODY).outcome == "new"


def test_query_id_template_is_observed_and_escaped():
    rows = observations()
    rows[-2]["_url"] = BASE + "/api/detail?noticeId=private-id-a"
    rows[-1]["_url"] = BASE + "/api/detail?noticeId=private-id-b"
    c = contract_from_discovery(build_discovery(rows, BASE + "/"))
    assert c.detail_ready() and c.detail_query == {"noticeId": "{id}"}
    request = Mock()
    request.get.return_value = Response(detail("a&b/c"))
    assert fetch_detail(request, c, "a&b/c") == BODY
    assert request.get.call_args.args[0] == BASE + "/api/detail?noticeId=a%26b%2Fc"


def test_changed_date_order_fails_before_cutoff():
    request = Request([listing([notice("older", "2026-09-18"), notice("newer", "2026-09-20")])])
    with pytest.raises(UiContractError):
        list(iter_notices(request, contract(), date_from=date(2026, 9, 19)))


def test_private_exception_messages_do_not_reach_cli_logs(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(agent, "LOG_FILE", tmp_path / "log")
    monkeypatch.setattr(agent, "cmd_run", Mock(side_effect=RuntimeError("PRIVATE-ID PRIVATE-TITLE PRIVATE-BODY")))
    assert agent.main(["--dry-run", "--cdp"]) == 1
    assert "PRIVATE" not in capsys.readouterr().out
    assert "PRIVATE" not in agent.LOG_FILE.read_text(encoding="utf-8")
