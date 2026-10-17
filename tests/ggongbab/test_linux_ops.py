"""Linux operations host: the /proc owner checks, on a synthetic /proc tree (no real process,
port, browser or service is touched)."""
from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from ggongbab import linux_proc  # noqa: E402
from ggongbab.ops_browser import UNIFIED_PORT, set_mode  # noqa: E402
from ggongbab.ops_storage import OpsError  # noqa: E402
from ggongbab.web.exit_codes import AuthRequired  # noqa: E402
from ggongbab import windows_portal_host as host_module  # noqa: E402

linux_only = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux /proc layout")
HEADER = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"


def tcp_line(n, address, port, state, inode):
    return (f"   {n}: {address}:{port:04X} 00000000:0000 {state} 00000000:00000000 00:00000000 "
            f"00000000  1000        0 {inode} 1 0000000000000000 100 0 0 10 0\n")


class FakeProc:
    def __init__(self, root: Path):
        self.root = root
        (root / "net").mkdir(parents=True)
        self.tcp, self.tcp6 = [], []
        self.flush()

    def flush(self):
        (self.root / "net" / "tcp").write_text(HEADER + "".join(self.tcp), encoding="ascii")
        (self.root / "net" / "tcp6").write_text(HEADER + "".join(self.tcp6), encoding="ascii")

    def listen(self, port, inode, address="0100007F", v6=False):
        (self.tcp6 if v6 else self.tcp).append(tcp_line(len(self.tcp), address, port, "0A", inode))
        self.flush()

    def process(self, pid, argv, *, comm="chrome", state="S", start="4242", sockets=(), raw=None):
        entry = self.root / str(pid)
        (entry / "fd").mkdir(parents=True)
        (entry / "comm").write_text(comm + "\n", encoding="utf-8")
        fields = [state] + ["0"] * 18 + [start] + ["0"] * 10
        (entry / "stat").write_text(f"{pid} ({comm}) " + " ".join(fields) + "\n", encoding="utf-8")
        data = raw if raw is not None else b"\0".join(a.encode() for a in argv) + b"\0"
        (entry / "cmdline").write_bytes(data)
        for n, inode in enumerate(sockets):
            os.symlink(f"socket:[{inode}]", entry / "fd" / str(n + 3))
        os.symlink("/dev/null", entry / "fd" / "0")


def browser_argv(profile, port=UNIFIED_PORT):
    return ["/opt/google/chrome/chrome", "--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={port}", f"--user-data-dir={profile}", "--no-first-run"]


@pytest.fixture
def proc(tmp_path, monkeypatch):
    fake = FakeProc(tmp_path / "proc")
    monkeypatch.setattr(linux_proc, "PROC", fake.root)
    return fake


@pytest.fixture
def ops_root(tmp_path):
    root = tmp_path / "ops"
    (root / ".local").mkdir(parents=True)
    set_mode(root / ".local", "unified")
    return root


def profile_of(root):
    return (root / ".local" / "ops-browser-profile").resolve()


def test_listener_table_parses_ipv4_ipv6_and_only_listen_rows(proc):
    proc.listen(UNIFIED_PORT, 111)
    proc.tcp.append(tcp_line(9, "0100007F", UNIFIED_PORT, "01", 999))       # ESTABLISHED: not a listener
    proc.listen(9999, 222)
    proc.listen(UNIFIED_PORT, 333, address="00000000000000000000000001000000", v6=True)
    assert linux_proc.listeners(UNIFIED_PORT) == [("127.0.0.1", 111), ("::1", 333)]


def test_inventory_verifies_the_one_dedicated_browser(proc, ops_root):
    profile = profile_of(ops_root)
    proc.listen(UNIFIED_PORT, 5001)
    proc.process(100, browser_argv(profile), sockets=[5001])
    # A renderer whose title Chrome rewrote (one space-joined argv string) and a zombie.
    proc.process(101, [], raw=f"/opt/google/chrome/chrome --type=renderer --user-data-dir={profile}\0".encode())
    proc.process(102, [], state="Z", raw=b"")
    proc.process(103, ["/usr/bin/python3", "x.py"], comm="python3")
    host = host_module.ResidentHost(ops_root, run=host_module.linux_run, split=host_module.linux_split)
    state, process = host.inspect()
    assert state == "verified" and process["pid"] == 100 and process["created"] == "4242"


@pytest.mark.parametrize("variant", ["public_bind", "second_listener", "foreign_owner", "two_browsers", "wrong_port"])
def test_inventory_fails_closed(proc, ops_root, variant):
    profile = profile_of(ops_root)
    argv = browser_argv(profile, 9999 if variant == "wrong_port" else UNIFIED_PORT)
    proc.listen(UNIFIED_PORT, 5001, address="00000000" if variant == "public_bind" else "0100007F")
    if variant == "second_listener":
        proc.listen(UNIFIED_PORT, 5002, address="00000000000000000000000001000000", v6=True)
    proc.process(100, argv, sockets=[] if variant == "foreign_owner" else [5001])
    if variant == "two_browsers":
        proc.process(200, browser_argv(profile))
    host = host_module.ResidentHost(ops_root, run=host_module.linux_run, split=host_module.linux_split)
    assert host.inspect() == ("unverified", None)


