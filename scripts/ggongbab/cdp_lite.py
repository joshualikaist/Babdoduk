"""Minimal Chrome DevTools Protocol client for a dedicated browser's LOOPBACK endpoint.

Standard library only (socket + RFC 6455 framing). It exists because Playwright's
`connect_over_cdp` initialises every page of the browser before it returns: one tab that
Chrome discarded or froze (measured on the Ops Chrome under memory pressure: the hidden
Portal tab, `document.wasDiscarded === true`) makes every client wait until it times out.
This client talks to the browser target and attaches to one page at a time, so a dead tab
cannot block it. It connects only to 127.0.0.1, never reads cookies, page content or titles,
and is used for: page liveness, tab restore (activate), window ids, process ids and close.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import struct
import time
import urllib.request
from urllib.parse import urlsplit

from .ops_storage import OpsError

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class CdpError(OpsError):
    """A CDP error response (method-level), reported as a fixed code only."""


def browser_ws_path(port: int, opener=urllib.request.urlopen) -> str:
    try:
        with opener(f"http://127.0.0.1:{int(port)}/json/version", timeout=3) as response:
            url = urlsplit(json.loads(response.read().decode("utf-8"))["webSocketDebuggerUrl"])
    except Exception:
        raise OpsError("OPS_BROWSER_TARGETS_UNAVAILABLE") from None
    if url.scheme != "ws" or url.hostname != "127.0.0.1" or url.port != int(port):
        raise OpsError("OPS_BROWSER_UNVERIFIED")   # never follow the endpoint anywhere else
    return url.path


class LoopbackCdp:
    def __init__(self, port: int, *, sock=None, path=None, timeout: float = 10):
        self.port = int(port)
        self._ids = 0
        self._buffer = b""
        if sock is None:
            path = path or browser_ws_path(self.port)
            try:
                sock = socket.create_connection(("127.0.0.1", self.port), timeout=timeout)
                self._handshake(sock, path)
            except OpsError:
                raise
            except Exception:
                raise OpsError("OPS_BROWSER_TARGETS_UNAVAILABLE") from None
        self.sock = sock

    def _handshake(self, sock, path):
        key = base64.b64encode(os.urandom(16)).decode()
        sock.sendall((f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nUpgrade: websocket\r\n"
                      f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
                      ).encode())
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = sock.recv(4096)
            if not chunk or len(data) > 16384:
                raise OpsError("OPS_BROWSER_TARGETS_UNAVAILABLE")
            data += chunk
        head, self._buffer = data.split(b"\r\n\r\n", 1)
        accept = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
        lines = head.decode("latin-1").split("\r\n")
        if " 101 " not in lines[0] + " " or f"sec-websocket-accept: {accept}".lower() not in [
                line.lower() for line in lines]:
            raise OpsError("OPS_BROWSER_TARGETS_UNAVAILABLE")

    # --- framing -------------------------------------------------------------------------
    def _send_frame(self, opcode: int, data: bytes) -> None:
        mask = os.urandom(4)
        n = len(data)
        if n < 126:
            header = struct.pack("!BB", 0x80 | opcode, 0x80 | n)
        elif n < 65536:
            header = struct.pack("!BBH", 0x80 | opcode, 0x80 | 126, n)
        else:
            header = struct.pack("!BBQ", 0x80 | opcode, 0x80 | 127, n)
        self.sock.sendall(header + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _need(self, count: int) -> None:
        while len(self._buffer) < count:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise OpsError("OPS_BROWSER_TARGETS_UNAVAILABLE")
            self._buffer += chunk

    def _read_message(self) -> dict:
        message = b""
        while True:
            self._need(2)
            first, second = self._buffer[0], self._buffer[1]
            length, offset = second & 0x7F, 2
            if length == 126:
                self._need(4)
                length, offset = struct.unpack("!H", self._buffer[2:4])[0], 4
            elif length == 127:
                self._need(10)
                length, offset = struct.unpack("!Q", self._buffer[2:10])[0], 10
            if second & 0x80:                       # a server never masks; refuse
                raise OpsError("OPS_BROWSER_TARGETS_UNAVAILABLE")
            self._need(offset + length)
            payload = self._buffer[offset:offset + length]
            self._buffer = self._buffer[offset + length:]
            opcode = first & 0x0F
            if opcode == 0x9:                       # ping -> pong
                self._send_frame(0xA, payload)
                continue
            if opcode == 0x8:
                raise OpsError("OPS_BROWSER_TARGETS_UNAVAILABLE")
            if opcode in (0x1, 0x0):
                message += payload
                if first & 0x80:
                    return json.loads(message.decode("utf-8"))
            # other opcodes (pong, binary) are ignored

    # --- commands ---------------------------------------------------------------------------
    def call(self, method: str, params=None, *, session=None, timeout: float = 5):
        """The command's result, or None when no answer arrives in time. Events are dropped."""
        self._ids += 1
        ident = self._ids
        message = {"id": ident, "method": method, "params": params or {}}
        if session:
            message["sessionId"] = session
        self._send_frame(0x1, json.dumps(message).encode("utf-8"))
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            self.sock.settimeout(remaining)
            try:
                reply = self._read_message()
            except (socket.timeout, TimeoutError):
                return None
            if reply.get("id") != ident:
                continue
            if "error" in reply:
                raise CdpError("OPS_BROWSER_CDP_ERROR")
            return reply.get("result", {})

    def close(self) -> None:
        try:
            self._send_frame(0x8, b"")
        except Exception:  # noqa: BLE001
            pass
        try:
            self.sock.close()
        except Exception:  # noqa: BLE001
            pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
