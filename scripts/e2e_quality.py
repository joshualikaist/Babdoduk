#!/usr/bin/env python3
"""Read-only quality checks of a deployed Babdoduk site (production or lab): accessibility, links, performance.

    python scripts/e2e_quality.py --base https://babdoduk.vercel.app
    python scripts/e2e_quality.py --base https://babdoduk-lab.vercel.app --out .local/e2e-quality --only a11y,links,perf

Stage 4 of the end-to-end checks (stage 1 is scripts/e2e_live.py). Chromium, 390 and 1280 px wide,
Korean and English. STRICTLY read-only: every request that is not GET/HEAD/OPTIONS is aborted in the
browser, the link checker only issues GET/HEAD, and Dooray/Portal/admin hosts are never contacted.

  a11y   axe-core (pinned, see AXE_VERSION; downloaded once into .local/cache) on index, ggongbab,
         mukbang, choose, event, history, worldcup (entry, and the result screen when the game can be
         played), plus a keyboard-only pass of the main flows (nav, language toggle, 꽁밥 filters, world
         cup tiles/start/picks, result share buttons, sound toggle) that records a visible focus ring.
         axe critical/serious violations and keyboard failures FAIL; moderate/minor only warn.
  links  crawls every internal page reachable from the nav and footer; every internal link and asset
         (html, css, js, images, json) must answer 200; broken #anchors; external links warn only.
  perf   transfer bytes, request count, largest images, LCP, CLS and load time per page; warns (never
         fails) on LCP > 2.5 s, CLS > 0.1, or > 3 MB on the phone; heaviest assets site-wide and images
         served much larger than they are displayed.

Output: <out>/quality-<host tag>.json (full report), <out>/quality-<host tag>.md (readable summary,
also on stdout and in $GITHUB_STEP_SUMMARY). Exit 1 on any failure.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import e2e_live as live  # noqa: E402  (pure helpers: phase, host tag, world cup window)

AXE_VERSION = "4.10.3"
AXE_URL = f"https://cdn.jsdelivr.net/npm/axe-core@{AXE_VERSION}/axe.min.js"
PAGES = ["index.html", "ggongbab.html", "mukbang.html", "choose.html", "event.html", "history.html", "worldcup.html"]
LANGS = ("ko", "en")
VIEWPORTS = {"phone": (390, 844, 2), "desktop": (1280, 800, 1)}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
FAIL_IMPACTS = ("critical", "serious")
IMPACT_ORDER = ("critical", "serious", "moderate", "minor")
LCP_WARN_MS = 2500
CLS_WARN = 0.1
PHONE_WEIGHT_WARN = 3 * 1024 * 1024
OVERSIZE_RATIO = 3.0          # natural pixels per displayed device pixel (linear) that counts as "much larger"
OVERSIZE_MIN_BYTES = 15 * 1024
CRAWL_PAGE_CAP = 60
EXTERNAL_TIMEOUT_MS = 10000
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/124.0 Safari/537.36")


# ---- pure helpers (tested in tests/test_e2e_quality.py) -------------------------------------------------

def normalize_link(href, page_url: str, base: str):
    """Resolve an href against the page it was found on. Returns (kind, url, fragment):
    kind 'internal' (same origin, fragment stripped), 'external' (other http/https origin) or 'skip'
    (empty, mailto:, tel:, javascript:, data:, blob:, a bare '#')."""
    if not href or not href.strip():
        return "skip", "", ""
    href = href.strip()
    if re.match(r"^(mailto|tel|javascript|data|blob|sms|kakaotalk|intent):", href, re.I):
        return "skip", "", ""
    url, fragment = urldefrag(urljoin(page_url, href))
    parts = urlparse(url)
    if parts.scheme not in ("http", "https"):
        return "skip", "", ""
    if href == "#" or (href.startswith("#") and not fragment):
        return "skip", "", ""
    if parts.netloc == urlparse(base).netloc:
        if parts.path in ("", "/"):
            url = urljoin(url, "/") if not parts.query else url
        return "internal", url, fragment
    return "external", url, fragment


def page_key(url: str) -> str:
    """The page a URL denotes without its query (a crawl renders each path once)."""
    parts = urlparse(url)
    return parts.path or "/"


# Fragments a page's script routes on (location.hash) instead of an element id.
APP_FRAGMENTS = {"/ggongbab.html": {"menu", "free"}}


def anchor_target_exists(fragment: str, ids, path: str = "") -> bool:
    """#top and an empty fragment always resolve (HTML spec), as do the hash routes a page's script
    handles itself (APP_FRAGMENTS); anything else needs a matching id/name."""
    if not fragment or fragment.lower() == "top" or fragment in APP_FRAGMENTS.get(path, ()):
        return True
    from urllib.parse import unquote
    ids = set(ids)
    return fragment in ids or unquote(fragment) in ids


def classify_axe(violations: list[dict]) -> dict:
    """Split axe violations by impact: counts for every impact, the failing ones (critical, serious)
    and the warnings (moderate, minor, or an unknown impact)."""
    counts = {name: 0 for name in IMPACT_ORDER}
    fails, warns = [], []
    for v in violations:
        impact = v.get("impact") or "minor"
        counts[impact if impact in counts else "minor"] += 1
        (fails if impact in FAIL_IMPACTS else warns).append(v)
    return {"counts": counts, "fail": fails, "warn": warns}


def group_violations(rows: list[dict]) -> list[dict]:
    """Collapse per-scope axe violations (page, rule, impact) into one row listing the scopes and the
    distinct element selectors, so the same defect found at 390/1280 and in ko/en reads once."""
    groups: dict[tuple, dict] = {}
    for row in rows:
        key = (row["page"], row["rule"], row["impact"])
        g = groups.setdefault(key, {"page": row["page"], "rule": row["rule"], "impact": row["impact"],
                                    "help": row.get("help", ""), "helpUrl": row.get("helpUrl", ""),
                                    "scopes": [], "elements": [], "evidence": ""})
        if row["scope"] not in g["scopes"]:
            g["scopes"].append(row["scope"])
        for el in row.get("elements", []):
            if el not in g["elements"]:
                g["elements"].append(el)
        g["evidence"] = g["evidence"] or row.get("evidence", "")
    order = {name: i for i, name in enumerate(IMPACT_ORDER)}
    return sorted(groups.values(), key=lambda g: (order.get(g["impact"], 9), g["page"], g["rule"]))


def oversize_ratio(natural_w: float, natural_h: float, shown_w: float, shown_h: float, dpr: float = 1.0) -> float:
    """How many times larger (linear, the bigger of the two axes) an image is than the device pixels it
    is drawn into. 0 when it is not displayed."""
    if shown_w <= 0 or shown_h <= 0 or natural_w <= 0 or natural_h <= 0:
        return 0.0
    return max(natural_w / (shown_w * dpr), natural_h / (shown_h * dpr))


def perf_warnings(page: str, scope: str, m: dict, phone: bool) -> list[str]:
    out = []
    if m.get("lcp_ms") is not None and m["lcp_ms"] > LCP_WARN_MS:
        out.append(f"{page} [{scope}] LCP {m['lcp_ms'] / 1000:.2f} s > 2.5 s")
    if m.get("cls", 0) > CLS_WARN:
        out.append(f"{page} [{scope}] CLS {m['cls']:.3f} > 0.1 (before scrolling: {m.get('cls_at_load', 0):.3f})")
    if phone and m.get("bytes", 0) > PHONE_WEIGHT_WARN:
        out.append(f"{page} [{scope}] page weight {m['bytes'] / 1048576:.1f} MB > 3 MB on the phone")
    return out


def human(n: float) -> str:
    return f"{n / 1048576:.2f} MB" if n >= 1048576 else f"{n / 1024:.0f} KB" if n >= 1024 else f"{int(n)} B"


# ---- axe -----------------------------------------------------------------------------------------------

def load_axe(cache_dir: Path) -> str:
    """The pinned axe-core, downloaded once into the cache directory."""
    path = cache_dir / f"axe-core-{AXE_VERSION}.min.js"
    if not path.exists() or path.stat().st_size < 100000:
        cache_dir.mkdir(parents=True, exist_ok=True)
        req = Request(AXE_URL, headers={"User-Agent": BROWSER_UA})
        with urlopen(req, timeout=60) as resp:
            data = resp.read()
        path.write_bytes(data)
    src = path.read_text(encoding="utf-8")
    if f"axe v{AXE_VERSION}" not in src[:400]:
        raise RuntimeError(f"cached axe-core is not v{AXE_VERSION}: {path}")
    return src


AXE_RUN = """async () => {
  const r = await axe.run(document, { resultTypes: ['violations'] });
  return r.violations.map(v => ({
    id: v.id, impact: v.impact, help: v.help, helpUrl: v.helpUrl,
    nodes: v.nodes.slice(0, 6).map(n => ({ target: n.target.join(' '), html: n.html.slice(0, 220),
                                            summary: (n.failureSummary || '').split('\\n').slice(0, 3).join(' | ').slice(0, 300) })),
    count: v.nodes.length }));
}"""


# ---- recording -----------------------------------------------------------------------------------------

class Quality:
    def __init__(self, base: str, out: Path):
        self.base = base.rstrip("/")
        self.out = out
        self.is_lab = urlparse(base).hostname == live.LAB_HOST
        self.a11y_rows: list[dict] = []        # per-scope axe violations
        self.a11y_runs: list[dict] = []        # (page, scope, counts) for every axe run
        self.keyboard: list[dict] = []         # keyboard-pass findings and passes
        self.links: dict = {"pages": [], "internal": [], "broken": [], "anchors": [], "external": []}
        self.perf: list[dict] = []
        self.warnings: list[str] = []
        self.errors: list[str] = []            # problems of the checks themselves (count as failures)
        self.posts: list[dict] = []
        self.meta: dict = {}

    def error(self, text: str):
        self.errors.append(text)
        print("  ! check error:", text, flush=True)


# ---- browser plumbing ----------------------------------------------------------------------------------

def make_context(browser, q: Quality, lang: str, vp: str):
    w, h, dpr = VIEWPORTS[vp]
    context = browser.new_context(
        viewport={"width": w, "height": h}, device_scale_factor=dpr, locale="ko-KR" if lang == "ko" else "en-US",
        timezone_id="Asia/Seoul", service_workers="block", accept_downloads=False, has_touch=w < 600,
        is_mobile=False, user_agent=BROWSER_UA)
    context.add_init_script(
        "try{localStorage.setItem('babdoduk-lang','%s');sessionStorage.setItem('babdoduk-welcome-seen','1');}catch(e){}" % lang)

    def guard(route):
        req = route.request
        parts = urlparse(req.url)
        if live.FORBIDDEN_HOST.search(parts.hostname or ""):
            q.error(f"request to a forbidden host aborted: {req.url}")
            route.abort()
            return
        if req.method not in SAFE_METHODS:
            q.posts.append({"method": req.method, "host": parts.hostname or "", "path": parts.path})
            route.abort()
            return
        route.continue_()

    context.route("**/*", guard)
    return context


def goto(q: Quality, page, path: str, settle_ms: int = 700):
    url = urljoin(q.base + "/", path)
    for attempt in (1, 2):
        try:
            resp = page.goto(url, wait_until="load", timeout=45000)
            break
        except Exception:
            if attempt == 2:
                raise
            page.wait_for_timeout(1500)
    settle(page, settle_ms)
    return resp


def settle(page, ms: int = 600):
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass
    page.wait_for_timeout(ms)


def scroll_through(page):
    page.evaluate("""async () => {
      const h = () => document.documentElement.scrollHeight;
      for (let y = 0; y < h(); y += Math.max(300, innerHeight * 0.8)) { scrollTo(0, y); await new Promise(r => setTimeout(r, 120)); }
      scrollTo(0, 0);
    }""")
    settle(page, 300)


def wait_for(page, js: str, timeout: int = 15000) -> bool:
    try:
        page.wait_for_function(js, timeout=timeout)
        return True
    except Exception:
        return False


# ---- accessibility -------------------------------------------------------------------------------------

def run_axe(q: Quality, page, axe_src: str, name: str, scope: str):
    page.evaluate(axe_src)
    violations = page.evaluate(AXE_RUN)
    result = classify_axe(violations)
    q.a11y_runs.append({"page": name, "scope": scope, **result["counts"]})
    for v in violations:
        q.a11y_rows.append({
            "page": name, "scope": scope, "rule": v["id"], "impact": v.get("impact") or "minor", "help": v["help"],
            "helpUrl": v["helpUrl"], "count": v["count"],
            "elements": [n["target"] for n in v["nodes"]],
            "evidence": (v["nodes"][0]["html"] + "  --  " + v["nodes"][0]["summary"]) if v["nodes"] else ""})
    return result


def a11y_pages(q: Quality, browser, axe_src: str):
    for vp in VIEWPORTS:
        for lang in LANGS:
            scope = f"{vp}/{lang}"
            context = make_context(browser, q, lang, vp)
            page = context.new_page()
            try:
                for name in PAGES:
                    try:
                        goto(q, page, name)
                        scroll_through(page)
                        res = run_axe(q, page, axe_src, name, scope)
                        c = res["counts"]
                        print(f"  a11y {name:14} {scope:11} critical={c['critical']} serious={c['serious']} "
                              f"moderate={c['moderate']} minor={c['minor']}", flush=True)
                    except Exception as exc:
                        q.error(f"a11y {name} [{scope}]: {str(exc).splitlines()[0][:200]}")
            finally:
                context.close()


# keyboard helpers ---------------------------------------------------------------------------------------

FOCUS_JS = """() => {
  const el = document.activeElement;
  if (!el || el === document.body || el === document.documentElement) return null;
  const cs = getComputedStyle(el);
  const r = el.getBoundingClientRect();
  const outline = cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0;
  const shadow = cs.boxShadow && cs.boxShadow !== 'none';
  const label = (el.getAttribute('aria-label') || el.innerText || el.value || '').trim().replace(/\\s+/g, ' ').slice(0, 40);
  const cls = (el.className && el.className.baseVal === undefined ? String(el.className) : '').trim().split(/\\s+/).slice(0, 2).join('.');
  return { tag: el.tagName.toLowerCase(), id: el.id || '', cls, label,
           fv: el.matches(':focus-visible'), indicator: !!(outline || shadow),
           outline: outline ? cs.outlineWidth + ' ' + cs.outlineStyle + ' ' + cs.outlineColor : '',
           inView: r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth,
           pressed: el.getAttribute('aria-pressed') };
}"""


def reset_focus(page):
    page.evaluate("() => { if (document.activeElement) document.activeElement.blur(); scrollTo(0, 0); }")


def focus_matches(page, selector: str) -> bool:
    return bool(page.evaluate("(s) => !!document.activeElement && document.activeElement.matches(s)", selector))


def tab_to(page, selector: str, max_tabs: int = 120, from_start: bool = True):
    """Press Tab until the focused element matches selector. Returns the focus info or None."""
    if from_start:
        reset_focus(page)
    for _ in range(max_tabs):
        page.keyboard.press("Tab")
        if focus_matches(page, selector):
            info = page.evaluate(FOCUS_JS)
            for _ in range(10):              # the browser's scroll-into-view may be smooth: give it up to ~2.5 s
                if not info or info["inView"]:
                    break
                page.wait_for_timeout(250)
                info = page.evaluate(FOCUS_JS)
            return info
    return None


class Keyboard:
    """Records keyboard-only findings: ok rows are passes, bad rows are real site issues."""

    def __init__(self, q: Quality, page, scope: str, page_name: str):
        self.q, self.page, self.scope, self.page_name = q, page, scope, page_name

    def add(self, check: str, ok: bool, detail: str = "", suggestion: str = ""):
        self.q.keyboard.append({"page": self.page_name, "scope": self.scope, "check": check, "ok": ok,
                                "detail": detail, "suggestion": suggestion})
        print(f"  kbd  {self.page_name:14} {self.scope:11} {'ok  ' if ok else 'FAIL'} {check} {detail if not ok else ''}", flush=True)

    def reach(self, label: str, selector: str, from_start: bool = True, max_tabs: int = 120):
        info = tab_to(self.page, selector, max_tabs, from_start)
        if not info:
            self.add(f"reach {label} with Tab", False, f"{selector} never received focus in {max_tabs} Tab presses",
                     "Make the control a focusable element in a sensible tab order (button/link, no tabindex=-1, not display:none).")
            return None
        self.add(f"reach {label} with Tab", True)
        shown = info["indicator"] and info["fv"] and info["inView"]
        self.add(f"{label}: visible focus", shown,
                 f"focus-visible={info['fv']} indicator={info['indicator']} inView={info['inView']} el={info['tag']}#{info['id']}.{info['cls']}",
                 "Give :focus-visible a clear outline or ring (see DESIGN_SYSTEM.md focus rules) and keep it in view.")
        return info


def keyboard_nav(q: Quality, page, scope: str):
    kb = Keyboard(q, page, scope, "index.html")
    goto(q, page, "index.html")
    kb.reach("nav wordmark", "a#navHome")
    for href in ("ggongbab.html", "mukbang.html", "event.html"):
        kb.reach(f"nav link {href}", f'a.site-nav-direct[href="{href}"]', from_start=True)
    lang0 = page.evaluate("document.documentElement.lang")
    info = kb.reach("language toggle", "#langToggle")
    if info:
        page.keyboard.press("Enter")
        page.wait_for_timeout(500)
        changed = page.evaluate("document.documentElement.lang") != lang0
        kb.add("language toggle activates with Enter", changed, f"lang stayed {lang0}")
        if changed:
            page.keyboard.press("Enter")   # put it back
            page.wait_for_timeout(300)
    # Activate a nav link with Enter and arrive.
    goto(q, page, "index.html")
    if kb.reach("nav link ggongbab (activate)", 'a.site-nav-direct[href="ggongbab.html"]'):
        page.keyboard.press("Enter")
        arrived = wait_for(page, "location.pathname.endsWith('ggongbab.html')", 8000)
        kb.add("Enter on a nav link navigates", arrived, f"url={page.url}")


def keyboard_filters(q: Quality, page, scope: str):
    kb = Keyboard(q, page, scope, "ggongbab.html")
    goto(q, page, "ggongbab.html", 1200)
    chips = page.locator('.gg-chip[data-group="food"]')
    values = [chips.nth(i).get_attribute("data-value") for i in range(chips.count())]
    if len(values) < 2:
        kb.add("food filter chips present", False, f"{len(values)} chips")
        return
    target = next((v for v in values if v not in ("all", "giveaway")), values[-1])
    sel = f'.gg-chip[data-group="food"][data-value="{target}"]'
    info = kb.reach(f"filter chip '{target}'", sel, max_tabs=150)
    if info:
        before = info["pressed"]
        page.keyboard.press("Space")
        page.wait_for_timeout(300)
        after = page.locator(sel).first.get_attribute("aria-pressed")
        kb.add("Space toggles a filter chip", after != before, f"aria-pressed {before} -> {after}")
    # Enter on the 'all' chip must make it the pressed one (the chips are a single-choice group).
    all_sel = '.gg-chip[data-group="food"][data-value="all"]'
    if info and kb.reach("filter chip 'all'", all_sel, max_tabs=150):
        page.keyboard.press("Enter")
        page.wait_for_timeout(300)
        pressed = page.locator(all_sel).first.get_attribute("aria-pressed")
        kb.add("Enter activates a filter chip", pressed == "true", f"'all' aria-pressed={pressed} after Enter")
    return


def skip_splash(page, kb: Keyboard):
    """The start gacha is a popover; try the keyboard first, fall back to a tap and say so."""
    is_open = "() => { const s = document.getElementById('wcSplash'); return !!s && s.matches(':popover-open'); }"
    if not page.evaluate(is_open):
        return
    page.keyboard.press("Enter")
    page.wait_for_timeout(500)
    if page.evaluate(is_open):
        page.keyboard.press("Space")
        page.wait_for_timeout(500)
    if page.evaluate(is_open):
        kb.add("start gacha (splash) can be skipped with the keyboard", False,
               "Enter/Space do nothing while #wcSplash is open; only a pointer tap skips it",
               "Let Enter/Space/Escape close the splash, or auto-advance it, so keyboard users are not stuck waiting.")
        vp = page.viewport_size
        page.mouse.click(vp["width"] / 2, vp["height"] / 2)
        page.wait_for_timeout(300)
    else:
        kb.add("start gacha (splash) can be skipped with the keyboard", True)


def worldcup_flow(q: Quality, browser, axe_src: str, lang: str, vp: str, phase: str):
    """Entry a11y happens in a11y_pages; here: keyboard flow of the world cup and, when the game is
    playable, axe on the match and result screens."""
    scope = f"{vp}/{lang}"
    context = make_context(browser, q, lang, vp)
    page = context.new_page()
    kb = Keyboard(q, page, scope, "worldcup.html")
    try:
        goto(q, page, "worldcup.html", 1000)
        wait_for(page, "() => document.getElementById('wcIntro') && !document.getElementById('wcIntro').hidden")
        # sound toggle
        sound = kb.reach("sound toggle", "#wcSound", max_tabs=150)
        if sound:
            before = page.locator("#wcSound").get_attribute("aria-pressed")
            page.keyboard.press("Space")
            page.wait_for_timeout(400)
            after = page.locator("#wcSound").get_attribute("aria-pressed")
            kb.add("Space toggles the sound button", after != before, f"aria-pressed {before} -> {after}")
            if after != before:
                page.keyboard.press("Enter")   # off again
                page.wait_for_timeout(300)
        if phase == "soon":
            tile = tab_to(page, "#wcCats .wc-tile", 60)
            kb.add("locked category tiles stay out of the tab order (inert by design)", tile is None,
                   "a locked mystery tile received focus")
            q.warnings.append(f"worldcup [{scope}]: game locked ('soon' phase), start/pick/result keyboard flow not exercised")
            return
        tile = kb.reach("category tile", "#wcCats .wc-tile", max_tabs=150)
        if tile:
            sel_before = page.evaluate("() => document.querySelector('#wcCats .wc-tile[aria-pressed=\"true\"], #wcCats .wc-tile.is-selected, #wcCats .wc-tile.on') ? 1 : 0")
            page.keyboard.press("Tab")                     # move to another tile and pick it with Enter
            page.keyboard.press("Enter")
            page.wait_for_timeout(300)
            kb.add("Enter picks a category tile", True)
        start = kb.reach("start button", "#wcStart", max_tabs=150)
        if not start:
            return
        page.keyboard.press("Enter")
        opened = wait_for(page, "() => { const s = document.getElementById('wcSplash'); return (s && s.matches(':popover-open')) || !document.getElementById('wcMatch').hidden; }", 10000)
        kb.add("Enter on start begins the game", opened)
        skip_splash(page, kb)
        wait_for(page, "() => !document.getElementById('wcMatch').hidden", 10000)
        # keyboard picks
        deadline = time.time() + 150
        first_card = True
        kbd_picks = 0
        while time.time() < deadline and not page.locator("#wcResult").is_visible():
            if page.evaluate("() => { const s = document.getElementById('wcSplash'); return !!s && s.matches(':popover-open'); }"):
                skip_splash(page, kb)
                continue
            if page.locator("#wcMatch").is_visible():
                card = tab_to(page, '#wcMatch .wc-card[data-side="0"]', 40) if first_card else tab_to(page, '#wcMatch .wc-card', 40)
                if card:
                    if first_card:
                        kb.add("match card visible focus", card["indicator"] and card["fv"],
                               f"focus-visible={card['fv']} indicator={card['indicator']}",
                               "Give .wc-card:focus-visible a visible ring.")
                        first_card = False
                    page.keyboard.press("Enter")
                    kbd_picks += 1
                    page.wait_for_timeout(450)
                else:
                    kb.add("a match card can be picked with the keyboard", False, "no .wc-card received focus in 40 Tab presses",
                           "Make the match cards buttons (or tabindex=0 with Enter/Space handlers).")
                    break
            else:
                page.wait_for_timeout(200)
        # fall back to the pointer so the result screen can still be checked
        if not page.locator("#wcResult").is_visible():
            kb.add("game reaches the result with keyboard picks alone", False, f"{kbd_picks} keyboard picks, then pointer fallback")
            live_deadline = time.time() + 120
            while time.time() < live_deadline and not page.locator("#wcResult").is_visible():
                if page.locator("#wcMatch").is_visible():
                    try:
                        page.locator('#wcMatch .wc-card[data-side="0"]').click(timeout=2000)
                    except Exception:
                        pass
                page.wait_for_timeout(350)
        else:
            kb.add("game reaches the result with keyboard picks alone", True, f"{kbd_picks} keyboard picks")
        if page.locator("#wcResult").is_visible():
            page.wait_for_timeout(1500)
            for label, sel in (("save-image button", "#wcSaveImage"), ("share button", "#wcShare"),
                               ("kakao button", "#wcKakao"), ("play-again button", "#wcAgain")):
                if page.locator(sel).count() and page.locator(sel).first.is_visible():
                    kb.reach(label + " (result)", sel, max_tabs=200)
                else:
                    q.warnings.append(f"worldcup [{scope}]: {sel} not visible on the result screen (skipped)")
            try:
                res = run_axe(q, page, axe_src, "worldcup.html#result", scope)
                c = res["counts"]
                print(f"  a11y worldcup#result {scope:11} critical={c['critical']} serious={c['serious']} "
                      f"moderate={c['moderate']} minor={c['minor']}", flush=True)
            except Exception as exc:
                q.error(f"a11y worldcup result [{scope}]: {str(exc).splitlines()[0][:200]}")
        else:
            q.error(f"worldcup [{scope}]: result screen not reached; result axe skipped")
    except Exception as exc:
        q.error(f"worldcup keyboard flow [{scope}]: {str(exc).splitlines()[0][:200]}")
    finally:
        context.close()


def phase_a11y(q: Quality, browser, axe_src: str, cache_phase: str):
    print("== accessibility (axe-core %s)" % AXE_VERSION, flush=True)
    a11y_pages(q, browser, axe_src)
    print("== keyboard-only pass", flush=True)
    for vp in VIEWPORTS:
        for lang in LANGS:
            scope = f"{vp}/{lang}"
            context = make_context(browser, q, lang, vp)
            page = context.new_page()
            try:
                keyboard_nav(q, page, scope)
                keyboard_filters(q, page, scope)
            except Exception as exc:
                q.error(f"keyboard pass [{scope}]: {str(exc).splitlines()[0][:200]}")
            finally:
                context.close()
            worldcup_flow(q, browser, axe_src, lang, vp, cache_phase)


# ---- performance ---------------------------------------------------------------------------------------

PERF_INIT = """(() => {
  const d = n => { if (!n || !n.tagName) return ''; return n.tagName.toLowerCase() + (n.id ? '#' + n.id : '') +
      (n.className && typeof n.className === 'string' ? '.' + n.className.trim().split(/\\s+/).slice(0, 2).join('.') : ''); };
  window.__q = { lcp: null, cls: 0, shifts: [] };
  try { new PerformanceObserver(l => { for (const e of l.getEntries()) window.__q.lcp = { t: e.startTime, url: e.url || '', size: e.size, el: d(e.element) }; })
    .observe({ type: 'largest-contentful-paint', buffered: true }); } catch (e) {}
  try { new PerformanceObserver(l => { for (const e of l.getEntries()) if (!e.hadRecentInput) {
      window.__q.cls += e.value; window.__q.shifts.push({ v: +e.value.toFixed(4), t: Math.round(e.startTime), s: (e.sources || []).map(x => d(x.node)).slice(0, 3) }); } })
    .observe({ type: 'layout-shift', buffered: true }); } catch (e) {}
})();"""

IMG_JS = """async () => {
  const dpr = window.devicePixelRatio || 1;
  const out = [];
  const seen = new Set();
  const d = n => n.tagName.toLowerCase() + (n.id ? '#' + n.id : '') + (n.className && typeof n.className === 'string' ? '.' + n.className.trim().split(/\\s+/).slice(0, 2).join('.') : '');
  for (const i of document.images) {
    const src = i.currentSrc || i.src; if (!src || src.startsWith('data:')) continue;
    const r = i.getBoundingClientRect();
    out.push({ url: src, nw: i.naturalWidth, nh: i.naturalHeight, w: r.width, h: r.height, el: d(i), kind: 'img', dpr });
  }
  const bgs = [];
  for (const el of document.querySelectorAll('*')) {
    const bi = getComputedStyle(el).backgroundImage;
    if (!bi || bi === 'none') continue;
    const m = [...bi.matchAll(/url\\(["']?([^"')]+)["']?\\)/g)].map(x => x[1]).filter(u => !u.startsWith('data:'));
    const r = el.getBoundingClientRect();
    for (const u of m) { const abs = new URL(u, location.href).href; bgs.push({ url: abs, w: r.width, h: r.height, el: d(el) }); }
    if (bgs.length > 120) break;
  }
  const dims = {};
  await Promise.all([...new Set(bgs.map(b => b.url))].slice(0, 60).map(u => new Promise(res => {
    const im = new Image(); const t = setTimeout(res, 4000);
    im.onload = () => { dims[u] = [im.naturalWidth, im.naturalHeight]; clearTimeout(t); res(); };
    im.onerror = () => { clearTimeout(t); res(); };
    im.src = u; })));
  for (const b of bgs) { const dm = dims[b.url]; if (dm) out.push({ url: b.url, nw: dm[0], nh: dm[1], w: b.w, h: b.h, el: b.el, kind: 'background', dpr }); }
  return out;
}"""


def measure_page(q: Quality, browser, name: str, lang: str, vp: str) -> dict:
    scope = f"{vp}/{lang}"
    context = make_context(browser, q, lang, vp)
    context.add_init_script(PERF_INIT)
    page = context.new_page()
    cdp = context.new_cdp_session(page)
    cdp.send("Network.enable")
    cdp.send("Network.setCacheDisabled", {"cacheDisabled": True})
    cdp.send("Performance.enable")
    reqs: dict[str, dict] = {}
    cdp.on("Network.requestWillBeSent", lambda e: reqs.setdefault(e["requestId"], {"url": e["request"]["url"], "type": e.get("type", ""), "bytes": 0, "done": False}))
    cdp.on("Network.responseReceived", lambda e: reqs.get(e["requestId"], {}).update(status=e["response"]["status"], mime=e["response"].get("mimeType", "")))

    def finished(e):
        r = reqs.get(e["requestId"])
        if r:
            r["bytes"], r["done"] = e["encodedDataLength"], True
    cdp.on("Network.loadingFinished", finished)
    try:
        goto(q, page, name, 1500)
        initial = page.evaluate("() => ({ lcp: window.__q && window.__q.lcp, cls: window.__q ? window.__q.cls : 0 })")
        nav = page.evaluate("""() => { const n = performance.getEntriesByType('navigation')[0];
            return n ? { load: Math.round(n.loadEventEnd), dcl: Math.round(n.domContentLoadedEventEnd), ttfb: Math.round(n.responseStart) } : null; }""")
        scroll_through(page)
        final = page.evaluate("() => window.__q")
        images = page.evaluate(IMG_JS)
        metrics = {m["name"]: m["value"] for m in cdp.send("Performance.getMetrics")["metrics"]}
    finally:
        context.close()

    items = [r for r in reqs.values() if r["done"] and not r["url"].startswith(("data:", "blob:"))]
    by_url: dict[str, int] = {}
    for r in items:
        by_url[r["url"]] = max(by_url.get(r["url"], 0), r["bytes"])
    total = sum(r["bytes"] for r in items)
    w, _h, dpr = VIEWPORTS[vp]
    oversized, big_images = [], []
    for im in images:
        size = by_url.get(im["url"], 0)
        ratio = oversize_ratio(im["nw"], im["nh"], im["w"], im["h"], dpr)
        row = {"url": im["url"], "natural": f"{im['nw']}x{im['nh']}", "shown": f"{round(im['w'])}x{round(im['h'])}",
               "bytes": size, "ratio": round(ratio, 1), "el": im["el"], "kind": im["kind"]}
        big_images.append(row)
        if ratio >= OVERSIZE_RATIO and size >= OVERSIZE_MIN_BYTES and im["w"] > 0:
            oversized.append(row)
    big_images.sort(key=lambda r: -r["bytes"])
    lcp = initial["lcp"]
    m = {"page": name, "scope": scope, "lang": lang, "viewport": vp, "bytes": total, "requests": len(items),
         "lcp_ms": round(lcp["t"]) if lcp else None, "lcp_el": (lcp or {}).get("el", ""), "lcp_url": (lcp or {}).get("url", ""),
         "cls": round(final["cls"], 4), "cls_at_load": round(initial["cls"], 4), "shifts": final["shifts"][:8],
         "load_ms": nav["load"] if nav else None, "dcl_ms": nav["dcl"] if nav else None, "ttfb_ms": nav["ttfb"] if nav else None,
         "script_ms": round(metrics.get("ScriptDuration", 0) * 1000), "dom_nodes": int(metrics.get("Nodes", 0)),
         "largest_images": big_images[:5], "oversized": sorted(oversized, key=lambda r: -r["bytes"])[:12],
         "assets": sorted(({"url": u, "bytes": b} for u, b in by_url.items()), key=lambda r: -r["bytes"])[:12],
         "statuses_bad": [{"url": r["url"], "status": r.get("status")} for r in items if r.get("status", 200) >= 400]}
    return m


def phase_perf(q: Quality, browser):
    print("== performance", flush=True)
    for vp in VIEWPORTS:
        for lang in LANGS:
            for name in PAGES:
                try:
                    m = measure_page(q, browser, name, lang, vp)
                    q.perf.append(m)
                    q.warnings.extend(perf_warnings(name, m["scope"], m, vp == "phone"))
                    print(f"  perf {name:14} {m['scope']:11} {human(m['bytes']):>9} req={m['requests']:3} "
                          f"LCP={m['lcp_ms']} CLS={m['cls']} load={m['load_ms']}ms", flush=True)
                except Exception as exc:
                    q.error(f"perf {name} [{vp}/{lang}]: {str(exc).splitlines()[0][:200]}")


# ---- links ---------------------------------------------------------------------------------------------

LINK_JS = """() => {
  const abs = (u) => { try { return new URL(u, location.href).href; } catch (e) { return ''; } };
  const out = { anchors: [], assets: [], ids: [] };
  for (const a of document.querySelectorAll('a[href], area[href]')) {
    out.anchors.push({ href: a.getAttribute('href'), text: (a.getAttribute('aria-label') || a.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 50) });
  }
  for (const el of document.querySelectorAll('img[src], script[src], link[href]:not([rel~=preconnect]):not([rel~=dns-prefetch]), source[src], video[src], audio[src], iframe[src], video[poster]')) {
    const u = el.getAttribute('src') || el.getAttribute('href') || el.getAttribute('poster');
    if (u) out.assets.push({ url: abs(u), tag: el.tagName.toLowerCase() });
    const ss = el.getAttribute('srcset');
    if (ss) for (const part of ss.split(',')) { const s = part.trim().split(/\\s+/)[0]; if (s) out.assets.push({ url: abs(s), tag: 'srcset' }); }
  }
  for (const el of document.querySelectorAll('[id], a[name]')) out.ids.push(el.id || el.getAttribute('name'));
  return out;
}"""


def phase_links(q: Quality, browser):
    print("== links", flush=True)
    context = make_context(browser, q, "ko", "desktop")
    page = context.new_page()
    seen_net: dict[str, int] = {}
    page.on("response", lambda r: seen_net.__setitem__(r.url, r.status))
    queue = ["/index.html"]
    visited: dict[str, dict] = {}       # path -> {ids, status, from}
    internal: dict[str, dict] = {}      # url -> {status, found_on:set, kind}
    external: dict[str, set] = {}
    anchor_refs: list[tuple] = []       # (found_on_page, target_url, fragment, text)
    found_from = {"/index.html": "start"}
    try:
        seeded = False
        while len(visited) < CRAWL_PAGE_CAP:
            if not queue:
                orphans = [p for p in PAGES if "/" + p not in visited]
                if seeded or not orphans:
                    break
                seeded = True
                for p in orphans:
                    q.warnings.append(f"/{p} is not reachable from any link on the crawled pages (nav/footer); crawled by name")
                    queue.append("/" + p)
                    found_from["/" + p] = "(seed, not linked)"
            path = queue.pop(0)
            key = page_key(path)
            if key in visited:
                continue
            url = urljoin(q.base + "/", path.lstrip("/"))
            try:
                resp = page.goto(url, wait_until="load", timeout=45000)
                settle(page, 700)
                scroll_through(page)
                data = page.evaluate(LINK_JS)
            except Exception as exc:
                visited[key] = {"ids": set(), "status": f"error: {str(exc).splitlines()[0][:120]}", "from": found_from.get(path, "")}
                continue
            visited[key] = {"ids": set(data["ids"]), "status": resp.status if resp else None, "from": found_from.get(path, "")}
            final_url = page.url
            for a in data["anchors"]:
                kind, target, frag = normalize_link(a["href"], final_url, q.base)
                if kind == "skip" and not (a["href"] or "").startswith("#"):
                    continue
                if kind == "skip":
                    if (a["href"] or "").strip() in ("#", ""):
                        continue
                    kind, target, frag = "internal", final_url.split("#")[0], a["href"].strip()[1:]
                if kind == "internal":
                    rec = internal.setdefault(target, {"found_on": set(), "kind": "link"})
                    rec["found_on"].add(key)
                    if frag:
                        anchor_refs.append((key, target, frag, a["text"]))
                    if page_key(target) not in visited and page_key(target) not in [page_key(x) for x in queue]:
                        if re.search(r"\.(html?)$", urlparse(target).path) or urlparse(target).path in ("", "/"):
                            queue.append(target)
                            found_from[target] = key
                elif kind == "external":
                    external.setdefault(target, set()).add(key)
            for asset in data["assets"]:
                kind, target, _ = normalize_link(asset["url"], final_url, q.base)
                if kind == "internal":
                    internal.setdefault(target, {"found_on": set(), "kind": asset["tag"]})["found_on"].add(key)
                elif kind == "external":
                    external.setdefault(target, set()).add(key)
        # network responses seen while loading (JSON data fetched by scripts, fonts, ...)
        for url, status in seen_net.items():
            kind, target, _ = normalize_link(url, q.base + "/", q.base)
            if kind == "internal":
                internal.setdefault(target, {"found_on": set(), "kind": "network"})["found_on"].add("(runtime request)")
        # status of every internal URL (GET only)
        for url, rec in sorted(internal.items()):
            key = page_key(url)
            if key in visited and url.split("?")[0].endswith(".html") and isinstance(visited[key]["status"], int):
                rec["status"] = visited[key]["status"]
                continue
            try:
                resp = context.request.get(url, timeout=30000)
                rec["status"] = resp.status
            except Exception as exc:
                rec["status"] = f"error: {str(exc).splitlines()[0][:100]}"
        for url, rec in internal.items():
            rec["found_on"] = sorted(rec["found_on"])
            if rec.get("status") != 200:
                q.links["broken"].append({"url": url, "status": rec.get("status"), "found_on": rec["found_on"], "kind": rec["kind"]})
        for key, info in visited.items():
            if info["status"] != 200:
                q.links["broken"].append({"url": key, "status": info["status"], "found_on": [info["from"]], "kind": "page"})
        # anchors
        done = set()
        for found_on, target, frag, text in anchor_refs:
            tkey = page_key(target)
            if (found_on, target, frag) in done:
                continue
            done.add((found_on, target, frag))
            if tkey not in visited:
                try:
                    page.goto(target, wait_until="load", timeout=45000)
                    settle(page, 500)
                    visited[tkey] = {"ids": set(page.evaluate(LINK_JS)["ids"]), "status": 200, "from": "anchor"}
                except Exception:
                    continue
            if not anchor_target_exists(frag, visited[tkey]["ids"], tkey):
                q.links["anchors"].append({"on": found_on, "href": f"{tkey}#{frag}", "text": text})
        # external (warn only)
        for url, pages in sorted(external.items()):
            host = urlparse(url).hostname or ""
            if live.FORBIDDEN_HOST.search(host):
                q.links["external"].append({"url": url, "status": "skipped (forbidden host)", "found_on": sorted(pages)})
                continue
            status: object = None
            for method in ("head", "get"):
                try:
                    resp = getattr(context.request, method)(url, timeout=EXTERNAL_TIMEOUT_MS, max_redirects=5)
                    status = resp.status
                    if status < 400:
                        break
                except Exception as exc:
                    status = f"error: {str(exc).splitlines()[0][:80]}"
            ok = isinstance(status, int) and status < 400
            q.links["external"].append({"url": url, "status": status, "ok": ok, "found_on": sorted(pages)})
            if not ok:
                q.warnings.append(f"external link {url} -> {status} (found on {', '.join(sorted(pages))})")
        q.links["pages"] = [{"page": k, "status": v["status"], "from": v["from"]} for k, v in visited.items()]
        q.links["internal"] = [{"url": u, "status": r.get("status"), "kind": r["kind"], "found_on": r["found_on"]}
                               for u, r in sorted(internal.items())]
        for b in q.links["broken"]:
            print(f"  BROKEN {b['status']} {b['url']} (on {', '.join(map(str, b['found_on']))})", flush=True)
        print(f"  {len(visited)} pages crawled, {len(internal)} internal URLs, {len(external)} external", flush=True)
    finally:
        context.close()


# ---- orchestration & report ----------------------------------------------------------------------------

def failures(q: Quality) -> list[str]:
    out = [f"check error: {e}" for e in q.errors]
    for g in group_violations([r for r in q.a11y_rows if r["impact"] in FAIL_IMPACTS]):
        out.append(f"axe {g['impact']} {g['rule']} on {g['page']} ({', '.join(g['scopes'])})")
    for k in q.keyboard:
        if not k["ok"]:
            out.append(f"keyboard: {k['check']} on {k['page']} [{k['scope']}]")
    for b in q.links["broken"]:
        out.append(f"broken link {b['status']} {b['url']}")
    for a in q.links["anchors"]:
        out.append(f"broken anchor {a['href']} on {a['on']}")
    for p in live.post_violations(q.posts, q.is_lab):
        out.append(f"non-GET request attempted: {p['method']} {p['host']}{p['path']}")
    return out


def summary_md(q: Quality, only: set) -> str:
    L = [f"# Babdoduk quality check: {q.base}", "",
         f"{q.meta.get('time_utc', '')} | axe-core {AXE_VERSION} | {'lab' if q.is_lab else 'production'} | "
         f"world cup phase: {q.meta.get('wc_phase')}", ""]
    fails = failures(q)
    L.append(f"**Result: {'FAIL' if fails else 'PASS'}** ({len(fails)} failures, {len(q.warnings)} warnings)")
    L.append("")
    if "a11y" in only:
        L += ["## Accessibility (axe violations per page, summed over 390/1280 and ko/en runs)", "",
              "| page | critical | serious | moderate | minor |", "| --- | --- | --- | --- | --- |"]
        pages = sorted({r["page"] for r in q.a11y_runs}, key=lambda p: (PAGES.index(p) if p in PAGES else 99, p))
        for p in pages:
            runs = [r for r in q.a11y_runs if r["page"] == p]
            L.append(f"| {p} | " + " | ".join(str(sum(r[i] for r in runs)) for i in IMPACT_ORDER) + " |")
        L.append("")
        for g in group_violations(q.a11y_rows):
            tag = "FAIL" if g["impact"] in FAIL_IMPACTS else "warn"
            L.append(f"- [{tag}] {g['impact']} `{g['rule']}` on {g['page']} ({', '.join(g['scopes'])}): {g['help']}. "
                     f"Elements: {'; '.join(g['elements'][:4])}. {g['helpUrl']}")
        L += ["", "### Keyboard-only pass", ""]
        bad = [k for k in q.keyboard if not k["ok"]]
        L.append(f"{len(q.keyboard) - len(bad)} checks passed, {len(bad)} failed.")
        for k in bad:
            L.append(f"- [FAIL] {k['page']} [{k['scope']}] {k['check']}: {k['detail']}")
        L.append("")
    if "links" in only:
        L += ["## Links", "", f"{len(q.links['pages'])} pages crawled, {len(q.links['internal'])} internal URLs checked, "
              f"{len(q.links['broken'])} broken, {len(q.links['anchors'])} broken anchors, "
              f"{sum(1 for e in q.links['external'] if not e.get('ok', True) or 'skipped' in str(e['status']))} external problems "
              f"of {len(q.links['external'])}.", ""]
        for b in q.links["broken"]:
            L.append(f"- [FAIL] {b['status']} {b['url']} (on {', '.join(map(str, b['found_on']))})")
        for a in q.links["anchors"]:
            L.append(f"- [FAIL] anchor {a['href']} missing (link on {a['on']}: '{a['text']}')")
        L.append("")
    if "perf" in only and q.perf:
        L += ["## Performance (cold cache, no throttling; this machine's network)", "",
              "| page | scope | transfer | requests | LCP | CLS | load |", "| --- | --- | --- | --- | --- | --- | --- |"]
        for m in q.perf:
            if m["lang"] == "ko":
                L.append(f"| {m['page']} | {m['scope']} | {human(m['bytes'])} | {m['requests']} | "
                         f"{m['lcp_ms'] if m['lcp_ms'] is not None else '-'} ms | {m['cls']} | {m['load_ms']} ms |")
        assets: dict[str, int] = {}
        for m in q.perf:
            for a in m["assets"]:
                assets[a["url"]] = max(assets.get(a["url"], 0), a["bytes"])
        L += ["", "Top 5 heaviest assets site-wide:", ""]
        for u, b in sorted(assets.items(), key=lambda kv: -kv[1])[:5]:
            L.append(f"- {human(b)}  {u}")
        over: dict[str, dict] = {}
        for m in q.perf:
            for o in m["oversized"]:
                cur = over.setdefault(o["url"], {**o, "pages": set()})
                cur["pages"].add(m["page"])
        L += ["", "Images served much larger than displayed (>= 3x linear):", ""]
        for o in sorted(over.values(), key=lambda r: -r["bytes"])[:12]:
            L.append(f"- {o['url']}  natural {o['natural']}, shown {o['shown']} ({o['ratio']}x), {human(o['bytes'])}, "
                     f"{o['el']} on {', '.join(sorted(o['pages']))}")
        L.append("")
    if q.warnings:
        L += ["## Warnings", ""] + [f"- {w}" for w in q.warnings[:80]] + [""]
    if fails:
        L += ["## Failures", ""] + [f"- {f}" for f in fails[:120]] + [""]
    return "\n".join(L)


def run(base: str, out: Path, only: set) -> Quality:
    from playwright.sync_api import sync_playwright

    q = Quality(base, out)
    now = dt.datetime.now(dt.timezone.utc)
    window = live.read_wc_window(q.base)
    phase = live.wc_phase(now, window, q.is_lab)
    q.meta = {"base": q.base, "time_utc": now.isoformat(timespec="seconds"), "wc_phase": phase, "wc_window": window,
              "axe_version": AXE_VERSION, "lab": q.is_lab, "checks": sorted(only)}
    axe_src = load_axe(ROOT / ".local" / "cache") if "a11y" in only else ""
    if axe_src:
        q.meta["axe_sha256"] = hashlib.sha256(axe_src.encode("utf-8")).hexdigest()
    with sync_playwright() as pw:
        channel = os.environ.get("BABDODUK_BROWSER", "chromium")
        browser = pw.chromium.launch(channel=None if channel == "chromium" else channel, headless=True)
        try:
            if "a11y" in only:
                phase_a11y(q, browser, axe_src, phase)
            if "links" in only:
                phase_links(q, browser)
            if "perf" in only:
                phase_perf(q, browser)
        finally:
            browser.close()
    return q


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--base", required=True, help="https://babdoduk.vercel.app or https://babdoduk-lab.vercel.app")
    parser.add_argument("--out", default=str(ROOT / ".local" / "e2e-quality"))
    parser.add_argument("--only", default="a11y,links,perf", help="comma list of a11y, links, perf")
    args = parser.parse_args(argv)
    only = {s.strip() for s in args.only.split(",") if s.strip()}
    if not only <= {"a11y", "links", "perf"}:
        parser.error("--only takes a11y, links, perf")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    q = run(args.base, out, only)
    fails = failures(q)
    tag = live.host_tag(q.base)
    report = {**q.meta, "ok": not fails, "failures": fails, "warnings": q.warnings, "errors": q.errors,
              "a11y": {"runs": q.a11y_runs, "violations": group_violations(q.a11y_rows), "raw": q.a11y_rows},
              "keyboard": q.keyboard, "links": q.links, "perf": q.perf, "aborted_non_get": q.posts}
    (out / f"quality-{tag}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=list), encoding="utf-8")
    text = summary_md(q, only)
    (out / f"quality-{tag}.md").write_text(text, encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(text)
    step = os.environ.get("GITHUB_STEP_SUMMARY")
    if step:
        with open(step, "a", encoding="utf-8") as fh:
            fh.write(text + "\n\n")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
