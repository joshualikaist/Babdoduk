#!/usr/bin/env python3
"""Write the shared site navigation and footer, the translations and the authored content into every page.

shared/nav.html and shared/footer.html are the single source of truth. Each page
keeps a static copy, so navigation and footer work without JavaScript; this script
renders the copy for each page (current-page marker, home link, lab-only links)
and replaces the page's <header class="site-nav"> and <footer class="site-footer">
blocks.

    python scripts/sync_site_chrome.py          # rewrite the pages
    python scripts/sync_site_chrome.py --check  # exit 1 and show the diff if any page drifted

Each page's translation table is written whole, between `<!-- @i18n:strings -->` and
`<!-- @end i18n -->`, followed by js/site.js (the language switch, scroll progress and "more"
menu every page shares). The table holds the page's title and the keys of the families it shows
(PAGES `strings`, plus a11y, nav and footer on every page) from i18n/ko.json and i18n/en.json, the
shared labels it shows (label_strings) and its data/content/ entries (CONTENT_STRINGS). Every key
the chrome renders must exist in both languages.

The shared labels (data/content/labels.json: free-food types, sources, magazine lanes, the
picker's cuisines) also go into the marked blocks of the scripts that need them (LABEL_BLOCKS), so
a label is named once and the same everywhere.

The authored page content (data/content/events.json and history.json, rendered by
scripts/page_content.py) is written into the marked blocks of event.html and history.html
(CONTENT_BLOCKS): the rows between `<!-- @content:<name> -->` and `<!-- @end content -->`, and
their translations between `// @content:<name>:<lang>` and `// @end content`.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

import page_content
from page_content import js_str

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "shared"
LABELS = ROOT / "data" / "content" / "labels.json"
I18N = ROOT / "i18n"
# The key families every page's table carries; PAGES `strings` adds the page's own.
COMMON_STRINGS = ("a11y", "nav", "footer")
# The food types the home calendar names (js/home-calendar.js FOOD_TYPES); any other type reads
# home.cal.foodFallback there.
HOME_FOOD_TYPES = ("meal", "lunchbox", "snack", "refreshment", "beverage", "coupon")

LAB_LINKS = [
    '<a class="nav-mega-link" href="lab.html" data-i18n="nav.lab">실험실</a>',
    '<a class="nav-mega-link" href="lab-ggongbab.html" data-i18n="nav.labFeed">꽁밥 실험</a>',
    '<a class="nav-mega-link" href="tip.html" data-i18n="nav.labTip">꽁밥 제보</a>',
]
LAB_RIBBON = [
    '<div class="lab-fork-ribbon">',
    '  실험용 오늘의 꽁밥 — <a href="lab.html">실험실</a> / 본편 <a href="ggongbab.html">오늘의 꽁밥</a>',
    '</div>',
]

# Page -> the nav link it marks as current (None on the home page, whose wordmark
# scrolls to the top instead of linking to itself), and the i18n/ key families its
# translation table carries besides COMMON_STRINGS (`strings`).
PAGES = {
    "index.html": {"current": None, "home": "#", "strings": ("home", "explore", "profile")},
    "ggongbab.html": {"current": "ggongbab.html", "strings": ("gg", "ggongbab", "km")},
    "mukbang.html": {"current": "mukbang.html", "strings": ("eat", "kaist", "km", "mg")},
    "event.html": {"current": "event.html", "strings": ("event",)},
    # Food Log is lab-only: no public nav/footer link points at it; it carries the lab links.
    "food.html": {"current": None, "lab": True, "strings": ("cal", "food")},
    "history.html": {"current": "history.html", "strings": ("history",)},
    # The menu world cup opens from an activity on event.html; no nav link points at it.
    "worldcup.html": {"current": None, "strings": ("wc",)},
    "lab.html": {"current": "lab.html", "lab": True, "strings": ("lab",)},
    "lab-ggongbab.html": {"current": "lab-ggongbab.html", "lab": True, "ribbon": True,
                          "strings": ("gg", "ggongbab", "km")},
    # The free-food tip board is lab-only (docs/GGONGBAB_TIPS.md): reached from the lab pages only.
    "tip.html": {"current": "tip.html", "lab": True, "strings": ("tip",)},
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
    if config.get("home") == "#":  # the home page's wordmark scrolls to the top
        rendered = rendered.replace('data-i18n-aria-key="nav.homeAria" aria-label="홈으로"',
                                    'data-i18n-aria-key="nav.topAria" aria-label="맨 위로"', 1)
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
    text = fill_blocks(page, "\n".join(lines), "i18n", {"strings": render_strings(page)})
    if page in CONTENT_BLOCKS:
        text = fill_blocks(page, text, "content", CONTENT_BLOCKS[page]())
    return text


def chrome_keys() -> set[str]:
    """Translation keys the shared nav and footer render."""
    keys: set[str] = set()
    for name in ("nav", "footer"):
        keys |= set(re.findall(r'data-i18n(?:-aria-key)?="([^"]+)"', (SHARED / f"{name}.html").read_text(encoding="utf-8")))
    return keys


def labels() -> dict:
    return json.loads(LABELS.read_text(encoding="utf-8"))


def label_strings(page: str) -> dict[str, dict[str, str]]:
    """The shared labels a page's translation tables carry, by key."""
    data, out = labels(), {}
    if page in ("ggongbab.html", "lab-ggongbab.html"):
        out.update({f"gg.food.{kind}": pair for kind, pair in data["freeFood"].items()})
        out.update({f"gg.source.{group}": pair for group, pair in data["sourceLabels"].items()})
    if page == "index.html":
        out.update({f"home.cal.food.{kind}": data["freeFood"][kind] for kind in HOME_FOOD_TYPES})
        out.update({f"home.cal.src.{group}": pair for group, pair in data["sourceLabels"].items()})
        out.update({f"home.desk.{lane}": spec["name"] for lane, spec in data["magazineLanes"].items()})
    if page == "mukbang.html":
        for lane, spec in data["magazineLanes"].items():
            out[f"mg.cat.{lane}"] = spec["name"]
            out[f"mg.{lane}.lead"] = spec["lead"]
            if "short" in spec:
                out[f"mg.cat.{lane}Short"] = spec["short"]
    return out


