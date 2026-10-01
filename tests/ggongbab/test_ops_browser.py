# -*- coding: utf-8 -*-
"""Unified Babdoduk Ops Chrome: one dedicated Chrome, one profile, one loopback CDP port, two
independent workers. Fakes only - no services, task registration, live Portal/Dooray or real
browser (the real-Chrome concurrency check is the opt-in test_ops_browser_real_chrome.py)."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ggongbab import dooray_radar as radar
from ggongbab import ops_browser as ob
from ggongbab import ops_browser_control as control
from ggongbab import ops_browser_proof as proof
from ggongbab.alerts import radar_alert
from ggongbab.config import KST
from ggongbab.ops_policy import DOORAY_PORT, PORTAL_PORT, REASONS
from ggongbab.ops_storage import OpsError, atomic_json
from ggongbab.portal_list_contract import LIST_URL
from ggongbab.portal_list_state import poller_lock
from ggongbab.portal_session import PortalSessionProvider
from ggongbab.resident_ops import Files, ops_browser_lines, status_lines
from ggongbab.web.exit_codes import AuthRequired
from ggongbab.windows_portal_host import INVENTORY_SCRIPT, STOP_SCRIPT, PortalHost, ResidentHost

ROOT = Path(__file__).resolve().parents[2]
SECRET = "SYNTHETIC-SECRET-TITLE"
PORTAL_URL = "https://portal.kaist.ac.kr/index.html?token=" + SECRET
DOORAY_URL = "https://kaist.gov-dooray.com/mail/systems/inbox?q=" + SECRET
SSO_URL = "https://sso.kaist.ac.kr/auth/twofactor/mfa/login2Fact?state=" + SECRET
DOORAY_LOGIN = "https://kaist.gov-dooray.com/idp/multi?next=" + SECRET


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("LIVE_OPERATION_FORBIDDEN")
    monkeypatch.setattr("urllib.request.urlopen", forbidden)
    monkeypatch.setattr("requests.sessions.Session.send", forbidden)
    monkeypatch.setattr("subprocess.Popen", forbidden)
    monkeypatch.setattr("subprocess.run", forbidden)


def write_contract(root):
    atomic_json(Path(root) / ".local" / "dooray-ui.json",
                {"mail_url": "https://kaist.gov-dooray.com/mail/systems/inbox?filter=" + SECRET})


# --- profile, port, mode ------------------------------------------------------------------
def test_unified_profile_and_port_are_new_and_loopback(tmp_path):
    slot = ob.unified_slot(tmp_path)
    assert slot.profile == tmp_path.resolve() / ".local" / "ops-browser-profile" and slot.unified
    assert slot.port == ob.UNIFIED_PORT == 9224 and slot.port not in (PORTAL_PORT, DOORAY_PORT)
    assert {ob.legacy_slot(tmp_path, r).profile.name for r in ("portal", "dooray")} == {
        "portal-browser-profile", "dooray-browser-profile"}
    code = " ".join(line.split("#", 1)[0] for line in
                    (ROOT / "scripts/ggongbab/ops_browser.py").read_text(encoding="utf-8").splitlines())
    assert "0.0.0.0" not in code and "localhost" not in code


def test_absent_mode_file_keeps_the_legacy_browsers_until_the_operator_switches(tmp_path):
    assert ob.read_mode(tmp_path / ".local") == "separate"
    assert ob.slot_for(tmp_path, "portal") == ob.legacy_slot(tmp_path, "portal")
    assert ob.slot_for(tmp_path, "dooray") == ob.legacy_slot(tmp_path, "dooray")
    ob.set_mode(tmp_path / ".local", "unified")
    assert ob.slot_for(tmp_path, "portal") == ob.slot_for(tmp_path, "dooray") == ob.unified_slot(tmp_path)
    ob.set_mode(tmp_path / ".local", "separate")              # the rollback
    assert ob.slot_for(tmp_path, "dooray").port == DOORAY_PORT


@pytest.mark.parametrize("content", [{"mode": "UNIFIED"}, {"mode": "unified", "x": 1}, {"other": 1}])
def test_corrupt_mode_file_fails_closed(tmp_path, content):
    atomic_json(tmp_path / ".local" / ob.MODE_FILE, content)
    with pytest.raises(OpsError):
        ob.slot_for(tmp_path, "portal")
    with pytest.raises(OpsError):
        ob.set_mode(tmp_path / ".local", "both")


def test_start_arguments_one_profile_loopback_two_tabs(monkeypatch, tmp_path):
    from ggongbab.web import resident
    captured = {}
    exe = tmp_path / "chrome.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(resident, "WINDOWS_CHROME_PATHS", (str(exe),))
    monkeypatch.setattr(resident.subprocess, "Popen",
                        lambda args, **_: captured.setdefault("args", args) and SimpleNamespace(poll=lambda: None))
    monkeypatch.setattr(resident, "is_running", lambda *_a, **_k: {"Browser": "Chrome/1"})
    slot = ob.unified_slot(tmp_path)
    resident.start_chrome(slot.profile, port=slot.port, start_urls=(ob.PORTAL_START, ob.DOORAY_FALLBACK),
                          log=lambda *_: None)
    args = captured["args"]
    assert args[1:6] == ["--remote-debugging-address=127.0.0.1", "--remote-debugging-port=9224",
                         f"--user-data-dir={slot.profile}", "--no-first-run", "--no-default-browser-check"]
    assert args[6:] == [ob.PORTAL_START, ob.DOORAY_FALLBACK]   # tabs of ONE window, no --new-window
    assert not any("0.0.0.0" in a or "User Data" in a or "--new-window" in a for a in args)


# --- shared-layer start / tabs -------------------------------------------------------------
def fake_targets(*urls):
    return lambda port: [{"id": f"t{i}", "url": url} for i, url in enumerate(urls)]


def test_tabs_are_opened_only_for_a_missing_role_on_loopback():
    opened = []

    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return None
        def read(self):
            return b"{}"

    calls = []
    def targets(port):
        calls.append(port)
        return [{"id": "a", "url": PORTAL_URL}] if len(calls) == 1 else [
            {"id": "a", "url": PORTAL_URL}, {"id": "b", "url": DOORAY_URL}]
    counts = ob.ensure_tabs(9224, "kaist.gov-dooray.com", ob.DOORAY_FALLBACK, targets=targets,
                            opener=lambda r, timeout: opened.append((r.get_method(), r.full_url)) or Response())
    assert counts == {"portal": 1, "dooray": 1, "sso": 0, "inbox": 1}
    assert opened == [("PUT", "http://127.0.0.1:9224/json/new?" + ob.DOORAY_FALLBACK)]
    assert ob.ensure_tabs(9224, "kaist.gov-dooray.com", ob.DOORAY_FALLBACK,
                          targets=fake_targets(PORTAL_URL, DOORAY_URL), opener=Mock())["portal"] == 1
    with pytest.raises(OpsError):
        ob.open_tab(9224, "http://portal.kaist.ac.kr/")       # https only
    with pytest.raises(OpsError):
        ob.open_tab(9224, "https://x.invalid/?a=1")           # no query values


def test_no_tab_is_opened_while_a_kaist_sso_login_page_is_open():
    """Before login the Portal tab sits on the KAIST SSO page; opening another Portal tab
    then would duplicate it."""
    opener = Mock()
    counts = ob.ensure_tabs(9224, "kaist.gov-dooray.com", ob.DOORAY_FALLBACK,
                            targets=fake_targets(SSO_URL, DOORAY_LOGIN), opener=opener)
    opener.assert_not_called()
    assert counts == {"portal": 0, "dooray": 1, "sso": 1, "inbox": 0}


def test_fresh_profile_starts_with_both_tabs_used_profile_restores_instead(tmp_path):
    starts = []
    start = lambda profile, **kw: starts.append(kw)
    ensured = []
    ensure = lambda port, host, url, roles, log: ensured.append(roles)
    slot = ob.unified_slot(tmp_path)
    ob.start_dedicated(slot.profile, port=slot.port, roles=("portal", "dooray"), dooray_url=ob.DOORAY_FALLBACK,
                       mail_host="kaist.gov-dooray.com", start=start, settled=lambda port: [], ensure=ensure)
    assert starts[-1]["start_urls"] == (ob.PORTAL_START, ob.DOORAY_FALLBACK) and starts[-1]["port"] == 9224
    (slot.profile / "Default").mkdir(parents=True)
    (slot.profile / "Default" / "Preferences").write_text("{}", encoding="utf-8")
    ob.start_dedicated(slot.profile, port=slot.port, roles=("portal", "dooray"), dooray_url=ob.DOORAY_FALLBACK,
                       mail_host="kaist.gov-dooray.com", start=start, settled=lambda port: [], ensure=ensure)
    assert starts[-1]["start_urls"] == () and ensured == [("portal", "dooray")] * 2


def test_settling_waits_for_session_restore_to_stop_adding_pages():
    seen = iter([[], [{"id": "a"}], [{"id": "a"}, {"id": "b"}]] + [[{"id": "a"}, {"id": "b"}]] * 20)
    clock = iter(range(0, 100))
    pages = ob.wait_for_settled_pages(9224, targets=lambda port: next(seen), settle=2, timeout=50,
                                      sleep=lambda _: None, clock=lambda: next(clock))
    assert [p["id"] for p in pages] == ["a", "b"]


def test_roles_are_exact_https_hostnames():
    host = "kaist.gov-dooray.com"
    assert ob.role_of(PORTAL_URL, host) == "portal" and ob.role_of(DOORAY_URL, host) == "dooray"
    assert ob.role_of(SSO_URL, host) == "sso"
    for url in ("http://portal.kaist.ac.kr/", "https://portal.kaist.ac.kr.evil.invalid/", "http://sso.kaist.ac.kr/",
                "chrome://newtab/", "https://evil.invalid/kaist.gov-dooray.com"):
        assert ob.role_of(url, host) == ""


# --- ownership --------------------------------------------------------------------------
def unified_host(tmp_path, inventory, *, tokens=None, **kw):
    ob.set_mode(tmp_path / ".local", "unified")
    profile = tmp_path.resolve() / ".local" / "ops-browser-profile"
    tokens = tokens or {
        "ops": ["chrome.exe", "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=9224",
                f"--user-data-dir={profile}"],
        "portal": ["chrome.exe", "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=9223",
                   f"--user-data-dir={tmp_path.resolve() / '.local/portal-browser-profile'}"],
        "personal": ["chrome.exe"],
        "renderer": ["chrome.exe", "--type=renderer", f"--user-data-dir={profile}"],
    }
    run = Mock(return_value=json.dumps(inventory))
    start, verify = Mock(), Mock()
    host = PortalHost(tmp_path, run=run, split=lambda value: tokens[value], start=start, verify=verify,
                      sleep=lambda _: None, **kw)
    return host, run, start, verify


OPS = {"pid": 700, "command": "ops", "created": "7000"}
LEGACY_PORTAL = {"pid": 600, "command": "portal", "created": "6000"}
PERSONAL = {"pid": 500, "command": "personal", "created": "5000"}
RENDERER = {"pid": 701, "command": "renderer", "created": "7001"}


def inv(listening=False, processes=(), owners=(), loopback=None):
    return {"listening": listening, "loopback": listening if loopback is None else loopback,
            "processes": list(processes), "owners": list(owners)}


def test_unified_owner_is_verified_by_port_profile_and_loopback(tmp_path):
    host, run, _, _ = unified_host(tmp_path, inv(True, [OPS, LEGACY_PORTAL, PERSONAL, RENDERER], [700]))
    assert host.port == 9224 and host.profile.name == "ops-browser-profile"
    assert host.inspect() == ("verified", OPS)
    assert run.call_args.args == (INVENTORY_SCRIPT, {"port": 9224})   # stdin JSON, not interpolated
    assert "9223" not in INVENTORY_SCRIPT and "9223" not in STOP_SCRIPT


@pytest.mark.parametrize("data", [
    inv(True, [LEGACY_PORTAL], [600]),                 # an unknown (other-profile) listener on 9224
    inv(True, [OPS], [701]),                           # listener owned by another pid
    inv(True, [OPS], [700, 701]),                      # ambiguous owners
    inv(True, [OPS], [700], loopback=False),           # not loopback-only
    inv(True, [], [999]),                              # non-Chrome / unlisted owner
    inv(True, [OPS, dict(OPS, pid=702, created="7002")], [700]),   # two browsers on one profile
])
def test_unknown_or_ambiguous_owner_fails_closed_and_is_never_stopped(tmp_path, data):
    host, run, start, verify = unified_host(tmp_path, data)
    assert host.inspect()[0] == "unverified"
    with pytest.raises(OpsError, match="PORTAL_RESIDENT_OWNER_UNVERIFIED"):
        host.ensure(recover_stale=True)
    start.assert_not_called()
    verify.assert_not_called()
    assert all(call.args[0] != STOP_SCRIPT for call in run.call_args_list)


@pytest.mark.parametrize("flags", [["--remote-debugging-port=9223"], ["--remote-debugging-address=0.0.0.0"],
                                   ["--user-data-dir=C:/elsewhere"]])
def test_wrong_flags_on_the_unified_profile_are_unverified(tmp_path, flags):
    profile = tmp_path.resolve() / ".local" / "ops-browser-profile"
    tokens = {"ops": ["chrome.exe", "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=9224",
                      f"--user-data-dir={profile}", *flags]}
    host, *_ = unified_host(tmp_path, inv(True, [OPS], [700]), tokens=tokens)
    assert host.inspect()[0] == "unverified"


def test_recovery_stops_only_the_verified_unified_process(tmp_path):
    host, run, start, verify = unified_host(tmp_path, inv())
    run.side_effect = [json.dumps(inv(False, [OPS, LEGACY_PORTAL, PERSONAL], [])), "",
                       json.dumps(inv(False, [LEGACY_PORTAL, PERSONAL], []))]
    host._start = Mock()
    host.ensure(recover_stale=True)
    stops = [call.args for call in run.call_args_list if call.args[0] == STOP_SCRIPT]
    assert stops == [(STOP_SCRIPT, dict(OPS, port=9224))]       # exact pid + creation + command line
    host._start.assert_called_once()
    verify.assert_called_once_with(host.profile, 9224)
    assert "CreationDate" in STOP_SCRIPT and "CommandLine -cne" in STOP_SCRIPT and "-Force" not in STOP_SCRIPT


def test_a_worker_start_of_the_unified_browser_opens_both_tabs(tmp_path, monkeypatch):
    write_contract(tmp_path)
    host, run, start, verify = unified_host(tmp_path, inv(False, [LEGACY_PORTAL, PERSONAL], []))
    seen = {}
    monkeypatch.setattr("ggongbab.windows_portal_host.start_dedicated",
                        lambda profile, **kw: seen.update(kw, profile=profile))
    host.ensure()
    assert seen["profile"] == host.profile and seen["port"] == 9224 and seen["roles"] == ("portal", "dooray")
    assert seen["dooray_url"] == "https://kaist.gov-dooray.com/mail/systems/inbox"   # no query value
    assert seen["mail_host"] == "kaist.gov-dooray.com"
    verify.assert_called_once_with(host.profile, 9224)


def test_concurrent_starts_of_the_shared_browser_are_serialised(tmp_path):
    host, *_ = unified_host(tmp_path, inv(True, [OPS], [700]))
    with poller_lock(tmp_path / ".local" / ob.START_LOCK):
        with pytest.raises(OpsError, match="OPS_BROWSER_START_BUSY"):
            host.ensure()
    host.ensure()   # free again: a verified browser is reused, never started twice


# --- page selection: Portal and Dooray in one browser -------------------------------------------
class Page:
    def __init__(self, url, context=None):
        self.url, self.context, self.closed = url, context, False
        self.navigations = []
    def is_closed(self):
        return self.closed
    def goto(self, *a, **k):
        self.navigations.append(a)


def test_dooray_page_is_the_inbox_never_the_portal_tab():
    portal, inbox, other = Page(PORTAL_URL), Page(DOORAY_URL), Page("https://kaist.gov-dooray.com/project")
    ctx = SimpleNamespace(pages=[portal, other, inbox])
    assert radar.dooray_page(ctx, "kaist.gov-dooray.com") is inbox
    assert radar.dooray_page(SimpleNamespace(pages=[portal, other]), "kaist.gov-dooray.com") is other
    for pages in ([portal], [Page("http://kaist.gov-dooray.com/mail/")], []):
        with pytest.raises(ConnectionError, match=radar.BROWSER):
            radar.dooray_page(SimpleNamespace(pages=pages), "kaist.gov-dooray.com")
    assert not portal.navigations and not inbox.navigations


def test_portal_handoff_with_the_dooray_tab_present_reads_only_the_portal_list_cookie():
    context = SimpleNamespace(cookies=Mock(return_value=[{
        "name": "JSESSIONID", "value": "x", "domain": "portal.kaist.ac.kr", "path": "/", "secure": True,
        "expires": -1}]))
    pages = [Page(DOORAY_URL, context), Page(PORTAL_URL, context)]    # ONE shared default context
    calls = []

    @contextmanager
    def attach(*args, **kwargs):
        calls.append(kwargs)
        yield SimpleNamespace(context=SimpleNamespace(pages=pages))

    client = Mock()
    provider = PortalSessionProvider(Path("ops-browser-profile"), 9224, owner_check=Mock(), attach=attach,
                                     client_factory=Mock(return_value=client), wall_time=lambda: 0)
    assert provider.acquire() is client
    context.cookies.assert_called_once_with([LIST_URL])
    client.fetch_list_page.assert_called_once_with(1)
    assert calls[0]["attach_only"] and calls[0]["start_url"] == "" and calls[0]["port"] == 9224
    assert not any(p.navigations for p in pages)
    only_dooray = PortalSessionProvider(Path("p"), 9224, owner_check=Mock(), wall_time=lambda: 0,
        attach=lambda *a, **k: contextmanager(lambda: (yield SimpleNamespace(
            context=SimpleNamespace(pages=[Page(DOORAY_URL, context)]))))())
    with pytest.raises(AuthRequired, match="PORTAL_CONTEXT_MISSING_OR_AMBIGUOUS"):
        only_dooray.acquire()


# --- the Radar on the shared browser ------------------------------------------------------
def workers_module(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("ggongbab_workers_ops_browser",
                                                  ROOT / "scripts/windows/ggongbab_workers.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    return module


@pytest.mark.parametrize("mode,port", [("unified", 9224), ("separate", 9222)])
def test_radar_verifies_the_owner_before_every_attach_and_uses_only_the_dooray_tab(tmp_path, monkeypatch, mode, port):
    workers = workers_module(tmp_path, monkeypatch)
    ob.set_mode(tmp_path / ".local", mode)
    contract = SimpleNamespace(require_ready=lambda: None, read_state_key="read", mail_url=DOORAY_URL)
    monkeypatch.setattr("ggongbab.web.ui_contract.load_contract", lambda path: contract)
    monkeypatch.setattr("ggongbab.config.load_settings", lambda: SimpleNamespace(has_supabase=False))
    captured = {}
    monkeypatch.setattr("ggongbab.dooray_radar.run_radar", lambda rf, **kw: captured.update(kw) or 0)
    owner = Mock(side_effect=AuthRequired("PORTAL_RESIDENT_OWNER_UNVERIFIED"))
    monkeypatch.setattr("ggongbab.portal_session.verify_resident_owner", owner)
    attached = []
    portal, inbox = Page(PORTAL_URL), Page(DOORAY_URL)

    @contextmanager
    def resident_session(profile, contract, **kw):
        attached.append((Path(profile).name, kw))
        yield SimpleNamespace(context=SimpleNamespace(pages=[portal, inbox]), page=portal)

    monkeypatch.setattr("ggongbab.web.resident.resident_session", resident_session)
    probed = []
    monkeypatch.setattr("ggongbab.web.resident.is_running", lambda p: probed.append(p) or {"Browser": "x"})
    assert workers.radar(Files(tmp_path), dry_run=True, once=True) == 0
    assert captured["browser_running"]() is True and probed == [port]
    with pytest.raises(radar.BrowserUnverified):
        with captured["session_factory"]():
            pytest.fail("attached to an unverified browser")
    assert attached == []                                   # no attach without a verified owner
    owner.side_effect = None
    with captured["session_factory"]() as session:
        assert session.page is inbox                         # never the Portal tab
    profile = "ops-browser-profile" if mode == "unified" else "dooray-browser-profile"
    assert owner.call_args.args[1] == port and Path(owner.call_args.args[0]).name == profile
    assert attached[0][0] == profile and attached[0][1]["attach_only"] and attached[0][1]["start_url"] == ""
    assert attached[0][1]["port"] == port and not portal.navigations


def test_an_unverified_radar_browser_backs_off_and_alerts_without_attaching(tmp_path):
    t0 = datetime(2026, 9, 28, 11, 50, tzinfo=KST).timestamp()
    files = radar.RadarFiles(tmp_path)
    files.set_enabled(True, t0)
    beats, waits = [], []
    lister = Mock()

    @contextmanager
    def unverified():
        raise radar.BrowserUnverified()
        yield  # pragma: no cover

    code = radar.run_radar(files, session_factory=unverified, writer=None, list_mails=lister, mail_host="h",
                           heartbeat=lambda *a: beats.append(a), max_cycles=2, clock=lambda: t0,
                           sleep=waits.append, log=lambda _: None)
    assert code == 0 and files.runtime_state()["reason"] == radar.UNVERIFIED
    lister.assert_not_called()
    assert files.unread_allowed()                          # not an unread violation: no latch
    assert [b[0] for b in beats] == ["collector_error"] * 2 and sum(waits) == 360
    alert = radar_alert(files.runtime_state(), running=True, enabled=True, unread_disabled=False, now=t0)
    assert alert.severity == "critical" and alert.reason == "BROWSER_UNVERIFIED"
    assert radar.UNVERIFIED in REASONS


# --- status -------------------------------------------------------------------------------
def test_ops_browser_status_shows_states_and_tabs_only(tmp_path):
    write_contract(tmp_path)
    targets = fake_targets(PORTAL_URL, DOORAY_URL, "https://kaist.gov-dooray.com/mail/" + SECRET)
    lines = "\n".join(ops_browser_lines(tmp_path, "verified", 9224, targets=targets))
    assert "Ops browser   : running (127.0.0.1:9224)" in lines
    assert "Portal tab    : present" in lines and "Dooray tab    : present (inbox)" in lines
    assert SECRET not in lines and "http" not in lines and "kaist" not in lines.lower().replace("kaist sso", "")
    login = "\n".join(ops_browser_lines(tmp_path, "verified", 9224, targets=fake_targets(SSO_URL, DOORAY_LOGIN)))
    assert "Portal tab    : SSO login page (log in there)" in login
    assert "Dooray tab    : present (login or not on the inbox) / KAIST SSO login page open" in login
    assert SECRET not in login and "http" not in login and "idp" not in login
    absent = "\n".join(ops_browser_lines(tmp_path, "verified", 9224, targets=fake_targets(PORTAL_URL)))
    assert "Dooray tab    : absent" in absent
    never = Mock(side_effect=AssertionError("queried an unverified listener"))
    for state, word in (("unverified", "unverified"), ("stale", "stale"), ("absent", "missing")):
        text = "\n".join(ops_browser_lines(tmp_path, state, 9224, targets=never))
        assert f"Ops browser   : {word}" in text


def test_worker_status_reports_the_mode_ports_and_tabs(tmp_path):
    write_contract(tmp_path)
    files = Files(tmp_path)
    files.set_enabled(True, 1000)
    host = Mock(inspect=Mock(return_value=("verified", {"command": SECRET})))
    separate = "\n".join(status_lines(files, host=host, now=1000))
    assert "separate" in separate and "(9223)" in separate and "(browser 9222)" in separate
    assert "Ops browser" not in separate
    ob.set_mode(files.local, "unified")
    unified = "\n".join(status_lines(files, host=host, now=1000, targets=fake_targets(PORTAL_URL, DOORAY_URL)))
    assert "unified" in unified and "(9224)" in unified and "(browser 9224)" in unified
    assert "Portal tab    : present" in unified and "Dooray tab    : present (inbox)" in unified
    assert SECRET not in unified and "9222" not in unified


# --- control: mode switch, rollback, legacy close/start, profiles ------------------------------
def local_snapshot(root):
    return {p.name: p.read_bytes() for p in (Path(root) / ".local").iterdir() if p.is_file()}


def test_mode_switch_requires_both_workers_stopped_and_touches_only_its_file(tmp_path):
    files = Files(tmp_path)
    files.set_enabled(False, 1000)
    atomic_json(files.local / "portal-list-state.json", {"version": 1, "baseline": SECRET})
    atomic_json(files.local / "ggongbab-mail-state.json", {"mails": []})
    for lock in control.worker_locks(files):
        with poller_lock(lock):
            with pytest.raises(OpsError, match="OPS_WORKERS_STILL_RUNNING"):
                control.switch_mode(files, "unified")
    before = local_snapshot(tmp_path)
    control.switch_mode(files, "unified")
    after = local_snapshot(tmp_path)
    assert json.loads(after.pop(ob.MODE_FILE)) == {"mode": "unified"}
    assert {k: v for k, v in after.items() if not k.endswith(".lock")} == {
        k: v for k, v in before.items() if not k.endswith(".lock")}
    control.switch_mode(files, "separate")                  # rollback = one value back
    assert ob.slot_for(tmp_path, "portal").port == 9223 and ob.slot_for(tmp_path, "dooray").port == 9222


def test_legacy_browsers_are_closed_only_after_cutover_and_only_when_verified(tmp_path):
    files = Files(tmp_path)
    for name in ("portal-browser-profile", "dooray-browser-profile", "ops-browser-profile"):
        (files.local / name / "Default").mkdir(parents=True)
    host = Mock(profile=files.local / "portal-browser-profile", port=9223)
    host.inspect.side_effect = [("verified", LEGACY_PORTAL), ("absent", None)]
    connect, verify = Mock(), Mock()
    with pytest.raises(OpsError):                           # still the workers' browser in separate mode
        control.close_legacy(files, "portal", host=host, connect=connect, verify=verify, sleep=lambda _: None)
    connect.assert_not_called()
    ob.set_mode(files.local, "unified")
    assert control.close_legacy(files, "portal", host=host, connect=connect, verify=verify,
                                sleep=lambda _: None) == "closed"
    verify.assert_called_once_with(host.profile, 9223)
    connect.assert_called_once_with(9223, 600)              # the CDP close is bound to the verified pid
    assert control.profile_inventory(files) == {"ops-browser-profile": True, "portal-browser-profile": True,
                                                "dooray-browser-profile": True}
    for state in ("unverified", "stale"):
        host.inspect.side_effect = [(state, None)]
        connect.reset_mock()
        with pytest.raises(OpsError):
            control.close_legacy(files, "portal", host=host, connect=connect, verify=verify, sleep=lambda _: None)
        connect.assert_not_called()


def test_a_close_that_does_not_complete_is_reported_never_forced(tmp_path):
    files = Files(tmp_path)
    ob.set_mode(files.local, "unified")
    host = Mock(profile=Path("p"), port=9222)
    host.inspect.return_value = ("verified", {"pid": 44, "command": "c", "created": "1"})
    with pytest.raises(OpsError, match="OPS_BROWSER_CLOSE_FAILED"):
        control.close_legacy(files, "dooray", host=host, connect=Mock(), verify=Mock(), sleep=lambda _: None)


def test_rollback_start_of_a_legacy_browser_needs_separate_mode(tmp_path):
    files = Files(tmp_path)
    host = Mock()
    host.inspect.return_value = ("absent", None)
    ob.set_mode(files.local, "unified")
    with pytest.raises(OpsError):
        control.start_legacy(files, "dooray", host=host)
    host.ensure.assert_not_called()
    ob.set_mode(files.local, "separate")
    control.start_legacy(files, "dooray", host=host)
    host.ensure.assert_called_once_with()
    host.inspect.return_value = ("unverified", None)
    with pytest.raises(OpsError, match="OPS_BROWSER_UNVERIFIED"):
        control.start_legacy(files, "dooray", host=host)


def test_operator_start_reuses_a_verified_browser_and_refuses_stale_or_unknown(tmp_path):
    write_contract(tmp_path)
    files = Files(tmp_path)
    host = Mock(port=9224)
    host.inspect.return_value = ("verified", OPS)
    tabs = Mock()
    control.start(files, host=host, tabs=tabs)
    host.ensure.assert_called_once_with(log=host.ensure.call_args.kwargs["log"])
    assert tabs.call_args.args == (9224, "kaist.gov-dooray.com", "https://kaist.gov-dooray.com/mail/systems/inbox")
    for state, code in (("stale", "OPS_BROWSER_STALE"), ("unverified", "OPS_BROWSER_UNVERIFIED")):
        host.reset_mock()
        host.inspect.return_value = (state, OPS)
        with pytest.raises(OpsError, match=code):
            control.start(files, host=host, tabs=tabs)
        host.ensure.assert_not_called()


def test_unified_recovery_pauses_both_workers_and_restarts_only_on_stale_or_attach_timeout(tmp_path):
    write_contract(tmp_path)
    files = Files(tmp_path)
    files.set_enabled(True, 1000)
    radar.RadarFiles(tmp_path).set_enabled(True, 1000)
    ob.set_mode(files.local, "unified")
    host = Mock(port=9224)
    for state, reason, restart in (("verified", "WORKER_RUNNING", False), ("stale", "WORKER_RUNNING", True),
                                   ("verified", "PORTAL_CDP_ATTACH_TIMEOUT", True), ("absent", "WORKER_RUNNING", False)):
        row = files.runtime_state()
        row["reason"] = reason
        atomic_json(files.runtime, row)
        host.reset_mock()
        host.inspect.return_value = (state, OPS if state != "absent" else None)
        assert control.recover(files, host=host, tabs=Mock(), wait=lambda f: None) is True
        host.ensure.assert_called_once_with(recover_stale=restart)
        assert not files.control_state()["enabled"] and not radar.RadarFiles(tmp_path).enabled()
    host.inspect.return_value = ("unverified", None)
    host.reset_mock()
    with pytest.raises(OpsError, match="OPS_BROWSER_UNVERIFIED"):
        control.recover(files, host=host, tabs=Mock(), wait=lambda f: None)
    host.ensure.assert_not_called()


# --- concurrency and the proof ------------------------------------------------------------
def test_two_cdp_clients_are_attached_at_the_same_time_before_either_works():
    events, lock = [], threading.Lock()

    def job(name):
        def run(barrier):
            with lock:
                events.append(name + ":attached")
            barrier.wait()
            with lock:
                events.append(name + ":work")
            return {"ok": True, "attached": time.monotonic(), "detached": time.monotonic() + 1}
        return run

    results = proof.run_jobs([("portal", job("portal"), str), ("dooray", job("dooray"), str)])
    assert all(r["ok"] for r in results.values())
    assert {e for e in events[:2]} == {"portal:attached", "dooray:attached"}
    assert proof.overlapped(results["portal"], results["dooray"])


def test_a_failing_client_aborts_the_barrier_instead_of_hanging_the_other():
    def failing(barrier):
        raise radar.BrowserUnverified()

    def waiting(barrier):
        barrier.wait()
        return {"ok": True}

    started = time.monotonic()
    results = proof.run_jobs([("portal", waiting, proof.portal_code), ("dooray", failing, proof.dooray_code)])
    assert time.monotonic() - started < 10
    assert results["dooray"] == {"ok": False, "code": radar.UNVERIFIED}
    assert results["portal"]["ok"] is False


def snap_fn(sequence):
    items = iter(sequence)
    return lambda: next(items)


def snap(pid=700, roles=None, windows=(1,)):
    return {"pid": pid, "created": "7000", "roles": roles or {"a": "portal", "b": "dooray"}, "windows": set(windows)}


def good_portal(barrier):
    barrier.wait()
    return {"ok": True, "attached": 1.0, "detached": 3.0}


def good_dooray(now):
    def run(barrier):
        barrier.wait()
        return {"ok": True, "attached": 2.0, "detached": 4.0, "guard_violations": 0,
                "counts": {"rows": 5, "unread": 1}, "unread": {"u1"}, "read": {"r1"}}
    return run


def run_fake_proof(tmp_path, snaps, *, cycles=4, portal=good_portal, dooray=good_dooray):
    return proof.run_proof(tmp_path, cycles=cycles, interval=60, dooray_every=3, host=Mock(),
                           contract=SimpleNamespace(), snap=snap_fn(snaps), portal=portal, dooray=dooray,
                           sleep=lambda _: None, clock=lambda: 1000.0, out=lambda _: None)


def test_the_proof_passes_only_with_one_stable_browser_and_overlapping_clients(tmp_path):
    report = run_fake_proof(tmp_path, [snap()] * 8)
    assert report["result"] == "PASS" and report["portal_ok"] == 4 and report["dooray_ok"] == 2
    assert report["overlaps"] == 2 and report["windows"] == 1 and report["chrome_pid"] == 700
    stored = (tmp_path / ".local" / proof.PROOF_FILE).read_text(encoding="utf-8")
    assert json.loads(stored)["result"] == "PASS"
    assert set(local_snapshot(tmp_path)) == {proof.PROOF_FILE}  # no worker state file is written


@pytest.mark.parametrize("after,field", [
    (snap(roles={"a": "dooray", "b": "dooray"}), "cross_navigation"),
    (snap(roles={"b": "dooray"}), "tabs_closed"),
    (snap(roles={"a": "portal", "b": "dooray", "c": ""}), "pages_added"),
    (snap(windows=(1, 2)), "windows_added"),
    (snap(pid=701), "browser_changed"),
])
def test_cross_navigation_closed_tabs_new_pages_windows_or_restarts_fail_the_proof(tmp_path, after, field):
    report = run_fake_proof(tmp_path, [snap(), after] + [after] * 6)
    assert report["result"] == "FAIL" and report[field] >= 1


def test_an_unread_guard_violation_stops_the_proof_and_never_touches_the_live_latch(tmp_path):
    def violating(now):
        def run(barrier):
            barrier.wait()
            return {"ok": True, "attached": 2.0, "detached": 4.0, "guard_violations": 1, "counts": {},
                    "unread": set(), "read": set()}
        return run
    report = run_fake_proof(tmp_path, [snap()] * 8, dooray=violating)
    assert report["result"] == "FAIL" and report["cycles_run"] == 1 and report["guard_violations"] == 1
    assert radar.RadarFiles(tmp_path).unread_allowed()


def test_the_proof_report_holds_counts_not_content(tmp_path):
    report = run_fake_proof(tmp_path, [snap()] * 8)
    blob = json.dumps(report)
    for forbidden in ("http", "kaist", SECRET, "u1", "r1", "JSESSIONID"):
        assert forbidden not in blob


def test_the_proof_snapshot_compares_roles_without_keeping_urls():
    host = Mock(inspect=Mock(return_value=("verified", OPS)))
    taken = proof.snapshot(host, 9224, "kaist.gov-dooray.com",
                           targets=fake_targets(PORTAL_URL, DOORAY_URL), windows=lambda port: {11})
    assert taken == {"pid": 700, "created": "7000", "roles": {"t0": "portal", "t1": "dooray"}, "windows": {11}}
    host.inspect.return_value = ("unverified", None)
    with pytest.raises(OpsError, match="OPS_BROWSER_UNVERIFIED"):
        proof.snapshot(host, 9224, "kaist.gov-dooray.com", targets=Mock(), windows=Mock())


def test_the_proof_dooray_scan_is_a_dry_run_with_no_writer():
    source = (ROOT / "scripts/ggongbab/ops_browser_proof.py").read_text(encoding="utf-8")
    job = source[source.index("def dooray_job("):source.index("def run_jobs(")]
    assert "dry_run=True" in job and "scan_once(session, AgentState.load(files.mail_state), None," in job
    for forbidden in ("state.save", "mark_run", "update_flash", "disable_unread", "request_refresh",
                      "TaskWriter", "HeartbeatWriter", "atomic_json(files", ".goto(", ".click("):
        assert forbidden not in source


# --- operator scripts -----------------------------------------------------------------------
def test_ops_browser_scripts_are_thin_wrappers():
    windows = ROOT / "scripts/windows"
    script = (windows / "ops_browser.ps1").read_text(encoding="utf-8")
    assert "'Start','Status','Recover'" in script
    for action in ("ops-browser-start", "ops-browser-status", "ops-browser-recover"):
        assert action in script
    for name, action in (("start", "Start"), ("status", "Status"), ("recover", "Recover")):
        text = (windows / f"{name}_ops_browser.cmd").read_text(encoding="utf-8")
        assert f'"%~dp0ops_browser.ps1" -Action {action}' in text
    for forbidden in ("Stop-Process", "taskkill", "Remove-Item", "0.0.0.0", "--remote-debugging-address"):
        assert forbidden not in script
