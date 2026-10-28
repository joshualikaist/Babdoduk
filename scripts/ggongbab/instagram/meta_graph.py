# -*- coding: utf-8 -*-
"""Meta Graph API, read only: Business Discovery of public Instagram professional accounts.

Owner setup and rules: docs/INSTAGRAM_RADAR.md. Only GET is ever sent. The token travels in the
Authorization header, never in a URL; with an app secret every call carries `appsecret_proof`.
Every answer's usage headers (X-App-Usage, X-Business-Use-Case-Usage) are returned to the caller,
which records them and slows down above 80 %. Errors become a GraphError with a fixed kind:
"rate_limit", "auth", "unsupported" or "other"; the message never contains the token.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Optional

GRAPH = "https://graph.facebook.com"
REQUIRED_SCOPES = frozenset({"instagram_basic", "instagram_manage_insights", "pages_read_engagement",
                             "pages_show_list"})
RATE_LIMIT_CODES = frozenset({4, 17, 32, 613, 80001, 80002, 80006})
AUTH_CODES = frozenset({102, 190, 200, 10})
MEDIA_FIELDS = ("id,caption,media_type,media_url,thumbnail_url,permalink,timestamp,"
                "children{media_type,media_url,thumbnail_url}")
USERNAME = re.compile(r"^[A-Za-z0-9._]{1,30}$")


class GraphError(Exception):
    def __init__(self, kind: str, code: Optional[int] = None, status: Optional[int] = None):
        super().__init__(f"GRAPH_{kind.upper()} code={code} status={status}")
        self.kind, self.code, self.status = kind, code, status


def classify(status: int, error: dict) -> str:
    code, sub = error.get("code"), error.get("error_subcode")
    if code in RATE_LIMIT_CODES or status == 429:
        return "rate_limit"
    if code in AUTH_CODES or status == 401:
        return "auth"
    # Business Discovery on a personal, missing or blocked account: code 110 (invalid user id) or
    # 100 with subcode 2207013 ("cannot be found") / a "business_discovery" message.
    if code == 110 or sub in (2207013, 2207031) or (code == 100 and "business" in str(error.get("message", "")).lower()):
        return "unsupported"
    return "other"


def usage_percent(headers) -> float:
    """The highest of every counter in X-App-Usage and X-Business-Use-Case-Usage, 0-100+."""
    best = 0.0
    for name in ("X-App-Usage", "X-Business-Use-Case-Usage"):
        raw = headers.get(name) if headers else None
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        rows = [data] if name == "X-App-Usage" else [r for v in data.values() for r in (v if isinstance(v, list) else [v])]
        for row in rows:
            for key in ("call_count", "total_cputime", "total_time"):
                value = row.get(key) if isinstance(row, dict) else None
                if isinstance(value, (int, float)):
                    best = max(best, float(value))
    return best


def mask(url: str) -> str:
    """A URL for logs: query values that could be secrets are replaced."""
    return re.sub(r"((?:access_token|appsecret_proof|oh|oe|_nc_sid|_nc_ohc|signature)=)[^&]+", r"\1***", url)


class GraphClient:
    def __init__(self, token: str, *, version: str = "v26.0", ig_user_id: str, app_secret: str = "",
                 opener: Callable = urllib.request.urlopen, timeout: float = 30):
        if not re.fullmatch(r"v\d+\.\d+", version) or not re.fullmatch(r"\d{5,25}", str(ig_user_id)):
            raise GraphError("other")
        self._token, self._secret = token, app_secret
        self.version, self.ig_user_id, self._opener, self.timeout = version, str(ig_user_id), opener, timeout
        self._ctx = ssl.create_default_context()

    def get(self, path: str, params: Optional[dict] = None) -> tuple[dict, dict]:
        """(JSON body, usage headers). GET only."""
        params = dict(params or {})
        if self._secret:
            params["appsecret_proof"] = hmac.new(self._secret.encode(), self._token.encode(), hashlib.sha256).hexdigest()
        url = f"{GRAPH}/{self.version}/{path.lstrip('/')}"
        if params:
            url += "?" + urllib.parse.urlencode(params, safe="{}(),.")
        request = urllib.request.Request(url, method="GET", headers={
            "Authorization": f"Bearer {self._token}", "User-Agent": "BabdodukFoodRadar/1.0"})
        try:
            with self._opener(request, timeout=self.timeout, context=self._ctx) as response:
                headers = {k: response.headers.get(k) for k in ("X-App-Usage", "X-Business-Use-Case-Usage")}
                return json.loads(response.read().decode("utf-8")), headers
        except urllib.error.HTTPError as exc:
            headers = {k: exc.headers.get(k) for k in ("X-App-Usage", "X-Business-Use-Case-Usage")} if exc.headers else {}
            try:
                error = json.loads(exc.read().decode("utf-8")).get("error") or {}
            except Exception:  # noqa: BLE001
                error = {}
            err = GraphError(classify(exc.code, error), error.get("code"), exc.code)
            err.headers = headers
            raise err from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise GraphError("other") from None

    # --- the calls this project makes ---------------------------------------------------------
    def token_status(self) -> dict:
        """{"valid": bool, "scopes": set, "expires_at": int|0 (0 = never)} from debug_token, falling
        back to me/permissions (which has no expiry)."""
        try:
            body, _ = self.get("debug_token", {"input_token": self._token})
            data = body.get("data") or {}
            return {"valid": bool(data.get("is_valid")), "scopes": set(data.get("scopes") or []),
                    "expires_at": int(data.get("expires_at") or 0)}
        except GraphError as exc:
            if exc.kind == "auth":
                raise
        body, _ = self.get("me/permissions")
        granted = {row.get("permission") for row in body.get("data") or [] if row.get("status") == "granted"}
        return {"valid": True, "scopes": granted, "expires_at": 0}

    def discover(self, username: str, *, limit: int = 10, after: str = "") -> tuple[dict, dict]:
        """Business Discovery of one public professional account: profile counts and `limit` media."""
        if not USERNAME.fullmatch(username) or not 1 <= limit <= 50:
            raise GraphError("other")
        media = f"media.after({after}).limit({limit})" if after else f"media.limit({limit})"
        fields = (f"username,business_discovery.username({username})"
                  f"{{username,name,followers_count,media_count,{media}{{{MEDIA_FIELDS}}}}}")
        body, headers = self.get(self.ig_user_id, {"fields": fields})
        found = body.get("business_discovery")
        if not isinstance(found, dict):
            raise GraphError("unsupported")
        return found, headers

    def download(self, url: str, *, max_bytes: int = 15 * 1024 * 1024) -> bytes:
        """A signed CDN image (no token is sent: these URLs carry their own signature)."""
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
        if urllib.parse.urlsplit(url).scheme != "https" or not (host.endswith(".cdninstagram.com") or host.endswith(".fbcdn.net")):
            raise GraphError("other")
        request = urllib.request.Request(url, method="GET", headers={"User-Agent": "BabdodukFoodRadar/1.0"})
        try:
            with self._opener(request, timeout=self.timeout, context=self._ctx) as response:
                data = response.read(max_bytes + 1)
        except (urllib.error.URLError, TimeoutError, OSError):
            raise GraphError("other") from None
        if len(data) > max_bytes:
            raise GraphError("other")
        return data
