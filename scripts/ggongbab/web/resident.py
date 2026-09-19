# -*- coding: utf-8 -*-
"""Resident Chrome driven over CDP, for when SSO escapes the automation context.

Why this exists, with the evidence that produced it. Running setup with the
installed Chrome channel, the lifecycle trace showed:

    [trace] navigation  page #1  main  https://sso.kaist.ac.kr  /auth/kaist/user/login/view
    [setup] still waiting (92s) - other-host

Page #1 sat on the KAIST SSO form for the whole run while the user finished
logging in and reached the mailbox on screen. The login therefore completed in a
browser this agent was not driving: a context escape, not a detection bug.

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

from .browser import NAV_TIMEOUT_MS, Session, ensure_session_restore, _playwright
from .exit_codes import AgentError
from .ui_contract import UiContract

DEBUG_HOST = "127.0.0.1"          # loopback only, never 0.0.0.0
DEFAULT_DEBUG_PORT = 9222
START_TIMEOUT_SECONDS = 30

WINDOWS_CHROME_PATHS = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
)


class ResidentError(AgentError):
    code = 1


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
                     reuse: bool = True) -> Iterator[Session]:
    """Attach to a resident Chrome, starting one when none is listening.

    The browser is left running on purpose when we started it for setup: that is
    what keeps the SSO session alive for the next command.
    """
    sync_playwright = _playwright()
    process: Optional[subprocess.Popen] = None
    existing = is_running(port) if reuse else None
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
        contexts = list(browser.contexts) or [browser.new_context()]
        context = contexts[0]
        try:
            context.set_default_timeout(NAV_TIMEOUT_MS)
        except Exception:  # noqa: BLE001
            pass
        page = context.pages[0] if context.pages else context.new_page()
        if start_url and existing:
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
