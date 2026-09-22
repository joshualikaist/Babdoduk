"""Synthetic only: no real browser, Portal, database or authentication traffic."""
import io
import json
import subprocess
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import urlencode, urlsplit, parse_qs

import pytest
import requests

import portal_web_agent as agent
import ggongbab.portal_session as sessions
from ggongbab.config import KST
from ggongbab.heartbeat import FIELDS, merge_heartbeat
from ggongbab.ingest_marker import portal_external_key
from ggongbab.portal_known_schema import known_contract
from ggongbab.portal_list_contract import LIST_URL, list_query, require_list_request
from ggongbab.portal_list_poller import PortalListPoller, ScanIncomplete, run_poller
from ggongbab.portal_list_state import PortalListState, ListStateError, poller_lock
from ggongbab.portal_session import PortalListClient, PortalSessionProvider, ListTransportError
from ggongbab.web.exit_codes import AuthRequired, UiContractError

NOW = datetime(2026, 9, 22, 9, tzinfo=KST)
SECRET = "SYNTHETIC-COOKIE-NEVER-LOG"
PRIVATE = "SYNTHETIC-PRIVATE-NOTICE"


def cookie(**overrides):
    return {"name": "JSESSIONID", "value": SECRET, "domain": "portal.kaist.ac.kr",
            "path": "/", "secure": True, "httpOnly": True, "expires": -1, **overrides}


def row(identifier="1", stamp=NOW, public="Y", title="세미나 점심 제공 " + PRIVATE):
    return {"pstNo": identifier, "boardNo": "SYNTHETIC-BOARD", "pstTtl": title,
            "regDt": stamp.isoformat(), "publicYn": public,
            "writerEmail": "synthetic@example.invalid", "pstCn": "SYNTHETIC-IGNORED-BODY"}


def page(rows, index=1, total=1):
    return {"data": rows, "page": {"pageIndex": index, "recordCountPerPage": 10,
                                   "totalPage": total, "totalRecord": total * 10}}


class Pages:
    def __init__(self, pages):
        self.pages, self.calls, self.closed = pages, [], False

    def fetch_list_page(self, index):
        self.calls.append(index)
        result = self.pages[index - 1]
        if isinstance(result, Exception):
            raise result
        return deepcopy(result)

    def close(self):
        self.closed = True


@pytest.fixture
def wire(monkeypatch):
    """Intercept the final adapter send: every HTTP test goes through the real guard."""
    calls, replies = [], []

    def send(_adapter, request, **kwargs):
        calls.append((request, kwargs))
        assert replies, "Unexpected network request"
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        status, body, headers = reply
        response = requests.Response()
        response.status_code = status
        response.headers.update(headers)
        response.raw = io.BytesIO(body)
        response.url, response.request = request.url, request
        return response

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)

    def reply(payload=None, status=200, headers=None, body=None):
        replies.append((status, body if body is not None else json.dumps(
            payload if payload is not None else page([row()])).encode(),
                        headers if headers is not None else {"Content-Type": "application/json"}))

    return SimpleNamespace(calls=calls, replies=replies, reply=reply)


