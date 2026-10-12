"""The Babdoduk Ops Chrome: one dedicated browser, one profile, one loopback CDP port.

The Portal worker and the Dooray Radar stay separate processes (separate failure domains);
only the browser is shared. Tab 1 is KAIST Portal, tab 2 is the Dooray inbox.

`.local/ops-browser.json` selects which dedicated browser the workers attach to:
  * `unified`  - the Ops Chrome (`.local/ops-browser-profile`, 127.0.0.1:9224);
  * `separate` - the two legacy dedicated browsers (Portal 9223, Dooray 9222). This is also the
    value when the file is absent, so deploying this code changes nothing until the operator
    switches, and switching back is the rollback.

Nothing here reads cookies, credentials, titles or mail. Tab detection uses the loopback
`/json/list` target list and keeps only the scheme and hostname of each page, in memory.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .ops_storage import OpsError, atomic_json, read_json
from .portal_known_schema import KNOWN_HOST as PORTAL_HOST

UNIFIED_PORT = 9224                      # new loopback port: never collides with 9222/9223
UNIFIED_PROFILE = "ops-browser-profile"
LEGACY = {"portal": ("portal-browser-profile", 9223), "dooray": ("dooray-browser-profile", 9222)}
MODES = ("separate", "unified")
MODE_FILE = "ops-browser.json"
START_LOCK = "ops-browser.lock"
PORTAL_START = "https://" + PORTAL_HOST + "/"
DOORAY_FALLBACK = "https://kaist.gov-dooray.com/mail/systems/inbox"
SSO_HOST = "sso.kaist.ac.kr"             # a tab here is a login in progress, not a missing tab


@dataclass(frozen=True)
class BrowserSlot:
    """Where one worker's dedicated browser lives. Paths and ports only."""
    profile: Path
    port: int
    unified: bool


def read_mode(local: Path) -> str:
    """Corrupt or unknown content fails closed; it is never treated as either mode."""
    data = read_json(Path(local) / MODE_FILE, {"mode": "separate"})
    if set(data) != {"mode"} or data["mode"] not in MODES:
        raise OpsError("OPS_STATE_UNAVAILABLE")
    return data["mode"]


def set_mode(local: Path, mode: str) -> None:
    if mode not in MODES:
        raise OpsError("OPS_CONFIGURATION_REQUIRED")
    atomic_json(Path(local) / MODE_FILE, {"mode": mode})


def unified_slot(root: Path) -> BrowserSlot:
    return BrowserSlot(Path(root).resolve() / ".local" / UNIFIED_PROFILE, UNIFIED_PORT, True)


def legacy_slot(root: Path, role: str) -> BrowserSlot:
    name, port = LEGACY[role]
    return BrowserSlot(Path(root).resolve() / ".local" / name, port, False)


def slot_for(root: Path, role: str) -> BrowserSlot:
    """The browser a worker uses under the current mode."""
    root = Path(root).resolve()
    return unified_slot(root) if read_mode(root / ".local") == "unified" else legacy_slot(root, role)


def dooray_start_url(contract_path: Path) -> str:
    """The calibrated inbox address, origin + path only (no query values)."""
    try:
        data = json.loads(Path(contract_path).read_text(encoding="utf-8"))
        parts = urlsplit(data.get("mail_url") or "")
        if parts.scheme == "https" and parts.hostname:
            return f"https://{parts.hostname}{parts.path or '/'}"
    except (OSError, ValueError, AttributeError):
        pass
    return DOORAY_FALLBACK


def dooray_host(contract_path: Path) -> str:
    return urlsplit(dooray_start_url(contract_path)).hostname or ""


def role_of(url: str, mail_host: str) -> str:
    """'portal', 'dooray', 'sso' (a KAIST SSO login page) or ''. Exact https hostname only."""
    try:
        parts = urlsplit(url or "")
    except ValueError:
        return ""
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host:
        return ""
    if host == PORTAL_HOST:
        return "portal"
    if mail_host and host == mail_host.lower():
        return "dooray"
    if host == SSO_HOST:
        return "sso"
    return ""


def page_targets(port: int, *, timeout: float = 2.0, opener=urllib.request.urlopen) -> list[dict]:
    """Top-level page targets of the loopback endpoint: id + url, in memory only."""
    try:
        with opener(f"http://127.0.0.1:{int(port)}/json/list", timeout=timeout) as response:
            targets = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        raise OpsError("OPS_BROWSER_TARGETS_UNAVAILABLE") from None
    if not isinstance(targets, list):
        raise OpsError("OPS_BROWSER_TARGETS_UNAVAILABLE")
    return [{"id": str(t.get("id") or ""), "url": str(t.get("url") or "")}
            for t in targets if isinstance(t, dict) and t.get("type") == "page"]


def tab_roles(targets: list[dict], mail_host: str) -> dict[str, int]:
    """Page counts per role, plus 'inbox': Dooray pages on the /mail application area."""
    counts = {"portal": 0, "dooray": 0, "sso": 0, "inbox": 0}
    for target in targets:
        role = role_of(target["url"], mail_host)
        if role:
            counts[role] += 1
        if role == "dooray" and re.match(r"^/mail(/|$)", urlsplit(target["url"]).path or "/"):
            counts["inbox"] += 1
    return counts


def open_tab(port: int, url: str, *, cdp=None) -> None:
    """Open one background tab in the existing window. Never a new window, never in front."""
    if urlsplit(url).scheme != "https" or "?" in url or "#" in url:
        raise OpsError("OPS_CONFIGURATION_REQUIRED")
    new_tab(port, url, cdp=cdp)


