# -*- coding: utf-8 -*-
"""Persistent browser session for Dooray.

The only credential this agent ever holds is a browser profile that the user
created by logging in themselves. There is no password handling anywhere in this
file, by design:

  * `--setup` opens a visible browser and waits for the human to finish SSO.
  * `--run` reuses that profile headlessly.
  * if the session has expired, the agent stops with AUTH_REQUIRED. It never
    types credentials, never replays a login form, never works around SSO.
"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Optional

from .exit_codes import AgentError, AuthRequired
from .ui_contract import UiContract

PROFILE_DIRNAME = "dooray-browser-profile"
SETUP_TIMEOUT_SECONDS = 600
NAV_TIMEOUT_MS = 45_000
# The real KAIST tenant. Used when --setup is run without --url.
DEFAULT_DOORAY_URL = "https://kaist.gov-dooray.com/"


class PlaywrightMissing(AgentError):
    code = 1


def ensure_session_restore(profile_dir: Path) -> None:
    """Make Chromium keep session cookies across restarts.

    Measured on the live profile: after `--setup` the only Dooray cookie left on
    disk was `SCOUTER` (monitoring). The authentication cookie is a *session*
    cookie, and Chromium discards those on exit unless the profile is set to
    restore the previous session. Without this, every scheduled run would land on
    the identity provider and the unattended design could never work.

    Only these two keys are touched; the rest of the profile is left alone.
    """
    prefs_path = profile_dir / "Default" / "Preferences"
    prefs: dict = {}
    if prefs_path.exists():
        try:
            prefs = json.loads(prefs_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            prefs = {}
    session = prefs.setdefault("session", {})
    profile = prefs.setdefault("profile", {})
    if session.get("restore_on_startup") == 1 and profile.get("exit_type") == "Normal":
        return
    session["restore_on_startup"] = 1          # "continue where you left off"
    session.setdefault("startup_urls", [])
    profile["exit_type"] = "Normal"            # a clean exit flushes session cookies
    prefs_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        prefs_path.write_text(json.dumps(prefs, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def dooray_cookie_summary(profile_dir: Path, host_fragment: str = "dooray") -> dict:
    """Cookie NAMES and counts from the profile, for diagnostics. Never values."""
    db = profile_dir / "Default" / "Network" / "Cookies"
    summary = {"dbExists": db.exists(), "total": 0, "host": 0, "persistent": 0, "names": []}
    if not db.exists():
        return summary
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
        rows = con.execute("select host_key, name, is_persistent from cookies").fetchall()
        con.close()
    except sqlite3.Error:
        return summary
    summary["total"] = len(rows)
    hits = [r for r in rows if host_fragment in (r[0] or "")]
    summary["host"] = len(hits)
    summary["persistent"] = sum(1 for r in hits if r[2])
    summary["names"] = sorted({r[1] for r in hits})[:12]
    return summary


def _playwright():
    try:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415
    except ImportError as exc:
        raise PlaywrightMissing(
            "playwright is not installed",
            hint="pip install -r requirements-ggongbab.txt  &&  python -m playwright install chromium",
        ) from exc
    return sync_playwright


@dataclass
class Session:
    page: Any
    context: Any
    contract: UiContract

    @property
    def url(self) -> str:
        try:
            return self.page.url or ""
        except Exception:  # noqa: BLE001
            return ""

    def at_login_screen(self) -> bool:
        return self.contract.looks_like_login(self.url)

    def assert_authenticated(self) -> None:
        """Stop the run rather than attempt anything clever about logging in."""
        if self.at_login_screen():
            raise AuthRequired(
                f"Dooray redirected to an identity page ({self.url.split('?')[0]})",
                hint="the stored profile has no Dooray auth cookie; run: "
                     "python scripts/dooray_web_agent.py --setup")
        marker = self.contract.logged_in_marker
        if marker:
            try:
                self.page.wait_for_selector(marker, timeout=15_000, state="attached")
            except Exception as exc:  # noqa: BLE001
                raise AuthRequired(
                    "the mailbox did not load as a logged-in page",
                    hint="the session may have expired; run --setup again") from exc


@contextmanager
def browser_session(profile_dir: Path, contract: UiContract, *, headless: bool,
                    start_url: str = "") -> Iterator[Session]:
    """Open the persistent profile. The profile directory holds the SSO cookies."""
    sync_playwright = _playwright()
    profile_dir.mkdir(parents=True, exist_ok=True)
    ensure_session_restore(profile_dir)
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=headless,
            viewport={"width": 1440, "height": 960},
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            args=["--disable-blink-features=AutomationControlled"],
        )
        context.set_default_timeout(NAV_TIMEOUT_MS)
        page = context.pages[0] if context.pages else context.new_page()
        try:
            target = start_url or contract.mail_url
            if target:
                page.goto(target, wait_until="domcontentloaded")
            yield Session(page=page, context=context, contract=contract)
        finally:
            try:
                context.close()
            except Exception:  # noqa: BLE001
                pass


def wait_for_login(session: Session, timeout_seconds: int = SETUP_TIMEOUT_SECONDS, log=print) -> str:
    """Block until the browser is off the SSO screen. Returns the landing URL.

    This proves a session exists. It does NOT prove the browser is looking at the
    mailbox: Dooray can land on Home, Project or Messenger. Deciding where the
    mail list lives is a separate step on purpose.
    """
    deadline = time.time() + timeout_seconds
    page = session.page
    while time.time() < deadline:
        url = page.url or ""
        if url and not session.contract.looks_like_login(url):
            time.sleep(3)   # let a redirect chain finish before believing it
            if not session.contract.looks_like_login(page.url or ""):
                return page.url or url
        time.sleep(2)
    raise AuthRequired("login was not completed in time",
                       hint="run --setup again and finish the SSO login in the window")
