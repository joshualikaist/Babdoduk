"""Offline public-page overflow and visible Windows Chromium scrollbar checks."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlparse

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SIZES = [(1920, 1080), (1440, 900), (768, 1024), (390, 844), (360, 800)]
LONG_TITLE = "아주긴한글제목" * 24 + " UnbrokenEnglishTitle" * 3 + "LongEnglishWord" * 30


def public_pages():
    """Discover tracked public HTML, excluding test fixtures and ignored scratch."""
    files = subprocess.check_output(["git", "ls-files", "-z", "*.html"], cwd=ROOT).decode().split("\0")
    return sorted(name for name in files if name and not name.startswith(("tests/", "scripts/"))
                  and re.search(r"<!doctype\s+html", (ROOT / name).read_text(encoding="utf-8"), re.I))


def contrast(a, b):
    def luminance(rgb):
        values = [int(n) / 255 for n in re.findall(r"\d+", rgb)[:3]]
        values = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in values]
        return sum(v * weight for v, weight in zip(values, (.2126, .7152, .0722)))
    light, dark = sorted((luminance(a), luminance(b)), reverse=True)
    return (light + .05) / (dark + .05)


def offline_route(route):
    url = urlparse(route.request.url)
    path = unquote(url.path).lstrip("/")
    if url.hostname != "site-ui.invalid":
        route.abort()  # no external fonts, SDKs, DBs, APIs, or image hosts
    elif path == "data/ggongbab/latest.json":
        future = (datetime.now(timezone(timedelta(hours=9))) + timedelta(days=8)).isoformat()
        route.fulfill(json={"events": [{"id": "ui-synthetic", "title": LONG_TITLE, "summary": LONG_TITLE,
            "startAt": future, "food": {"provided": "true", "type": "meal"}}]})
    else:
        file = (ROOT / path).resolve()
        if (file.is_file() and ROOT in file.parents and not any(p.startswith(".") for p in Path(path).parts)
                and file.suffix in (".html", ".css", ".js", ".json", ".png", ".jpg", ".svg", ".webp", ".woff2")):
            route.fulfill(path=str(file))
        else:
            route.fulfill(status=404, body="")


MEASURE = """() => {
  const root = document.documentElement, body = document.body;
  const style = getComputedStyle(root);
  const part = name => getComputedStyle(root, '::-webkit-scrollbar' + name);
  const bounds = selector => [...document.querySelectorAll(selector)].map(el => {
    const r = el.getBoundingClientRect(); return {left:r.left,right:r.right};
  });
  return {rootWidth:root.clientWidth, rootScroll:root.scrollWidth,
    bodyWidth:body.clientWidth, bodyScroll:body.scrollWidth,
    track:part('-track').backgroundColor, thumb:part('-thumb').backgroundColor,
    corner:part('-corner').backgroundColor, width:part('').width, height:part('').height,
    thumbVariable:style.getPropertyValue('--scrollbar-thumb').trim(),
    hoverVariable:style.getPropertyValue('--scrollbar-thumb-hover').trim(),
    background:getComputedStyle(body).backgroundColor, scrollbarColor:style.scrollbarColor,
    viewportGutter:window.innerWidth-root.clientWidth,
    footer:bounds('.site-footer, .site-footer-inner'), nav:bounds('.site-nav'),
    overflowElements:root.scrollWidth > root.clientWidth ? [...body.querySelectorAll('*')].filter(el => {
      const r=el.getBoundingClientRect(); return r.width && r.right > root.clientWidth+1 && getComputedStyle(el).visibility === 'visible';
    }).map(el => el.tagName+'.'+el.className).slice(0,16) : []};
}"""


def inspect_page(page, name, size, screenshot_dir=None):
    page.set_viewport_size({"width": size[0], "height": size[1]})
    page.goto("https://site-ui.invalid/" + name, wait_until="networkidle")
    if name in ("ggongbab.html", "lab-ggongbab.html"):
        page.locator(".gg-card").first.wait_for()
    count = 0

    def check(ok, detail):
        nonlocal count
        assert ok, f"{name} {size}: {detail}"
        count += 1

    metrics = page.evaluate(MEASURE)
    check(metrics["rootScroll"] <= metrics["rootWidth"], ("root overflow", metrics))
    check(metrics["bodyScroll"] <= metrics["bodyWidth"], ("body overflow", metrics))
    for kind in ("footer", "nav"):
        check(bool(metrics[kind]) and all(r["left"] >= -1 and r["right"] <= metrics["rootWidth"] + 1
                                        for r in metrics[kind]), (kind, metrics[kind]))
    check(metrics["track"] == metrics["background"], ("track surface", metrics))
    check(metrics["corner"] == metrics["track"], "corner surface")
    check(metrics["width"] == metrics["height"] == "16px", "both scrollbar axes remain usable")
    check(contrast(metrics["track"], metrics["thumb"]) >= 3, "thumb contrast >= 3:1")
    check(metrics["thumbVariable"] != metrics["hoverVariable"], "distinct hover thumb")
    check(metrics["scrollbarColor"] == "auto", "Chromium pseudo parts not overridden")
    # Chrome is launched without Playwright's default --hide-scrollbars. This
    # proves a classic Windows scrollbar actually occupies space, not just CSS.
    if page.evaluate("document.documentElement.scrollHeight > innerHeight"):
        check(metrics["viewportGutter"] == 16, ("visible Windows scrollbar gutter", metrics))

    direct = page.locator(".nav-mega-row > .site-nav-direct")
    check(direct.count() == 2, "two direct food tasks in navigation")
    check(direct.nth(0).get_attribute("href") == "ggongbab.html"
          and direct.nth(1).get_attribute("href") == "mukbang.html#what",
          "availability and choice have separate destinations")
    check(page.locator(".nav-mega-row > .nav-mega").count() == 1,
          "secondary destinations share one More menu")
    nav_items = page.locator("#navHome, .site-nav-direct, .nav-mega-trigger, #langToggle").evaluate_all(
        """els => els.map(el => { const r = el.getBoundingClientRect(); return {left:r.left,right:r.right,
          height:r.height,font:parseFloat(getComputedStyle(el).fontSize)}; }).sort((a,b) => a.left-b.left)""")
    check(all(nav_items[i]["right"] <= nav_items[i + 1]["left"] + 1
              for i in range(len(nav_items) - 1)), "navigation controls do not overlap")
    check(all(item["font"] >= 12 and item["height"] >= 44 for item in nav_items),
          ("navigation text >= 12px with 44px targets", nav_items))
    brand = page.locator("#navHome").evaluate("""el => { const s = getComputedStyle(el);
      return [s.backgroundImage, s.webkitTextFillColor, s.animationName]; }""")
    check("linear-gradient" in brand[0] and "99, 102, 241" in brand[0] and brand[1] == "rgba(0, 0, 0, 0)"
          and brand[2] == "none", ("original gradient wordmark; reduced motion stops its animation", brand))
    footer_layer = page.locator(".site-footer").evaluate(
        "el => [getComputedStyle(el).position, parseInt(getComputedStyle(el).zIndex, 10)]")
    check(footer_layer[0] != "static" and footer_layer[1] >= 1,
          ("footer paints above the fixed body::before canvas", footer_layer))
    footer_links = page.locator(".site-footer a").evaluate_all("els => els.map(el => el.getAttribute('href'))")
    check(footer_links and all(href and href != "#" and (ROOT / href.split("#")[0]).is_file()
                               for href in footer_links if not href.startswith(("mailto:", "https:"))),
          ("footer links resolve to real pages", footer_links))
    check(direct.nth(0).inner_text() == "오늘의 꽁밥"
          and direct.nth(1).inner_text() == "메뉴 고르기", "Korean primary labels")
    page.locator("#langToggle").click()
    english = [direct.nth(i).inner_text() for i in range(2)]
    check(english == ["Today's free food", "Choose a dish"], ("English primary labels", english,
          page.evaluate("document.documentElement.lang")))
    page.locator("#langToggle").click()
    nav = page.locator(".nav-mega-trigger").first
    nav.click()
    check(nav.get_attribute("aria-expanded") == "true", "navigation opens")
    panel = page.locator("#navMorePanel").bounding_box()
    check(panel is not None and panel["x"] >= -1 and panel["x"] + panel["width"] <= metrics["rootWidth"] + 1,
          "More menu remains inside viewport")
    page.keyboard.press("Escape")
    check(nav.get_attribute("aria-expanded") == "false", "navigation Escape closes")

    if name == "mukbang.html":
        check(metrics["track"] == "rgb(247, 244, 238)", "magazine paper color")
        # Exercise all four lanes with multiple, deliberately unbroken titles;
        # test DOM only, never generated data on disk.
        page.evaluate("""title => document.querySelectorAll('.mg-lane-items').forEach(box => {
          box.replaceChildren();
          for (let i=0;i<4;i++) {
            const article=document.createElement('article'); article.className='mg-story';
            const heading=document.createElement('h4'); heading.textContent=title;
            const summary=document.createElement('p'); summary.textContent=title;
            article.append(heading,summary); box.append(article);
          }
        })""", LONG_TITLE)
        lanes = page.locator(".mg-lane-items").evaluate_all("""boxes => boxes.map(box => ({
          width:box.clientWidth,scroll:box.scrollWidth,overflow:getComputedStyle(box).overflowX,
          snap:getComputedStyle(box).scrollSnapType,bound:box.hasAttribute('data-rail-bound'),
          cards:[...box.children].map(el=>{const r=el.getBoundingClientRect();return {
            x:r.x, y:r.y, bottom:r.bottom, width:el.clientWidth, scroll:el.scrollWidth,
            basis:getComputedStyle(el).flexBasis,snap:getComputedStyle(el).scrollSnapAlign};})
        }))""")
        check(len(lanes) == 4, "four categories retained")
        for lane in lanes:
            check(lane["scroll"] <= lane["width"], "no lane horizontal overflow")
            check(lane["overflow"] == "visible" and lane["snap"] == "none", "no carousel scroll container")
            check(not lane["bound"], "no auto-scroll binding")
            for i, card in enumerate(lane["cards"]):
                check(card["scroll"] <= card["width"], "long Korean/English content wraps")
                check(card["basis"] == "auto" and card["snap"] == "none", "default article layout")
                if i:
                    previous = lane["cards"][i-1]
                    check(card["y"] >= previous["bottom"] - 1 and abs(card["x"]-previous["x"]) < 1,
                          "articles stack vertically")
        columns = page.locator(".mg-lanes").evaluate("el => getComputedStyle(el).gridTemplateColumns.split(' ').length")
        check(columns == (4 if size[0] > 1024 else 2 if size[0] > 640 else 1), "category column layout retained")
        check(page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth && document.body.scrollWidth <= document.body.clientWidth"), "long titles do not expand page")
        page.locator(".mg-lane--trend").scroll_into_view_if_needed()

    if screenshot_dir:
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(screenshot_dir / f"{Path(name).stem}-{size[0]}x{size[1]}.png"))
    return {"checks": count, "overflow": metrics["rootScroll"]-metrics["rootWidth"],
            "track": metrics["track"], "thumb": metrics["thumb"], "gutter": metrics["viewportGutter"]}


def magazine_tools(page):
    """Picker and magazine cafeteria contracts on synthetic data, at phone width."""
    count = 0

    def check(ok, detail):
        nonlocal count
        assert ok, f"mukbang.html tools: {detail}"
        count += 1

    yesterday = (datetime.now(timezone(timedelta(hours=9))) - timedelta(days=1)).strftime("%Y-%m-%d")
    menu = {"date": yesterday, "restaurants": [{"id": "r1", "name": "<b>식당</b>",
            "breakfast": {"items": []}, "lunch": {"items": ["<img src=x onerror=alert(1)>"], "price": "5,000원"},
            "dinner": {"items": ["저녁"]}}]}
    page.route("**/data/kaist-menu/latest.json", lambda route: route.fulfill(json=menu))
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto("https://site-ui.invalid/mukbang.html", wait_until="networkidle")
    page.evaluate("localStorage.removeItem('babdoduk-food-preferences')")
    page.reload(wait_until="networkidle")
    tools = page.locator("#kaistToday")
    title = page.locator("#kaistTitle").inner_text()
    check("오늘" not in title and tools.locator(".kaist-date.is-stale").count() == 1,
          ("stale cafeteria data is labelled, not titled today", title))
    check(tools.locator("img").count() == 0 and tools.locator("b").count() == 0, "generated menu text is escaped")
    check(tools.locator("[role=tablist]").count() == 0 and tools.locator(".kaist-meal[aria-pressed]").count() == 3,
          "meal and restaurant controls are pressed toggles, not partial tabs")
    check(tools.locator(".kaist-to-hub").get_attribute("href") == "ggongbab.html#menu", "summary links to the hub")
    tools.locator('.kaist-meal[data-kaist-meal="dinner"]').focus()
    page.keyboard.press("Enter")
    check(page.evaluate("document.activeElement.dataset.kaistMeal") == "dinner", "focus survives re-render")

    page.locator(".eat-spinbtn").wait_for()
    check(page.locator('.eat-hunger[role="group"] [aria-pressed]').count() == 3, "hunger options are pressed toggles")
    page.locator(".eat-spinbtn").click()
    page.locator(".eat-hero h3").wait_for()
    check("MATCH" not in page.locator("#eatPanel").inner_text() and not page.locator(".eat-match").count(),
          "internal score is not shown as a probability")
    check(page.locator(".eat-reasons li").count() >= 1 and page.locator(".eat-scope").is_visible(),
          "reason and suggestion scope are visible")
    check(page.evaluate("document.activeElement.matches('.eat-hero h3')"), "focus moves to the result")
    check(page.locator("#eatStatus").inner_text().strip() != "", "result is announced")
    dish = page.locator('[data-eat="take"]').get_attribute("data-id")
    page.locator('[data-eat="take"]').click()
    prefs = page.evaluate("JSON.parse(localStorage.getItem('babdoduk-food-preferences'))")
    check(dish in prefs["likes"] and dish not in prefs["eaten"], "choosing a dish is not recorded as eaten")
    page.evaluate("localStorage.removeItem('babdoduk-food-preferences')")
    page.unroute("**/data/kaist-menu/latest.json")

    # Edition provenance: collected stories link out safely, desk memos say so,
    # and an older edition is not presented as today's.
    edition = {"date": "2026-01-02", "schedule": "Daily 10:00 KST",
               "featured": {"title": "F", "summary": "s", "source": "Src", "url": "https://example.org/f",
                            "medium": "blog", "category": "tips"},
               "lanes": {lane: {"lead": lane, "items": [
                   {"title": "link", "summary": "s", "source": "Src", "url": "https://example.org/a", "medium": "blog"},
                   {"title": "desk", "summary": "s", "source": "밥도둑 데스크", "url": "", "medium": "desk"},
                   {"title": "bad", "summary": "s", "source": "Src", "url": "javascript:alert(1)", "medium": "blog"}]}
                   for lane in ("tips", "trend", "health", "habit")}}
    page.route("**/data/magazine/index.json", lambda route: route.fulfill(
        json={"latest": "2026-01-02", "dates": ["2026-01-02"]}))
    page.route("**/data/magazine/2026-01-02.json", lambda route: route.fulfill(json=edition))
    page.goto("https://site-ui.invalid/mukbang.html", wait_until="networkidle")
    lane = page.locator('[data-lane-items="tips"]')
    check(lane.locator("a.mg-story").count() == 1
          and lane.locator("a.mg-story").get_attribute("rel") == "noopener", "one safe outbound story")
    check(not page.locator('a[href^="javascript"]').count(), "non-http story URLs are not linked")
    check(lane.locator(".mg-story--desk").count() == 2 and "자체 메모" in lane.locator(".mg-story--desk").first.inner_text(),
          "stories without a source link are labelled as desk notes")
    check("지난 호" in page.locator(".mg-masthead-issue").inner_text(), "past edition is labelled")
    page.unroute("**/data/magazine/index.json")
    page.unroute("**/data/magazine/2026-01-02.json")
    return count


def home_summary(page):
    """Home leads with the two food tasks and states only what the payloads support."""
    count = 0

    def check(ok, detail):
        nonlocal count
        assert ok, f"index.html summary: {detail}"
        count += 1

    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst).replace(microsecond=0)
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    later = (now + timedelta(hours=2)).isoformat()
    events = [{"id": "ok", "title": "ok", "startAt": now.isoformat(), "endAt": later, "food": {"provided": "true"}},
              {"id": "review", "title": "r", "startAt": now.isoformat(), "endAt": later,
               "food": {"provided": "true"}, "needs_review": True},
              {"id": "unknown", "title": "u", "startAt": now.isoformat(), "endAt": later, "food": {"provided": "unknown"}}]
    page.route("**/data/kaist-menu/latest.json", lambda route: route.fulfill(json={
        "date": yesterday, "restaurants": [{"id": "r1", "name": "r1", "lunch": {"items": ["밥"]}}]}))
    page.route("**/data/ggongbab/latest.json", lambda route: route.fulfill(json={
        "generatedAt": now.isoformat(), "events": events}))
    page.route("**/data/magazine/index.json", lambda route: route.fulfill(status=404, body=""))
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto("https://site-ui.invalid/index.html", wait_until="networkidle")
    actions = page.locator(".home-actions a").evaluate_all("els => els.map(el => el.getAttribute('href'))")
    check(actions == ["ggongbab.html", "mukbang.html#what"], ("primary actions", actions))
    check(page.locator(".home-actions a").first.bounding_box()["y"] < 844, "primary action in first mobile screen")
    check(page.locator('a[href="#"]').count() == 1 and page.locator("#navHome").get_attribute("href") == "#",
          "no placeholder links except back-to-top")
    check(not page.locator("#welcomePopup").count(), "no blocking welcome dialog")
    menu = page.locator("#homeMenuStatus")
    check(menu.get_attribute("data-state") == "stale" and "오늘 1곳" not in menu.inner_text(),
          ("stale cafeteria is not counted as today", menu.inner_text()))
    free = page.locator("#homeFreeStatus")
    check(free.get_attribute("data-state") == "ready" and "오늘 1개" in free.inner_text(),
          ("only public rows are counted", free.inner_text()))
    meta = free.locator("[data-home-meta]").inner_text()
    check(meta.startswith("마지막 발행") and "전체 목록은 꽁밥 탭에서" in meta
          and not any(word in meta for word in ("최신", "최근", "실시간")),
          ("snapshot is labelled by its last publication, not as fresher elsewhere", meta))
    page.locator("#langToggle").click()
    meta_en = free.locator("[data-home-meta]").inner_text()
    check(meta_en.startswith("Last published") and "full list" in meta_en
          and not any(word in meta_en.lower() for word in ("latest", "live", "real-time", "realtime")),
          ("English publication label", meta_en))
    page.locator("#langToggle").click()
    check(page.locator("#homeFeature").is_hidden(), "missing magazine edition leaves no empty card")
    for pattern in ("**/data/kaist-menu/latest.json", "**/data/ggongbab/latest.json", "**/data/magazine/index.json"):
        page.unroute(pattern)
    return count


SHELF = ["today", "pick", "map", "log"]
SHELF_HREFS = ["ggongbab.html", "mukbang.html#what", "https://naver.me/5NeqUPzI", "food.html"]
GROUPS = ["바로가기", "읽어보기", "밥도둑 소식"]
NEWS_HREFS = ["event.html#notice", "event.html#archive", "history.html"]
HOME_TOP = """() => {
  const q = s => document.querySelector(s);
  const box = el => { const r = el.getBoundingClientRect(); return {x:r.x, y:r.y, w:r.width, h:r.height, right:r.right, bottom:r.bottom}; };
  const track = q('#homeShelf'), nav = q('[data-shelf-nav]'), style = getComputedStyle(track);
  return {
    root: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    body: document.body.scrollWidth - document.body.clientWidth,
    hero: box(q('.home-hero')), title: q('.home-hero h1').textContent,
    cta: {href: q('.home-actions .btn-primary').getAttribute('href'), box: box(q('.home-actions .btn-primary'))},
    banners: [...track.querySelectorAll(':scope > li[data-banner]')].map(li => { const a = li.querySelector('a');
      return {name: li.dataset.banner, href: a.getAttribute('href'), target: a.getAttribute('target'),
              rel: a.getAttribute('rel') || '', box: box(li), title: li.querySelector('h3').textContent}; }),
    track: {box: box(track), overflow: style.overflowX, snap: style.scrollSnapType, client: track.clientWidth,
            scroll: track.scrollWidth, left: track.scrollLeft},
    navShown: !nav.hidden && getComputedStyle(nav).display !== 'none', shelf: box(q('.home-shelf')),
    collageHidden: q('.home-collage').getAttribute('aria-hidden'),
    photos: [...document.querySelectorAll('.home-collage img')].map(img => ({alt: img.getAttribute('alt'),
      loading: img.getAttribute('loading'), width: img.getAttribute('width'), height: img.getAttribute('height'),
      priority: img.getAttribute('fetchpriority')})),
    headings: [...document.querySelectorAll('main h1, main h2, main h3')].filter(h => !h.closest('[hidden]'))
      .map(h => Number(h.tagName[1])),
    states: [q('#homeMenuStatus').dataset.state, q('#homeFreeStatus').dataset.state],
    groups: [...document.querySelectorAll('main > .home-group')].map(g => ({
      title: g.querySelector('h2 [data-i18n]').textContent, purpose: (g.querySelector('.home-group-purpose') || {}).textContent || ''})),
    news: [...document.querySelectorAll('.home-news-row')].map(a => a.getAttribute('href')),
    mainText: q('main').innerText
  };
}"""


def home_hero_shelf(page):
    """One editorial hero with the dated strip, then a five-banner shelf that only moves when asked."""
    count = 0

    def check(ok, detail):
        nonlocal count
        assert ok, f"index.html hero/shelf: {detail}"
        count += 1

    def shelf_left():
        return page.evaluate("document.getElementById('homeShelf').scrollLeft")

    for width, height in SIZES:
        page.set_viewport_size({"width": width, "height": height})
        page.goto("https://site-ui.invalid/index.html", wait_until="networkidle")
        top = page.evaluate(HOME_TOP)
        where = f"{width}x{height}"
        check(top["root"] <= 0 and top["body"] <= 0, (where, "no body/root horizontal overflow", top["root"], top["body"]))
        check(top["hero"]["h"] > 0 and top["title"].startswith("KAIST에서"), (where, "hero and headline render"))
        check(top["cta"]["href"] == "ggongbab.html" and top["cta"]["box"]["bottom"] <= height,
              (where, "primary CTA inside the first screen", top["cta"]))
        names = [b["name"] for b in top["banners"]]
        check(names == SHELF and [b["href"] for b in top["banners"]] == SHELF_HREFS, (where, "banner set and order", names))
        check(all((ROOT / b["href"].split("#")[0]).is_file() for b in top["banners"] if not b["href"].startswith("https:")),
              (where, "internal banner links resolve"))
        mapped = next(b for b in top["banners"] if b["name"] == "map")
        check(mapped["target"] == "_blank" and "noopener" in mapped["rel"].split(), (where, "map opens safely", mapped))
        widths = {b["name"]: b["box"]["w"] for b in top["banners"]}
        check(min(widths["today"], widths["pick"]) > max(widths["map"], widths["log"]),
              (where, "today and pick outrank the discovery banners", widths))
        check([g["title"] for g in top["groups"]] == GROUPS and all(g["purpose"] for g in top["groups"]),
              (where, "utility, reading and news groups, each with a stated purpose", top["groups"]))
        check(top["news"] == NEWS_HREFS and all((ROOT / h.split("#")[0]).is_file() for h in top["news"]),
              (where, "news leads with notices; past activity is one link", top["news"]))
        check("지난 이벤트" not in top["mainText"] and "오늘의 한 끼" not in top["mainText"]
              and top["mainText"].count("오늘의 꽁밥") >= 2, (where, "no archive-first or stale hub labels"))
        check(top["collageHidden"] == "true" and top["photos"] and all(
            ph["alt"] == "" and ph["width"] and ph["height"] for ph in top["photos"]), (where, "decorative collage", top["photos"]))
        check(top["photos"][0]["loading"] is None and top["photos"][0]["priority"] == "high",
              (where, "above-the-fold hero photo is not lazy"))
        levels = top["headings"]
        check(levels[0] == 1 and all(b <= a + 1 for a, b in zip(levels, levels[1:])), (where, "heading order", levels))
        track = top["track"]
        check(track["overflow"] in ("auto", "scroll") and track["snap"].startswith("x"), (where, "native scroll snap", track))
        check(track["scroll"] > track["client"], (where, "the shelf continues beyond the view", track))
        peek = next(b["box"] for b in top["banners"] if b["box"]["right"] > track["box"]["right"] + 1)
        check(peek["x"] < track["box"]["right"] - 24, (where, "the next banner visibly peeks", peek, track["box"]))
        if width >= 1024:
            check(top["banners"][0]["box"]["y"] < height, (where, "shelf starts inside the first screen", top["shelf"]))
        if width >= 768:
            check(top["navShown"], (where, "desktop shelf buttons are shown"))
            prev, nxt = page.locator('[data-shelf-dir="-1"]'), page.locator('[data-shelf-dir="1"]')
            check(prev.get_attribute("aria-disabled") == "true" and nxt.get_attribute("aria-disabled") == "false",
                  (where, "bounds at the start"))
            nxt.focus()
            page.keyboard.press("Enter")
            page.wait_for_function("document.querySelector('[data-shelf-dir=\"-1\"]').getAttribute('aria-disabled') === 'false'")
            check(shelf_left() > 0, (where, "Enter on next scrolls the shelf"))
            for _ in range(8):
                if nxt.get_attribute("aria-disabled") == "true":
                    break
                page.keyboard.press("Enter")
                page.wait_for_timeout(60)
            check(nxt.get_attribute("aria-disabled") == "true" and page.evaluate("document.activeElement.dataset.shelfDir") == "1",
                  (where, "next is marked at the end and keeps focus"))
            prev.focus()
            for _ in range(8):
                if prev.get_attribute("aria-disabled") == "true":
                    break
                page.keyboard.press("Enter")
                page.wait_for_timeout(60)
            check(shelf_left() <= 1, (where, "previous returns to the start"))
        else:
            check(not top["navShown"], (where, "touch widths swipe instead of buttons"))
            shelf = page.locator("#homeShelf")
            shelf.scroll_into_view_if_needed()
            box = shelf.bounding_box()
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            page.mouse.wheel(320, 0)
            page.wait_for_function("document.getElementById('homeShelf').scrollLeft > 0", timeout=3000)
            check(shelf_left() > 0, (where, "native horizontal scroll moves the shelf"))
            page.evaluate("document.getElementById('homeShelf').scrollLeft = 0")
        page.wait_for_timeout(1200)
        check(shelf_left() <= 1 and page.evaluate(
            "document.getAnimations().filter(a => a.effect && document.getElementById('homeShelf').contains(a.effect.target)).length") == 0,
            (where, "nothing moves on its own"))
        page.locator("#langToggle").click()
        english = page.evaluate(HOME_TOP)
        check(english["title"].startswith("What should") and english["banners"][0]["title"] == "Today's free food"
              and [g["title"] for g in english["groups"]] == ["Shortcuts", "Read", "Babdoduk news"]
              and english["root"] <= 0 and english["body"] <= 0, (where, "English fits", english["root"], english["body"]))
        page.locator("#langToggle").click()

    # Reduced motion (this context) removes the hover lift.
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto("https://site-ui.invalid/index.html", wait_until="networkidle")
    link = page.locator(".home-banner-link").first
    link.hover()
    motion = link.evaluate("el => [getComputedStyle(el).transform, getComputedStyle(el).transitionDuration]")
    check(motion == ["none", "0s"], ("reduced motion keeps banners still", motion))

    # Menu published today and no free food: the strip says so; the hero keeps its shape.
    today = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
    page.route("**/data/kaist-menu/latest.json", lambda route: route.fulfill(json={
        "date": today, "restaurants": [{"id": "r1", "name": "r1", "lunch": {"items": ["밥"]}}]}))
    page.route("**/data/ggongbab/latest.json", lambda route: route.fulfill(json={
        "generatedAt": datetime.now(timezone(timedelta(hours=9))).isoformat(), "events": []}))
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto("https://site-ui.invalid/index.html", wait_until="networkidle")
    top = page.evaluate(HOME_TOP)
    check(top["states"] == ["ready", "empty"] and "오늘 1곳" in page.locator("#homeMenuStatus").inner_text()
          and "예정된 꽁밥이 아직 없어요" in page.locator("#homeFreeStatus").inner_text(), ("menu ready, free empty", top["states"]))
    check(top["hero"]["h"] > 0 and [b["name"] for b in top["banners"]] == SHELF and top["root"] <= 0,
          "hero and shelf keep their shape")
    page.unroute("**/data/kaist-menu/latest.json")
    page.unroute("**/data/ggongbab/latest.json")
    return count


def event_bands(page):
    """Dates decide now / coming up / past; confirmation is reported separately."""
    count = 0

    def check(ok, detail):
        nonlocal count
        assert ok, f"event.html: {detail}"
        count += 1

    today = datetime.now(timezone(timedelta(hours=9))).date()
    labels = {"now": "진행 중", "upcoming": "예정", "past": "지난 일정"}

    def expected(start, end):
        return "upcoming" if today.isoformat() < start else "past" if today.isoformat() > end else "now"

    page.set_viewport_size({"width": 390, "height": 844})
    page.goto("https://site-ui.invalid/event.html", wait_until="networkidle")
    rows = page.locator(".event-tab-row").evaluate_all("""rows => rows.map(r => ({start:r.dataset.start,
      end:r.dataset.end, band:r.dataset.band, conf:r.dataset.confirmation,
      chip:r.querySelector('[data-event-state]').textContent, title:r.querySelector('.event-tab-title').textContent}))""")
    for row in rows:
        check(row["band"] == expected(row["start"], row["end"]), ("band from dates", row))
        check(row["chip"].startswith(labels[row["band"]]), ("band label", row))
        check("(예정)" not in row["title"], ("tentative state is a status, not a title suffix", row))
        if row["band"] == "past" and row["conf"] in ("announced", "tentative"):
            check("기록 없음" in row["chip"] or "미확인" in row["chip"], ("past date is not reported as held", row))
    live = sum(row["band"] != "past" for row in rows)
    check(page.locator("#eventEmpty").is_visible() == (live == 0), "empty notice only when nothing is current")
    order = page.evaluate("""() => [...document.querySelectorAll('main h1, main h2')].map(h => h.id || h.tagName)""")
    check(order == ["H1", "eventNoticeTitle", "eventUpcomingTitle", "eventListTitle"], ("notices, upcoming, then record", order))
    check(page.locator("#eventNoticeEmpty").is_visible() and page.locator("#eventNotices li").count() == 0,
          "no invented notices: the empty notice state is shown")
    check(page.locator("#eventUpcoming li").count() == live
          and page.locator("#eventListTitle").inner_text() == ("활동 기록" if live else "지난 활동 기록"),
          "upcoming summary and record heading follow the dates")
    page.locator("#eventTab0").focus()
    page.keyboard.press("ArrowDown")
    check(page.evaluate("document.activeElement.id") == "eventTab1"
          and page.locator("#eventPanel1").is_visible(), "arrow keys move between events")

    # A synthetic upcoming, unconfirmed row: shown as coming up, opened first.
    start, end = (today + timedelta(days=3)).isoformat(), (today + timedelta(days=4)).isoformat()
    source = (ROOT / "event.html").read_text(encoding="utf-8").replace(
        'data-start="2026-05-19" data-end="2026-05-20"', f'data-start="{start}" data-end="{end}"', 1)
    page.route("**/event.html", lambda route: route.fulfill(content_type="text/html", body=source))
    page.goto("https://site-ui.invalid/event.html", wait_until="networkidle")
    chip = page.locator("#eventTab1 [data-event-state]").inner_text()
    check(chip.startswith("예정") and "미확정" in chip, ("upcoming tentative row", chip))
    check(page.locator("#eventEmpty").is_hidden(), "empty notice hidden when something is scheduled")
    check(page.locator("#eventTab1").get_attribute("aria-selected") == "true", "first scheduled event opens")
    upcoming = page.locator("#eventUpcoming .event-upcoming-item")
    check(upcoming.count() == 1 and "카빙" in upcoming.inner_text() and page.locator("#eventListTitle").inner_text() == "활동 기록",
          ("the scheduled row is summarised at the top", upcoming.count()))
    page.locator("#eventTab0").click()
    upcoming.focus()
    page.keyboard.press("Enter")
    check(page.evaluate("document.activeElement.id") == "eventTab1"
          and page.locator("#eventPanel1").is_visible(), "the summary opens its record")
    page.unroute("**/event.html")
    return count


def food_provenance(page):
    """Published and browser-saved food log entries are labelled; storage keeps its shape."""
    count = 0

    def check(ok, detail):
        nonlocal count
        assert ok, f"food.html: {detail}"
        count += 1

    shared = {"currency": "KRW", "entries": [{"date": "2026-05-10", "total": 1000, "items": []},
                                             {"date": "2026-05-11", "total": 2000, "items": []}]}
    local = [{"date": "2026-05-11", "total": 3000, "items": []}, {"date": "2026-05-12", "total": 4000, "items": []}]
    page.route("**/data/food-log.json", lambda route: route.fulfill(json=shared))
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto("https://site-ui.invalid/food.html", wait_until="networkidle")
    page.evaluate("list => localStorage.setItem('babdoduk-food-local', JSON.stringify(list))", local)
    saved = page.evaluate("localStorage.getItem('babdoduk-food-local')")
    page.reload(wait_until="networkidle")
    check(page.locator("main h1").count() == 1, "main landmark with one page heading")
    cells = page.locator(".food-cal-cell.has-data").evaluate_all(
        "els => els.map(el => ({local: el.classList.contains('is-local'), label: el.getAttribute('aria-label')}))")
    check([c["local"] for c in cells] == [False, True, True], ("browser entries are marked", cells))
    check("공개 기록" in cells[0]["label"] and "대신" in cells[1]["label"], ("source named in labels", cells))
    check("공개 기록 1일" in page.locator("#foodSourceLegend").inner_text()
          and "이 브라우저 2일" in page.locator("#foodSourceLegend").inner_text(), "legend counts each source")
    check(page.evaluate("localStorage.getItem('babdoduk-food-local')").find("_source") < 0,
          "provenance tags are not written to storage")
    check(page.evaluate("localStorage.getItem('babdoduk-food-local')") == saved,
          "existing browser records are byte-for-byte unchanged")
    labels = page.locator("#foodInputBody select, #foodInputBody input").evaluate_all(
        "els => els.map(el => el.getAttribute('aria-label'))")
    check(labels and all(labels), ("every input row control is named", labels))
    page.evaluate("localStorage.removeItem('babdoduk-food-local')")
    page.unroute("**/data/food-log.json")
    return count


STRUCTURE = r"""() => {
  const issues = [];
  const visible = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0
    && getComputedStyle(el).visibility !== 'hidden' && !el.closest('[hidden]'); };
  const named = el => {
    const by = (el.getAttribute('aria-labelledby') || '').split(' ').map(id => (document.getElementById(id) || {}).textContent || '').join(' ');
    const label = el.labels && el.labels[0] ? el.labels[0].textContent : '';
    return (el.getAttribute('aria-label') || by || label || el.textContent || el.getAttribute('title') || '').trim();
  };
  if (document.querySelectorAll('h1').length !== 1) issues.push('h1 count');
  if (document.querySelectorAll('main').length !== 1) issues.push('main count');
  document.querySelectorAll('img:not([alt])').forEach(img => issues.push('img alt ' + img.getAttribute('src')));
  document.querySelectorAll('button, a[href], select, input, textarea, [role=tab]').forEach(el => {
    if (!visible(el)) return;
    if (!named(el)) issues.push('unnamed ' + el.tagName + '#' + el.id + '.' + el.className);
    const r = el.getBoundingClientRect();
    if (el.matches('button, [role=tab], select, input') && (r.width < 24 || r.height < 24))
      issues.push('target ' + el.tagName + '.' + el.className);
  });
  const ids = {};
  document.querySelectorAll('[id]').forEach(el => { ids[el.id] = (ids[el.id] || 0) + 1; });
  Object.keys(ids).forEach(id => { if (ids[id] > 1) issues.push('duplicate id ' + id); });
  document.querySelectorAll('a[target=_blank]').forEach(a => { if (!/noopener/.test(a.rel)) issues.push('noopener ' + a.href); });
  return issues;
}"""


def history_archive(page):
    """Every timeline entry sits on the same plate, in one accent, with honest image sizes."""
    count = 0

    def check(ok, detail):
        nonlocal count
        assert ok, f"history.html: {detail}"
        count += 1

    for width, height in ((1440, 900), (390, 844)):
        page.set_viewport_size({"width": width, "height": height})
        page.goto("https://site-ui.invalid/history.html", wait_until="networkidle")
        plates = page.locator(".timeline-item").evaluate_all("""items => items.map(item => {
          const plate = item.querySelector('.timeline-item-media'), s = plate && getComputedStyle(plate), r = plate && plate.getBoundingClientRect();
          const img = item.querySelector('img');
          return plate ? {w: Math.round(r.width), h: Math.round(r.height), radius: s.borderRadius, inline: item.getAttribute('style'),
            accent: getComputedStyle(item.querySelector('.timeline-year')).color, shadow: s.boxShadow,
            img: img ? [img.naturalWidth, img.naturalHeight, +img.getAttribute('width'), +img.getAttribute('height'), img.complete] : null} : null;
        })""")
        check(plates and all(plates), ("every entry has a plate", plates))
        check(len({(p["w"], p["h"], p["radius"]) for p in plates}) == 1 and plates[0]["w"] == plates[0]["h"],
              ("one square plate size and radius", plates))
        check(len({p["accent"] for p in plates}) == 1 and not any(p["inline"] for p in plates)
              and all(p["shadow"] == "none" for p in plates), ("one accent, no per-entry colour or shadow", plates))
        check(all(p["img"] is None or (p["img"][4] and p["img"][:2] == p["img"][2:4]) for p in plates),
              ("images load and declare their real size", [p["img"] for p in plates]))
    return count


def structure_and_failures(page):
    """Landmarks, names and target sizes in both languages; honest states when data is unavailable."""
    count = 0

    def check(ok, detail):
        nonlocal count
        assert ok, detail
        count += 1

    page.set_viewport_size({"width": 1440, "height": 900})
    for name in public_pages():
        for lang in ("ko", "en"):
            page.goto("https://site-ui.invalid/" + name, wait_until="networkidle")
            page.evaluate("lang => localStorage.setItem('babdoduk-lang', lang)", lang)
            page.reload(wait_until="networkidle")
            issues = page.evaluate(STRUCTURE)
            check(not issues, (name, lang, issues))
    page.evaluate("localStorage.setItem('babdoduk-lang', 'ko')")

    page.route("**/data/**", lambda route: route.fulfill(status=503, body=""))
    page.goto("https://site-ui.invalid/index.html", wait_until="networkidle")
    check(page.locator("#homeMenuStatus").get_attribute("data-state") == "error"
          and page.locator("#homeFreeStatus").get_attribute("data-state") == "error", "home names unavailable data")
    check(page.locator(".home-hero h1").is_visible() and page.locator(".home-actions .btn-primary").is_visible()
          and page.locator("#homeShelf > li[data-banner]").count() == 4, "hero and shelf survive missing data")
    check(page.locator("#homeFeature").is_hidden() and page.locator(".home-desks a").count() == 4
          and page.locator(".home-read .explore-card").is_visible() and page.locator(".home-news-row").count() == 3,
          "reading and news groups keep their links, with no invented edition")
    page.goto("https://site-ui.invalid/ggongbab.html", wait_until="networkidle")
    page.locator("#foodHubFree .gg-state").first.wait_for()
    counts = page.locator(".gg-counts").inner_text()
    check("확인 중" not in counts and "실패" in counts, ("hub counts report failure, not loading", counts))
    page.goto("https://site-ui.invalid/mukbang.html", wait_until="networkidle")
    check(page.locator("#mgEditionStatus").is_visible(), "magazine says the edition did not load")
    text = page.locator("main").inner_text()
    check("min read" not in text and "ISSUE 01" not in text and "2026.09.12" not in text,
          "fallback desk notes carry no invented edition metadata")
    page.unroute("**/data/**")
    return count


def run_checks(screenshots=False):
    report = {"pages": public_pages(), "sizes": SIZES, "results": {}, "checks": 0}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True,
            ignore_default_args=["--hide-scrollbars"],
            args=["--disable-features=OverlayScrollbar,FluentOverlayScrollbar"])
        context = browser.new_context(timezone_id="Asia/Seoul", reduced_motion="reduce", service_workers="block")
        context.route("**/*", offline_route)
        api_attempts = []
        context.on("request", lambda req: api_attempts.append(req.url)
                   if req.resource_type in ("fetch", "xhr", "eventsource")
                   and urlparse(req.url).hostname != "site-ui.invalid" else None)
        context.add_init_script("sessionStorage.setItem('babdoduk-welcome-seen','1');")
        page = context.new_page()
        # WebSockets bypass routing and emit no request event; record every attempt.
        page.on("websocket", lambda ws: api_attempts.append(ws.url))
        for size in SIZES:
            for name in report["pages"]:
                result = inspect_page(page, name, size, ROOT / ".local/site-ui-shots" if screenshots else None)
                report["results"][f"{name}:{size[0]}x{size[1]}"] = result
                report["checks"] += result["checks"]
        report["checks"] += magazine_tools(page)
        report["checks"] += home_summary(page)
        report["checks"] += home_hero_shelf(page)
        report["checks"] += event_bands(page)
        report["checks"] += history_archive(page)
        report["checks"] += food_provenance(page)
        report["checks"] += structure_and_failures(page)
        # High contrast must defer to the system; custom colors/widths must not
        # leak from either the standards or WebKit rule sets.
        page.emulate_media(forced_colors="active")
        check = page.evaluate(MEASURE)
        assert check["scrollbarColor"] == "auto"
        assert check["width"] == "auto"
        report["checks"] += 2
        assert not api_attempts, ("static pages attempted a live API request", api_attempts[:5])
        report["checks"] += 1
        browser.close()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--screenshots", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run_checks(args.screenshots), ensure_ascii=False, indent=2))