def new_tab(port: int, url: str, *, cdp=None) -> None:
    """`Target.createTarget` with `background: true`. DevTools `PUT /json/new` restores and focuses
    a minimized window (measured 2026-10-12, Chrome 154); a background target does neither."""
    from .cdp_lite import LoopbackCdp
    try:
        with (cdp or LoopbackCdp)(port) as client:
            created = client.call("Target.createTarget", {"url": url, "background": True})
    except OpsError:
        raise OpsError("OPS_BROWSER_TAB_OPEN_FAILED") from None
    if not (created or {}).get("targetId"):
        raise OpsError("OPS_BROWSER_TAB_OPEN_FAILED")


def wait_for_settled_pages(port: int, *, targets=page_targets, settle: float = 2.0, timeout: float = 15.0,
                           sleep=time.sleep, clock=time.monotonic) -> list[dict]:
    """After a start, wait until session restore stops adding pages, so no tab is duplicated."""
    deadline = clock() + timeout
    last, stable_since, pages = None, clock(), []
    while clock() < deadline:
        try:
            pages = targets(port)
        except OpsError:
            pages = []
        key = sorted(p["id"] for p in pages)
        if pages and key == last:
            if clock() - stable_since >= settle:
                return pages
        else:
            last, stable_since = key, clock()
        sleep(0.5)
    return pages


def ensure_tabs(port: int, mail_host: str, dooray_url: str, *, roles=("portal", "dooray"),
                targets=page_targets, cdp=None, log=lambda _: None) -> dict[str, int]:
    """Open a role's tab only when that role has no page at all. Never closes or moves a tab.

    While a KAIST SSO page is open a login is in progress and that page may BE the missing tab
    (Portal redirects there before login), so nothing is opened then: no duplicate tabs.
    """
    present = tab_roles(targets(port), mail_host)
    for role in roles:
        if not present[role] and not present["sso"]:
            open_tab(port, PORTAL_START if role == "portal" else dooray_url, cdp=cdp)
            log("OPS_BROWSER_TAB_OPENED")
    return tab_roles(targets(port), mail_host)


BUSY_PROBE_SECONDS = 5                   # a busy renderer answers within this; a discarded tab never does


def wake_tabs(port: int, mail_host: str, *, cdp=None, wait: float = 15, sleep=time.sleep,
              clock=time.monotonic) -> dict:
    """Restore any page that Chrome discarded, before a Playwright client attaches.

    Playwright initialises EVERY page while attaching, so one dead tab (measured: the hidden
    Portal tab discarded under memory pressure) blocks both workers. Each page is probed with a
    renderer round trip, and once more with a longer wait so a merely busy page is left alone.
    A page that answers neither is reloaded in place with `Page.reload` on its own session:
    Chrome reloads the discarded tab from its own URL and session, as a click on the tab would,
    without activating the tab or the window. (`Target.activateTarget`, used before, restores
    and focuses a minimized window - measured 2026-10-12, Chrome 154 - so the Ops Chrome jumped
    in front of the owner's work.) Nothing is navigated elsewhere, typed, evaluated or closed. A
    page that stays unresponsive fails closed. Returns counts and the roles restored.
    """
    from .cdp_lite import LoopbackCdp
    restored, roles = 0, []
    with (cdp or LoopbackCdp)(port) as client:
        targets = (client.call("Target.getTargets") or {}).get("targetInfos")
        if targets is None:
            raise OpsError("OPS_BROWSER_TARGETS_UNAVAILABLE")
        pages = [t for t in targets if t.get("type") == "page"]
        for target in pages:
            attached = client.call("Target.attachToTarget", {"targetId": target["targetId"], "flatten": True})
            if not attached:
                raise OpsError("OPS_BROWSER_TAB_UNRESPONSIVE")
            session = attached["sessionId"]
            try:
                if client.call("Runtime.getIsolateId", session=session, timeout=2) is not None:
                    continue
                if client.call("Runtime.getIsolateId", session=session, timeout=BUSY_PROBE_SECONDS) is not None:
                    continue
                client.call("Page.reload", {}, session=session)
                deadline = clock() + wait
                while client.call("Runtime.getIsolateId", session=session, timeout=1.5) is None:
                    if clock() >= deadline:
                        raise OpsError("OPS_BROWSER_TAB_UNRESPONSIVE")
                    sleep(0.5)
                restored += 1
                roles.append(role_of(target.get("url", ""), mail_host) or "other")
            finally:
                client.call("Target.detachFromTarget", {"sessionId": session}, timeout=2)
    return {"pages": len(pages), "restored": restored, "roles": roles}


def start_dedicated(profile: Path, *, port: int, roles, dooray_url: str, mail_host: str, start=None,
                    settled=wait_for_settled_pages, ensure=ensure_tabs, log=lambda _: None,
                    minimized: bool = False) -> None:
    """Start a dedicated Chrome with its tabs: the Ops Chrome uses roles portal + dooray.

    A fresh profile gets the start addresses on the command line (one window, one tab each).
    A used profile starts with no address, so Chrome restores its own tabs instead of adding
    duplicates; a role that restore did not bring back is then opened as a tab. `minimized`:
    a start no person asked for (a worker or the watchdog) opens minimized and in the background.
    """
    from .web.resident import start_chrome
    start = start or start_chrome
    urls = tuple(PORTAL_START if role == "portal" else dooray_url for role in roles)
    fresh = not (Path(profile) / "Default" / "Preferences").exists()
    start(Path(profile), port=port, start_urls=urls if fresh else (), log=lambda _: None, minimized=minimized)
    settled(port)
    ensure(port, mail_host, dooray_url, roles=roles, log=log)
