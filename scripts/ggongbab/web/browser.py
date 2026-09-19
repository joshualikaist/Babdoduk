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
import re
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Optional
from urllib.parse import urlparse

from .exit_codes import AgentError, AuthRequired
from .ui_contract import UiContract

PROFILE_DIRNAME = "dooray-browser-profile"
# Short enough that a bug shows up fast; login normally finishes in seconds.
SETUP_TIMEOUT_SECONDS = 180
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


def location_of(url: str) -> str:
    """origin + path. Query values never reach a log."""
    parsed = urlparse(url or "")
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}" if parsed.netloc else (url or "")


# Reports the document's state instead of passing judgement in the page. Asking
# for `readyState === 'complete'` was too strict: a Dooray SPA that the user is
# already using can sit at `interactive`, and the mail view renders into a frame,
# leaving the top document's text nearly empty.
_STATE_JS = """
() => {
  try {
    return {
      ready: document.readyState || '',
      body: !!document.body,
      text: ((document.body && document.body.innerText) || '').trim().length
    };
  } catch (e) { return { ready: 'error', body: false, text: 0 }; }
}
"""

# The mail application area, confirmed against the live tenant
# (https://kaist.gov-dooray.com/mail/systems/inbox).
MAIL_PATH = re.compile(r"^/mail(/|$)", re.I)

# classification -> how good a login signal it is
RANKS = {
    "authenticated-mail": 4,
    "authenticated-mail-frame": 3,
    "authenticated-app": 2,
    "app-root": 1,
    "identity-provider": 0,
    "other-host": 0,
    "not-ready": 0,
    "unreadable": 0,
}


@dataclass
class PageObservation:
    page: Any
    url: str
    path: str = "/"
    frame_url: str = ""
    ready: str = ""
    has_body: bool = False
    text_len: int = 0
    classification: str = "unreadable"

    @property
    def rank(self) -> int:
        return RANKS.get(self.classification, 0)

    @property
    def authenticated(self) -> bool:
        return self.rank > 0

    def lines(self) -> list[str]:
        out = [f"  page: {urlparse(self.url).path or '/'}"]
        if self.frame_url:
            out.append(f"  frame: {urlparse(self.frame_url).path or '/'}")
        if self.ready:
            out.append(f"  readyState: {self.ready}")
        out.append(f"  classification: {self.classification}")
        return out


def _mail_frame_url(page, host: str) -> str:  # noqa: ANN001
    """A frame under the mail area, if the shell hosts the mailbox in one."""
    try:
        frames = list(page.frames)
    except Exception:  # noqa: BLE001
        return ""
    for frame in frames:
        try:
            url = frame.url or ""
        except Exception:  # noqa: BLE001
            continue
        if not url or url.startswith("about:"):
            continue
        if host and urlparse(url).netloc.lower() != host.lower():
            continue
        if MAIL_PATH.match(urlparse(url).path or "/"):
            return url
    return ""


def observe_page(page, contract: UiContract, host: str = "") -> Optional[PageObservation]:  # noqa: ANN001
    """What this page actually is, with a reason - never a bare yes/no."""
    try:
        if page.is_closed():
            return None
        url = page.url or ""
    except Exception:  # noqa: BLE001
        return None
    if not url or url.startswith("about:"):
        return None
    path = urlparse(url).path or "/"
    obs = PageObservation(page=page, url=url, path=path)
    if host and urlparse(url).netloc.lower() != host.lower():
        obs.classification = "other-host"
        return obs
    if contract.looks_like_login(url):
        obs.classification = "identity-provider"
        return obs

    state: dict = {}
    try:
        state = page.evaluate(_STATE_JS) or {}
    except Exception:  # noqa: BLE001 - mid-navigation
        state = {}
    obs.ready = str(state.get("ready") or "")
    obs.has_body = bool(state.get("body"))
    obs.text_len = int(state.get("text") or 0)
    reachable = bool(obs.ready) and obs.ready != "error"

    obs.frame_url = _mail_frame_url(page, host)
    if MAIL_PATH.match(path):
        # Being inside the mail application is itself the signal. A rendered
        # mailbox can still report `interactive`, so readiness is not demanded.
        obs.classification = "authenticated-mail" if reachable or obs.has_body else "not-ready"
        return obs
    if obs.frame_url:
        obs.classification = "authenticated-mail-frame" if reachable or obs.has_body else "not-ready"
        return obs
    if path not in ("", "/"):
        obs.classification = ("authenticated-app"
                              if obs.has_body and obs.ready in ("interactive", "complete")
                              else "not-ready")
        return obs
    # The bare root is the weakest signal: it is also what shows for a moment
    # before the redirect to the identity provider starts.
    obs.classification = ("app-root"
                          if obs.has_body and obs.ready == "complete" and obs.text_len > 0
                          else "not-ready")
    return obs


