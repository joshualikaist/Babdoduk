#!/usr/bin/env python3
"""Every page's text in Korean and English, as one snapshot, and the comparison of two snapshots.

For changes that must not change what a reader sees or hears (data plan phases 4 and 5: content
and translations move out of the pages, the pages stay the same):

    python scripts/check_page_text.py --snapshot before.json --data DIR
    ... change the pages ...
    python scripts/check_page_text.py --snapshot after.json --data DIR
    python scripts/check_page_text.py --compare before.json after.json

Each page is served from this tree with no network (no fonts, APIs or image hosts), the page
clock is fixed, and with --data the data/ files come from DIR, so two trees are compared on the
same content. A snapshot keeps the visible text line by line and every accessible name the page
carries (aria-label, title, alt, placeholder, the document title and description). The comparison
prints what changed and exits 1 when anything did.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
HOST = "page-text.invalid"
CLOCK = "2026-10-12T12:00:00+09:00"
# The hub's two tabs read different data, so both are taken.
VARIANTS = {"ggongbab.html": ["ggongbab.html#free", "ggongbab.html#menu"]}
CAPTURE = """() => {
  const text = (document.body ? document.body.innerText : '').split('\\n')
    .map(line => line.replace(/\\s+/g, ' ').trim()).filter(Boolean);
  const names = new Set();
  for (const el of document.querySelectorAll('[aria-label],[title],[alt],[placeholder],[aria-description]')) {
    for (const attr of ['aria-label', 'title', 'alt', 'placeholder', 'aria-description']) {
      const value = el.getAttribute(attr);
      if (value && value.trim()) names.add(`${el.tagName.toLowerCase()}[${attr}]=${value.trim()}`);
    }
  }
  const meta = document.querySelector('meta[name="description"]');
  return {title: document.title, lang: document.documentElement.lang,
          description: meta ? meta.getAttribute('content') : '', text, names: [...names].sort()};
}"""


def pages() -> list[str]:
    names = sorted(p.name for p in ROOT.glob("*.html")
                   if re.search(r"<!doctype\s+html", p.read_text(encoding="utf-8"), re.I))
    out = []
    for name in names:
        out += VARIANTS.get(name, [name])
    return out


def snapshot(out: Path, data: Path | None) -> dict:
    from playwright.sync_api import sync_playwright

    def route(request_route):
        url = urlparse(request_route.request.url)
        path = unquote(url.path).lstrip("/")
        if url.hostname != HOST:
            request_route.abort()
            return
        base = data if data is not None and path.startswith("data/") else ROOT
        rel = path[len("data/"):] if base is data else path
        file = (base / rel).resolve()
        if file.is_file() and (base.resolve() in file.parents):
            request_route.fulfill(path=str(file))
        else:
            request_route.fulfill(status=404, body="")

    result = {}
    browser_name = os.environ.get("BABDODUK_BROWSER", "chrome")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=None if browser_name == "chromium" else browser_name, headless=True)
        for lang in ("ko", "en"):
            context = browser.new_context(viewport={"width": 1440, "height": 900}, timezone_id="Asia/Seoul",
                                          reduced_motion="reduce", service_workers="block")
            context.clock.set_fixed_time(CLOCK)
            context.route("**/*", route)
            context.add_init_script(f"try {{ localStorage.setItem('babdoduk-lang', '{lang}'); "
                                    "sessionStorage.setItem('babdoduk-welcome-seen', '1'); } catch (e) {}")
            # The picker's reel draws random dishes: the same seeded sequence on every load.
            context.add_init_script("(() => { let s = 20261012; Math.random = () => { s |= 0; s = s + 0x6D2B79F5 | 0;"
                                    " let t = Math.imul(s ^ s >>> 15, 1 | s); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;"
                                    " return ((t ^ t >>> 14) >>> 0) / 4294967296; }; })();")
            page = context.new_page()
            for name in pages():
                page.goto(f"https://{HOST}/{name}", wait_until="networkidle")
                page.wait_for_timeout(300)
                result[f"{name}|{lang}"] = page.evaluate(CAPTURE)
            context.close()
        browser.close()
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result


def compare(before: dict, after: dict) -> list[str]:
    report = []
    for key in sorted(set(before) | set(after)):
        if key not in after or key not in before:
            report.append(f"== {key}: only in {'before' if key in before else 'after'}")
            continue
        a, b = before[key], after[key]
        for field in ("title", "lang", "description"):
            if a.get(field) != b.get(field):
                report.append(f"== {key} {field}: {a.get(field)!r} -> {b.get(field)!r}")
        diff = list(difflib.unified_diff(a["text"], b["text"], lineterm="", n=1))
        if diff:
            report.append(f"== {key} text")
            report += diff[2:]
        lost, gained = sorted(set(a["names"]) - set(b["names"])), sorted(set(b["names"]) - set(a["names"]))
        if lost or gained:
            report.append(f"== {key} accessible names")
            report += [f"-{n}" for n in lost] + [f"+{n}" for n in gained]
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--snapshot", type=Path, metavar="OUT")
    mode.add_argument("--compare", type=Path, nargs=2, metavar=("BEFORE", "AFTER"))
    parser.add_argument("--data", type=Path, help="serve data/ from this folder instead of the tree's own")
    args = parser.parse_args(argv)
    if args.snapshot:
        result = snapshot(args.snapshot, args.data)
        print(f"page text snapshot: {len(result)} page views -> {args.snapshot}")
        return 0
    before, after = (json.loads(path.read_text(encoding="utf-8")) for path in args.compare)
    report = compare(before, after)
    print("\n".join(report) if report else f"no change in {len(after)} page views")
    return 1 if report else 0


if __name__ == "__main__":
    sys.exit(main())
