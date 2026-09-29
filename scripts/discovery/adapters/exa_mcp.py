# -*- coding: utf-8 -*-
"""A small client for Exa's hosted MCP server (https://mcp.exa.ai/mcp), the web-search route
Agent Reach configures through mcporter (upstream a19a171). It needs no API key: this client
sends no credential of any kind, only the public search query.

Protocol: MCP streamable HTTP. POST JSON-RPC `initialize`, then `notifications/initialized`,
then `tools/call` for `web_search_exa` (search with highlights) and `web_fetch_exa` (the page
as clean text). The server may answer with plain JSON or with SSE `data:` lines, and returns a
session id in the `Mcp-Session-Id` header that later calls send back.

Parsing is of the server's text output: blocks with a `Title:` or `# ` header line, then
`URL:`, optional `Published:` / `Author:` / `Highlights:` lines and the page text.
"""
from __future__ import annotations

import json
import time
import urllib.request

from ..common import UA

MCP_URL = "https://mcp.exa.ai/mcp"
PROTOCOL = "2025-03-26"


class MCPError(Exception):
    """A JSON-RPC or tool error. `code` is fixed text, never the server's message."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class ExaMCP:
    def __init__(self, opener=urllib.request.urlopen, url: str = MCP_URL, pause: float = 1.0, sleep=time.sleep):
        self.opener, self.url, self.pause, self.sleep = opener, url, pause, sleep
        self.session = None
        self.next_id = 1
        self.calls = 0

    def _post(self, payload: dict) -> list[dict]:
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                   "User-Agent": UA}
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        if self.calls and self.pause:
            self.sleep(self.pause)                 # a polite pace for a free public service
        self.calls += 1
        request = urllib.request.Request(self.url, data=json.dumps(payload).encode("utf-8"), headers=headers,
                                         method="POST")
        with self.opener(request, timeout=60) as res:
            body = res.read().decode("utf-8", "replace")
            session = getattr(res, "headers", None) and res.headers.get("Mcp-Session-Id")
        if session:
            self.session = session
        messages = [json.loads(line[5:].strip()) for line in body.splitlines()
                    if line.startswith("data:") and line[5:].strip().startswith("{")]
        if not messages and body.strip().startswith("{"):
            messages = [json.loads(body)]
        return messages

    def _request(self, method: str, params: dict) -> dict:
        rid = self.next_id
        self.next_id += 1
        for message in self._post({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}):
            if message.get("id") == rid:
                if message.get("error"):
                    raise MCPError("MCP_ERROR")
                return message.get("result") or {}
        raise MCPError("MCP_NO_RESPONSE")

    def start(self) -> dict:
        result = self._request("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                              "clientInfo": {"name": "babdoduk-magazine", "version": "1"}})
        try:
            self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except Exception:  # noqa: BLE001 - a notification has no answer to wait for
            pass
        return result.get("serverInfo") or {}

    def call(self, name: str, arguments: dict) -> str:
        result = self._request("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise MCPError("TOOL_ERROR")
        return "".join(part.get("text", "") for part in result.get("content") or [] if isinstance(part, dict))

    def search(self, query: str, objective: str, num: int) -> list[dict]:
        return parse_blocks(self.call("web_search_exa", {"query": query, "numResults": num, "objective": objective}))

    def fetch(self, urls: list[str], max_chars: int) -> list[dict]:
        if not urls:
            return []
        return parse_blocks(self.call("web_fetch_exa", {"urls": urls, "maxCharacters": max_chars}))


def _meta(line: str, key: str):
    value = line[len(key):].strip()
    return None if value in ("", "N/A") else value


def parse_blocks(text: str) -> list[dict]:
    """[{title, url, published, author, highlights, body}] from search or fetch output."""
    lines = (text or "").splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith("URL: ")]
    blocks = []
    for n, at in enumerate(starts):
        header = lines[at - 1] if at > 0 else ""
        title = header[len("Title:"):].strip() if header.startswith("Title:") else \
            header[2:].strip() if header.startswith("# ") else ""
        end = len(lines)
        if n + 1 < len(starts):
            nxt = starts[n + 1]
            end = nxt - 1 if nxt > 0 and lines[nxt - 1].startswith(("Title:", "# ")) else nxt
        block = {"title": title, "url": lines[at][5:].strip(), "published": None, "author": None,
                 "highlights": "", "body": ""}
        rest, i = [], at + 1
        highlights = False
        while i < end:
            line = lines[i]
            if line.startswith("Published:") and not rest:
                block["published"] = _meta(line, "Published:")
            elif line.startswith("Author:") and not rest:
                block["author"] = _meta(line, "Author:")
            elif line.startswith("Highlights:") and not rest:
                highlights = True
            else:
                rest.append(line)
            i += 1
        joined = "\n".join(rest).strip()
        if highlights:
            block["highlights"] = "\n".join(p.strip() for p in joined.split("\n...\n") if p.strip() and p.strip() != "...")
        else:
            block["body"] = joined
        blocks.append(block)
    return blocks