def observe_pages(context, contract: UiContract, host: str = "") -> list[PageObservation]:  # noqa: ANN001
    out: list[PageObservation] = []
    for page in list(getattr(context, "pages", []) or []):
        obs = observe_page(page, contract, host)
        if obs is not None:
            out.append(obs)
    out.sort(key=lambda o: o.rank, reverse=True)
    return out


def authenticated_pages(context, contract: UiContract, host: str = "") -> list:  # noqa: ANN001
    """Signed-in pages, best first, as (page, url)."""
    return [(o.page, o.url) for o in observe_pages(context, contract, host) if o.authenticated]


def wait_for_login(session: Session, timeout_seconds: int = SETUP_TIMEOUT_SECONDS, log=print,
                   host: str = "", poll_seconds: float = 1.0, stable_polls: int = 3) -> str:
    """Block until a signed-in Dooray page exists anywhere in the context.

    Every cycle re-reads `context.pages`. The launch page is never trusted: KAIST
    SSO can leave it parked on the identity provider while the authenticated app
    opens in another tab, and a version that polled one fixed page waited out the
    whole timeout without noticing.

    A candidate must also hold still. Opening the tenant root shows that URL for a
    moment before the redirect to the identity provider begins, so the same page
    has to look signed-in on several consecutive polls before it counts.

    On success `session.page` is repointed at the page that won, and its URL is
    returned. That URL proves a session exists; it does not claim to be the mailbox.
    """
    deadline = time.time() + timeout_seconds
    last_message = ""
    streak_url = ""
    streak = 0

    def say(message: str) -> None:
        nonlocal last_message
        if message != last_message:       # only when the state actually changes
            log(message)
            last_message = message

    say("[setup] waiting for SSO login...")
    while time.time() < deadline:
        observations = observe_pages(session.context, session.contract, host)
        best = observations[0] if observations and observations[0].authenticated else None

        # Report what was actually seen. The old message claimed "identity
        # provider" whenever no candidate was found, which was often untrue: the
        # page could simply have failed a readiness check.
        report = ["[setup] observed:"]
        for obs in observations[:3]:
            report.extend(obs.lines())
        if not observations:
            report.append("  (no open page yet)")
        say("\n".join(report))

        if best is not None:
            key = f"{id(best.page)}|{best.url}"
            if key == streak_url:
                streak += 1
            else:
                streak_url, streak = key, 1
            if streak >= stable_polls:
                session.page = best.page
                log("[setup] authenticated Dooray page detected")
                log("[setup] continuing...")
                return best.url
        else:
            streak_url, streak = "", 0
        time.sleep(poll_seconds)
    final = observe_pages(session.context, session.contract, host)
    seen = ", ".join(f"{urlparse(o.url).path or '/'} ({o.classification})" for o in final[:3]) or "nothing"
    raise AuthRequired(
        f"no signed-in Dooray page appeared within {timeout_seconds // 60} minutes; last seen: {seen}",
        hint="run --setup again and finish the SSO login in the browser window")
