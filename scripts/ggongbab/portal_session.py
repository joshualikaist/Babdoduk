"""Memory-only handoff from an authenticated dedicated Chrome to a LIST client.

No cookie files, environment variables, credentials, redirects or authentication
requests. Public methods never return a cookie jar or an unrestricted Session.
"""
from __future__ import annotations

import ctypes
import json
import math
import os
import subprocess
import time
from email.utils import parsedate_to_datetime
from http.cookiejar import DefaultCookiePolicy
from pathlib import Path
from urllib.parse import urlsplit, urlencode

import requests

from .portal_list_contract import (LIST_URL, MAX_RESPONSE_BYTES, list_query,
                                   require_list_request, validate_page)
from .portal_known_schema import KNOWN_HOST
from .web.exit_codes import AuthRequired, UiContractError

SAFE_REASON_CODES = frozenset({
    "PORTAL_CDP_ATTACH_TIMEOUT", "PORTAL_RESIDENT_OWNER_UNVERIFIED",
    "PORTAL_CONTEXT_MISSING_OR_AMBIGUOUS", "PORTAL_SESSION_COOKIE_MISSING_OR_AMBIGUOUS",
    "PORTAL_SESSION_COOKIE_UNUSABLE", "PORTAL_SESSION_HANDOFF_FAILED",
    "PORTAL_LIST_SESSION_UNAVAILABLE", "PORTAL_LIST_AUTH_REQUIRED",
    "PORTAL_LIST_REDIRECT_REQUIRES_MANUAL_REVIEW",
})


def safe_reason_code(error):
    value = str(error)
    return value if value in SAFE_REASON_CODES else "PORTAL_SESSION_HANDOFF_FAILED"


class ListTransportError(Exception):
    def __init__(self, retry_after=0):
        super().__init__("PORTAL_LIST_TRANSPORT_UNAVAILABLE")
        self.retry_after = retry_after


def retry_after_seconds(value, now):
    try:
        if value.isdigit():
            return int(value)
        stamp = parsedate_to_datetime(value)
        return max(0, stamp.timestamp() - now) if stamp.tzinfo else 0
    except (ValueError, TypeError, OverflowError):
        return 0


class _PortalCookies(DefaultCookiePolicy):
    def set_ok(self, cookie, request):
        return (cookie.name == "JSESSIONID" and cookie.domain.lstrip(".") == KNOWN_HOST
                and cookie.secure and super().set_ok(cookie, request))


class _ListSession(requests.Session):
    def __init__(self):
        super().__init__()
        self.trust_env = False  # No ambient proxy/.netrc credentials.
        self.cookies.set_policy(_PortalCookies())
        self.headers.update({"Accept": "application/json"})

    def send(self, request, **kwargs):
        require_list_request(request.method, request.url)
        kwargs.update(allow_redirects=False, verify=True)
        return super().send(request, **kwargs)


class PortalListClient:
    def __init__(self, cookie, *, session_factory=_ListSession, monotonic=time.monotonic):
        _eligible_cookie([cookie], time.time())
        self._session = session_factory()
        self._monotonic = monotonic
        self._closed = False
        self._session.cookies.set("JSESSIONID", cookie["value"], domain=cookie["domain"],
                                  path=cookie["path"], secure=True,
                                  expires=None if cookie.get("expires", -1) < 0 else int(cookie["expires"]))

    def fetch_list_page(self, page_index):
        if self._closed:
            raise AuthRequired("PORTAL_LIST_SESSION_UNAVAILABLE")
        url = LIST_URL + "?" + urlencode(list_query(page_index))
        require_list_request("GET", url)
        try:
            _eligible_cookie([
                {"name": c.name, "value": c.value, "domain": c.domain, "path": c.path,
                 "secure": c.secure, "expires": c.expires if c.expires is not None else -1}
                for c in self._session.cookies
            ], time.time())
            started = self._monotonic()
            with self._session.get(url, timeout=(5, 15), allow_redirects=False,
                                   stream=True) as response:
                status = response.status_code
                if status in (401, 403):
                    raise AuthRequired("PORTAL_LIST_AUTH_REQUIRED")
                if 300 <= status < 400:
                    # Do not guess whether an unknown redirect is an SSO endpoint.
                    raise AuthRequired("PORTAL_LIST_REDIRECT_REQUIRES_MANUAL_REVIEW")
                if status == 429 or 500 <= status < 600:
                    retry = response.headers.get("Retry-After", "")
                    delay = retry_after_seconds(retry, time.time())
                    raise ListTransportError(delay)
                if status != 200:
                    raise UiContractError("PORTAL_LIST_HTTP_CONTRACT_CHANGED")
                media = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
                if media != "application/json":
                    raise UiContractError("PORTAL_LIST_EXPECTED_JSON")
                body = bytearray()
                for chunk in response.iter_content(4096):
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise UiContractError("PORTAL_LIST_RESPONSE_TOO_LARGE")
                    if self._monotonic() - started > 20:
                        raise ListTransportError()
                try:
                    payload = json.loads(body)
                except (ValueError, UnicodeError):
                    raise UiContractError("PORTAL_LIST_JSON_INVALID") from None
                validate_page(payload, page_index)
                return payload
        except (AuthRequired, UiContractError):
            self.close()
            raise
        except ListTransportError:
            raise
        except Exception:
            raise ListTransportError() from None

    def close(self):
        if not self._closed:
            self._closed = True
            self._session.cookies.clear()
            self._session.close()


