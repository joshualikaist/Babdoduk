# -*- coding: utf-8 -*-
"""Resident Chrome driven over CDP, for when SSO escapes the automation context.

Why this exists, with the evidence that produced it. Running setup with the
installed Chrome channel, the lifecycle trace showed:

    [trace] navigation  page #1  main  https://sso.kaist.ac.kr  /auth/kaist/user/login/view
    [setup] still waiting (92s) - other-host

Page #1 appeared to stay on the KAIST SSO form while the user reached the mailbox
on screen. That alone cannot distinguish a different browser, an unobserved
context, or a stale Playwright event loop. Setup must monitor all CDP contexts
and keep processing browser events before diagnosing a hand-off.

So instead of asking Playwright to own the browser, we start a normal Chrome
ourselves with a dedicated profile and a debugging port, and attach to it. Every
window that Chrome opens - including ones the SSO flow spawns - belongs to that
browser and is visible over the connection. The browser also keeps running
between commands, which is what makes a session cookie survive.

Safety: the debugging port is bound to 127.0.0.1 only, never to an address that
accepts outside connections. The dedicated profile under `.local/` is used; the
user's own Chrome profile is never opened.
"""
from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional
from urllib.parse import urlparse

from .browser import NAV_TIMEOUT_MS, Session, ensure_session_restore, _playwright
from .exit_codes import AgentError, AuthRequired
from .ui_contract import UiContract
from .page_select import collect_targets

DEBUG_HOST = "127.0.0.1"          # loopback only, never 0.0.0.0
DEFAULT_DEBUG_PORT = 9222
START_TIMEOUT_SECONDS = 30

WINDOWS_CHROME_PATHS = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
)


class ResidentError(AgentError):
    code = 1


class BrowserScope:
    """Page discovery and observation across a CDP browser's live contexts.

    Refresh on each poll: SSO may create a context after we attach. Existing
    observers and the detection timeout must also follow those new contexts.
    """

    def __init__(self, browser, port):
        self.browser = browser
        self.port = port
        self._contexts = []
        self._listeners = []
        self._timeout = NAV_TIMEOUT_MS

    def refresh(self):
        contexts = list(self.browser.contexts)
        for context in contexts:
            if context in self._contexts:
                continue
            self._contexts.append(context)
            context.set_default_timeout(self._timeout)
            for event, handler in list(self._listeners):
                context.on(event, handler)
                if event == "page":
                    for page in list(context.pages):
                        handler(page)
        return contexts

    @property
    def pages(self):
        return [page for context in self.refresh() for page in list(context.pages)]

    def set_default_timeout(self, timeout):
        self._timeout = timeout
        for context in self.refresh():
            context.set_default_timeout(timeout)

    def on(self, event, handler):
        for context in self.refresh():
            context.on(event, handler)
        self._listeners.append((event, handler))

    def remove_listener(self, event, handler):
        registered = [h for e, h in self._listeners if e == event and h == handler]
        self._listeners = [(e, h) for e, h in self._listeners
                           if not (e == event and h == handler)]
        for context in self._contexts:
            for callback in registered:
                try:
                    context.remove_listener(event, callback)
                except Exception:  # a context may have closed during SSO
                    pass

    def diagnose(self, host, log):
        """Compare protocol targets with Playwright, without titles or secrets."""
        log(f"[setup] CDP endpoint: {endpoint(self.port)}")
        log(f"[setup] Playwright contexts: {len(self.browser.contexts)}")
        try:
            with urllib.request.urlopen(f"{endpoint(self.port)}/json/list", timeout=2) as res:
                targets = json.loads(res.read().decode("utf-8"))
            mail_seen = False
            for target in targets:
                if target.get("type") != "page":
                    continue
                parsed = urlparse(target.get("url", ""))
                log(f"  CDP page: {parsed.hostname or ''}{parsed.path}")
                mail_seen |= (parsed.netloc.lower() == host.lower()
                              and (parsed.path == "/mail" or parsed.path.startswith("/mail/")))
            if mail_seen:
                log("[setup] CDP sees a mail tab; Playwright did not select a stable mailbox.")
            else:
                log("[setup] No mail tab is visible at this CDP endpoint.")
                log("[setup] If the inbox is visible, check whether it is in another Chrome/profile.")
        except (urllib.error.URLError, OSError, ValueError):
            log("[setup] Could not read CDP targets; check the resident Chrome connection.")


def endpoint(port: int = DEFAULT_DEBUG_PORT) -> str:
    return f"http://{DEBUG_HOST}:{port}"


