# -*- coding: utf-8 -*-
"""Opt-in real-browser check of the shared Ops Chrome layer (BABDODUK_REAL_CHROME=1, Windows).

Uses the installed Google Chrome with a THROWAWAY profile under pytest's tmp_path, a throwaway
loopback port and two local pages on two hostnames (127.0.0.1 and localhost). No Portal, Dooray,
account, cookie or the owner's own Chrome profile is involved, and only the Chrome this test
started is closed. It proves on a real browser what the unified design relies on:
  * the start addresses open as two tabs of ONE window;
  * the owner check verifies the real process by profile, port and loopback address;
  * two CDP clients (two threads, two Playwright drivers) are attached at the same time;
  * neither client closes Chrome, closes or navigates the other's tab, or opens a window;
  * detaching leaves Chrome running with every tab where it was;
  * `PUT /json/new` adds a tab to the existing window, not a new window;
  * the graceful close is bound to the verified browser PID.
"""
from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import socket
import threading
import time
from urllib.parse import urlsplit

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("BABDODUK_REAL_CHROME") != "1" or os.name != "nt",
                                reason="opt-in: set BABDODUK_REAL_CHROME=1 on Windows with Google Chrome")


class Pages(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = f"<html><head><title>{self.path}</title></head><body>{self.path}</body></html>".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def pages_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Pages)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()


def by_host(context, host):
    return [p for p in context.pages if urlsplit(p.url).hostname == host]


def test_one_real_chrome_serves_two_concurrent_cdp_clients(tmp_path, pages_server):
    from ggongbab import ops_browser as ob
    from ggongbab.ops_browser_control import _cdp_close
    from ggongbab.ops_browser_proof import window_ids
    from ggongbab.portal_session import verify_resident_owner
    from ggongbab.web.resident import is_running, resident_session, start_chrome
    from ggongbab.web.ui_contract import UiContract
    from ggongbab.windows_portal_host import ResidentHost

    port = free_port()
    profile = (tmp_path / "ops-browser-profile").resolve()
    url_a = f"http://127.0.0.1:{pages_server}/portal-like"
    url_b = f"http://localhost:{pages_server}/mail/inbox"
    process = start_chrome(profile, port=port, start_urls=(url_a, url_b), log=lambda *_: None)
    try:
        pages = ob.wait_for_settled_pages(port, settle=2, timeout=30)
        assert sorted(urlsplit(p["url"]).hostname for p in pages) == ["127.0.0.1", "localhost"]
        host = ResidentHost(tmp_path, slot=ob.BrowserSlot(profile, port, True))
        state, owner = host.inspect()
        assert state == "verified"
        verify_resident_owner(profile, port)
        windows = window_ids(port)
        assert len(windows) == 1                            # two tabs, one window

        barrier = threading.Barrier(2, timeout=60)
        results = {}

        def client(name, url):
            hostname = urlsplit(url).hostname
            try:
                with resident_session(profile, UiContract(mail_url=url), start_url="", port=port,
                                      attach_only=True, log=lambda *_: None) as session:
                    attached = time.monotonic()
                    mine = by_host(session.context, hostname)
                    assert len(mine) == 1
                    barrier.wait()                          # both clients attached right now
                    status = mine[0].request.get(url).status
                    title = mine[0].evaluate("document.title")
                    others = [p.url for p in session.context.pages if p not in mine]
                results[name] = {"attached": attached, "detached": time.monotonic(), "status": status,
                                 "title": title, "others": others}
            except BaseException as exc:  # noqa: BLE001
                barrier.abort()
                results[name] = {"error": repr(exc)}

        threads = [threading.Thread(target=client, args=("a", url_a)), threading.Thread(target=client, args=("b", url_b))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(120)
        assert "error" not in results["a"] and "error" not in results["b"], results
        a, b = results["a"], results["b"]
        assert a["attached"] < b["detached"] and b["attached"] < a["detached"]   # overlapping clients
        assert a["status"] == b["status"] == 200
        assert a["title"] == "/portal-like" and b["title"] == "/mail/inbox"

        after = ob.page_targets(port)
        assert {p["id"]: p["url"] for p in after} == {p["id"]: p["url"] for p in pages}   # nothing closed/moved
        assert is_running(port) and host.inspect() == ("verified", owner)                 # same live process
        assert window_ids(port) == windows                                               # no new window

        ob.new_tab(port, f"http://127.0.0.1:{pages_server}/third")
        time.sleep(1)
        assert len(ob.page_targets(port)) == 3 and window_ids(port) == windows           # tab, not window

        # A hidden tab that Chrome froze must not block attaching: wake_tabs restores it.
        from ggongbab.cdp_lite import LoopbackCdp
        hidden = [p for p in ob.page_targets(port) if p["url"].endswith("/portal-like")][0]
        with LoopbackCdp(port) as cdp:
            session = cdp.call("Target.attachToTarget", {"targetId": hidden["id"], "flatten": True})["sessionId"]
            cdp.call("Page.setWebLifecycleState", {"state": "frozen"}, session=session)
            cdp.call("Target.detachFromTarget", {"sessionId": session})
        woke = ob.wake_tabs(port, "")
        assert woke["pages"] == 3 and set(woke["roles"]) <= {"other"}
        from playwright.sync_api import sync_playwright
        from ggongbab.web.resident import endpoint
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(endpoint(port), timeout=20_000)   # no hang
            assert len(browser.contexts[0].pages) == 3
            browser.close()
        assert {p["id"] for p in ob.page_targets(port)} >= {p["id"] for p in pages}       # nothing closed

        with pytest.raises(Exception):
            _cdp_close(port, owner["pid"] + 1)               # a different PID is never closed
        assert is_running(port)
        _cdp_close(port, owner["pid"])
        process.wait(timeout=30)
        assert host.inspect()[0] == "absent"
        assert profile.is_dir()                              # the profile itself is kept
    finally:
        if process.poll() is None:
            process.terminate()                              # only the Chrome this test started
            process.wait(timeout=30)
