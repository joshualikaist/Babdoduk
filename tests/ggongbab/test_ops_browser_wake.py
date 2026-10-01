# -*- coding: utf-8 -*-
"""Discarded/frozen tabs in the shared Ops Chrome: the loopback CDP client and the tab wake.

Measured live (2026-10-01): with 0.4 GB RAM free, Chrome discarded the hidden Portal tab
(`document.wasDiscarded === true`); Playwright's connect_over_cdp then waited on that page and
timed out, for every client. Fakes and a local socket pair only - no browser or service."""
from __future__ import annotations

from contextlib import contextmanager
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import struct
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ggongbab import ops_browser as ob
from ggongbab import ops_browser_control as control
from ggongbab import ops_browser_proof as proof
from ggongbab.cdp_lite import GUID, CdpError, LoopbackCdp, browser_ws_path
from ggongbab.ops_storage import OpsError
from ggongbab.resident_ops import Files, run_worker
from ggongbab.web.exit_codes import AuthRequired
from ggongbab.windows_portal_host import PortalHost

ROOT = Path(__file__).resolve().parents[2]
HOST = "kaist.gov-dooray.com"
SAFE_METHODS = {"Target.getTargets", "Target.attachToTarget", "Target.detachFromTarget", "Runtime.getIsolateId",
                "Target.activateTarget"}


# --- a fake browser-level CDP endpoint for wake_tabs --------------------------------------
class FakeCdp:
    """Pages: {target_id: (url, alive_before, alive_after_activate)}."""
    def __init__(self, pages):
        self.pages, self.calls, self.activated = pages, [], set()
        self.sessions = {}

    def __call__(self, port):
        self.port = port
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def call(self, method, params=None, *, session=None, timeout=5):
        self.calls.append(method)
        params = params or {}
        if method == "Target.getTargets":
            return {"targetInfos": [{"targetId": t, "type": "page", "url": url} for t, (url, *_) in self.pages.items()]
                    + [{"targetId": "w", "type": "shared_worker", "url": "https://" + HOST + "/w.js"}]}
        if method == "Target.attachToTarget":
            sid = "s-" + params["targetId"]
            self.sessions[sid] = params["targetId"]
            return {"sessionId": sid}
        if method == "Runtime.getIsolateId":
            target = self.sessions[session]
            _, before, after = self.pages[target]
            alive = after if target in self.activated else before
            return {"id": "isolate"} if alive else None
        if method == "Target.activateTarget":
            self.activated.add(params["targetId"])
            return {}
        if method == "Target.detachFromTarget":
            return {}
        raise AssertionError("unexpected CDP method " + method)


PORTAL = "https://portal.kaist.ac.kr/"
INBOX = "https://" + HOST + "/mail/systems/inbox"


def test_live_tabs_are_left_alone():
    cdp = FakeCdp({"p": (PORTAL, True, True), "d": (INBOX, True, True)})
    assert ob.wake_tabs(9224, HOST, cdp=cdp) == {"pages": 2, "restored": 0, "roles": []}
    assert "Target.activateTarget" not in cdp.calls and set(cdp.calls) <= SAFE_METHODS
    assert cdp.calls.count("Target.detachFromTarget") == 2


def test_a_discarded_portal_tab_is_restored_by_activation_only():
    cdp = FakeCdp({"p": (PORTAL, False, True), "d": (INBOX, True, True)})
    assert ob.wake_tabs(9224, HOST, cdp=cdp, sleep=lambda _: None) == {"pages": 2, "restored": 1, "roles": ["portal"]}
    assert cdp.activated == {"p"}                           # never the live Dooray tab
    assert set(cdp.calls) <= SAFE_METHODS                    # no navigate, reload, evaluate or close


def test_a_tab_that_stays_dead_fails_closed():
    cdp = FakeCdp({"p": (PORTAL, False, False)})
    ticks = iter(range(0, 1000))
    with pytest.raises(OpsError, match="OPS_BROWSER_TAB_UNRESPONSIVE"):
        ob.wake_tabs(9224, HOST, cdp=cdp, wait=5, sleep=lambda _: None, clock=lambda: next(ticks))
    assert cdp.calls[-1] == "Target.detachFromTarget"        # the probe session is always released