def _object(mapping: dict) -> str:
    return json.dumps(mapping, ensure_ascii=False)


# Scripts of lab-only experiments (not promoted to production in the current main baseline). A tree
# without one, like main, has no block to write there; any other missing script stops the sync.
LAB_ONLY_SCRIPTS = {"js/ggongbab-public-feed.js"}


def present(blocks: dict, root: Path) -> dict:
    """The label blocks of the scripts this tree has: lab-only scripts it lacks are left out."""
    return {path: block for path, block in blocks.items() if path not in LAB_ONLY_SCRIPTS or (root / path).exists()}


# Script blocks between `// @labels:<name>` and `// @end labels`, rendered from the labels.
ALL_LABEL_BLOCKS = {
    "js/eat-slot.js": {
        "cuisines": lambda data: [
            f"var CUISINE_BY_CUISINE = {_object(data['cuisines']['byCuisine'])};",
            f"var CUISINE_BY_GROUP = {_object(data['cuisines']['byGroup'])};",
        ],
    },
    "js/ggongbab-public-feed.js": {
        "source-names": lambda data: [
            "var NAMES = Object.freeze(" + _object({k: v["dataName"] for k, v in data["sources"].items()}) + ");",
        ],
    },
}
LABEL_BLOCKS = present(ALL_LABEL_BLOCKS, ROOT)


# Page blocks rendered from data/content/ (scripts/page_content.py), and their translations.
CONTENT_BLOCKS = {
    "event.html": lambda: {**page_content.event_blocks(), **page_content.worldcup_font_block()},
    "history.html": page_content.history_blocks,
    "worldcup.html": page_content.worldcup_blocks,
    "index.html": page_content.home_font_block,
}
# Scripts with `// @content:<name>` blocks written from data/content/ (loaded by a page only when needed).
CONTENT_SCRIPTS = {
    "js/worldcup-entry-data.js": page_content.worldcup_entry_data_blocks,
    "js/worldcup-gate.js": page_content.worldcup_gate_blocks,
}
# The single keys (not whole families) a page's table carries besides its PAGES `strings`.
PAGE_KEYS = {
    "event.html": page_content.WORLDCUP_ENTRY_KEYS,
    "index.html": page_content.WORLDCUP_GATE_KEYS,
}
CONTENT_STRINGS = {
    "event.html": page_content.event_strings,
    "history.html": page_content.history_strings,
}


