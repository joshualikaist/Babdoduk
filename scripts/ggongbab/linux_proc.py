"""Linux process and listener inventory for the dedicated Chrome. Values never leave memory.

The Linux counterpart of the PowerShell `Get-NetTCPConnection` / `Win32_Process` queries in
`windows_portal_host.py` and `portal_session.py`, read from `/proc`:

* listeners of a TCP port, from `/proc/net/tcp` and `/proc/net/tcp6` (state LISTEN);
* the processes holding a listener's socket inode, from `/proc/<pid>/fd`;
* Google Chrome processes (`comm` "chrome") with their argv and start time (`stat` field 22).

Chrome on Linux rewrites its own process title, the browser process included (measured
2026-10-17, Chrome 146): `cmdline` is then ONE NUL-terminated string of the arguments joined by
spaces. Such a title is split on spaces. An argument that itself contains a space (a profile path
with a space) then no longer matches exactly, so the check fails closed; the operations checkout
therefore lives in a path without spaces (scripts/linux/ops.sh refuses one).

Everything fails closed the same way: an unreadable or ambiguous answer raises, and callers turn
that into their fixed "owner unverified" code. A zombie has no command line and can own neither a
port nor a profile, so it is skipped instead of making every inspection ambiguous.
"""
from __future__ import annotations

import os
from pathlib import Path
import signal
import time

PROC = Path("/proc")
LISTEN = "0A"
CHROME_NAMES = frozenset({"chrome"})
LOOPBACK_V4 = "127.0.0.1"
TERM_GRACE_SECONDS = 5


def _ipv4(hex_addr):
    raw = bytes.fromhex(hex_addr)
    return ".".join(str(b) for b in reversed(raw))


def _ipv6(hex_addr):
    raw = bytes.fromhex(hex_addr)
    # Four 32-bit words, each in host (little-endian) order.
    words = b"".join(raw[i:i + 4][::-1] for i in range(0, 16, 4))
    import ipaddress
    return str(ipaddress.IPv6Address(words))


def listeners(port, *, proc=None):
    """[(address, inode)] of every LISTEN socket on `port`, IPv4 and IPv6."""
    proc = Path(proc or PROC)
    found = []
    for name, parse in (("tcp", _ipv4), ("tcp6", _ipv6)):
        path = proc / "net" / name
        if not path.exists():
            continue
        for line in path.read_text(encoding="ascii").splitlines()[1:]:
            fields = line.split()
            if len(fields) < 10 or fields[3] != LISTEN:
                continue
            address, port_hex = fields[1].split(":")
            if int(port_hex, 16) != port:
                continue
            found.append((parse(address), int(fields[9])))
    return found


def socket_owners(inodes, *, proc=None):
    """Sorted pids whose open descriptors include one of the socket inodes.

    Only the operator's own processes are readable; a listener held by anyone else therefore
    has no visible owner, which callers treat as unverified."""
    proc = Path(proc or PROC)
    targets = {f"socket:[{inode}]" for inode in inodes}
    owners = set()
    if not targets:
        return []
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            for fd in (entry / "fd").iterdir():
                try:
                    if os.readlink(fd) in targets:
                        owners.add(int(entry.name))
                        break
                except OSError:
                    continue
        except OSError:
            continue
    return sorted(owners)


def _stat(entry):
    """(state, starttime) from /proc/<pid>/stat; the name field may contain spaces or ')'."""
    text = (entry / "stat").read_text(encoding="utf-8", errors="replace")
    rest = text[text.rindex(")") + 2:].split()
    return rest[0], rest[19]


def process(pid, *, proc=None):
    """{pid, command, created} of a live Chrome process, None for any other or vanished pid."""
    entry = Path(proc or PROC) / str(pid)
    try:
        name = (entry / "comm").read_text(encoding="utf-8", errors="replace").strip()
        if name not in CHROME_NAMES:
            return None
        state, created = _stat(entry)
        if state in ("Z", "X"):
            return None
        raw = (entry / "cmdline").read_bytes()
    except (OSError, ValueError, IndexError):
        return None
    return {"pid": int(pid), "command": argv(raw), "created": created}


def argv(raw):
    """argv from a raw `cmdline`: NUL-separated, or one space-joined rewritten title."""
    parts = raw.split(b"\0")
    if parts and parts[-1] == b"":
        parts.pop()
    if len(parts) == 1 and b" " in parts[0]:
        parts = [part for part in parts[0].split(b" ") if part]
    return [part.decode("utf-8", errors="surrogateescape") for part in parts]


def chrome_processes(*, proc=None):
    proc = Path(proc or PROC)
    found = []
    for entry in proc.iterdir():
        if entry.name.isdigit():
            info = process(entry.name, proc=proc)
            if info is not None:
                found.append(info)
    return found


def inventory(port, *, proc=None):
    """The same shape as windows_portal_host.INVENTORY_SCRIPT's answer, `command` as argv."""
    bound = listeners(port, proc=proc)
    return {
        "listening": bool(bound),
        "loopback": len(bound) == 1 and bound[0][0] == LOOPBACK_V4,
        "owners": socket_owners([inode for _, inode in bound], proc=proc),
        "processes": chrome_processes(proc=proc),
    }


def owner_command(port, *, proc=None):
    """argv of the single Chrome process owning the single loopback listener on `port`."""
    bound = listeners(port, proc=proc)
    if len(bound) != 1 or bound[0][0] != LOOPBACK_V4:
        raise ValueError()
    owners = socket_owners([bound[0][1]], proc=proc)
    if len(owners) != 1:
        raise ValueError()
    info = process(owners[0], proc=proc)
    if info is None or not info["command"]:
        raise ValueError()
    return info["command"]


def _same(expected, *, proc=None):
    info = process(int(expected["pid"]), proc=proc)
    return (info is not None and info["command"] == list(expected["command"])
            and info["created"] == str(expected["created"]))


def stop_verified(expected, *, proc=None, kill=os.kill, sleep=time.sleep, grace=TERM_GRACE_SECONDS):
    """Stop exactly one process that an inventory just verified, after re-checking its identity.

    PID reuse, a changed command line or start time, or a changed listener owner aborts. SIGTERM
    first (Chrome saves its session); a browser still alive after the grace period, and still the
    same process, gets SIGKILL - the Windows recovery's Stop-Process is a hard stop too."""
    pid, port = int(expected["pid"]), int(expected["port"])
    if not _same(expected, proc=proc):
        raise ValueError()
    bound = listeners(port, proc=proc)
    if bound:
        if len(bound) != 1 or bound[0][0] != LOOPBACK_V4:
            raise ValueError()
        if socket_owners([bound[0][1]], proc=proc) != [pid]:
            raise ValueError()
    kill(pid, signal.SIGTERM)
    for _ in range(int(grace * 2)):
        sleep(0.5)
        if not _same(expected, proc=proc):
            return
    if _same(expected, proc=proc):
        kill(pid, signal.SIGKILL)
