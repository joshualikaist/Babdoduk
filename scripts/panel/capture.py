#!/usr/bin/env python3
"""Photograph the site once for the virtual review panel (docs/PANEL.md).

    python scripts/panel/capture.py --out .local/panel/<run> [--base https://babdoduk-lab.vercel.app]

Opens every public page in Korean as an iPhone, an Android phone and a computer, read-only (GET only),
and writes shots/<page>-<device>.jpg plus facts.json: headings, visible text, small tap targets,
overflowing elements, console errors, failed requests and load timings. Every reviewer reads the same
capture, so the site is visited once per run.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

PAGES = ("index.html", "ggongbab.html", "choose.html", "mukbang.html", "event.html", "history.html",
         "worldcup.html", "tip.html", "my.html", "privacy.html")
DEVICES = {
    "iphone": {"viewport": {"width": 390, "height": 844}, "device_scale_factor": 2, "is_mobile": True,
               "has_touch": True,
               "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 "
                             "(KHTML, like Gecko) CriOS/138.0.7204.156 Mobile/15E148 Safari/604.1"},
    "android": {"viewport": {"width": 412, "height": 915}, "device_scale_factor": 2, "is_mobile": True,
                "has_touch": True,
                "user_agent": "Mozilla/5.0 (Linux; Android 15; SM-S928N) AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/138.0.7204.157 Mobile Safari/537.36"},
    "desktop": {"viewport": {"width": 1440, "height": 900}, "device_scale_factor": 1},
}
MAX_SHOT_HEIGHT = 6000

OBSERVE = """
window.__panel = { lcp: 0, cls: 0 };
try {
  new PerformanceObserver(l => { for (const e of l.getEntries()) window.__panel.lcp = e.startTime; })
    .observe({ type: 'largest-contentful-paint', buffered: true });
  new PerformanceObserver(l => { for (const e of l.getEntries()) if (!e.hadRecentInput) window.__panel.cls += e.value; })
    .observe({ type: 'layout-shift', buffered: true });
} catch (e) {}
"""

FACTS = """(mobile) => {
  const vis = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const name = el => (el.getAttribute('aria-label') || el.innerText || el.value || el.title || '').trim().replace(/\\s+/g, ' ').slice(0, 60);
  const where = el => { const r = el.getBoundingClientRect(); return { x: Math.round(r.left), y: Math.round(r.top + scrollY),
    w: Math.round(r.width), h: Math.round(r.height) }; };
  const controls = [...document.querySelectorAll('a[href], button, input, select, textarea, [role=button], summary')].filter(vis);
  const limit = mobile ? 44 : 24;
  const small = controls.filter(el => { const r = el.getBoundingClientRect(); return r.height < limit || r.width < limit; })
    .slice(0, 40).map(el => ({ tag: el.tagName.toLowerCase(), id: el.id, cls: String(el.className).slice(0, 60), name: name(el), ...where(el) }));
  const wide = [...document.querySelectorAll('body *')].filter(el => vis(el) && el.getBoundingClientRect().right > innerWidth + 1)
    .slice(0, 20).map(el => ({ tag: el.tagName.toLowerCase(), id: el.id, cls: String(el.className).slice(0, 60), ...where(el) }));
  const nav = performance.getEntriesByType('navigation')[0] || {};
  const res = performance.getEntriesByType('resource');
  return {
    title: document.title,
    headings: [...document.querySelectorAll('h1, h2, h3')].filter(vis).map(h => h.tagName.toLowerCase() + ' ' + h.innerText.trim().slice(0, 80)),
    text: document.body.innerText.replace(/\\n{3,}/g, '\\n\\n').slice(0, 6000),
    controls: controls.length,
    smallTargets: small,
    overflow: { page: document.documentElement.scrollWidth > innerWidth, elements: wide },
    height: document.documentElement.scrollHeight,
    timing: { domContentLoaded: Math.round(nav.domContentLoadedEventEnd || 0), load: Math.round(nav.loadEventEnd || 0),
              lcp: Math.round(window.__panel.lcp), cls: Math.round(window.__panel.cls * 1000) / 1000,
              requests: res.length, kilobytes: Math.round(res.reduce((s, r) => s + (r.transferSize || 0), 0) / 1024) },
  };
}"""


def capture(base: str, out: Path) -> dict:
    shots = out / "shots"
    shots.mkdir(parents=True, exist_ok=True)
    report = {"base": base, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "pages": {}}
    channel = os.environ.get("BABDODUK_BROWSER", "chrome")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=None if channel == "chromium" else channel, headless=True)
        for device, opts in DEVICES.items():
            context = browser.new_context(locale="ko-KR", timezone_id="Asia/Seoul", **opts)
            context.add_init_script(OBSERVE)
            context.route("**/*", lambda route: route.continue_() if route.request.method in ("GET", "HEAD")
                          else route.abort())
            for page_name in PAGES:
                page = context.new_page()
                errors, failed = [], []
                page.on("console", lambda m, e=errors: m.type == "error" and e.append(m.text[:200]))
                page.on("pageerror", lambda x, e=errors: e.append(str(x)[:200]))
                page.on("requestfailed", lambda r, f=failed: f.append(r.url[:160]))
                try:
                    page.goto(f"{base}/{page_name}", wait_until="load", timeout=45000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=8000)
                    except Exception:
                        pass
                    page.wait_for_timeout(800)
                    facts = page.evaluate(FACTS, bool(opts.get("is_mobile")))
                    shot = shots / f"{page_name[:-5]}-{device}.jpg"
                    height = min(facts["height"], MAX_SHOT_HEIGHT)
                    page.screenshot(path=str(shot), type="jpeg", quality=70,
                                    clip={"x": 0, "y": 0, "width": opts["viewport"]["width"], "height": height},
                                    full_page=True)
                    facts.update(shot=f"shots/{shot.name}", consoleErrors=errors, failedRequests=failed)
                except Exception as exc:
                    facts = {"error": str(exc)[:300]}
                report["pages"].setdefault(page_name, {})[device] = facts
                page.close()
            context.close()
        browser.close()
    (out / "facts.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="https://babdoduk-lab.vercel.app")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    report = capture(args.base.rstrip("/"), args.out)
    bad = [f"{p}/{d}" for p, ds in report["pages"].items() for d, f in ds.items() if "error" in f]
    print(f"captured {sum(len(d) for d in report['pages'].values())} views into {args.out}" + (f"; failed: {bad}" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