def fill_blocks(path: str, text: str, kind: str, rendered: dict[str, list[str]]) -> str:
    """Replace the lines between each `// @<kind>:<name>` (or `<!-- @<kind>:<name> -->`) marker and
    the next `// @end <kind>` (or `<!-- @end <kind> -->`) with the rendered rows, at the marker's
    indentation."""
    lines = text.split("\n")
    for name, rows in rendered.items():
        opening = (f"// @{kind}:{name}", f"<!-- @{kind}:{name} -->")
        starts = [i for i, line in enumerate(lines) if line.strip() in opening]
        if len(starts) != 1:
            raise SystemExit(f"{path}: expected one {opening[0]} block, found {len(starts)}")
        start = starts[0]
        closing = (f"// @end {kind}", f"<!-- @end {kind} -->")
        end = next((i for i in range(start + 1, len(lines)) if lines[i].strip() in closing), None)
        if end is None:
            raise SystemExit(f"{path}: the {opening[0]} block has no {closing[0]}")
        indent = lines[start][: len(lines[start]) - len(lines[start].lstrip())]
        lines[start + 1:end] = [indent + row if row else row for row in rows]
    return "\n".join(lines)


def synced_content_script(path: str) -> str:
    """The script with its content blocks rendered from data/content/."""
    return fill_blocks(path, (ROOT / path).read_text(encoding="utf-8"), "content", CONTENT_SCRIPTS[path]())


def synced_script(path: str) -> str:
    """The script with its label blocks rendered from data/content/labels.json."""
    data = labels()
    rendered = {name: render_block(data) for name, render_block in LABEL_BLOCKS[path].items()}
    return fill_blocks(path, (ROOT / path).read_text(encoding="utf-8"), "labels", rendered)


def i18n() -> dict[str, dict[str, str]]:
    return {lang: json.loads((I18N / f"{lang}.json").read_text(encoding="utf-8")) for lang in ("ko", "en")}


def page_strings(page: str) -> dict[str, dict[str, str]]:
    """The page's translation table in each language: its title, its families' keys from i18n/, the
    shared labels it shows and its data/content/ entries."""
    data = i18n()
    families = COMMON_STRINGS + PAGES[page].get("strings", ())
    labelled = label_strings(page)
    content = CONTENT_STRINGS[page]() if page in CONTENT_STRINGS else {"ko": {}, "en": {}}
    tables = {}
    for lang in ("ko", "en"):
        entries = {key: value for key, value in data[lang].items()
                   if key.split(".")[0] in families or key in PAGE_KEYS.get(page, ())}
        entries.update({key: pair[lang] for key, pair in labelled.items()})
        entries.update(content[lang])
        tables[lang] = {"docTitle": data[lang][f"title.{page[:-len('.html')]}"], **dict(sorted(entries.items()))}
    missing = sorted(key for key in chrome_keys() for lang in ("ko", "en") if key not in tables[lang])
    if missing:
        raise SystemExit(f"{page}: the translation table lacks shared chrome keys {missing}")
    return tables


def render_strings(page: str) -> list[str]:
    """The table script and js/site.js, as the page's `@i18n:strings` block."""
    rows = ["<script>",
            "  // Written by scripts/sync_site_chrome.py from i18n/ and data/content/; edit those, not this table.",
            "  window.BABDODUK_STR = {"]
    tables = page_strings(page)
    for lang in ("ko", "en"):
        rows.append(f"    {lang}: {{")
        for key, value in tables[lang].items():
            name = key if key.isidentifier() else f"'{key}'"
            rows.append(f"      {name}: {js_str(value)},")
        rows.append("    }" + ("," if lang == "ko" else ""))
    rows += ["  };", "</script>", '<script src="js/site.js"></script>']
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="report drift instead of rewriting")
    args = parser.parse_args(argv)
    drifted = []
    targets = ([(page, synced) for page in PAGES] + [(path, synced_script) for path in LABEL_BLOCKS]
               + [(path, synced_content_script) for path in CONTENT_SCRIPTS])
    for page, render_target in targets:
        path = ROOT / page
        current = path.read_text(encoding="utf-8")
        expected = render_target(page)
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
            print(f"\nsite chrome drift in {len(drifted)} file(s): {', '.join(drifted)}. Edit shared/nav.html, "
                  "shared/footer.html, i18n/ or data/content/, then run python scripts/sync_site_chrome.py.")
            return 1
        print(f"site chrome in sync: {len(PAGES)} pages, {len(LABEL_BLOCKS) + len(CONTENT_SCRIPTS)} scripts")
        return 0
    print(f"rewrote {len(drifted)} page(s)" + (f": {', '.join(drifted)}" if drifted else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