def test_list_transport_only_exact_url_cookie_and_no_ambient_auth(wire, monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://synthetic.invalid:99")
    wire.reply()
    client = PortalListClient(cookie())
    assert client.fetch_list_page(1)["data"][0]["pstNo"] == "1"
    request, kwargs = wire.calls[0]
    assert request.method == "GET"
    assert urlsplit(request.url).path == "/wz/api/board/recents"
    assert parse_qs(urlsplit(request.url).query, keep_blank_values=True)["pstNo"] == [""]
    assert request.headers["Cookie"] == "JSESSIONID=" + SECRET
    assert "Authorization" not in request.headers
    assert kwargs["verify"] is True and not kwargs["proxies"]
    client.close()
    assert len(client._session.cookies) == 0
    with pytest.raises(AuthRequired):
        client.fetch_list_page(1)
    assert len(wire.calls) == 1


@pytest.mark.parametrize("method,url", [
    ("GET", LIST_URL + "/123"), ("GET", LIST_URL + "/"),
    ("GET", LIST_URL + "%2f123"), ("POST", LIST_URL),
    ("GET", LIST_URL.replace("portal.kaist.ac.kr", "other.invalid")),
    ("GET", LIST_URL.replace("https:", "http:")),
    ("GET", LIST_URL.replace("portal.kaist.ac.kr", "portal.kaist.ac.kr:443")),
    ("GET", "https://portal.kaist.ac.kr/auth/login"),
])
def test_prepared_request_guard_blocks_before_network(wire, method, url):
    request = requests.Request(method, url, params=list_query(1)).prepare()
    with sessions._ListSession() as transport, pytest.raises(UiContractError):
        transport.send(request)
    assert wire.calls == []


@pytest.mark.parametrize("change", [
    {"pstNo": "123"}, {"menuNo": "22"}, {"pageIndex": "0"},
    {"pageIndex": "01"}, {"loginId": "SYNTHETIC-ID"}, {"recordCountPerPage": "100"},
])
def test_query_guard_rejects_identity_and_unverified_parameters(wire, change):
    request = requests.Request("GET", LIST_URL, params={**list_query(1), **change}).prepare()
    with sessions._ListSession() as transport, pytest.raises(UiContractError):
        transport.send(request)
    assert wire.calls == []


def test_duplicate_query_fragment_and_invalid_page_rejected(wire):
    url = LIST_URL + "?" + urlencode(list_query(1))
    for invalid in (url + "&pstNo=", url + "#fragment"):
        with pytest.raises(UiContractError):
            require_list_request("GET", invalid)
    for value in (True, 0, -1, "1", 10001):
        with pytest.raises(UiContractError):
            PortalListClient(cookie()).fetch_list_page(value)
    assert not wire.calls


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308, 401, 403])
def test_auth_or_redirect_stops_without_followup_and_clears_cookie(wire, status):
    wire.reply(status=status, headers={"Location": "https://sso.invalid/auth/" + SECRET})
    client = PortalListClient(cookie())
    with pytest.raises(AuthRequired) as error:
        client.fetch_list_page(1)
    assert SECRET not in str(error.value)
    assert len(wire.calls) == 1 and not client._session.cookies


@pytest.mark.parametrize("status,body,headers", [
    (200, b"<html>login</html>", {"Content-Type": "text/html"}),
    (200, b"not json", {"Content-Type": "application/json"}),
    (200, b'{"data": []}', {"Content-Type": "application/json"}),
    (404, b"private", {}),
    (200, b"x" * 2_000_001, {"Content-Type": "application/json"}),
], ids=["html", "invalid-json", "changed-schema", "not-found", "oversized"])
def test_bad_response_not_auth_success(wire, status, body, headers):
    wire.reply(status=status, body=body, headers=headers)
    client = PortalListClient(cookie())
    with pytest.raises(UiContractError):
        client.fetch_list_page(1)
    assert not client._session.cookies


def test_timeout_and_rate_limit_are_not_auth_expiry(wire):
    client = PortalListClient(cookie())
    wire.replies.append(requests.Timeout(SECRET))
    with pytest.raises(ListTransportError) as error:
        client.fetch_list_page(1)
    assert SECRET not in str(error.value)
    wire.reply(status=429, headers={"Retry-After": "120"})
    with pytest.raises(ListTransportError) as error:
        client.fetch_list_page(1)
    assert error.value.retry_after == 120
    wire.reply(status=503)
    with pytest.raises(ListTransportError):
        client.fetch_list_page(1)
    client.close()
    assert sessions.retry_after_seconds("Tue, 22 Sep 2026 00:02:00 GMT", NOW.timestamp()) == 120


def test_response_wall_budget_is_bounded(wire):
    wire.reply()
    ticks = iter([0, 21])
    client = PortalListClient(cookie(), monotonic=lambda: next(ticks))
    with pytest.raises(ListTransportError):
        client.fetch_list_page(1)
    client.close()