def test_unreadable_targets_fail_closed():
    cdp = Mock()
    cdp.return_value.__enter__ = lambda s: s
    cdp.return_value.__exit__ = lambda *a: None
    cdp.return_value.call.return_value = None
    with pytest.raises(OpsError, match="OPS_BROWSER_TARGETS_UNAVAILABLE"):
        ob.wake_tabs(9224, HOST, cdp=cdp)


# --- the loopback websocket client ---------------------------------------------------------------
def server_frame(obj, opcode=0x1, fin=True):
    data = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
    n = len(data)
    head = bytes([(0x80 if fin else 0) | opcode]) + (bytes([n]) if n < 126 else bytes([126]) + struct.pack("!H", n))
    return head + data


def read_client_frame(sock):
    def need(k):
        data = b""
        while len(data) < k:
            data += sock.recv(k - len(data))
        return data
    first, second = need(2)
    assert second & 0x80, "client frames must be masked"
    n = second & 0x7F
    if n == 126:
        n = struct.unpack("!H", need(2))[0]
    elif n == 127:
        n = struct.unpack("!Q", need(8))[0]
    mask = need(4)
    payload = bytes(b ^ mask[i % 4] for i, b in enumerate(need(n)))
    return first & 0x0F, payload


def test_client_frames_are_masked_and_replies_events_pings_are_handled():
    client_sock, server_sock = socket.socketpair()
    cdp = LoopbackCdp(9224, sock=client_sock)
    seen = {}

    def server():
        opcode, payload = read_client_frame(server_sock)
        message = json.loads(payload)
        seen["request"] = message
        server_sock.sendall(server_frame({"method": "Target.targetCreated", "params": {}}))   # an event
        server_sock.sendall(server_frame(b"hi", opcode=0x9))                                   # a ping
        part = json.dumps({"id": message["id"], "result": {"ok": True}}).encode()
        server_sock.sendall(server_frame(part[:5], fin=False)
                            + bytes([0x80 | 0x0, len(part) - 5]) + part[5:])                  # fragmented
        seen["pong"] = read_client_frame(server_sock)

    thread = threading.Thread(target=server)
    thread.start()
    assert cdp.call("Target.getTargets", {"x": 1}) == {"ok": True}
    thread.join(5)
    assert seen["request"]["method"] == "Target.getTargets" and seen["request"]["params"] == {"x": 1}
    assert seen["pong"] == (0xA, b"hi")
    cdp.close()
    server_sock.close()


def test_no_answer_is_none_and_an_error_reply_is_a_fixed_code():
    client_sock, server_sock = socket.socketpair()
    cdp = LoopbackCdp(9224, sock=client_sock)
    assert cdp.call("Runtime.getIsolateId", session="s", timeout=0.3) is None
    read_client_frame(server_sock)

    def reply_error():
        _, payload = read_client_frame(server_sock)
        server_sock.sendall(server_frame({"id": json.loads(payload)["id"], "error": {"message": "SECRET"}}))

    thread = threading.Thread(target=reply_error)
    thread.start()
    with pytest.raises(CdpError) as caught:
        cdp.call("Target.activateTarget", {"targetId": "t"})
    thread.join(5)
    assert str(caught.value) == "OPS_BROWSER_CDP_ERROR" and "SECRET" not in str(caught.value)
    cdp.close()
    server_sock.close()


def test_handshake_requires_the_exact_accept_key():
    for good in (True, False):
        client_sock, server_sock = socket.socketpair()

        def server():
            request = b""
            while b"\r\n\r\n" not in request:
                request += server_sock.recv(4096)
            key = [line.split(b": ", 1)[1] for line in request.split(b"\r\n") if line.startswith(b"Sec-WebSocket-Key")][0]
            accept = base64.b64encode(hashlib.sha1(key + GUID.encode()).digest()) if good else b"wrong"
            server_sock.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                                b"Connection: Upgrade\r\nSec-WebSocket-Accept: " + accept + b"\r\n\r\n")

        thread = threading.Thread(target=server)
        thread.start()
        client = LoopbackCdp.__new__(LoopbackCdp)
        client.port, client._buffer = 9224, b""
        if good:
            client._handshake(client_sock, "/devtools/browser/x")
        else:
            with pytest.raises(OpsError):
                client._handshake(client_sock, "/devtools/browser/x")
        thread.join(5)
        client_sock.close()
        server_sock.close()