def test_inventory_reports_absent_and_stale(proc, ops_root):
    host = host_module.ResidentHost(ops_root, run=host_module.linux_run, split=host_module.linux_split)
    assert host.inspect() == ("absent", None)
    proc.process(100, browser_argv(profile_of(ops_root)))          # running, but not listening
    assert host.inspect()[0] == "stale"


def test_the_platform_picks_the_proc_tools_on_linux(monkeypatch):
    monkeypatch.setattr(host_module.os, "name", "posix")
    monkeypatch.setattr(host_module.sys, "platform", "linux")
    assert host_module.platform_tools() == (host_module.linux_run, host_module.linux_split)
    monkeypatch.setattr(host_module.sys, "platform", "darwin")
    with pytest.raises(OpsError):
        host_module.platform_tools()[0](host_module.INVENTORY_SCRIPT, {"port": UNIFIED_PORT})


def test_linux_split_accepts_only_an_argv_list():
    assert host_module.linux_split(["a", "--b"]) == ["a", "--b"]
    for bad in ("a --b", [1], None):
        with pytest.raises(OpsError):
            host_module.linux_split(bad)


def test_stop_rechecks_identity_then_terms_and_kills_only_the_same_process(proc, ops_root):
    profile = profile_of(ops_root)
    proc.listen(UNIFIED_PORT, 5001)
    proc.process(100, browser_argv(profile), sockets=[5001])
    expected = {"pid": 100, "command": browser_argv(profile), "created": "4242", "port": UNIFIED_PORT}
    sent = []
    for changed in ({"created": "1"}, {"command": browser_argv(profile)[:-1]}, {"pid": 101}):
        with pytest.raises(ValueError):
            linux_proc.stop_verified(dict(expected, **changed), kill=lambda *a: sent.append(a), sleep=lambda _: None)
    assert sent == []
    # Still the same process after the grace period: SIGKILL follows.
    linux_proc.stop_verified(expected, kill=lambda *a: sent.append(a), sleep=lambda _: None)
    assert sent == [(100, signal.SIGTERM), (100, signal.SIGKILL)]


def test_stop_does_not_kill_after_a_graceful_exit(proc, ops_root):
    import shutil
    profile = profile_of(ops_root)
    proc.process(100, browser_argv(profile))
    expected = {"pid": 100, "command": browser_argv(profile), "created": "4242", "port": UNIFIED_PORT}
    sent = []

    def kill(pid, sig):
        sent.append((pid, sig))
        shutil.rmtree(proc.root / "100")               # the browser exits on SIGTERM

    linux_proc.stop_verified(expected, kill=kill, sleep=lambda _: None)
    assert sent == [(100, signal.SIGTERM)]


def test_rewritten_chrome_title_is_split_and_a_spaced_profile_fails_closed(proc, ops_root, tmp_path):
    profile = profile_of(ops_root)
    proc.listen(UNIFIED_PORT, 5001)
    proc.process(100, [], sockets=[5001], raw=(" ".join(browser_argv(profile)) + "\0").encode())
    host = host_module.ResidentHost(ops_root, run=host_module.linux_run, split=host_module.linux_split)
    state, process = host.inspect()
    assert state == "verified" and process["command"] == browser_argv(profile)
    assert linux_proc.argv(b"a\0b c\0") == ["a", "b c"]          # real NUL-separated argv is kept as-is


@linux_only
def test_spaced_profile_in_a_rewritten_title_is_unverified(proc, tmp_path):
    from ggongbab import portal_session
    profile = (tmp_path / "with space").resolve()
    proc.listen(9223, 7001)
    proc.process(300, [], sockets=[7001], raw=(" ".join(browser_argv(profile, 9223)) + "\0").encode())
    with pytest.raises(AuthRequired):
        portal_session.verify_resident_owner(profile, 9223)


@linux_only
def test_resident_owner_check_on_linux(proc, tmp_path):
    from ggongbab import portal_session
    profile = (tmp_path / "dedicated profile").resolve()
    proc.listen(9223, 7001)
    proc.process(300, browser_argv(profile, 9223), sockets=[7001])
    portal_session.verify_resident_owner(profile, 9223)
    for args in ((tmp_path / "other", 9223), (profile, 9224), (profile, 0)):
        with pytest.raises(AuthRequired):
            portal_session.verify_resident_owner(*args)


@linux_only
def test_resident_owner_check_rejects_a_non_chrome_owner(proc, tmp_path):
    from ggongbab import portal_session
    profile = (tmp_path / "p").resolve()
    proc.listen(9223, 7001)
    proc.process(300, browser_argv(profile, 9223), comm="python3", sockets=[7001])
    with pytest.raises(AuthRequired):
        portal_session.verify_resident_owner(profile, 9223)


def test_ops_script_is_valid_bash():
    script = ROOT / "scripts" / "linux" / "ops.sh"
    assert script.exists()
    if not __import__("shutil").which("bash"):
        pytest.skip("bash not available")
    assert subprocess.run(["bash", "-n", str(script)]).returncode == 0
    text = script.read_text(encoding="utf-8")
    assert "vercel" not in text and "--force" not in text
    assert "KillMode=process" in text