@pytest.mark.parametrize("overrides", [
    {"secure": False}, {"domain": "sso.kaist.ac.kr"}, {"path": "/wz/api/board/recent"},
    {"path": "/other"}, {"expires": NOW.timestamp() - 1}, {"value": ""},
    {"value": SECRET + "\r\n"}, {"partitionKey": "https://other.invalid"},
    {"secure": "true"}, {"domain": None}, {"expires": "tomorrow"}, {"expires": float("nan")},
])
def test_unsupported_cookie_fails_closed(overrides):
    with pytest.raises(AuthRequired):
        sessions._eligible_cookie([cookie(**overrides)], NOW.timestamp())


def provider_for(client, cookies=None, contexts=1):
    attach_calls = []
    browser_contexts = [SimpleNamespace(cookies=Mock(return_value=cookies or [cookie()]))
                        for _ in range(contexts)]
    pages = [SimpleNamespace(url="https://portal.kaist.ac.kr/", context=c)
             for c in browser_contexts]

    @contextmanager
    def attach(*args, **kwargs):
        attach_calls.append(kwargs)
        yield SimpleNamespace(context=SimpleNamespace(pages=pages))

    owner = Mock()
    factory = Mock(return_value=client)
    provider = PortalSessionProvider("synthetic-profile", 9223, owner_check=owner,
                                     attach=attach, client_factory=factory,
                                     wall_time=lambda: NOW.timestamp())
    return provider, attach_calls, factory, owner, browser_contexts


def test_handoff_once_without_navigation_then_polls_have_no_browser(tmp_path):
    client = Pages([page([row()])])
    provider, attachments, factory, owner, contexts = provider_for(client)
    beats, sleeps, logs = [], [], []
    result = run_poller(provider, PortalListState(tmp_path / "state"), emit_heartbeat=beats.append,
                        max_cycles=3, interval=30, sleep=sleeps.append, monotonic=lambda: 0,
                        now=lambda: NOW, log=logs.append)
    assert result == 0 and client.closed and len(attachments) == 1
    assert attachments[0]["attach_only"] and attachments[0]["start_url"] == ""
    owner.assert_called_once()
    contexts[0].cookies.assert_called_once_with([LIST_URL])
    assert factory.call_count == 1 and client.calls == [1, 1, 1, 1]
    assert sleeps == [30, 30]
    assert all(set(b) == set(FIELDS) and b["agent_id"] == "portal-list-poller" for b in beats)
    assert all(b["last_publish_at"] is None for b in beats)
    assert SECRET not in json.dumps(beats) + " ".join(logs)


@pytest.mark.parametrize("contexts,cookies", [(0, None), (2, None), (1, [cookie(), cookie(path="/wz")]),
                                               (1, [{"name": "other"}])])
def test_handoff_missing_or_ambiguous_context_cookie_makes_zero_http(contexts, cookies):
    client = Pages([])
    provider, _, factory, _, _ = provider_for(client, cookies=cookies, contexts=contexts)
    with pytest.raises(AuthRequired):
        provider.acquire()
    factory.assert_not_called()
    assert not client.calls


def test_failed_owner_attestation_never_reads_browser():
    client = Pages([])
    provider, attachments, factory, owner, _ = provider_for(client)
    owner.side_effect = AuthRequired("safe")
    with pytest.raises(AuthRequired):
        provider.acquire()
    assert not attachments and not client.calls


@pytest.mark.skipif(sessions.os.name != "nt", reason="Windows process attestation")
def test_windows_owner_attestation_matches_exact_profile(monkeypatch, tmp_path):
    profile = tmp_path / "dedicated profile"
    args = ["chrome.exe", "--remote-debugging-port=9223", "--remote-debugging-address=127.0.0.1",
            "--user-data-dir=" + str(profile)]
    run = Mock(return_value=SimpleNamespace(stdout=subprocess.list2cmdline(args)))
    monkeypatch.setattr(sessions.subprocess, "run", run)
    sessions.verify_resident_owner(profile, 9223)
    assert "127.0.0.1" in run.call_args.args[0][-1]
    with pytest.raises(AuthRequired):
        sessions.verify_resident_owner(tmp_path / "other", 9223)
    with pytest.raises(AuthRequired):
        sessions.verify_resident_owner(profile, 9224)