@pytest.mark.parametrize("ws,ok", [("ws://127.0.0.1:9224/devtools/browser/a", True),
                                   ("ws://localhost:9224/devtools/browser/a", False),
                                   ("ws://127.0.0.1:9999/devtools/browser/a", False),
                                   ("wss://127.0.0.1:9224/devtools/browser/a", False),
                                   ("ws://evil.invalid:9224/devtools/browser/a", False)])
def test_the_client_follows_only_the_loopback_endpoint_of_the_same_port(ws, ok):
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return None
        def read(self):
            return json.dumps({"webSocketDebuggerUrl": ws}).encode()
    opener = lambda url, timeout: Response() if url == "http://127.0.0.1:9224/json/version" else None
    if ok:
        assert browser_ws_path(9224, opener=opener) == "/devtools/browser/a"
    else:
        with pytest.raises(OpsError):
            browser_ws_path(9224, opener=opener)


def test_the_client_source_reads_no_content():
    source = (ROOT / "scripts/ggongbab/cdp_lite.py").read_text(encoding="utf-8")
    wake = (ROOT / "scripts/ggongbab/ops_browser.py").read_text(encoding="utf-8")
    for forbidden in ("Runtime.evaluate", "Page.navigate", "Page.reload", "getCookies", "Input.", "closeTarget"):
        assert forbidden not in source and forbidden not in wake
    assert '"127.0.0.1"' in source and "0.0.0.0" not in source


# --- where the wake runs -------------------------------------------------------------------
def test_the_worker_host_wakes_tabs_only_after_the_owner_is_verified(tmp_path):
    order = []
    run = Mock(return_value=json.dumps({"listening": True, "loopback": True, "owners": [7],
                                        "processes": [{"pid": 7, "command": "c", "created": "1"}]}))
    profile = tmp_path.resolve() / ".local" / "portal-browser-profile"
    split = lambda _: ["chrome.exe", f"--user-data-dir={profile}", "--remote-debugging-port=9223",
                       "--remote-debugging-address=127.0.0.1"]
    logs = []
    host = PortalHost(tmp_path, run=run, split=split, start=Mock(), sleep=lambda _: None,
                      verify=lambda *a: order.append("verify"),
                      wake=lambda port, host: order.append(("wake", port)) or {"pages": 1, "restored": 1, "roles": ["portal"]})
    host.ensure(log=logs.append)
    assert order == ["verify", ("wake", 9223)] and "OPS_BROWSER_TAB_RESTORED" in logs
    order.clear()
    host.verify = Mock(side_effect=AuthRequired("PORTAL_RESIDENT_OWNER_UNVERIFIED"))
    with pytest.raises(AuthRequired):
        host.ensure()
    assert order == []                                       # an unverified browser is never touched


@pytest.mark.parametrize("code,expected", [("OPS_BROWSER_TAB_UNRESPONSIVE", "PORTAL_CDP_ATTACH_TIMEOUT"),
                                           ("OPS_BROWSER_TARGETS_UNAVAILABLE", "PORTAL_CDP_ATTACH_TIMEOUT"),
                                           ("PORTAL_RESIDENT_OWNER_UNVERIFIED", "PORTAL_RESIDENT_OWNER_UNVERIFIED")])
def test_a_tab_that_cannot_be_restored_takes_the_known_attach_timeout_path(tmp_path, monkeypatch, code, expected):
    files = Files(tmp_path)
    files.set_enabled(True, 1000)
    seen = {}

    def fake_run(provider, state, **kwargs):
        try:
            provider.acquire()
        except AuthRequired as exc:
            seen["code"] = str(exc)
        return 10

    monkeypatch.setattr("ggongbab.resident_ops.run_poller", fake_run)
    monkeypatch.setattr("ggongbab.db.supabase_client.SupabaseClient", lambda *a: Mock())
    host = Mock(profile=Path("p"), port=9224)
    host.ensure.side_effect = OpsError(code)
    settings = SimpleNamespace(has_supabase=True, supabase_url="https://fake.invalid", supabase_secret_key="fake")
    assert run_worker(files, settings=settings, host=host) == 10
    assert seen["code"] == expected