def is_running(port: int = DEFAULT_DEBUG_PORT, timeout: float = 1.5) -> Optional[dict]:
    """Version info when a debuggable Chrome answers on the loopback port."""
    try:
        with urllib.request.urlopen(f"{endpoint(port)}/json/version", timeout=timeout) as res:
            return json.loads(res.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None


def chrome_executable() -> str:
    """Path to the INSTALLED Google Chrome.

    Playwright's bundled Chromium is also called `chrome.exe`, so asking
    Playwright for an executable path and checking the file name picks the wrong
    browser. The installed locations are checked first, and the bundled build is
    only a last resort - with the resident design the point is to run the same
    browser the machine (and the SSO flow) already uses.
    """
    for candidate in WINDOWS_CHROME_PATHS:
        if Path(candidate).exists():
            return candidate
    local = Path.home() / "AppData/Local/Google/Chrome/Application/chrome.exe"
    if local.exists():
        return str(local)
    raise ResidentError("Google Chrome was not found",
                        hint="install Google Chrome, or run setup without --cdp")


def start_chrome(profile_dir: Path, port: int = DEFAULT_DEBUG_PORT, start_url: str = "",
                 log=print) -> subprocess.Popen:
    """Launch a normal Chrome with the dedicated profile and a loopback debug port."""
    profile_dir = Path(profile_dir).resolve()
    profile_dir.mkdir(parents=True, exist_ok=True)
    ensure_session_restore(profile_dir)
    executable = chrome_executable()
    args = [
        executable,
        f"--remote-debugging-address={DEBUG_HOST}",
        f"--remote-debugging-port={port}",
        # Absolute: the command line is what stop_chrome matches on.
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if start_url:
        args.append(start_url)
    log(f"Browser engine : Google Chrome (resident, debug port {port} on {DEBUG_HOST})")
    log(f"  executable   : {Path(executable).parent.name}/{Path(executable).name}")
    process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + START_TIMEOUT_SECONDS
    while time.time() < deadline:
        if is_running(port):
            return process
        if process.poll() is not None:
            raise ResidentError("Chrome exited immediately",
                                hint="close any Chrome already using this debug port")
        time.sleep(0.5)
    raise ResidentError(f"Chrome did not open the debug port within {START_TIMEOUT_SECONDS}s")


@contextmanager
def resident_session(profile_dir: Path, contract: UiContract, *, start_url: str = "",
                     port: int = DEFAULT_DEBUG_PORT, log=print,
                     reuse: bool = True, attach_only: bool = False) -> Iterator[Session]:
    """Attach to a resident Chrome, starting one when none is listening.

    The browser is left running on purpose when we started it for setup: that is
    what keeps the SSO session alive for the next command.
    """
    process: Optional[subprocess.Popen] = None
    existing = is_running(port) if reuse else None
    if attach_only:
        if not existing:
            raise AuthRequired("An existing resident Portal browser is required")
        start_url = ""  # Observation must not navigate, reload, or start Chrome.
    sync_playwright = _playwright()
    if existing:
        log(f"Browser engine : Google Chrome (resident, already listening on {DEBUG_HOST}:{port})")
    else:
        process = start_chrome(profile_dir, port, start_url, log=log)

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.connect_over_cdp(endpoint(port), timeout=30_000)
        except Exception as exc:  # noqa: BLE001
            raise ResidentError(f"could not attach to Chrome ({exc.__class__.__name__})",
                                hint=f"check that Chrome is listening on {DEBUG_HOST}:{port}") from exc
        contexts = list(browser.contexts)
        if attach_only and not any(c.pages for c in contexts):
            browser.close()
            raise AuthRequired("An existing Portal page is required")
        contexts = contexts or [browser.new_context()]
        context = BrowserScope(browser, port)
        # URL-only lookup avoids evaluating unrelated tabs while attaching.
        host = urlparse(start_url or contract.mail_url).netloc
        targets = collect_targets(context, host, with_evidence=False) if host else []
        mailbox = next((target for target in targets if target.mail_path), None)
        pages = context.pages
        page = mailbox.page if mailbox else (pages[0] if pages else contexts[0].new_page())
        if start_url and existing and mailbox is None:
            # Keep existing SSO/MFA tabs intact when attaching again.
            page = contexts[0].new_page()
            try:
                page.goto(start_url, wait_until="domcontentloaded")
            except Exception:  # noqa: BLE001
                pass
        session = Session(page=page, context=context, contract=contract)
        session.engine = "Google Chrome (resident/CDP)"
        try:
            yield session
        finally:
            # Detach without closing: the window stays open and stays logged in.
            try:
                browser.close()
            except Exception:  # noqa: BLE001
                pass


def stop_chrome(profile_dir: Path, port: int = DEFAULT_DEBUG_PORT, log=print) -> bool:
    """Close the resident Chrome started for this profile. Only on request.

    Matched by the dedicated profile path on the command line, so a Chrome the
    user opened for their own browsing is never touched.
    """
    if not is_running(port):
        log("no resident Chrome is listening")
        return False
    marker = str(Path(profile_dir).resolve())
    query = (
        "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
        f"Where-Object {{ $_.CommandLine -like '*{marker}*' }} | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
    )
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", query],
                       check=False, capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        log(f"could not stop Chrome automatically ({exc.__class__.__name__}); close the window")
        return False
    time.sleep(1.5)
    still = bool(is_running(port))
    log("resident Chrome closed" if not still else "Chrome is still listening; close the window")
    return not still
