#!/usr/bin/env python3
"""Read-only cross-browser / cross-device check of the core Babdoduk journeys (E2E stage 2).

    python scripts/e2e_browsers.py --base https://babdoduk-lab.vercel.app
    python scripts/e2e_browsers.py --base https://babdoduk.vercel.app --engines webkit-iphone13,firefox-desktop

Engines (the Safari stand-in is Playwright WebKit with the iPhone 13 descriptor):
  webkit-iphone13   WebKit,   'iPhone 13'
  firefox-desktop   Firefox,  1280x800
  chromium-pixel7   Chromium, 'Pixel 7'

Journeys per engine: home (calendar, promo), 꽁밥 (filters incl. the gift chip), magazine, one event
card, the 먹방 월드컵 (category tiles, start, skipped gacha, played to the result when its gate is open,
the 1080x1920 story card and its toDataURL, the sound toggle creating exactly one AudioContext without
an exception, the share buttons, the friend-link banner). Per page: no horizontal scroll, tap targets
of at least 44 px on touch devices, fonts rendered, no console or page errors.

STRICTLY read-only, exactly as scripts/e2e_live.py (whose helpers it imports): every non-GET request is
aborted in the browser; any non-GET other than lab's rpc/worldcup_record_game is a failure.
Output: <out>/e2e-browsers-<site>.json, a stdout summary, screenshots of failures. Exit 1 on failure.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e2e_live as live  # noqa: E402
from e2e_live import (Report, finish_signals, goto, make_context, new_signals,  # noqa: E402
                      play_to_result, post_violations, read_wc_window, settle, wait_for, wc_phase)

ROOT = live.ROOT
MIN_TARGET = 44
ENGINES = {
    "webkit-iphone13": {"browser": "webkit", "device": "iPhone 13", "touch": True},
    "firefox-desktop": {"browser": "firefox", "device": None, "size": (1280, 800), "touch": False},
    "chromium-pixel7": {"browser": "chromium", "device": "Pixel 7", "touch": True},
}
# Main controls whose touch size is checked (only those that are visible on the page).
TARGET_SELECTORS = {
    "index.html": ["#langToggle", ".home-wc a"],
    "ggongbab.html": [".gg-chip"],
    "worldcup.html": ["#wcStart", "#wcCats .wc-tile", "#wcSound", "#wcSaveImage", "#wcShare"],
}
AUDIO_HOOK = """(() => {
  window.__audioCount = 0; window.__audioErrors = [];
  for (const name of ['AudioContext', 'webkitAudioContext']) {
    const Orig = window[name]; if (!Orig || Orig.__wrapped) continue;
    const W = function (...a) { window.__audioCount++; try { return new Orig(...a); } catch (e) { window.__audioErrors.push(String(e)); throw e; } };
    W.prototype = Orig.prototype; W.__wrapped = true; window[name] = W;
  }
  addEventListener('error', e => window.__audioErrors.push(String(e.message)));
  addEventListener('unhandledrejection', e => window.__audioErrors.push(String(e.reason)));
})();"""


# ---- pure helpers (tested in tests/test_e2e_browsers.py) -----------------------------------------------

def horizontal_overflow(scroll_width: int, inner_width: int, tolerance: int = 1) -> bool:
    """True when the page scrolls sideways."""
    return scroll_width > inner_width + tolerance


def small_targets(boxes: list[dict], minimum: int = MIN_TARGET) -> list[dict]:
    """Boxes ({'sel','w','h'}) smaller than `minimum` px on either side (half a pixel of slack)."""
    return [b for b in boxes if min(b["w"], b["h"]) + 0.5 < minimum]


def parse_engines(text: str | None) -> list[str]:
    if not text:
        return list(ENGINES)
    names = [t.strip() for t in text.split(",") if t.strip()]
    unknown = [n for n in names if n not in ENGINES]
    if unknown:
        raise ValueError(f"unknown engine(s) {unknown}; choose from {list(ENGINES)}")
    return names


def is_known_noise(text: str) -> bool:
    """Console errors that are the browser's report of something outside the site's control or of our own
    read-only abort: Firefox rejecting Cloudflare's __cf_bm cookie on the Supabase host, Firefox reporting a request cut off by our own
    next navigation, and Firefox describing the aborted world cup record POST as a blocked cross-origin request."""
    return "__cf_bm" in text or "Navigated away from page" in text or ("Cross-Origin Request Blocked" in text and "rpc/worldcup_record_game" in text)


def audio_ok(count: int, errors: list[str]) -> tuple[bool, str]:
    """The sound toggle must create exactly one AudioContext and throw nothing."""
    return count == 1 and not errors, f"contexts={count} errors={errors[:3]}"


# ---- per-page checks -----------------------------------------------------------------------------------

def layout_checks(rep: Report, page, label: str, touch: bool, path: str):
    sw, iw = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
    rep.check(f"{label}: no horizontal scroll", not horizontal_overflow(sw, iw), f"scrollWidth={sw} innerWidth={iw}")
    fonts = page.evaluate("""async () => { try { await document.fonts.ready; } catch (e) {}
      const faces = [...document.fonts]; const body = getComputedStyle(document.body).fontFamily;
      const h = document.querySelector('h1,h2'); const hw = h ? h.getBoundingClientRect().width : 0;
      return { errors: faces.filter(f => f.status === 'error').map(f => f.family), loaded: faces.filter(f => f.status === 'loaded').length,
               body, heading: hw }; }""")
    rep.check(f"{label}: fonts render", not fonts["errors"] and fonts["heading"] > 0,
              f"failed={fonts['errors']} loaded={fonts['loaded']} body={fonts['body'][:60]}")
    if touch:
        boxes = []
        for sel in TARGET_SELECTORS.get(path, []):
            loc = page.locator(sel)
            for i in range(min(loc.count(), 12)):
                el = loc.nth(i)
                if el.is_visible():
                    b = el.bounding_box()
                    if b:
                        boxes.append({"sel": sel, "w": round(b["width"]), "h": round(b["height"])})
        bad = small_targets(boxes)
        rep.check(f"{label}: tap targets >= {MIN_TARGET}px ({len(boxes)} measured)", not bad,
                  "; ".join(f"{b['sel']} {b['w']}x{b['h']}" for b in bad[:6]))


# ---- journeys ------------------------------------------------------------------------------------------

def j_home(rep, page, phase, touch):
    goto(rep, page, "index.html", lambda: settle(page))
    ok = wait_for(page, "() => document.getElementById('homeCal') && document.getElementById('homeCal').dataset.state !== 'loading'")
    cells = page.locator("#homeCalGrid > *").count()
    rep.check("home: calendar renders", ok and cells > 0, f"cells={cells}")
    promo = page.locator(".home-wc").first
    vis = promo.count() > 0 and promo.is_visible()
    rep.check(f"home: world cup promo {'shown' if phase != 'ended' else 'hidden'} ({phase})", vis == (phase in ("soon", "live")), f"visible={vis}")
    layout_checks(rep, page, "home", touch, "index.html")


def j_ggongbab(rep, page, touch):
    goto(rep, page, "ggongbab.html", lambda: settle(page, 1000))
    wait_for(page, "() => document.querySelector('.gg-chip')")
    chips = page.locator('.gg-chip[data-group="food"]')
    values = [chips.nth(i).get_attribute("data-value") for i in range(chips.count())]
    rep.check("ggongbab: food chips incl. giveaway", {"all", "meal", "snack", "refreshment", "giveaway"} <= set(values), str(values))
    gift = page.locator('.gg-chip[data-group="food"][data-value="giveaway"]')
    rep.check("ggongbab: gift chip shows the emoji", gift.count() > 0 and "\U0001F381" in gift.first.inner_text())
    for v in values:
        sel = f'.gg-chip[data-group="food"][data-value="{v}"]'
        try:
            page.locator(sel).first.click(timeout=5000)
            page.wait_for_timeout(250)
            rep.check(f"ggongbab: chip '{v}' toggles", page.locator(sel).first.get_attribute("aria-pressed") == "true"
                      and page.locator('.gg-chip[data-group="food"][aria-pressed="true"]').count() == 1)
        except Exception as exc:
            rep.check(f"ggongbab: chip '{v}' toggles", False, str(exc).splitlines()[0])
    page.locator('.gg-chip[data-group="food"][data-value="all"]').first.click()
    layout_checks(rep, page, "ggongbab", touch, "ggongbab.html")


def j_simple(rep, page, path, touch):
    goto(rep, page, path, lambda: settle(page))
    rep.check(f"{path}: heading visible", page.locator("h1").first.is_visible())
    body = page.locator("main").first.inner_text() if page.locator("main").count() else ""
    rep.check(f"{path}: main content present", len(body.strip()) > 150, f"{len(body.strip())} chars")
    if path == "event.html":
        card = page.locator(".event-item").first
        rep.check("event: an event card renders", card.count() > 0 and card.inner_text().strip() != "")
    layout_checks(rep, page, path, touch, path)


def sound_check(rep, page):
    toggle = page.locator("#wcSound")
    if not page.evaluate("() => !!(window.AudioContext || window.webkitAudioContext)"):
        # Playwright's WebKit build (Linux/Windows) has no Web Audio, unlike Safari: the page must then
        # simply keep the toggle hidden and stay quiet.
        rep.warn("this engine has no Web Audio (Playwright WebKit build); the toggle is only checked to stay hidden")
        rep.check("worldcup: without Web Audio the sound toggle stays hidden", not page.locator("#wcSound").is_visible())
        return
    if not (toggle.count() and wait_for(page, "() => { const d = document.getElementById('wcSoundDock'); return d && !d.hidden; }", 5000)):
        rep.check("worldcup: sound toggle present", False)
        return
    try:
        toggle.click(timeout=5000)
        page.wait_for_timeout(500)
        on = toggle.get_attribute("aria-pressed")
        toggle.click(timeout=5000)
        page.wait_for_timeout(300)
        toggle.click(timeout=5000)
        page.wait_for_timeout(300)
        count, errors = page.evaluate("[window.__audioCount, window.__audioErrors]")
        ok, detail = audio_ok(count, errors)
        rep.check("worldcup: sound toggle creates exactly one AudioContext, no errors", ok and on == "true", f"{detail} pressedAfterFirst={on}")
        toggle.click(timeout=5000)   # leave it off
    except Exception as exc:
        rep.check("worldcup: sound toggle works", False, str(exc).splitlines()[0])


def j_worldcup(rep, page, phase, size, friend_id, cat, touch):
    goto(rep, page, "worldcup.html", lambda: settle(page))
    rep.check("worldcup: start screen shows", wait_for(page, "() => document.getElementById('wcIntro') && !document.getElementById('wcIntro').hidden"))
    tiles = page.locator("#wcCats .wc-tile")
    rep.check("worldcup: category tiles render", tiles.count() >= 2, f"{tiles.count()}")
    layout_checks(rep, page, "worldcup intro", touch, "worldcup.html")
    sound_check(rep, page)
    if phase == "soon":
        rep.check("worldcup: locked before the window (lock pill)", page.locator("#wcLocked").is_visible())
    else:
        try:
            tiles.nth(min(1, tiles.count() - 1)).click(timeout=5000)
            rep.check("worldcup: a category can be picked", True)
        except Exception as exc:
            rep.check("worldcup: a category can be picked", False, str(exc).splitlines()[0])
        page.locator("#wcStart").click()
        wait_for(page, "() => { const s = document.getElementById('wcSplash'); return (s && s.matches(':popover-open')) || !document.getElementById('wcMatch').hidden; }", 8000)
        if page.evaluate("() => { const s = document.getElementById('wcSplash'); return !!s && s.matches(':popover-open'); }"):
            live.tap_splash(page, size)
        rep.check("worldcup: game starts (gacha skipped)", wait_for(page, "() => !document.getElementById('wcMatch').hidden", 10000))
        finished = play_to_result(rep, page, size)
        rep.check("worldcup: picks lead to the result screen", finished)
        if finished:
            made = wait_for(page, "() => { const i = document.getElementById('wcStoryPreview'); return i && !i.hidden && i.complete && i.naturalWidth > 0; }", 25000)
            dims = page.evaluate("() => { const i = document.getElementById('wcStoryPreview'); return i ? [i.naturalWidth, i.naturalHeight] : null; }")
            rep.check("worldcup: story card canvas is 1080x1920", made and dims == [1080, 1920], f"made={made} dims={dims}")
            n = page.evaluate("""() => { try { const i = document.getElementById('wcStoryPreview'); const c = document.createElement('canvas');
              c.width = i.naturalWidth; c.height = i.naturalHeight; c.getContext('2d').drawImage(i, 0, 0);
              const u = c.toDataURL('image/png'); return u.startsWith('data:image/png;base64,') ? u.length : -1; } catch (e) { return -2; } }""")
            rep.check("worldcup: story toDataURL works", n > 10000, f"len={n}")
            rep.check("worldcup: save and share buttons present", page.locator("#wcSaveImage").is_visible() and page.locator("#wcShare").is_visible())
            layout_checks(rep, page, "worldcup result", touch, "worldcup.html")
    goto(rep, page, f"worldcup.html?from={friend_id}&cat={cat}", lambda: settle(page, 800))
    wait_for(page, "() => document.getElementById('wcFriend') && !document.getElementById('wcFriend').hidden", 8000)
    rep.check("worldcup: friend link shows the banner", page.locator("#wcFriend").is_visible() and bool(page.locator("#wcFriendText").inner_text().strip()))
    layout_checks(rep, page, "worldcup friend", touch, "worldcup.html")


# ---- orchestration -------------------------------------------------------------------------------------

def run(base: str, out: Path, engines: list[str]) -> Report:
    from playwright.sync_api import sync_playwright

    rep = Report(base.rstrip("/"), out)
    window = read_wc_window(rep.base)
    now = dt.datetime.now(dt.timezone.utc)
    phase = wc_phase(now, window, rep.is_lab)
    catalog = json.loads((ROOT / "data" / "content" / "worldcup.json").read_text(encoding="utf-8"))
    friend_id = catalog["dishes"][0]
    cat = (catalog.get("categories") or {}).get(friend_id) or "random"
    rep.meta = {"base": rep.base, "now_utc": now.isoformat(), "kst_date": live.kst_date(now), "wc_phase": phase,
                "wc_window": window, "lab": rep.is_lab, "engines": engines}
    with sync_playwright() as pw:
        for name in engines:
            spec = ENGINES[name]
            browser = getattr(pw, spec["browser"]).launch(headless=True)
            try:
                if spec["device"]:
                    desc = dict(pw.devices[spec["device"]])
                    desc.pop("default_browser_type", None)
                    size = (desc["viewport"]["width"], desc["viewport"]["height"])
                else:
                    desc, size = {}, spec["size"]
                signals = new_signals()
                context = make_context(browser, rep, "ko", size, signals, desc)
                context.add_init_script(AUDIO_HOOK)
                page = context.new_page()
                touch = spec["touch"]
                journeys = [
                    ("home", lambda: j_home(rep, page, phase, touch)),
                    ("ggongbab", lambda: j_ggongbab(rep, page, touch)),
                    ("magazine", lambda: j_simple(rep, page, "mukbang.html", touch)),
                    ("event", lambda: j_simple(rep, page, "event.html", touch)),
                    ("worldcup", lambda: j_worldcup(rep, page, phase, size, friend_id, cat, touch)),
                ]
                for jname, fn in journeys:
                    rep.scope = f"{name}/{jname}"
                    before = len(rep.failures)
                    try:
                        fn()
                    except Exception as exc:
                        rep.check(f"{jname}: journey completed", False, f"{type(exc).__name__}: {str(exc).splitlines()[0] if str(exc) else ''}")
                    if len(rep.failures) > before:
                        rep.screenshot(page, "fail")
                rep.scope = f"{name}/site-wide"
                signals["console"] = [c for c in signals["console"] if not is_known_noise(c[1])]
                finish_signals(rep, signals)
                context.close()
            finally:
                browser.close()
    rep.scope = "read-only"
    bad = post_violations(rep.posts, rep.is_lab)
    rep.check("no forbidden non-GET request was attempted", not bad,
              "; ".join(f"{p['method']} {p['host']}{p['path']} [{p['scope']}]" for p in bad[:5]))
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", default="https://babdoduk-lab.vercel.app")
    ap.add_argument("--out", default=str(ROOT / ".local" / "e2e-browsers"))
    ap.add_argument("--engines", help="comma list of " + ",".join(ENGINES) + " (default: all)")
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rep = run(args.base, out, parse_engines(args.engines))
    tag = live.host_tag(rep.base)
    (out / f"e2e-browsers-{tag}.json").write_text(json.dumps(
        {**rep.meta, "ok": not rep.failures, "results": rep.results, "warnings": rep.warnings,
         "aborted_non_get": rep.posts, "screenshots": rep.screens}, ensure_ascii=False, indent=2), encoding="utf-8")
    text = live.summary_text(rep).replace("# E2E live:", "# E2E browsers:")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(text)
    step = os.environ.get("GITHUB_STEP_SUMMARY")
    if step:
        with open(step, "a", encoding="utf-8") as fh:
            fh.write(text + "\n\n")
    return 1 if rep.failures else 0


if __name__ == "__main__":
    sys.exit(main())