def workers_module(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("ggongbab_workers_wake", ROOT / "scripts/windows/ggongbab_workers.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    return module


@pytest.mark.parametrize("restored,settle", [([], False), (["portal"], False), (["dooray"], True)])
def test_the_radar_settles_after_its_own_inbox_was_restored(tmp_path, monkeypatch, restored, settle):
    workers = workers_module(tmp_path, monkeypatch)
    contract = SimpleNamespace(require_ready=lambda: None, read_state_key="read", mail_url=INBOX)
    monkeypatch.setattr("ggongbab.web.ui_contract.load_contract", lambda path: contract)
    monkeypatch.setattr("ggongbab.config.load_settings", lambda: SimpleNamespace(has_supabase=False))
    captured = {}
    monkeypatch.setattr("ggongbab.dooray_radar.run_radar", lambda rf, **kw: captured.update(kw) or 0)
    monkeypatch.setattr("ggongbab.portal_session.verify_resident_owner", lambda *a: None)
    monkeypatch.setattr("ggongbab.ops_browser.wake_tabs",
                        lambda port, host: {"pages": 2, "restored": len(restored), "roles": restored})
    order = []
    monkeypatch.setattr(workers.time, "sleep", lambda s: order.append(("sleep", s)))
    inbox = SimpleNamespace(url=INBOX, is_closed=lambda: False)

    @contextmanager
    def resident_session(*a, **k):
        order.append("attach")
        yield SimpleNamespace(context=SimpleNamespace(pages=[inbox]), page=None)

    monkeypatch.setattr("ggongbab.web.resident.resident_session", resident_session)
    assert workers.radar(Files(tmp_path), dry_run=True, once=True) == 0
    with captured["session_factory"]() as session:
        assert session.page is inbox
    assert order == ([("sleep", workers.RESTORE_SETTLE_SECONDS)] if settle else []) + ["attach"]


def test_a_radar_wake_failure_is_a_browser_backoff_without_attach(tmp_path, monkeypatch):
    workers = workers_module(tmp_path, monkeypatch)
    contract = SimpleNamespace(require_ready=lambda: None, read_state_key="read", mail_url=INBOX)
    monkeypatch.setattr("ggongbab.web.ui_contract.load_contract", lambda path: contract)
    monkeypatch.setattr("ggongbab.config.load_settings", lambda: SimpleNamespace(has_supabase=False))
    captured = {}
    monkeypatch.setattr("ggongbab.dooray_radar.run_radar", lambda rf, **kw: captured.update(kw) or 0)
    monkeypatch.setattr("ggongbab.portal_session.verify_resident_owner", lambda *a: None)
    monkeypatch.setattr("ggongbab.ops_browser.wake_tabs", Mock(side_effect=OpsError("OPS_BROWSER_TAB_UNRESPONSIVE")))
    monkeypatch.setattr("ggongbab.web.resident.resident_session", Mock(side_effect=AssertionError("attached")))
    workers.radar(Files(tmp_path), dry_run=True, once=True)
    with pytest.raises(ConnectionError, match="DOORAY_BROWSER_ABSENT"):
        with captured["session_factory"]():
            pass


# --- browser-level helpers used by the proof and the cutover ---------------------------------------
class BrowserLevel(FakeCdp):
    def __init__(self, pid=44, windows=None):
        super().__init__({"p": (PORTAL, True, True), "d": (INBOX, True, True)})
        self.pid, self.windows = pid, windows or {"p": 1, "d": 1}

    def call(self, method, params=None, *, session=None, timeout=5):
        if method == "Browser.getWindowForTarget":
            self.calls.append(method)
            return {"windowId": self.windows[params["targetId"]]}
        if method == "SystemInfo.getProcessInfo":
            self.calls.append(method)
            return {"processInfo": [{"type": "browser", "id": self.pid}, {"type": "renderer", "id": 99}]}
        if method == "Browser.close":
            self.calls.append(method)
            return {}
        return super().call(method, params, session=session, timeout=timeout)


def test_window_ids_never_attach_to_a_page():
    cdp = BrowserLevel(windows={"p": 1, "d": 2})
    assert proof.window_ids(9224, cdp=cdp) == {1, 2}
    assert "Target.attachToTarget" not in cdp.calls


def test_the_close_is_sent_only_to_the_verified_browser_pid():
    cdp = BrowserLevel(pid=44)
    with pytest.raises(OpsError, match="OPS_BROWSER_UNVERIFIED"):
        control._cdp_close(9222, 45, cdp=cdp)
    assert "Browser.close" not in cdp.calls
    control._cdp_close(9222, 44, cdp=cdp)
    assert cdp.calls[-1] == "Browser.close" and "Target.attachToTarget" not in cdp.calls
