#!/usr/bin/env python3
"""Read-only end-to-end check of a deployed Babdoduk site (production or lab).

    python scripts/e2e_live.py --base https://babdoduk.vercel.app
    python scripts/e2e_live.py --base https://babdoduk-lab.vercel.app --out .local/e2e-live

It opens the real site in Chromium the way a visitor does (Korean and English, a 390x844 phone and a
1280x800 desktop) and checks the user journeys: home, 꽁밥, the magazine/events/history pages, the
먹방 월드컵 (played through to the result when its gate is open), plus site-wide link, image, console
and status checks, the lab-only pages answering 404 on production, and page load timings.

STRICTLY read-only:
  * No form is submitted and the script never sends a POST of its own.
  * Every request that is not GET/HEAD/OPTIONS is aborted in the browser before it leaves, whichever
    host it targets (the world cup's stats RPC on lab included: finishing a game on lab *tries* to
    record it, and that attempt is aborted and noted, never delivered).
  * On production a single attempted non-GET request is a failure; on lab only the world cup
    record RPC is tolerated.
  * Requests to Dooray, the Portal or any admin system are aborted and reported as failures.

Output: <out>/e2e-<host tag>.json (full report), a readable summary on stdout (and in
$GITHUB_STEP_SUMMARY), and screenshots of failures in <out>/screenshots/. Exit 1 on any failure.
Slow pages (> 5 s) only warn. The world cup phase is computed from the real date in KST, as
js/worldcup-gate.js does; nothing else depends on the wall clock.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse

ROOT = Path(__file__).resolve().parents[1]
KST = dt.timezone(dt.timedelta(hours=9))
PROD_HOST = "babdoduk.vercel.app"
LAB_HOST = "babdoduk-lab.vercel.app"
LANGS = ("ko", "en")
VIEWPORTS = {"phone": (390, 844), "desktop": (1280, 800)}
SLOW_MS = 5000
LINK_CAP = 60
LAB_ONLY = ["lab.html", "food.html", "lab-ggongbab.html", "data/food-log.json", "calendar.ics"]
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
FORBIDDEN_HOST = re.compile(r"dooray|portal\.kaist|admin\.", re.I)
RECORD_RPC = "rpc/worldcup_record_game"


# ---- pure helpers (tested in tests/test_e2e_live.py) ---------------------------------------------------

def parse_wc_window(text: str) -> dict:
    match = re.search(r"window\.BABDODUK_WC_WINDOW\s*=\s*(\{.*?\});", text)
    if not match:
        raise RuntimeError("BABDODUK_WC_WINDOW not found in js/worldcup-gate.js")
    return json.loads(match.group(1))


def read_wc_window(base: str | None = None, root: Path = ROOT) -> dict:
    """The world cup window of the site under test (its served js/worldcup-gate.js, so a lab-only
    previewFrom is seen where it exists); the repo's copy when the site cannot be read."""
    if base:
        try:
            from urllib.request import urlopen
            with urlopen(base.rstrip("/") + "/js/worldcup-gate.js", timeout=30) as resp:
                return parse_wc_window(resp.read().decode("utf-8"))
        except Exception:
            pass
    return parse_wc_window((root / "js" / "worldcup-gate.js").read_text(encoding="utf-8"))