def make_baseline(tmp_path, rows=None):
    state = PortalListState(tmp_path / "state.json")
    client = Pages([page(rows if rows is not None else [row()])])
    poller = PortalListPoller(client, state)
    counts = poller.poll_once()
    assert counts["baseline"] and not counts["new"] and not counts["pending"]
    return state, client, poller


def test_baseline_no_historical_alert_then_equal_dates_nonmonotonic_ids(tmp_path):
    state, client, poller = make_baseline(tmp_path, [row("900")])
    client.pages = [page([row("2"), row("1"), row("900")])]
    counts = poller.poll_once()
    assert counts["new"] == counts["candidates"] == counts["pending"] == 2
    assert poller.poll_once()["new"] == 0
    text = state.path.read_text(encoding="utf-8")
    for secret in (SECRET, PRIVATE, "SYNTHETIC-BOARD", "pstNo", "pstTtl", "writerEmail", "pstCn"):
        assert secret not in text
    restored = PortalListState(state.path)
    assert PortalListPoller(client, restored).poll_once()["new"] == 0


@pytest.mark.parametrize("public", ["N", "", "y", "unknown"])
def test_only_exact_public_y_is_a_candidate(tmp_path, public):
    state, client, poller = make_baseline(tmp_path, [])
    client.pages = [page([row(public=public)])]
    assert poller.poll_once()["pending"] == 0


@pytest.mark.parametrize("bad", [None, True, 1])
def test_invalid_public_state_does_not_advance_checkpoint(tmp_path, bad):
    state, client, poller = make_baseline(tmp_path)
    before = state.path.read_bytes()
    client.pages = [page([row(public=bad)])]
    with pytest.raises(UiContractError):
        poller.poll_once()
    assert state.path.read_bytes() == before


def test_updates_and_withdrawal_remove_pending_without_detail(tmp_path):
    state, client, poller = make_baseline(tmp_path, [])
    client.pages = [page([row()])]
    assert poller.poll_once()["pending"] == 1
    client.pages = [page([row(title="설명회 변경")])]
    assert poller.poll_once()["updated"] == 1
    client.pages = [page([row(public="N")])]
    assert poller.poll_once()["pending"] == 0


def test_pagination_overlap_reordering_and_burst(tmp_path):
    state, client, poller = make_baseline(tmp_path, [row("old")])
    first = [row(str(n)) for n in range(10)]
    second = [row(str(n)) for n in range(9, 19)]
    third = [row(str(n)) for n in range(19, 25)]
    client.pages = [page(first, 1, 4), page(second[::-1], 2, 4), page(third, 3, 4), page([row("old")], 4, 4)]
    counts = poller.poll_once()
    assert counts["pages"] == 4 and counts["new"] == 25
    assert counts["pending"] == 25


def test_page_cap_failure_and_conflicting_snapshot_never_advance(tmp_path):
    state, client, _ = make_baseline(tmp_path, [row("old")])
    before = state.path.read_bytes()
    client.pages = [page([row("a")], 1, 3), page([row("b")], 2, 3)]
    poller = PortalListPoller(client, state, max_pages=2)
    with pytest.raises(ScanIncomplete):
        poller.poll_once()
    assert before == state.path.read_bytes()
    client.pages = [page([row("a")], 1, 2), page([row("a", title="changed")], 2, 2)]
    with pytest.raises(ScanIncomplete):
        poller.poll_once()
    assert before == state.path.read_bytes()


def test_state_write_failure_retries_same_detection(monkeypatch, tmp_path):
    state, client, poller = make_baseline(tmp_path)
    client.pages = [page([row("new"), row()])]
    original = deepcopy(state.data)
    with monkeypatch.context() as patch:
        patch.setattr("ggongbab.portal_list_state.os.replace", Mock(side_effect=OSError(SECRET)))
        with pytest.raises(ListStateError) as error:
            poller.poll_once()
        assert SECRET not in str(error.value) and state.data == original
    assert poller.poll_once()["new"] == 1


