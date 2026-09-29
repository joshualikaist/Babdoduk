#!/usr/bin/env python3
"""Write the shared site navigation and footer into every page.

shared/nav.html and shared/footer.html are the single source of truth. Each page
keeps a static copy, so navigation and footer work without JavaScript; this script
renders the copy for each page (current-page marker, home link, lab-only links)
and replaces the page's <header class="site-nav"> and <footer class="site-footer">
blocks.

    python scripts/sync_site_chrome.py          # rewrite the pages
    python scripts/sync_site_chrome.py --check  # exit 1 and show the diff if any page drifted

Strings the chrome owns (CHROME_STRINGS) are written into every page's ko and en translation
tables, and every key the chrome renders must exist in both.
"""
from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "shared"

LAB_LINKS = [
    '<a class="nav-mega-link" href="lab.html" data-i18n="nav.lab">실험실</a>',
    '<a class="nav-mega-link" href="lab-ggongbab.html" data-i18n="nav.labFeed">꽁밥 실험</a>',
]
LAB_RIBBON = [
    '<div class="lab-fork-ribbon">',
    '  실험용 오늘의 꽁밥 — <a href="lab.html">실험실</a> / 본편 <a href="ggongbab.html">오늘의 꽁밥</a>',
    '</div>',
]

# Page -> the nav link it marks as current (None on the home page, whose wordmark
# scrolls to the top instead of linking to itself).
PAGES = {
    "index.html": {"current": None, "home": "#"},
    "ggongbab.html": {"current": "ggongbab.html"},
    "mukbang.html": {"current": "mukbang.html"},
    "event.html": {"current": "event.html"},
    # Food Log is lab-only: no public nav/footer link points at it; it carries the lab links.
    "food.html": {"current": None, "lab": True},
    "history.html": {"current": "history.html"},
    "lab.html": {"current": "lab.html", "lab": True},
    "lab-ggongbab.html": {"current": "lab-ggongbab.html", "lab": True, "ribbon": True},
}

# Strings the shared chrome owns. Each page keeps its own translation table, so these
# entries are written into every page's ko and en tables by this script.
CHROME_STRINGS = {
    "footer.contact": {"ko": "문의", "en": "Contact"},
}

BLOCKS = (("nav", '<header class="site-nav"', "</header>"),
          ("footer", '<footer class="site-footer"', "</footer>"))


def template(name: str) -> list[str]:
    return (SHARED / f"{name}.html").read_text(encoding="utf-8").rstrip("\n").split("\n")


def render_nav(page: str, config: dict) -> list[str]:
    out: list[str] = []
    current = config.get("current")
    in_panel = False
    for line in template("nav"):
        indent = line[: len(line) - len(line.lstrip())]
        stripped = line.strip()
        if stripped == "<!-- @ribbon -->":
            out += [indent + row for row in LAB_RIBBON] if config.get("ribbon") else []
            continue
        if stripped == "<!-- @lab-links -->":
            out += [indent + row for row in LAB_LINKS] if config.get("lab") else []
            continue
        out.append(line)
    rendered = "\n".join(out)
    rendered = rendered.replace('<a href="index.html" id="navHome"', f'<a href="{config.get("home", "index.html")}" id="navHome"')
    if current:
        pattern = re.compile(r'<a class="(site-nav-direct|nav-mega-link)" href="' + re.escape(current) + '"')
        match = pattern.search(rendered)
        if not match:
            raise SystemExit(f"{page}: no nav link for {current}")
        kind = match.group(1)
        rendered = pattern.sub(f'<a class="{kind} is-current" href="{current}" aria-current="page"', rendered, count=1)
        in_panel = kind == "nav-mega-link"
    if in_panel:
        rendered = rendered.replace('class="nav-mega-trigger"', 'class="nav-mega-trigger is-current"', 1)
    return rendered.split("\n")


def render(page: str, kind: str) -> list[str]:
    return render_nav(page, PAGES[page]) if kind == "nav" else template("footer")


def synced(page: str) -> str:
    """The page with its nav and footer blocks replaced by the shared copies."""
    text = (ROOT / page).read_text(encoding="utf-8")
    lines = text.split("\n")
    for kind, start_tag, end_tag in BLOCKS:
        starts = [i for i, line in enumerate(lines) if line.lstrip().startswith(start_tag)]
        if len(starts) != 1:
            raise SystemExit(f"{page}: expected one {start_tag}, found {len(starts)}")
        start = starts[0]
        end = next(i for i in range(start, len(lines)) if lines[i].strip() == end_tag)
        indent = lines[start][: len(lines[start]) - len(lines[start].lstrip())]
        block = [indent + row if row else row for row in render(page, kind)]
        lines[start:end + 1] = block
    return sync_strings(page, "\n".join(lines))


def chrome_keys() -> set[str]:
    """Translation keys the shared nav and footer render."""
    keys: set[str] = set()
    for name in ("nav", "footer"):
        keys |= set(re.findall(r'data-i18n(?:-aria-key)?="([^"]+)"', (SHARED / f"{name}.html").read_text(encoding="utf-8")))
    return keys


def sync_strings(page: str, text: str) -> str:
    """Write CHROME_STRINGS into the page's ko and en tables; every chrome key must exist in both."""
    lines = text.split("\n")
    blocks = []
    for lang in ("ko", "en"):
        start = next(i for i, line in enumerate(lines) if line.strip() == f"{lang}: {{")
        end = next(i for i in range(start + 1, len(lines)) if lines[i].strip() in ("},", "}"))
        blocks.append((start, end, lang))
    for start, end, lang in sorted(blocks, reverse=True):  # later block first: indexes stay valid
        body = lines[start + 1:end]
        for key, values in CHROME_STRINGS.items():
            anchor = next(i for i, line in enumerate(body) if line.lstrip().startswith("'footer.copyright':"))
            indent = body[anchor][: len(body[anchor]) - len(body[anchor].lstrip())]
            entry = f"{indent}'{key}': '{values[lang]}',"
            found = [i for i, line in enumerate(body) if line.lstrip().startswith(f"'{key}':")]
            if found:
                body[found[0]] = entry
            else:
                body.insert(anchor + 1, entry)
        missing = sorted(k for k in chrome_keys() if not any(line.lstrip().startswith(f"'{k}':") for line in body))
        if missing:
            raise SystemExit(f"{page}: the {lang} translation table lacks shared chrome keys {missing}")
        lines[start + 1:end] = body
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="report drift instead of rewriting")
    args = parser.parse_args(argv)
    drifted = []
    for page in PAGES:
        path = ROOT / page
        current = path.read_text(encoding="utf-8")
        expected = synced(page)
        if current == expected:
            continue
        drifted.append(page)
        if args.check:
            diff = difflib.unified_diff(current.split("\n"), expected.split("\n"),
                                        f"{page} (committed)", f"{page} (from shared/)", lineterm="", n=1)
            print("\n".join(diff))
        else:
            path.write_bytes(expected.encode("utf-8"))
    if args.check:
        if drifted:
            print(f"\nsite chrome drift in {len(drifted)} page(s): {', '.join(drifted)}. "
                  "Edit shared/nav.html or shared/footer.html, then run python scripts/sync_site_chrome.py.")
            return 1
        print(f"site chrome in sync: {len(PAGES)} pages")
        return 0
    print(f"rewrote {len(drifted)} page(s)" + (f": {', '.join(drifted)}" if drifted else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