def kst_date(now: dt.datetime) -> str:
    """A moment as its Korean calendar date, YYYY-MM-DD."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    return now.astimezone(KST).strftime("%Y-%m-%d")


def wc_phase(now: dt.datetime, window: dict, is_lab: bool = False) -> str:
    """'soon' before the first day (KST), 'live' from the first day to the last day inclusive, else
    'ended'. Lab (and localhost) honour window['previewFrom'] as the first day, as js/worldcup-gate.js."""
    start, end = window.get("start"), window.get("end")
    if not start or not end:
        return "live"
    first = start
    early = window.get("previewFrom")
    if is_lab and early and early < start:
        first = early
    today = kst_date(now)
    if today < first:
        return "soon"
    return "ended" if today > end else "live"


def dedupe_links(hrefs, base: str, cap: int = LINK_CAP) -> list[str]:
    """Same-origin http(s) links, fragments dropped, de-duplicated in order, at most `cap`."""
    origin = urlparse(base)
    seen, out = set(), []
    for href in hrefs:
        if not href:
            continue
        url = urldefrag(urljoin(base, href.strip()))[0]
        parts = urlparse(url)
        if parts.scheme not in ("http", "https") or parts.netloc != origin.netloc:
            continue
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
        if len(out) >= cap:
            break
    return out


def host_tag(base: str) -> str:
    host = urlparse(base).hostname or "site"
    return "lab" if host == LAB_HOST else "prod" if host == PROD_HOST else re.sub(r"\W+", "-", host)


def post_violations(posts: list[dict], is_lab: bool) -> list[dict]:
    """The attempted non-GET requests that are not allowed: any on production, anything but the world
    cup record RPC on lab."""
    if not is_lab:
        return list(posts)
    return [p for p in posts if not (p["host"].endswith(".supabase.co") and p["path"].endswith(RECORD_RPC))]


# ---- recording -----------------------------------------------------------------------------------------

class Report:
    def __init__(self, base: str, out: Path):
        self.base, self.out = base, out
        self.is_lab = urlparse(base).hostname == LAB_HOST
        self.results: list[dict] = []
        self.warnings: list[str] = []
        self.timings: list[dict] = []
        self.retries: list[dict] = []
        self.posts: list[dict] = []
        self.screens: list[str] = []
        self.link_cache: dict[str, int] = {}
        self.scope = ""
        self.meta: dict = {}

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.results.append({"scope": self.scope, "check": name, "ok": bool(ok), "detail": str(detail)[:600]})
        return bool(ok)

    def warn(self, text: str):
        self.warnings.append(f"[{self.scope}] {text}")

    @property
    def failures(self):
        return [r for r in self.results if not r["ok"]]

    def screenshot(self, page, label: str):
        try:
            shots = self.out / "screenshots"
            shots.mkdir(parents=True, exist_ok=True)
            name = re.sub(r"[^\w.-]+", "_", f"{host_tag(self.base)}-{self.scope}-{label}")[:150] + ".png"
            page.screenshot(path=str(shots / name), full_page=False)
            self.screens.append(name)
        except Exception:
            pass


# ---- browser plumbing ---------------------------------------------------------------------------------

def make_context(browser, rep: Report, lang: str, size: tuple[int, int], signals: dict):
    context = browser.new_context(
        viewport={"width": size[0], "height": size[1]}, locale="ko-KR" if lang == "ko" else "en-US",
        timezone_id="Asia/Seoul", service_workers="block", accept_downloads=False,
        has_touch=size[0] < 600, is_mobile=False)
    context.add_init_script(
        "try{localStorage.setItem('babdoduk-lang','%s');sessionStorage.setItem('babdoduk-welcome-seen','1');}catch(e){}" % lang)

    aborted: set[str] = set()
    signals["aborted"] = aborted

    def guard(route):
        req = route.request
        parts = urlparse(req.url)
        if FORBIDDEN_HOST.search(parts.hostname or ""):
            rep.check("never contacts Dooray/Portal/admin", False, req.url)
            aborted.add(req.url)
            route.abort()
            return
        if req.method not in SAFE_METHODS:
            rep.posts.append({"scope": rep.scope, "method": req.method, "host": parts.hostname or "",
                              "path": parts.path, "url": req.url})
            aborted.add(req.url)
            route.abort()
            return
        route.continue_()

    context.route("**/*", guard)

    def on_page(page):
        page.on("pageerror", lambda e: signals["page_errors"].append(f"{page.url}: {e}"))
        page.on("console", lambda m: m.type == "error" and signals["console"].append(
            (page.url, m.text, m.location.get("url", ""))))
        page.on("requestfailed", lambda r: signals["failed"].append((r.url, r.failure or "")))
        page.on("response", lambda r: r.status >= 400 and signals["bad"].append((r.url, r.status, page.url)))

    context.on("page", on_page)
    return context


def new_signals() -> dict:
    return {"page_errors": [], "console": [], "failed": [], "bad": [], "aborted": set()}


def goto(rep: Report, page, path: str, ready=None) -> float:
    """Navigate (one retry on a network error, recorded), wait, return the load time in ms."""
    url = urljoin(rep.base + "/", path)
    start = time.time()
    for attempt in (1, 2):
        try:
            page.goto(url, wait_until="load", timeout=45000)
            break
        except Exception as exc:
            if attempt == 2:
                raise
            rep.retries.append({"scope": rep.scope, "url": url, "error": str(exc).splitlines()[0][:200]})
            page.wait_for_timeout(1500)
    ms = round((time.time() - start) * 1000)
    if ready:
        ready()
    rep.timings.append({"scope": rep.scope, "page": path, "ms": ms})
    if ms > SLOW_MS:
        rep.warn(f"{path} loaded in {ms} ms (> {SLOW_MS} ms)")
    return ms


def settle(page, ms: int = 600):
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass
    page.wait_for_timeout(ms)


def scroll_through(page):
    """Scroll the page top to bottom so lazy images load, then back."""
    page.evaluate("""async () => {
      const h = () => document.documentElement.scrollHeight;
      for (let y = 0; y < h(); y += Math.max(300, innerHeight * 0.8)) { scrollTo(0, y); await new Promise(r => setTimeout(r, 120)); }
      scrollTo(0, 0);
    }""")
    settle(page, 300)


# ---- site-wide checks per page -------------------------------------------------------------------------

def check_images(rep: Report, page, label: str):
    broken = page.evaluate("""() => [...document.images].filter(i => {
        const src = i.currentSrc || i.getAttribute('src') || '';
        return src && i.complete && i.naturalWidth === 0 && !/\\.svg(\\?|$)/i.test(src);
      }).map(i => i.currentSrc || i.src).slice(0, 8)""")
    rep.check(f"{label}: every image loads", not broken, ", ".join(broken))


def check_links(rep: Report, page, context, label: str):
    hrefs = page.evaluate("() => [...document.querySelectorAll('a[href]')].map(a => a.href)")
    links = dedupe_links(hrefs, rep.base)
    bad = []
    for url in links:
        if url not in rep.link_cache:
            try:
                status = context.request.get(url, timeout=30000, max_redirects=5).status
            except Exception as exc:
                status = -1
                rep.link_cache[url + "#error"] = 0
                rep.warn(f"link {url}: {str(exc).splitlines()[0][:120]}")
            rep.link_cache[url] = status
        if rep.link_cache[url] != 200:
            bad.append(f"{url} -> {rep.link_cache[url]}")
    rep.check(f"{label}: {len(links)} internal links return 200", not bad, "; ".join(bad[:8]))


def page_checks(rep: Report, page, context, label: str):
    scroll_through(page)
    check_images(rep, page, label)
    check_links(rep, page, context, label)


def finish_signals(rep: Report, signals: dict):
    """Console/page errors and unexpected 4xx/5xx for the whole scenario."""
    aborted = signals["aborted"]
    errors = [f"{u}: {t[:160]}" for u, t, src in signals["console"] if src not in aborted
              and not (t.startswith("Failed to load resource") and "ERR_FAILED" in t and not src)]
    # A resource error line in the console is the same event as a bad response; report it there once.
    errors = [e for e in errors if "Failed to load resource" not in e]
    rep.check("no console errors", not errors, " | ".join(errors[:6]))
    rep.check("no page errors", not signals["page_errors"], " | ".join(signals["page_errors"][:6]))
    own = lambda u: urlparse(u).hostname in (urlparse(rep.base).hostname, "babdoduk.vercel.app", LAB_HOST)         or (urlparse(u).hostname or "").endswith(".supabase.co")
    # Third-party hosts (hot-linked article photos, fonts) are outside our control: their failures warn.
    bad = [f"{s} {u} (on {p})" for u, s, p in signals["bad"] if u not in aborted and own(u)]
    for u, s, p in signals["bad"]:
        if u not in aborted and not own(u):
            rep.warn(f"third-party {s} {u} (on {p})")
    rep.check("no unexpected 4xx/5xx responses", not bad, " | ".join(bad[:8]))
    failed = [f"{u}: {why}" for u, why in signals["failed"]
              if u not in aborted and "ERR_ABORTED" not in why and own(u)]
    for u, why in signals["failed"]:
        if u not in aborted and "ERR_ABORTED" not in why and not own(u):
            rep.warn(f"third-party request failed {u}: {why}")
    rep.check("no failed network requests", not failed, " | ".join(failed[:6]))


# ---- journeys ------------------------------------------------------------------------------------------

def wait_for(page, js: str, timeout: int = 15000) -> bool:
    try:
        page.wait_for_function(js, timeout=timeout)
        return True
    except Exception:
        return False


def journey_home(rep: Report, page, context, phase: str, lang: str):
    label = "home"
    goto(rep, page, "index.html", lambda: settle(page))
    rep.check("home: title visible", page.locator("h1").first.is_visible())
    ok = wait_for(page, "() => document.getElementById('homeCal') && document.getElementById('homeCal').dataset.state !== 'loading'")
    cells = page.locator("#homeCalGrid > *").count()
    rep.check("home: calendar renders", ok and cells > 0, f"state={page.get_attribute('#homeCal', 'data-state')} cells={cells}")
    attr = page.evaluate("document.documentElement.getAttribute('data-wc-phase')")
    rep.check("home: world cup phase attribute matches the date", attr == phase, f"page={attr} expected={phase}")
    promo = page.locator(".home-wc").first
    promo_visible = promo.count() > 0 and promo.is_visible()
    rep.check(f"home: world cup promo {'shown' if phase != 'ended' else 'hidden'} ({phase})",
              promo_visible == (phase in ("soon", "live")), f"visible={promo_visible}")
    if phase == "soon":
        rep.check("home: promo shows the countdown", bool(page.locator(".home-wc [data-wc-countdown]").first.inner_text().strip()))
    if phase == "live":
        rep.check("home: promo links to the game", page.locator(".home-wc-cta--live").first.is_visible())
    # Language toggle: flips the page language and flips back.
    toggle = page.locator("#langToggle")
    try:
        if not toggle.is_visible():
            for sel in (".site-nav-more", "#navMoreBtn", "[aria-controls='navMorePanel']", ".site-nav-toggle"):
                if page.locator(sel).count() and page.locator(sel).first.is_visible():
                    page.locator(sel).first.click()
                    break
        toggle.click(timeout=5000)
        page.wait_for_timeout(400)
        now = page.evaluate("document.documentElement.lang")
        flipped = now != lang
        rep.check("home: language toggle switches language", flipped, f"{lang} -> {now}")
        if not toggle.is_visible():
            for sel in (".site-nav-more", "#navMoreBtn", "[aria-controls='navMorePanel']", ".site-nav-toggle"):
                if page.locator(sel).count() and page.locator(sel).first.is_visible():
                    page.locator(sel).first.click()
                    break
        toggle.click(timeout=5000)
        page.wait_for_timeout(300)
        rep.check("home: language toggle switches back", page.evaluate("document.documentElement.lang") == lang)
    except Exception as exc:
        rep.check("home: language toggle works", False, str(exc).splitlines()[0])
    page_checks(rep, page, context, label)


def journey_ggongbab(rep: Report, page, context):
    goto(rep, page, "ggongbab.html", lambda: settle(page, 1000))
    feed = page.locator("#ggongbabFeed")
    rep.check("ggongbab: feed container present", feed.count() > 0)
    wait_for(page, "() => { const f = document.getElementById('ggongbabFeed'); return f && f.querySelector('.gg-chip'); }")
    cards = page.locator("#ggongbabFeed .gg-card").count()
    text = page.locator("#ggongbabFeed").inner_text().strip() if feed.count() else ""
    rep.check("ggongbab: cards or the empty state render", cards > 0 or len(text) > 20, f"cards={cards} text={text[:80]!r}")
    chips = page.locator('.gg-chip[data-group="food"]')
    values = [chips.nth(i).get_attribute("data-value") for i in range(chips.count())]
    rep.check("ggongbab: food chips incl. giveaway present", {"all", "meal", "snack", "refreshment", "giveaway"} <= set(values), str(values))
    gift = page.locator('.gg-chip[data-group="food"][data-value="giveaway"]')
    rep.check("ggongbab: giveaway chip shows the gift icon", gift.count() > 0 and "\U0001F381" in gift.first.inner_text())
    for value in values:
        try:
            page.locator(f'.gg-chip[data-group="food"][data-value="{value}"]').first.click(timeout=5000)
            page.wait_for_timeout(250)
            pressed = page.locator(f'.gg-chip[data-group="food"][data-value="{value}"]').first.get_attribute("aria-pressed")
            others = page.locator('.gg-chip[data-group="food"][aria-pressed="true"]').count()
            rep.check(f"ggongbab: chip '{value}' toggles", pressed == "true" and others == 1, f"pressed={pressed} pressedCount={others}")
            rep.check(f"ggongbab: chip '{value}' leaves the feed rendered", page.locator("#ggongbabFeed").inner_text().strip() != "")
        except Exception as exc:
            rep.check(f"ggongbab: chip '{value}' toggles", False, str(exc).splitlines()[0])
    page.locator('.gg-chip[data-group="food"][data-value="all"]').first.click()
    rep.check("ggongbab: archive section exists", page.locator(".gg-archive").count() > 0)
    page_checks(rep, page, context, "ggongbab")


def journey_simple(rep: Report, page, context, path: str, main_sel: str, heading_sel: str):
    goto(rep, page, path, lambda: settle(page))
    rep.check(f"{path}: heading visible", page.locator(heading_sel).first.is_visible())
    body = page.locator(main_sel).first.inner_text() if page.locator(main_sel).count() else ""
    rep.check(f"{path}: main content present", len(body.strip()) > 150, f"{len(body.strip())} chars")
    page_checks(rep, page, context, path)


def tap_splash(page, size):
    page.mouse.click(size[0] / 2, size[1] / 2)
    page.wait_for_timeout(250)


def play_to_result(rep: Report, page, size, timeout_s: int = 150) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if page.locator("#wcResult").is_visible():
            return True
        popover = page.evaluate("() => { const s = document.getElementById('wcSplash'); return !!s && s.matches(':popover-open'); }")
        if popover:
            tap_splash(page, size)
            continue
        if page.locator("#wcMatch").is_visible():
            try:
                page.locator('#wcMatch .wc-card[data-side="0"]').click(timeout=2000)
            except Exception:
                pass
            page.wait_for_timeout(350)
        else:
            page.wait_for_timeout(200)
    return False


def journey_worldcup(rep: Report, page, context, phase: str, size, friend_id: str, category_hint: str):
    goto(rep, page, "worldcup.html", lambda: settle(page))
    ok = wait_for(page, "() => document.getElementById('wcIntro') && !document.getElementById('wcIntro').hidden")
    rep.check("worldcup: start screen shows", ok)
    attr = page.evaluate("document.documentElement.getAttribute('data-wc-phase')")
    rep.check("worldcup: phase attribute matches the date", attr == phase, f"page={attr} expected={phase}")

    if phase == "soon":
        rep.check("worldcup: lock pill visible", page.locator("#wcLocked").is_visible())
        blur = page.evaluate("() => getComputedStyle(document.querySelector('.wc-tiles')).filter")
        rep.check("worldcup: categories are blurred while locked", "blur" in (blur or ""), f"filter={blur}")
        rep.check("worldcup: mystery lock badge visible", page.locator("#wcMysteryLock").is_visible())
        goto(rep, page, f"worldcup.html?cat={category_hint}&go=1", lambda: settle(page, 800))
        started = page.locator("#wcMatch").is_visible() or page.locator("#wcResult").is_visible()
        rep.check("worldcup: ?go=1 starts nothing while locked", not started and page.locator("#wcIntro").is_visible())
    else:
        if phase == "ended":
            rep.check("worldcup: 'event ended' note shown", page.locator(".wc-ended").first.is_visible())
        tiles = page.locator("#wcCats .wc-tile")
        rep.check("worldcup: category tiles render", tiles.count() >= 2, f"{tiles.count()}")
        try:
            tiles.nth(min(1, tiles.count() - 1)).click(timeout=5000)
            page.wait_for_timeout(300)
            rep.check("worldcup: a category can be picked", True)
        except Exception as exc:
            rep.check("worldcup: a category can be picked", False, str(exc).splitlines()[0])
        page.locator("#wcStart").click()
        # The start gacha: tap to skip it if it plays.
        opened = wait_for(page, "() => { const s = document.getElementById('wcSplash'); return (s && s.matches(':popover-open')) || !document.getElementById('wcMatch').hidden; }", 8000)
        if page.evaluate("() => { const s = document.getElementById('wcSplash'); return !!s && s.matches(':popover-open'); }"):
            tap_splash(page, size)
        rep.check("worldcup: game starts (gacha skipped)", opened and wait_for(page, "() => !document.getElementById('wcMatch').hidden", 10000))
        finished = play_to_result(rep, page, size)
        rep.check("worldcup: picks lead to the result screen", finished)
        if finished:
            rep.check("worldcup: winner is named", bool(page.locator("#wcWinner").inner_text().strip()))
            made = wait_for(page, "() => { const i = document.getElementById('wcStoryPreview'); return i && !i.hidden && i.complete && i.naturalWidth > 0; }", 25000)
            dims = page.evaluate("() => { const i = document.getElementById('wcStoryPreview'); return i ? [i.naturalWidth, i.naturalHeight] : null; }")
            rep.check("worldcup: story card is generated at 1080x1920", made and dims == [1080, 1920], f"made={made} dims={dims}")
            url_len = page.evaluate("""() => { try { const i = document.getElementById('wcStoryPreview'); const c = document.createElement('canvas');
              c.width = i.naturalWidth; c.height = i.naturalHeight; c.getContext('2d').drawImage(i, 0, 0);
              const u = c.toDataURL('image/png'); return u.startsWith('data:image/png;base64,') ? u.length : -1; } catch (e) { return -2; } }""")
            rep.check("worldcup: story canvas toDataURL works", url_len > 10000, f"len={url_len}")
            rep.check("worldcup: save and share buttons present",
                      page.locator("#wcSaveImage").is_visible() and page.locator("#wcShare").is_visible())
    # The friend link (a shared result) in any phase.
    goto(rep, page, f"worldcup.html?from={friend_id}&cat={category_hint}", lambda: settle(page, 800))
    wait_for(page, "() => document.getElementById('wcFriend') && !document.getElementById('wcFriend').hidden", 8000)
    banner = page.locator("#wcFriend")
    rep.check("worldcup: friend link shows the banner", banner.is_visible() and bool(page.locator("#wcFriendText").inner_text().strip()))
    page_checks(rep, page, context, "worldcup")


def lab_only_checks(rep: Report, context):
    rep.scope = "lab-only"
    for path in LAB_ONLY:
        url = urljoin(rep.base + "/", path)
        try:
            status = context.request.get(url, timeout=30000, max_redirects=5).status
        except Exception as exc:
            rep.check(f"{path}: reachable check", False, str(exc).splitlines()[0])
            continue
        if rep.is_lab:
            rep.check(f"{path} is served on lab", status == 200, f"status={status}")
        else:
            rep.check(f"{path} is 404 on production", status == 404, f"status={status}")


# ---- orchestration --------------------------------------------------------------------------------------

PAGES = [
    ("mukbang.html", "main", "h1"),
    ("event.html", "main", "h1"),
    ("history.html", "main", "h1"),
    ("choose.html", "main", "h1, h2"),
]


def run(base: str, out: Path) -> Report:
    from playwright.sync_api import sync_playwright

    rep = Report(base.rstrip("/"), out)
    window = read_wc_window(rep.base)
    now = dt.datetime.now(dt.timezone.utc)
    phase = wc_phase(now, window, rep.is_lab)
    catalog = json.loads((ROOT / "data" / "content" / "worldcup.json").read_text(encoding="utf-8"))
    friend_id = catalog["dishes"][0]
    category_id = (catalog.get("categories") or {}).get(friend_id) or "random"
    rep.meta = {"base": rep.base, "now_utc": now.isoformat(), "kst_date": kst_date(now), "wc_phase": phase,
                "wc_window": window, "lab": rep.is_lab}
    with sync_playwright() as pw:
        channel = os.environ.get("BABDODUK_BROWSER", "chromium")
        browser = pw.chromium.launch(channel=None if channel == "chromium" else channel, headless=True)
        try:
            for lang in LANGS:
                for vp, size in VIEWPORTS.items():
                    signals = new_signals()
                    context = make_context(browser, rep, lang, size, signals)
                    page = context.new_page()
                    if (lang, vp) == (LANGS[0], "phone"):
                        lab_only_checks(rep, context)
                    journeys = [
                        ("home", lambda: journey_home(rep, page, context, phase, lang)),
                        ("ggongbab", lambda: journey_ggongbab(rep, page, context)),
                    ] + [
                        (p.split(".")[0], (lambda p=p, m=m, h=h: journey_simple(rep, page, context, p, m, h)))
                        for p, m, h in PAGES
                    ] + [
                        ("worldcup", lambda: journey_worldcup(rep, page, context, phase, size, friend_id, category_id)),
                    ]
                    for name, fn in journeys:
                        rep.scope = f"{lang}/{vp}/{name}"
                        before = len(rep.failures)
                        try:
                            fn()
                        except Exception as exc:
                            rep.check(f"{name}: journey completed", False, f"{type(exc).__name__}: {str(exc).splitlines()[0] if str(exc) else ''}")
                        if len(rep.failures) > before:
                            rep.screenshot(page, "fail")
                    rep.scope = f"{lang}/{vp}/site-wide"
                    finish_signals(rep, signals)
                    context.close()
        finally:
            browser.close()
    rep.scope = "read-only"
    violations = post_violations(rep.posts, rep.is_lab)
    rep.check("no forbidden non-GET request was attempted", not violations,
              "; ".join(f"{p['method']} {p['host']}{p['path']} [{p['scope']}]" for p in violations[:5]))
    return rep


def summary_text(rep: Report) -> str:
    fails = rep.failures
    lines = [f"# E2E live: {rep.base}  ({'FAIL' if fails else 'PASS'})",
             f"- checks: {len(rep.results)}, failed: {len(fails)}, warnings: {len(rep.warnings)}, "
             f"navigation retries: {len(rep.retries)}, aborted non-GET attempts: {len(rep.posts)}",
             f"- world cup phase (KST {rep.meta['kst_date']}): {rep.meta['wc_phase']}"]
    if rep.timings:
        slow = sorted(rep.timings, key=lambda t: -t["ms"])[:3]
        lines.append("- slowest: " + ", ".join(f"{t['page']} {t['ms']} ms ({t['scope']})" for t in slow))
    if fails:
        lines.append("\n## Failures")
        lines += [f"- [{r['scope']}] {r['check']}: {r['detail']}" for r in fails]
    if rep.warnings:
        lines.append("\n## Warnings")
        lines += [f"- {w}" for w in rep.warnings[:30]]
    if rep.retries:
        lines.append("\n## Navigation retries")
        lines += [f"- [{r['scope']}] {r['url']}: {r['error']}" for r in rep.retries]
    if rep.screens:
        lines.append("\nScreenshots: " + ", ".join(rep.screens))
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--base", required=True, help="https://babdoduk.vercel.app or https://babdoduk-lab.vercel.app")
    parser.add_argument("--out", default=str(ROOT / ".local" / "e2e-live"))
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rep = run(args.base, out)
    report = {**rep.meta, "ok": not rep.failures, "results": rep.results, "warnings": rep.warnings,
              "timings": rep.timings, "retries": rep.retries, "aborted_non_get": rep.posts,
              "screenshots": rep.screens}
    (out / f"e2e-{host_tag(rep.base)}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    text = summary_text(rep)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(text)
    step = os.environ.get("GITHUB_STEP_SUMMARY")
    if step:
        with open(step, "a", encoding="utf-8") as fh:
            fh.write(text + "\n\n")
    return 1 if rep.failures else 0


if __name__ == "__main__":
    sys.exit(main())