def test_corrupt_state_fails_closed_and_lock_releases(tmp_path):
    path = tmp_path / "state"
    path.write_text("broken", encoding="utf-8")
    with pytest.raises(ListStateError):
        PortalListState(path)
    lock = tmp_path / "lock"
    with poller_lock(lock):
        with pytest.raises(ListStateError), poller_lock(lock):
            pass
    with poller_lock(lock):
        pass


@pytest.mark.parametrize("failure,code,status", [(AuthRequired(SECRET), 10, "auth_required"),
                                                (UiContractError(SECRET), 20, "ui_changed")])
def test_poll_failure_stops_without_reacquiring_and_preserves_heartbeat(tmp_path, failure, code, status):
    state, client, _ = make_baseline(tmp_path)
    client.pages = [failure]
    provider = SimpleNamespace(acquire=Mock(return_value=client))
    beats, logs = [], []
    assert run_poller(provider, state, emit_heartbeat=beats.append, log=logs.append,
                      sleep=lambda _: pytest.fail("must stop"), now=lambda: NOW) == code
    assert provider.acquire.call_count == 1 and client.closed
    assert beats[-1]["status"] == status and beats[-1]["last_success_at"] is None
    healthy = {**beats[-1], "last_success_at": (NOW - timedelta(minutes=1)).isoformat()}
    assert merge_heartbeat(healthy, beats[-1])["last_success_at"] == healthy["last_success_at"]
    assert SECRET not in json.dumps(beats) + "".join(logs)


@pytest.mark.parametrize("interval", [30, 60])
def test_backoff_retry_after_and_cadence_with_fake_clock(tmp_path, interval):
    class Recovering:
        def __init__(self):
            self.calls = 0
        def fetch_list_page(self, _index):
            self.calls += 1
            if self.calls == 1:
                raise ListTransportError(180)
            return page([])
        def close(self):
            pass
    provider = SimpleNamespace(acquire=Mock(return_value=Recovering()))
    beats, sleeps = [], []
    assert run_poller(provider, PortalListState(tmp_path / "state"), emit_heartbeat=beats.append,
                      interval=interval, max_cycles=3, monotonic=lambda: 0,
                      sleep=sleeps.append, log=lambda _: None) == 0
    assert sum(sleeps) == 180 + interval and max(sleeps) <= 30
    assert [b["status"] for b in beats] == ["collector_error", "healthy", "healthy"]


def test_heartbeat_failure_stops_and_does_not_publish(tmp_path):
    client = Pages([page([])])
    logs = []
    assert run_poller(SimpleNamespace(acquire=lambda: client), PortalListState(tmp_path / "state"),
                      emit_heartbeat=Mock(side_effect=RuntimeError(SECRET)), log=logs.append) == 1
    assert client.closed and len(client.calls) == 1 and SECRET not in "".join(logs)


def test_cli_list_mode_never_enters_legacy_detail_or_writer(monkeypatch, tmp_path):
    monkeypatch.setattr(agent, "LOCAL_DIR", tmp_path)
    monkeypatch.setattr(agent, "log", lambda _: None)
    monkeypatch.setattr(agent, "load_settings", lambda: SimpleNamespace(has_supabase=False))
    monkeypatch.setattr(agent, "_require_contract", lambda: pytest.fail("legacy detail contract"))
    monkeypatch.setattr(agent, "TaskWriter", lambda _: pytest.fail("task writer"))
    monkeypatch.setattr(agent, "fetch_detail", lambda *a: pytest.fail("detail"))
    client = Pages([page([])])
    acquire = Mock(return_value=client)
    monkeypatch.setattr(sessions.PortalSessionProvider, "acquire", acquire)
    assert agent.main(["--poll-list", "--cdp", "--once", "--local-only"]) == 0
    assert acquire.call_count == 1 and (tmp_path / "portal-list-state.json").exists()
    assert not known_contract().detail_ready()


def test_cli_missing_heartbeat_config_fails_before_handoff(monkeypatch):
    monkeypatch.setattr(agent, "log", lambda _: None)
    monkeypatch.setattr(agent, "load_settings", lambda: SimpleNamespace(has_supabase=False))
    acquire = Mock(side_effect=AssertionError("No handoff"))
    monkeypatch.setattr(sessions.PortalSessionProvider, "acquire", acquire)
    assert agent.main(["--poll-list", "--cdp", "--once"]) == 1
    acquire.assert_not_called()