def verify_resident_owner(profile_dir: Path, port: int):
    """Verify the loopback listener belongs to the expected Windows Chrome profile.

    OS process metadata stays in memory and is never included in errors/logs.
    Other platforms fail closed until an equivalent owner check is implemented.
    """
    if os.name != "nt" or type(port) is not int or not 1 <= port <= 65535:
        raise AuthRequired("PORTAL_RESIDENT_OWNER_UNVERIFIED")
    script = (f"$c = @(Get-NetTCPConnection -State Listen -LocalPort {port} -ErrorAction Stop); "
              "if ($c.Count -ne 1 -or $c[0].LocalAddress -ne '127.0.0.1') { exit 1 }; "
              "$p = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $c[0].OwningProcess); "
              "if ($p.Name -ne 'chrome.exe') { exit 1 }; $p.CommandLine")
    try:
        result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                                capture_output=True, text=True, timeout=10, check=True,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        count = ctypes.c_int()
        split = ctypes.windll.shell32.CommandLineToArgvW
        split.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
        split.restype = ctypes.POINTER(ctypes.c_wchar_p)
        argv = split(result.stdout.strip(), ctypes.byref(count))
        if not argv:
            raise ValueError()
        try:
            args = [argv[i] for i in range(count.value)]
        finally:
            free = ctypes.windll.kernel32.LocalFree
            free.argtypes = [ctypes.c_void_p]
            free(argv)
        profiles = [a.split("=", 1)[1] for a in args if a.startswith("--user-data-dir=")]
        if (len(profiles) != 1 or Path(profiles[0]).resolve() != profile_dir.resolve()
                or f"--remote-debugging-port={port}" not in args
                or "--remote-debugging-address=127.0.0.1" not in args):
            raise ValueError()
    except Exception:
        raise AuthRequired("PORTAL_RESIDENT_OWNER_UNVERIFIED") from None


def _eligible_cookie(cookies, now):
    if not isinstance(cookies, list) or not all(isinstance(c, dict) for c in cookies):
        raise AuthRequired("PORTAL_SESSION_COOKIE_UNUSABLE")
    cookies = [c for c in cookies if c.get("name") == "JSESSIONID"]
    if len(cookies) != 1:
        raise AuthRequired("PORTAL_SESSION_COOKIE_MISSING_OR_AMBIGUOUS")
    cookie = cookies[0]
    path = cookie.get("path")
    expires = cookie.get("expires", -1)
    if (not isinstance(cookie.get("domain"), str) or cookie["domain"].lstrip(".") != KNOWN_HOST
            or cookie.get("secure") is not True or not isinstance(path, str) or not path.startswith("/")
            or not (urlsplit(LIST_URL).path == path
                    or urlsplit(LIST_URL).path.startswith(path.rstrip("/") + "/"))
            or not isinstance(cookie.get("value"), str) or not cookie["value"]
            or any(ch in cookie["value"] for ch in "\r\n;")
            or cookie.get("partitionKey")
            or type(expires) not in (int, float) or not math.isfinite(expires)
            or (expires >= 0 and expires <= now)):
        raise AuthRequired("PORTAL_SESSION_COOKIE_UNUSABLE")
    return cookie


class PortalSessionProvider:
    def __init__(self, profile_dir, port, *, owner_check=verify_resident_owner,
                 attach=None, client_factory=PortalListClient, wall_time=time.time):
        self._profile_dir, self._port = Path(profile_dir), port
        self._owner_check, self._attach = owner_check, attach
        self._client_factory, self._wall_time = client_factory, wall_time

    def acquire(self):
        """Called once per process start/recovery, never inside the poll loop."""
        from .web.resident import resident_session
        from .web.ui_contract import UiContract
        attach = self._attach or resident_session
        client = None
        try:
            self._owner_check(self._profile_dir, self._port)
            with attach(self._profile_dir, UiContract(mail_url="https://" + KNOWN_HOST + "/"),
                        port=self._port, start_url="", attach_only=True, reuse=True,
                        log=lambda _: None) as browser:
                contexts = {}
                for page in browser.context.pages:
                    parsed = urlsplit(page.url)
                    if parsed.scheme == "https" and parsed.netloc == KNOWN_HOST:
                        contexts[id(page.context)] = page.context
                if len(contexts) != 1:
                    raise AuthRequired("PORTAL_CONTEXT_MISSING_OR_AMBIGUOUS")
                context = next(iter(contexts.values()))
                cookie = _eligible_cookie(context.cookies([LIST_URL]), self._wall_time())
                client = self._client_factory(cookie)
                del cookie
            # Positive evidence is the exact LIST response, not cookie presence.
            client.fetch_list_page(1)
            return client
        except (AuthRequired, UiContractError, ListTransportError):
            if client:
                client.close()
            raise
        except Exception as exc:
            if client:
                client.close()
            from .web.resident import ResidentAttachTimeout
            if isinstance(exc, ResidentAttachTimeout):
                raise AuthRequired("PORTAL_CDP_ATTACH_TIMEOUT") from None
            raise AuthRequired("PORTAL_SESSION_HANDOFF_FAILED") from None
