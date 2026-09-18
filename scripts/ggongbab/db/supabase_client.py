# -*- coding: utf-8 -*-
"""Minimal PostgREST client for Supabase using only the standard library.

The service-role key is used exclusively here, in backend jobs. It is never
written to logs, JSON exports or the frontend.
"""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

UA = "BabdodukGgongbab/1.0 (+https://github.com/joshualikaist/Babdoduk)"


class SupabaseError(Exception):
    pass


class SupabaseClient:
    def __init__(self, url: str, service_key: str, timeout: int = 30):
        if not url or not service_key:
            raise SupabaseError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
        self.rest = url.rstrip("/") + "/rest/v1"
        self.key = service_key
        self.timeout = timeout
        self._ctx = ssl.create_default_context()

    def _request(self, method: str, table: str, params: Optional[dict[str, Any]] = None,
                 body: Any = None, prefer: str = "") -> Any:
        url = f"{self.rest}/{table}"
        if params:
            url += "?" + urllib.parse.urlencode(params, safe="*.,()=:")
        headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": UA,
        }
        if prefer:
            headers["Prefer"] = prefer
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=self._ctx) as res:
                raw = res.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise SupabaseError(f"{method} {table}: HTTP {exc.code} {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise SupabaseError(f"{method} {table}: {exc.__class__.__name__}") from exc
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return None

    # ------------------------------------------------------------------
    def select(self, table: str, params: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
        params = {"select": "*", **(params or {})}
        result = self._request("GET", table, params)
        return result if isinstance(result, list) else []

    def insert(self, table: str, rows: list[dict[str, Any]] | dict[str, Any], returning: bool = True) -> list[dict[str, Any]]:
        body = rows if isinstance(rows, list) else [rows]
        result = self._request("POST", table, body=body, prefer="return=representation" if returning else "return=minimal")
        return result if isinstance(result, list) else []

    def upsert(self, table: str, rows: list[dict[str, Any]] | dict[str, Any], on_conflict: str,
               ignore_duplicates: bool = False) -> list[dict[str, Any]]:
        body = rows if isinstance(rows, list) else [rows]
        resolution = "ignore-duplicates" if ignore_duplicates else "merge-duplicates"
        result = self._request("POST", table, {"on_conflict": on_conflict}, body,
                               prefer=f"resolution={resolution},return=representation")
        return result if isinstance(result, list) else []

    def update(self, table: str, match: dict[str, Any], values: dict[str, Any]) -> list[dict[str, Any]]:
        params = {k: f"eq.{v}" for k, v in match.items()}
        result = self._request("PATCH", table, params, values, prefer="return=representation")
        return result if isinstance(result, list) else []

    def ping(self) -> bool:
        self._request("GET", "sources", {"select": "id", "limit": 1})
        return True