def test_cookie_rotation_and_ambiguity_never_send_extra_cookie(wire):
    client = PortalListClient(cookie())
    # Model the cookie-jar result of a legitimate same-scope Set-Cookie rotation.
    client._session.cookies.set("JSESSIONID", "SYNTHETIC-ROTATED", domain="portal.kaist.ac.kr",
                                path="/", secure=True)
    wire.reply()
    client.fetch_list_page(1)
    assert wire.calls[0][0].headers["Cookie"] == "JSESSIONID=SYNTHETIC-ROTATED"
    client._session.cookies.set("JSESSIONID", SECRET, domain="portal.kaist.ac.kr",
                                path="/wz", secure=True)
    with pytest.raises(AuthRequired):
        client.fetch_list_page(1)
    assert len(wire.calls) == 1 and not client._session.cookies


def test_expired_cookie_stops_before_request(wire):
    client = PortalListClient(cookie())
    client._session.cookies.set("JSESSIONID", SECRET, domain="portal.kaist.ac.kr",
                                path="/", secure=True, expires=1)
    with pytest.raises(AuthRequired):
        client.fetch_list_page(1)
    assert wire.calls == []


def test_metadata_ignores_body_and_view_counts_and_normalizes_kst(tmp_path):
    state, client, poller = make_baseline(tmp_path)
    changed = row()
    changed.update(pstCn="SYNTHETIC-CHANGED-BODY", inqCnt=1234,
                   regDt="2026-09-22T00:00:00+00:00")
    client.pages = [page([changed])]
    assert poller.poll_once()["updated"] == 0
    assert next(iter(state.data["notices"].values()))["reg_dt"] == NOW.isoformat()


def test_failed_handoff_does_not_leave_client_or_cookie(wire):
    client = PortalListClient(cookie())
    provider, attachments, _, _, _ = provider_for(client)
    wire.reply(status=401)
    with pytest.raises(AuthRequired):
        provider.acquire()
    assert len(attachments) == 1 and len(wire.calls) == 1 and not client._session.cookies


def test_cli_heartbeat_uses_existing_rpc_with_no_publication(monkeypatch, tmp_path):
    monkeypatch.setattr(agent, "LOCAL_DIR", tmp_path)
    monkeypatch.setattr(agent, "log", lambda _: None)
    monkeypatch.setattr(agent, "load_settings", lambda: SimpleNamespace(
        has_supabase=True, supabase_url="https://synthetic.invalid", supabase_secret_key="SYNTHETIC-DB"))
    db = Mock()
    monkeypatch.setattr("ggongbab.db.supabase_client.SupabaseClient", Mock(return_value=db))
    monkeypatch.setattr(sessions.PortalSessionProvider, "acquire", lambda _: Pages([page([])]))
    assert agent.main(["--poll-list", "--cdp", "--once"]) == 0
    name, args = db.rpc.call_args.args
    assert name == "ggongbab_record_heartbeat"
    assert args["p_agent_id"] == "portal-list-poller" and args["p_status"] == "healthy"
    assert args["p_last_publish_at"] is None
    assert SECRET not in json.dumps(args) and PRIVATE not in json.dumps(args)


def test_restart_after_auth_recovery_reuses_detection_ledger(tmp_path):
    state, _, _ = make_baseline(tmp_path)
    logs, beats = [], []
    failed = SimpleNamespace(acquire=Mock(side_effect=AuthRequired(SECRET)))
    assert run_poller(failed, state, emit_heartbeat=beats.append, log=logs.append, once=True) == 10
    recovered = SimpleNamespace(acquire=lambda: Pages([page([row(), row("new")])]))
    restored = PortalListState(state.path)
    assert run_poller(recovered, restored, emit_heartbeat=beats.append, log=logs.append, once=True) == 0
    assert len(restored.data["pending"]) == 1
    assert [b["status"] for b in beats] == ["auth_required", "healthy"]
    assert SECRET not in "".join(logs)
