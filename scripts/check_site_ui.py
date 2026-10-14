"""Offline public-page overflow and visible Windows Chromium scrollbar checks."""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import parse_qs, unquote, urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SIZES = [(1920, 1080), (1440, 900), (768, 1024), (390, 844), (360, 800)]
# The browser the checks drive: the installed Chrome locally (Windows classic scrollbars), or the
# Chromium bundled with the pinned Playwright container in CI (BABDODUK_BROWSER=chromium).
BROWSER = os.environ.get("BABDODUK_BROWSER", "chrome")
IN_CI = os.environ.get("CI") == "true" or os.environ.get("GITHUB_ACTIONS") == "true"


def launch(pw):
    return pw.chromium.launch(channel=None if BROWSER == "chromium" else BROWSER, headless=True,
                              ignore_default_args=["--hide-scrollbars"],
                              args=["--disable-features=OverlayScrollbar,FluentOverlayScrollbar"])


def new_context(browser):
    context = browser.new_context(timezone_id="Asia/Seoul", reduced_motion="reduce", service_workers="block")
    context.route("**/*", offline_route)
    context.add_init_script("sessionStorage.setItem('babdoduk-welcome-seen','1');")
    return context
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


SITE_HOST = "site-ui.invalid"
# Hosts the launch gate tells apart (js/worldcup-gate.js): production, lab and localhost are served from
# the same files here, so a check can load a page "as" each; every other host is refused.
GATE_HOSTS = {"babdoduk.vercel.app": "production", "babdoduk-lab.vercel.app": "lab", "localhost": "localhost"}
SERVED_HOSTS = {SITE_HOST, *GATE_HOSTS}


def offline_route(route):
    url = urlparse(route.request.url)
    path = unquote(url.path).lstrip("/")
    if url.hostname not in SERVED_HOSTS:
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
    check(direct.count() == 3, "three direct destinations in navigation")
    check([direct.nth(i).get_attribute("href") for i in range(3)] == ["ggongbab.html", "mukbang.html", "event.html"],
          "today's food, the magazine (which carries the picker) and the news are the direct destinations "
          "(owner, 2026-10-13: news left the More menu)")
    check(not page.locator('.site-nav a[href="mukbang.html#what"], .site-nav a[href="choose.html"]').count(),
          "the picker is not presented as a separate product in navigation")
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
          and direct.nth(1).inner_text() == "밥도둑 매거진", "Korean primary labels")
    page.locator("#langToggle").click()
    english = [direct.nth(i).inner_text() for i in range(2)]
    check(english == ["Today's free food", "Magazine"], ("English primary labels", english,
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
    """One picker: mukbang.html#what (synthetic data, phone width); choose.html only redirects there.
    Magazine provenance: only source-backed stories render, never desk filler."""
    count = 0

    def check(ok, detail):
        nonlocal count
        assert ok, f"mukbang.html#what / magazine: {detail}"
        count += 1

    yesterday = (datetime.now(timezone(timedelta(hours=9))) - timedelta(days=1)).strftime("%Y-%m-%d")
    today = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
    menu = {"date": yesterday, "restaurants": [{"id": "r1", "name": "<b>식당</b>",
            "breakfast": {"items": []}, "lunch": {"items": ["<img src=x onerror=alert(1)>"], "price": "5,000원"},
            "dinner": {"items": ["저녁"]}}]}
    page.route("**/data/kaist-menu/latest.json", lambda route: route.fulfill(json=menu))
    page.route("**/data/kaist-menu/week.json", lambda route: route.fulfill(json={
        "days": [{"date": today, "available": False, "status": "NOT_PUBLISHED_YET"}]}))
    page.route(f"**/data/kaist-menu/{today}.json", lambda route: route.fulfill(status=404, body=""))
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto("https://site-ui.invalid/mukbang.html#what", wait_until="networkidle")
    page.evaluate("localStorage.removeItem('babdoduk-food-preferences')")
    page.reload(wait_until="networkidle")
    tools = page.locator("#kaistToday")
    title = page.locator("#kaistTitle").inner_text()
    check("오늘" not in title and tools.locator(".kaist-date.is-stale").count() == 1,
          ("stale cafeteria data is labelled, not titled today", title))
    check(tools.locator("img").count() == 0 and tools.locator("b").count() == 0, "generated menu text is escaped")
    check(tools.locator("[role=tablist]").count() == 0 and tools.locator(".kaist-meal[aria-pressed]").count() == 3,
          "meal and restaurant controls are pressed toggles, not partial tabs")
    check(tools.locator(".kaist-to-hub").get_attribute("href") == "ggongbab.html#menu"
          and not tools.locator(".kaist-to-slot").count(), "summary links to the hub; the picker is on this page")
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
    page.unroute("**/data/kaist-menu/week.json")
    page.unroute(f"**/data/kaist-menu/{today}.json")

    # One picker product: it lives at mukbang.html#what; choose.html is only a compatibility redirect.
    page.goto("https://site-ui.invalid/mukbang.html", wait_until="networkidle")
    check(page.locator("#what #eatApp").count() == 1 and page.locator("#eatApp").count() == 1,
          "exactly one picker, inside the magazine at #what")
    page.goto("https://site-ui.invalid/choose.html", wait_until="networkidle")
    page.wait_for_function("location.pathname.endsWith('/mukbang.html') && location.hash === '#what'", timeout=10000)
    page.locator("#eatApp").wait_for()
    landed = urlparse(page.url)          # the magazine adds ?d=<edition> itself
    check(landed.path.endswith("/mukbang.html") and landed.fragment == "what" and page.locator("#eatApp").count() == 1,
          ("choose.html redirects to the one picker", page.url))

    # Edition provenance: only source-backed stories render (a desk item or a non-http URL is
    # dropped, never shown as a note), an empty lane says so, and an older edition is labelled.
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
    check(not page.locator(".mg-story--desk").count() and "밥도둑 데스크" not in page.inner_text("main"),
          "desk filler is never rendered")
    check("밥도둑 데스크" not in page.content() and "계란후라이 하나도" not in page.content(),
          "no fabricated default story in the page itself")
    check("지난 호" in page.locator(".mg-masthead-issue").inner_text(), "past edition is labelled")
    page.unroute("**/data/magazine/index.json")
    page.unroute("**/data/magazine/2026-01-02.json")
    return count


PNG_1PX = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
                        "0000000d49444154789c6360f8cfc0f01f0005000101d9b3c6600000000049454e44ae426082")


def magazine_edition_time(page):
    """The masthead says when an edition was actually built (its generatedAt, KST), never a fixed
    schedule: the scheduled run starts hours late. Until today's edition lands, yesterday's newest
    edition is the latest one, not a past one; an older edition is a past one. Fixed page clock
    in its own context, so it cannot leak into the other checks. Text as set, before the
    masthead's CSS capitals."""
    count = 0

    def check(ok, detail):
        nonlocal count
        assert ok, f"mukbang.html edition time: {detail}"
        count += 1

    lanes = ("tips", "trend", "health", "habit")
    editions = {day: {"date": day, "generatedAt": f"{day}T15:36:00+09:00", "schedule": "Daily 10:00 KST",
                      "featured": None, "lanes": {lane: {"lead": lane, "items": []} for lane in lanes}}
                for day in ("2026-01-01", "2026-01-02")}
    context = new_context(page.context.browser)
    try:
        context.clock.set_fixed_time("2026-01-03T09:00:00+09:00")      # the morning before 01-03 runs
        view = context.new_page()
        view.route("**/data/magazine/index.json", lambda route: route.fulfill(
            json={"latest": "2026-01-02", "dates": ["2026-01-01", "2026-01-02"]}))
        view.route("**/data/magazine/2026-01-0*.json", lambda route: route.fulfill(
            json=editions[urlparse(route.request.url).path.rsplit("/", 1)[-1][:-len(".json")]]))
        view.goto("https://site-ui.invalid/mukbang.html", wait_until="networkidle")
        issue = view.locator(".mg-masthead-issue").text_content().strip()
        check(issue == "2026.01.02 · 최신 호", ("yesterday's newest edition is the latest one", issue))
        stamps = [view.locator(sel).text_content().strip() for sel in ("#mgSchedule", "#mgBoardWeek")]
        check(stamps == ["15:36 발행", "2026.01.02 · 15:36 발행"], ("the edition's own build time", stamps))
        claims = view.locator(".mg-method, #mgSchedule, #mgBoardWeek, .mg-masthead-issue").all_text_contents()
        check(not any("10:00" in text for text in claims), ("no fixed schedule is claimed", claims))
        view.locator("#langToggle").click()
        # The magazine redraws its masthead in a task after the switch (mukbang.html's setTimeout), so
        # wait for the redraw, up to 5 s, before reading; a masthead that never changes still fails below.
        try:
            view.wait_for_function("() => document.documentElement.lang === 'en' && !/[가-힣]/.test("
                                   "document.querySelector('.mg-masthead-issue').textContent)", timeout=5000)
        except PlaywrightTimeoutError:
            pass
        issue_en = view.locator(".mg-masthead-issue").text_content().strip()
        check(issue_en == "2026.01.02 · Latest edition" and
              view.locator("#mgSchedule").text_content().strip() == "Published 15:36 KST", ("English", issue_en))
        view.locator("#langToggle").click()
        view.goto("https://site-ui.invalid/mukbang.html?d=2026-01-01", wait_until="networkidle")
        past = view.locator(".mg-masthead-issue").text_content().strip()
        check(past == "2026.01.01 · 지난 호", ("an older edition is a past one", past))
    finally:
        context.close()
    return count


def release_contracts(page):
    """Product roles that changed: choose.html only redirects, food.html is lab-only (noindex,
    nofollow, reachable from lab.html, linked from no public page in either language), and the
    event that did not happen appears nowhere."""
    count = 0

    def check(ok, detail):
        nonlocal count
        assert ok, f"release contracts: {detail}"
        count += 1

    choose = (ROOT / "choose.html").read_text(encoding="utf-8")
    check('name="robots" content="noindex"' in choose and "mukbang.html#what" in choose
          and 'id="eatApp"' not in choose and "food-picker.js" not in choose,
          "choose.html is a noindex redirect with no picker of its own")
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto("https://site-ui.invalid/food.html", wait_until="networkidle")
    robots = page.locator('meta[name="robots"]').get_attribute("content") or ""
    check("noindex" in robots and "nofollow" in robots, ("food.html is noindex, nofollow", robots))
    check(page.locator("#foodSourceLegend").count() == 1, "the Food Log implementation is kept")
    page.goto("https://site-ui.invalid/lab.html", wait_until="networkidle")
    check(page.locator('main a[href="food.html"]').count() == 1, "the lab links the Food Log (lab-only access)")
    for lang in ("ko", "en"):
        for name in GUARD_PAGES + ["choose.html"]:
            page.goto("https://site-ui.invalid/index.html", wait_until="domcontentloaded")
            page.evaluate("lang => localStorage.setItem('babdoduk-lang', lang)", lang)
            page.goto("https://site-ui.invalid/" + name, wait_until="networkidle")
            links = page.locator('a[href="food.html"], a[href$="/food.html"]').count()
            check(links == 0, (f"{name} {lang}: no public link to the Food Log", links))
            if name == "event.html":
                check("STROKE" not in page.content() and "Unbelievable" not in page.content(),
                      (f"{name} {lang}: no trace of the event that did not happen"))
    page.evaluate("localStorage.setItem('babdoduk-lang', 'ko')")
    return count


def magazine_sparse(page):
    """Sparse editions look intentional: an empty lane says so quietly, a hero without its own
    image is text-only (no BABDODUK placeholder), no featured story hides the hero, no filler.
    The hero label says what the hero is: 오늘의 추천 글 unless it is a qualified trend with
    evidence, and trend stories list their evidence kinds."""
    count = 0

    def check(ok, detail):
        nonlocal count
        assert ok, f"mukbang.html sparse: {detail}"
        count += 1

    lanes = ("tips", "trend", "health", "habit")

    def story(n, lane):
        return {"title": f"{lane} story {n}", "summary": "원문에서 가져온 짧은 발췌입니다.", "source": "Real Source",
                "url": f"https://example.org/{lane}/{n}", "medium": "blog"}

    featured_img = dict(story(0, "tips"), category="tips", image="https://img.example.invalid/f.png",
                        imageSource="feed_media")
    featured_text = dict(story(0, "tips"), category="tips")
    evidence = ["explicit_source_claim", "corroborated"]
    featured_trend = dict(story(0, "trend"), category="trend", heroKind="trend", trendEvidence=evidence,
                          image="https://img.example.invalid/t.png", imageSource="source_page_og", medium="news")
    featured_claim = dict(story(0, "trend"), category="trend", heroKind="trend", medium="news",
                          image="https://img.example.invalid/c.png", imageSource="source_page_og")   # no evidence
    fixtures = [
        ("trend hero", featured_trend, {"tips": [story(1, "tips")], "trend": [dict(story(1, "trend"), trendEvidence=evidence)],
                                        "health": [], "habit": [dict(story(1, "habit"), medium="research")]}),
        ("trend claim without evidence", featured_claim, {lane: [story(1, lane)] for lane in lanes}),
        ("four lanes", featured_img, {lane: [story(1, lane)] for lane in lanes}),
        ("two lanes", featured_img, {"tips": [story(1, "tips"), story(2, "tips")], "trend": [story(1, "trend")],
                                     "health": [], "habit": []}),
        ("one lane empty", featured_text, {"tips": [story(1, "tips")], "trend": [story(1, "trend")],
                                           "health": [story(1, "health")], "habit": []}),
        ("all empty", None, {lane: [] for lane in lanes}),
    ]
    page.route("https://img.example.invalid/**", lambda route: route.fulfill(body=PNG_1PX, content_type="image/png"))
    page.route("**/data/magazine/index.json", lambda route: route.fulfill(
        json={"latest": "2026-01-03", "dates": ["2026-01-03"]}))
    for label, featured, items in fixtures:
        edition = {"date": "2026-01-03", "schedule": "Daily 10:00 KST", "featured": featured,
                   "lanes": {lane: {"lead": lane, "items": items[lane]} for lane in lanes}}
        def serve(payload):
            return lambda route: route.fulfill(json=payload)   # Playwright passes (route, request)
        page.route("**/data/magazine/2026-01-03.json", serve(edition))
        for width, height in ((390, 844), (1440, 900)):
            page.set_viewport_size({"width": width, "height": height})
            page.goto("https://site-ui.invalid/mukbang.html", wait_until="networkidle")
            where = f"{label} {width}"
            empty = sum(1 for lane in lanes if not items[lane])
            check(page.locator(".mg-lane-empty").count() == empty, (where, "one quiet note per empty lane"))
            check(page.locator("a.mg-story").count() == sum(len(v) for v in items.values()), (where, "no filler stories"))
            main = page.inner_text("main")
            check("밥도둑 데스크" not in main and "BABDODUK" not in page.locator("#featured").inner_text(),
                  (where, "no desk filler and no placeholder word"))
            hero_hidden = page.locator("#featured").is_hidden()
            check(hero_hidden == (featured is None), (where, "the hero exists only for a real featured story"))
            if featured is not None:
                qualified = featured.get("heroKind") == "trend" and featured.get("trendEvidence")
                label = page.inner_text("#mgHeroLabel").strip()
                check(label == ("지금 뜨는 먹거리" if qualified else "오늘의 추천 글"), (where, "hero label", label))
                tags = page.inner_text("#mgHeroTags").strip()
                check(("유행 근거" in tags and "여러 매체가 다룸" in tags) if qualified else tags == "",
                      (where, "a trend hero lists its evidence; any other hero lists none"))
                cards = page.locator('[data-lane-items="trend"] .mg-story-tags')
                check(cards.count() == sum(1 for s in items["trend"] if s.get("trendEvidence")),
                      (where, "trend cards show their evidence"))
                visual = page.locator("#mgHeroVisual")
                if featured.get("image"):
                    page.wait_for_function("document.getElementById('mgHeroVisual').classList.contains('has-photo')")
                    check(visual.is_visible(), (where, "the story's own image is shown"))
                else:
                    check(visual.is_hidden() and "mg-hero--text" in (page.locator("#featured").get_attribute("class") or ""),
                          (where, "no image: a quiet text-only hero"))
            check(page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth"),
                  (where, "no page-level horizontal overflow"))
        page.unroute("**/data/magazine/2026-01-03.json")
    page.unroute("**/data/magazine/index.json")
    page.unroute("https://img.example.invalid/**")
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
    today = now.strftime("%Y-%m-%d")
    later = (now + timedelta(hours=2)).isoformat()
    events = [{"id": "ok", "title": "ok", "startAt": now.isoformat(), "endAt": later, "food": {"provided": "true"}},
              {"id": "review", "title": "r", "startAt": now.isoformat(), "endAt": later,
               "food": {"provided": "true"}, "needs_review": True},
              {"id": "unknown", "title": "u", "startAt": now.isoformat(), "endAt": later, "food": {"provided": "unknown"}}]
    page.route("**/data/kaist-menu/latest.json", lambda route: route.fulfill(json={
        "date": yesterday, "restaurants": [{"id": "r1", "name": "r1", "lunch": {"items": ["밥"]}}]}))
    page.route("**/data/kaist-menu/week.json", lambda route: route.fulfill(json={
        "weekStart": "2026-09-28", "days": [{"date": today, "available": False, "status": "NOT_PUBLISHED_YET"}]}))
    page.route(f"**/data/kaist-menu/{today}.json", lambda route: route.fulfill(status=404, body=""))
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
    head = page.locator("#homeCalToday").inner_text().strip()
    kst_label = f"{now.month}월 {now.day}일 ({'월화수목금토일'[now.weekday()]})"
    check(head == kst_label and "요일" not in head and "기준" not in head,
          ("the calendar names today's KST date, briefly", head, kst_label))
    check(page.locator(".home-today-note, #homeStamp").count() == 0
          and "공개 조건을 통과" not in page.locator("main").inner_text()
          and "지금 확인된 정보" not in page.locator("main").inner_text(),
          "the public-condition strip and explanatory header are gone")
    check(page.locator(".home-photo-tag, .home-collage-note").count() == 0
          and "오늘 학식 메뉴가 아니에요" not in page.content(),
          "collage has no numbered dish labels or disclaimer")
    choice = page.evaluate("""() => {
      const M = window.BabdodukKaistMenu;
      const saved = {date:'2026-09-29', restaurants:[{id:'a'}]};
      const dated = {date:'2026-09-30', restaurants:[{id:'b'}]};
      const open = {days:[{date:'2026-09-30', available:true}]};
      const closed = {days:[{date:'2026-09-30', available:false}]};
      return {
        night: M.resolveTodayChoice(saved, open, dated, '2026-09-29').use,
        morning: M.resolveTodayChoice(saved, open, dated, '2026-09-30').use,
        absent: M.resolveTodayChoice(saved, closed, dated, '2026-09-30').use,
        nofile: M.resolveTodayChoice(saved, open, null, '2026-09-30').use
      };
    }""")
    check(choice == {"night": "latest", "morning": "dated", "absent": "stale", "nofile": "stale"},
          ("23:59 uses latest; 00:01 uses today's file only when it exists", choice))
    colors = page.evaluate("""() => {
      const color = sel => getComputedStyle(document.querySelector(sel)).color;
      return {copy: color('.footer-apple-copy'), mail: color('.footer-apple-email-plain'),
              contact: color('.footer-apple-email-plain [data-i18n="footer.contact"]')};
    }""")
    check(colors["copy"] == colors["mail"] == colors["contact"], ("footer contact matches copyright", colors))
    page.set_viewport_size({"width": 1440, "height": 900})
    wide = page.evaluate("""() => {
      const color = sel => getComputedStyle(document.querySelector(sel)).color;
      return color('.footer-apple-copy') === color('.footer-apple-email-plain');
    }""")
    check(wide, "footer contact matches copyright at 1440")
    page.set_viewport_size({"width": 390, "height": 844})
    free = page.locator("#homeCal")
    answer = page.locator("#homeCalAnswer").inner_text()
    check(free.get_attribute("data-state") == "ready" and answer.startswith("오늘 1개"),
          ("only public rows are counted", answer))
    meta = page.locator("#homeCalPublished").inner_text()
    check(meta.startswith("마지막 변경")
          and not any(word in meta for word in ("최신", "최근", "실시간")),
          ("snapshot is labelled by its last change, not as fresher elsewhere", meta))
    page.locator("#langToggle").click()
    meta_en = page.locator("#homeCalPublished").inner_text()
    check(meta_en.startswith("Last changed")
          and not any(word in meta_en.lower() for word in ("latest", "live", "real-time", "realtime")),
          ("English last-change label", meta_en))
    check(re.fullmatch(r"[A-Z][a-z]{2} \d{1,2} \([A-Z][a-z]{2}\)", page.locator("#homeCalToday").inner_text().strip()) is not None,
          ("English calendar date is month, day and weekday", page.locator("#homeCalToday").inner_text()))
    en_colors = page.evaluate("""() => {
      const color = sel => getComputedStyle(document.querySelector(sel)).color;
      return color('.footer-apple-copy') === color('.footer-apple-email-plain');
    }""")
    check(en_colors, "English footer contact matches copyright")
    page.locator("#langToggle").click()
    check(page.locator("#homeFeature").is_hidden(), "missing magazine edition leaves no empty card")
    page.unroute("**/data/kaist-menu/week.json")
    page.unroute(f"**/data/kaist-menu/{today}.json")
    page.unroute("**/data/kaist-menu/latest.json")
    page.route("**/data/kaist-menu/latest.json", lambda route: route.fulfill(json={
        "date": yesterday, "restaurants": [{"id": "old", "name": "old", "lunch": {"items": ["어제밥"]}}]}))
    page.route("**/data/kaist-menu/week.json", lambda route: route.fulfill(json={
        "weekStart": "2026-09-28", "days": [{"date": today, "available": True, "status": "AVAILABLE", "restaurantCount": 1}]}))
    page.route(f"**/data/kaist-menu/{today}.json", lambda route: route.fulfill(json={
        "date": today, "restaurants": [{"id": "r1", "name": "r1", "lunch": {"items": ["오늘확인된학식"]}}]}))
    page.goto("https://site-ui.invalid/index.html", wait_until="networkidle")
    ready = page.locator("#homeMenuStatus")
    check(ready.get_attribute("data-state") == "ready" and "오늘 1곳" in ready.inner_text()
          and "아직 올라오지" not in ready.inner_text(),
          ("yesterday latest plus today's dated file is today's menu", ready.inner_text()))
    for pattern in ("**/data/kaist-menu/latest.json", "**/data/kaist-menu/week.json",
                    f"**/data/kaist-menu/{today}.json", "**/data/ggongbab/latest.json", "**/data/magazine/index.json"):
        page.unroute(pattern)
    return count


# Food Log is lab-only (lab.html): it has no public home banner, nav or footer link. Free food is the
# calendar above the shelf, so the shelf keeps the picker and the map.
SHELF = ["pick", "map"]
SHELF_HREFS = ["mukbang.html#what", "https://naver.me/5NeqUPzI"]
GROUPS = ["오늘 먹기", "읽어보기", "밥도둑 소식"]
NEWS_HREFS = ["event.html#now", "event.html#archive"]
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
    states: [q('#homeMenuStatus').dataset.state, q('#homeCal').dataset.state],
    cal: box(q('#homeCal')), grid: box(q('#homeCal .hc-grid')), collage: box(q('.home-collage')),
    groups: [...document.querySelectorAll('main > .home-group')].map(g => ({
      title: g.querySelector('h2 [data-i18n]').textContent, purpose: (g.querySelector('.home-group-purpose') || {}).textContent || ''})),
    news: [...document.querySelectorAll('.home-news-row')].map(a => a.getAttribute('href')),
    newsBlocks: [...document.querySelectorAll('.home-news-block')].map(b => { const s = getComputedStyle(b); return {
      kind: b.dataset.news, y: b.getBoundingClientRect().y, bg: s.backgroundColor, shadow: s.boxShadow,
      links: [...b.querySelectorAll('a')].map(a => ({href: a.getAttribute('href'), text: a.textContent.trim()}))}; }),
    story: document.querySelector('.home-news-story') ? document.querySelector('.home-news-story').getAttribute('href') : null,
    mainText: q('main').innerText
  };
}"""


def home_hero_shelf(page):
    """One editorial hero, the free-food calendar in the first screen, then a shelf that only moves when asked."""
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
        check(widths["pick"] > widths["map"], (where, "the picker outranks the discovery banner", widths))
        check(top["grid"]["bottom"] <= height and top["grid"]["h"] > 0,
              (where, "the calendar grid is in the first screen", top["grid"]))
        if width <= 720:
            check(top["cal"]["y"] < top["collage"]["y"],
                  (where, "phones: the calendar comes before the decorative collage", top["cal"], top["collage"]))
        check([g["title"] for g in top["groups"]] == GROUPS and not any(g["purpose"] for g in top["groups"]),
              (where, "eat, read and news groups; the numbered title needs no description line", top["groups"]))
        check(top["news"] == NEWS_HREFS and all((ROOT / h.split("#")[0]).is_file() for h in top["news"]),
              (where, "news leads with notices; past activity is one link", top["news"]))
        blocks = top["newsBlocks"]
        check([b["kind"] for b in blocks] == ["current", "record"] and blocks[0]["y"] < blocks[1]["y"],
              (where, "current information sits above the past record", blocks))
        check([[link["href"] for link in b["links"]] for b in blocks] == [["event.html#now"], ["event.html#archive"]]
              and blocks[1]["links"][0]["text"].startswith("활동 기록 보기"),
              (where, "the past record has exactly one CTA, to the activity record", blocks))
        check(blocks[0]["bg"] != "rgba(0, 0, 0, 0)" and "inset" in blocks[0]["shadow"]
              and blocks[1]["bg"] == "rgba(0, 0, 0, 0)" and blocks[1]["shadow"] == "none",
              (where, "only current information is carded with the accent; the record stays quiet", blocks))
        check(top["story"] == "history.html", (where, "the story link stays in the news group"))
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
        if track["scroll"] <= track["client"] + 1:
            # Everything fits (three banners on a wide screen): nothing to scroll, so no buttons.
            check(not top["navShown"] and all(b["box"]["right"] <= track["box"]["right"] + 1 for b in top["banners"]),
                  (where, "a shelf that fits shows every banner and no scroll buttons", track))
            continue
        peek = next(b["box"] for b in top["banners"] if b["box"]["right"] > track["box"]["right"] + 1)
        check(peek["x"] < track["box"]["right"] - 24, (where, "the next banner visibly peeks", peek, track["box"]))
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
        check(english["title"].startswith("What should") and english["banners"][0]["title"] == "Can't decide? Give it a spin"
              and [g["title"] for g in english["groups"]] == ["Eat today", "Read", "Babdoduk news"]
              and english["root"] <= 0 and english["body"] <= 0, (where, "English fits", english["root"], english["body"]))
        check(english["newsBlocks"][1]["links"][0]["text"].startswith("See the activity record"),
              (where, "English record CTA", english["newsBlocks"]))
        page.locator("#langToggle").click()

    # Reduced motion (this context) removes the hover lift.
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto("https://site-ui.invalid/index.html", wait_until="networkidle")
    link = page.locator(".home-banner-link").first
    link.hover()
    motion = link.evaluate("el => [getComputedStyle(el).transform, getComputedStyle(el).transitionDuration]")
    check(motion == ["none", "0s"], ("reduced motion keeps banners still", motion))

    # Menu published today and no free food: the calendar says so; the hero keeps its shape.
    today = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
    page.route("**/data/kaist-menu/latest.json", lambda route: route.fulfill(json={
        "date": today, "restaurants": [{"id": "r1", "name": "r1", "lunch": {"items": ["밥"]}}]}))
    page.route("**/data/ggongbab/latest.json", lambda route: route.fulfill(json={
        "generatedAt": datetime.now(timezone(timedelta(hours=9))).isoformat(), "events": []}))
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto("https://site-ui.invalid/index.html", wait_until="networkidle")
    top = page.evaluate(HOME_TOP)
    check(top["states"] == ["ready", "empty"] and "오늘 1곳" in page.locator("#homeMenuStatus").inner_text()
          and page.locator("#homeCalAnswer").inner_text() == "예정된 꽁밥이 없어요", ("menu ready, free empty", top["states"]))
    check(top["hero"]["h"] > 0 and [b["name"] for b in top["banners"]] == SHELF and top["root"] <= 0,
          "hero and shelf keep their shape")
    page.unroute("**/data/kaist-menu/latest.json")
    page.unroute("**/data/ggongbab/latest.json")
    return count


def event_bands(page):
    """Dates decide now / coming up / past; confirmation is reported separately and briefly."""
    count = 0

    def check(ok, detail):
        nonlocal count
        assert ok, f"event.html: {detail}"
        count += 1

    today = datetime.now(timezone(timedelta(hours=9))).date()
    labels = {"now": "진행 중", "upcoming": "예정"}

    def expected(start, end):
        return "upcoming" if today.isoformat() < start else "past" if today.isoformat() > end else "now"

    ROWS = """items => items.map(r => { const state = r.querySelector('[data-event-state]');
      return {start:r.dataset.start, end:r.dataset.end, band:r.dataset.band, conf:r.dataset.confirmation,
        list:r.parentElement.id, chip:state.textContent, chipShown:!state.hidden, title:r.querySelector('.event-name').textContent,
        cta:r.querySelector('[data-event-cta]').textContent, linkBand:r.querySelector('.event-link').dataset.band,
        onSite:r.querySelector('.event-link').hasAttribute('data-event-page'),
        open:r.querySelector('details.event-more').open}; })"""

    def cta(row, lang="ko"):
        """An original post is a record once past; an activity on a page of this site opens it."""
        words = {"ko": (("페이지 보기", "페이지 보기"), ("게시물 보기", "당시 게시물")),
                 "en": (("Open the page", "Open the page"), ("View post", "Original post"))}[lang]
        return words[0 if row["onSite"] else 1][row["band"] == "past"]
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto("https://site-ui.invalid/event.html", wait_until="networkidle")
    rows = page.locator(".event-item").evaluate_all(ROWS)
    check(len(rows) == 3, ("three authored activities", rows))
    check([row["title"] for row in rows if row["onSite"]] == ["먹방 월드컵 32강"]
          and page.locator(".event-link[data-event-page][target]").count() == 0,
          ("the menu world cup opens its page in place", rows))
    check("STROKE" not in page.content() and "언빌리버블" not in page.content(),
          "an event that did not happen is not presented")
    for row in rows:
        check(row["band"] == expected(row["start"], row["end"]), ("band from dates", row))
        check(row["list"] == ("eventList" if row["band"] == "past" else "eventUpcoming"), ("past rows under 지난 활동", row))
        check("(예정)" not in row["title"], ("tentative state is a status, not a title suffix", row))
        check("진행됨" not in row["chip"] or row["conf"] == "held", ("only a confirmed event says it took place", row))
        if row["band"] == "past":
            expected_chip = {"announced": "", "tentative": "진행 여부 미확인"}.get(row["conf"])
            if expected_chip is not None:
                check(row["chip"] == expected_chip and row["chipShown"] == bool(expected_chip),
                      ("a past date is not reported as held; an unconfirmed plan says so briefly", row))
        else:
            # The world cup before its launch says when it opens (js/worldcup-gate.js).
            wanted = "10/16 공개 예정" if row["band"] == "upcoming" and row["onSite"] else labels[row["band"]]
            check(row["chip"].startswith(wanted), ("current rows name their band", row))
        check(not row["open"], ("details stay folded by default", row))
        check(row["linkBand"] == row["band"] and row["cta"] == cta(row),
              ("a past link opens the original post as a record; a live link is an action", row))
    check(page.locator(".event-num, .page-num").count() == 0, "event page has no decorative numbers")
    check(page.locator(".event-elsewhere").count() == 0, "the title row does not compete with a hub cross-link")
    empty = page.locator("#eventEmpty")
    check("Instagram" not in empty.inner_text() and empty.locator("a").count() == 0,
          ("empty state is only the absence line", empty.inner_text()))
    insta = page.locator(".event-instagram a")
    check(insta.count() == 1 and insta.get_attribute("href") == "https://www.instagram.com/babdodukms/"
          and "noopener" in (insta.get_attribute("rel") or "") and "@babdodukms" in insta.inner_text(),
          "Instagram is a bottom channel, not an event")

    def participation(lang_tag):
        fields = page.locator(".event-item").evaluate_all("""items => items.map(r => {
          const fields = r.querySelectorAll('[data-detail="participation"]');
          return {band: r.dataset.band, fields: fields.length,
                  historical: fields.length === 1 && fields[0].classList.contains('is-historical'),
                  tags: [...r.querySelectorAll('.event-detail-historical')].map(t => t.textContent)}; })""")
        for field in fields:
            past = field["band"] == "past"
            check(field["fields"] == 1 and field["historical"] == past and field["tags"] == ([lang_tag] if past else []),
                  ("past participation instructions are marked historical, once", field))

    participation("당시 안내 · 지금은 참여할 수 없어요")
    check(page.locator(".event-elsewhere").count() == 0, "free food stays in navigation, not in the news title")
    # Full context is one keyboard action away.
    tentative = page.locator('.event-item[data-confirmation="tentative"]')
    tentative.locator("details.event-more summary").focus()
    page.keyboard.press("Enter")
    note = tentative.locator("[data-event-note]")
    check(tentative.locator("details.event-more").evaluate("d => d.open") and note.is_visible()
          and "진행 여부" in note.inner_text(), ("자세히 opens the full state explanation", note.inner_text()))
    page.locator("#langToggle").click()
    english = page.locator("[data-event-cta]").all_text_contents()
    check(english == [cta(row, "en") for row in rows],
          ("English CTA follows the band", english))
    participation("Original instructions · no longer open")
    page.locator("#langToggle").click()
    participation("당시 안내 · 지금은 참여할 수 없어요")
    live = sum(row["band"] != "past" for row in rows)
    check(page.locator("#eventEmpty").is_visible() == (live == 0), "empty state only when nothing is current")
    check(page.locator("#eventEmpty a").count() == 0, "Instagram is not part of the empty state")
    order = page.evaluate("""() => [...document.querySelectorAll('main h1, main h2')].filter(h => !h.closest('[hidden]'))
      .map(h => h.id || h.tagName)""")
    check(order == ["H1", "eventNowTitle", "eventListTitle"], ("지금, then 지난 활동", order))
    check(page.locator("#eventNotices li").count() == 0 and page.locator("#eventNotices").is_hidden(),
          "no invented notices")
    check(not page.locator(".event-lead, .event-archive-note, .event-counts, .event-boundary").count(),
          "no lead, scope or count paragraphs")

    # A synthetic upcoming, unconfirmed row moves into 지금 with an actionable link.
    start, end = (today + timedelta(days=3)).isoformat(), (today + timedelta(days=4)).isoformat()
    source = (ROOT / "event.html").read_text(encoding="utf-8").replace(
        'data-start="2026-05-19" data-end="2026-05-20"', f'data-start="{start}" data-end="{end}"', 1)
    page.route("**/event.html", lambda route: route.fulfill(content_type="text/html", body=source))
    page.goto("https://site-ui.invalid/event.html", wait_until="networkidle")
    rows = page.locator(".event-item").evaluate_all(ROWS)
    upcoming = [row for row in rows if row["list"] == "eventUpcoming" and "카빙" in row["title"]]
    check(len(upcoming) == 1
          and upcoming[0]["chip"].startswith("예정") and "미확정" in upcoming[0]["chip"],
          ("the scheduled, unconfirmed row leads under 지금", upcoming))
    check(upcoming[0]["cta"] == "게시물 보기" and upcoming[0]["linkBand"] == "upcoming"
          and page.locator("#eventUpcoming .event-detail-historical").count() == 0,
          "an upcoming row keeps an actionable link and unmarked instructions")
    check(page.locator("#eventEmpty").is_hidden() and page.locator("#eventUpcoming").is_visible(),
          "empty state hidden when something is scheduled")
    check(page.locator("#eventList .event-num").count() == 0, "the record has no row numbers")
    page.unroute("**/event.html")
    return count


# The page clocks of the world cup's launch window (2026-10-16 .. 2026-10-23, Korea time, both days included).
WC_SOON = "2026-10-14T21:30:00+09:00"        # before the launch: D-2, 1 day 2 hours left
WC_EVE = "2026-10-15T23:59:00+09:00"         # the last minute before it opens
WC_OPENS = "2026-10-15T15:00:00Z"            # = 2026-10-16 00:00 in Korea, whatever the browser's timezone
WC_RUNNING = "2026-10-18T12:00:00+09:00"
WC_LAST = "2026-10-23T23:59:00+09:00"
WC_ENDED = "2026-10-24T00:00:00+09:00"


def event_entry(page):
    """The world cup's start screen in its activity's card on event.html (owner 2026-10-14: the live
    event, not a teaser photo and a button): the headline, nine tiles with counts, the preview, the
    start button and the photo chip; no teaser, no 지금 해보기; the start opens worldcup.html with the
    category and go=1, and worldcup.html then plays that category at once, only for go=1. The page
    clock is fixed inside the launch window (WC_RUNNING), so the checks do not depend on the wall clock;
    worldcup_gate covers before the launch, the last day, the end and the hosts."""
    count = 0

    def check(ok, detail):
        nonlocal count
        assert ok, f"event.html entry: {detail}"
        count += 1

    source = (ROOT / "event.html").read_text(encoding="utf-8")
    row = 'data-start="2026-10-16" data-end="2026-10-23"'
    assert row in source

    cup = json.loads((ROOT / "data/content/worldcup.json").read_text(encoding="utf-8"))
    counts = {"all": len(cup["dishes"])}
    for dish, cat in cup["categories"].items():
        counts[cat] = counts.get(cat, 0) + 1
    SNAP = """() => { const box = document.querySelector('.event-item .wc-embed'), r = e => e && e.getBoundingClientRect();
      const visible = e => !!e && getComputedStyle(e).display !== 'none' && r(e).width > 0;
      const link = document.querySelector('.event-link[data-event-page]');
      return {embed: visible(box), intro: visible(document.querySelector('#wcIntro')),
        title: document.querySelector('#wcIntroTitle').textContent, tone: document.querySelector('.wc-intro-tone').textContent,
        tiles: [...document.querySelectorAll('.wc-tile')].map(t => ({cat: t.dataset.cat, name: t.querySelector('.wc-tile-name').textContent,
          n: t.querySelector('.wc-tile-n').textContent, pressed: t.getAttribute('aria-pressed')})),
        preview: [...document.querySelectorAll('#wcPreviewPhotos img')].map(i => ({src: i.getAttribute('src'), alt: i.alt, ok: i.naturalWidth > 0})),
        floaters: [...document.querySelectorAll('.wc-floater')].filter(visible).length,
        start: visible(document.querySelector('#wcStart')) && document.querySelector('#wcStart').textContent,
        chip: visible(document.querySelector('.wc-chip')) && document.querySelector('.wc-chip').textContent.trim(),
        link: visible(link) && link.textContent.trim(), teaser: document.querySelectorAll('.event-teaser').length,
        scripts: [...document.scripts].map(s => s.getAttribute('src')).filter(Boolean),
        slim: window.BABDODUK_WORLDCUP ? Object.keys(window.BABDODUK_WORLDCUP).sort() : null,
        overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        text: document.body.innerText}; }"""

    page.clock.set_fixed_time(WC_RUNNING)
    for width, height in ((390, 844), (1280, 800)):
        page.set_viewport_size({"width": width, "height": height})
        page.goto("https://site-ui.invalid/event.html", wait_until="networkidle")
        page.evaluate("localStorage.removeItem('babdoduk-lang')")
        page.wait_for_selector("#wcIntro:not([hidden])")
        snap = page.evaluate(SNAP)
        check(snap["embed"] and snap["intro"] and snap["title"] == "오늘의 32강, 뭐가 나올까?"
              and snap["tone"] == "시험기간으로 지친 당신! 메뉴나 골라~", (width, "the headline and tone line", snap["title"]))
        check([t["cat"] for t in snap["tiles"]] == ["all", "korean", "chinese", "japanese", "western", "world", "snack", "dessert", "random"]
              and [t["n"] for t in snap["tiles"][:-1]] == [f"{counts[t['cat']]}개" for t in snap["tiles"][:-1]]
              and snap["tiles"][-1]["name"] == "아무거나" and snap["tiles"][-1]["pressed"] is None
              and [t["pressed"] for t in snap["tiles"][:-1]].count("true") == 1, (width, "nine tiles with counts, the random tile", snap["tiles"]))
        check(len(snap["preview"]) == 5 and all(p["ok"] and p["alt"] and p["src"].startswith("images/worldcup/") for p in snap["preview"]),
              (width, "five dishes of the next draw, loaded and named", snap["preview"]))
        check(snap["floaters"] == 4 and snap["start"] == "🎰32강 시작", (width, "floating photos and the start button", snap["floaters"], snap["start"]))
        check(snap["chip"] == "📷 사진 위키미디어 공용(잘라서 줄임)" and "판매 여부" not in snap["text"],
              (width, "one photo chip and no price sentence", snap["chip"]))
        check(snap["teaser"] == 0 and snap["link"] is False and "지금 해보기" not in snap["text"] and "VS" not in snap["text"],
              (width, "no teaser photos, no vs badge and no 지금 해보기 button", snap["link"]))
        check(snap["overflow"] <= 0, (width, "no horizontal scroll", snap["overflow"]))
        check("js/worldcup.js" in snap["scripts"] and "js/worldcup-entry-data.js" in snap["scripts"]
              and "photos" not in snap["slim"] and "basis" not in snap["slim"], (width, "the slim data, not the pool with its photo credits", snap["slim"]))
        # Inside the card: after the date, title and state, before 자세히.
        order = page.evaluate("""() => { const item = document.querySelector('.event-item .wc-embed').closest('.event-item');
          return [...item.children].map(c => c.className.split(' ')[0] || c.tagName); }""")
        check(order == ["event-date", "event-name", "event-state", "wc-embed", "event-link", "event-more"], (width, "inside the event card", order))
        # Keyboard: a tile toggles with Space and the start button is reachable and focus is visible.
        page.locator('.wc-tile[data-cat="korean"]').focus()
        page.keyboard.press("Space")
        check(page.locator('.wc-tile[data-cat="korean"]').get_attribute("aria-pressed") == "true"
              and page.locator("#wcPreviewPhotos img").count() == 5, (width, "a tile is chosen by keyboard"))
        page.locator("#wcStart").focus()
        check(page.evaluate("getComputedStyle(document.activeElement).outlineStyle") != "none", (width, "visible focus on the start button"))

    # English, and the language switch re-words the tiles and the headline.
    page.set_viewport_size({"width": 390, "height": 844})
    page.locator("#langToggle").click()
    snap = page.evaluate(SNAP)
    check(snap["title"] == "What’s in today’s round of 32?" and snap["start"] == "🎰Start the round of 32"
          and snap["tiles"][1]["name"] == "Korean" and snap["tiles"][-1]["name"] == "Surprise me"
          and snap["chip"] == "📷 Photos: Wikimedia Commons (cropped, resized)", ("English", snap["title"], snap["start"]))
    check(snap["overflow"] <= 0, "English: no horizontal scroll")
    page.locator("#langToggle").click()

    # Start: worldcup.html?cat=<chosen>&go=1; a saved game is not touched until then.
    page.locator('.wc-tile[data-cat="japanese"]').click()
    with page.expect_navigation() as navigation:
        page.locator("#wcStart").click()
    sent = urlparse(navigation.value.url)
    check(sent.path == "/worldcup.html" and parse_qs(sent.query) == {"cat": ["japanese"], "go": ["1"]},
          ("the start opens the game page with the category and go=1", navigation.value.url))
    page.wait_for_selector("#wcMatch:not([hidden])")
    game = page.evaluate("JSON.parse(localStorage.getItem('babdoduk-worldcup')).game")
    check(game["category"] == "japanese" and game["winners"] == [] and len(game["entrants"]) == 32
          and all(cup["categories"][d] == "japanese" for d in game["entrants"]), ("worldcup.html started the chosen category", game["category"]))
    check(page.url.endswith("/worldcup.html") and page.locator("#wcGame").inner_text() == "일식 32강",
          ("the address is cleaned and the match is on screen", page.url, page.locator("#wcGame").inner_text()))
    check(page.evaluate("document.activeElement === document.querySelector('.wc-card')"), "the first card has the focus")
    page.reload(wait_until="networkidle")
    check(page.evaluate("JSON.parse(localStorage.getItem('babdoduk-worldcup')).game.entrants") == game["entrants"]
          and page.locator("#wcResume").is_visible() and page.locator("#wcMatch").is_hidden(),
          "a reload keeps the game and offers 이어하기, it does not deal another")

    # Never without go=1; an unknown category is ignored (the whole pool); a saved game is replaced by a fresh one.
    def arrive(query, saved=None):
        page.goto("https://site-ui.invalid/worldcup.html", wait_until="networkidle")
        page.evaluate("localStorage.removeItem('babdoduk-worldcup')")
        if saved:
            page.evaluate("s => localStorage.setItem('babdoduk-worldcup', JSON.stringify(s))", saved)
        page.goto("https://site-ui.invalid/worldcup.html" + query, wait_until="networkidle")
        return page.evaluate("JSON.parse(localStorage.getItem('babdoduk-worldcup'))")

    for query in ("?cat=korean", "?cat=korean&go=0", "?go=true", ""):
        stored = arrive(query)
        check(page.locator("#wcIntro").is_visible() and page.locator("#wcMatch").is_hidden()
              and not (stored or {}).get("game"), ("no go=1, no auto start", query))
    check(page.locator("#wcIntro").is_visible() and page.locator('.wc-tile[data-cat="all"]').get_attribute("aria-pressed") == "true",
          "the start screen without go=1 (all chosen)")
    chips = page.locator(".wc-chip")
    check(chips.count() == 1 and " ".join(chips.inner_text().split()) == "📷 사진 위키미디어 공용(잘라서 줄임)" and "판매 여부" not in page.content()
          and page.locator(".wc-scope").count() == 0, "worldcup.html ends with the one photo chip")
    stored = arrive("?cat=korean&go=1")
    check(stored["game"]["category"] == "korean" and page.locator("#wcGame").inner_text() == "한식 32강", "go=1 starts korean")
    for query in ("?cat=nope&go=1", "?go=1", "?cat=%3Cb%3E&go=1"):
        stored = arrive(query)
        check(stored["game"]["category"] == "all" and page.locator("#wcGame").inner_text() == "전체 32강", ("an unknown category is ignored", query))
    old = worldcup_saved(cup, 16, 7, "korean")
    stored = arrive("?cat=western&go=1", old)
    check(stored["game"]["category"] == "western" and len(stored["game"]["entrants"]) == 32 and stored["game"]["winners"] == []
          and stored["game"]["entrants"] != old["game"]["entrants"], "a saved game is replaced when a start is asked for")
    stored = arrive("?cat=western", old)
    check(stored["game"]["entrants"] == old["game"]["entrants"] and page.locator("#wcResume").is_visible(),
          "without go=1 a saved game stays and 이어하기 is offered")
    page.evaluate("localStorage.removeItem('babdoduk-worldcup')")

    # With motion the arrival plays the start gacha, as if the button had been pressed on the page.
    page.emulate_media(reduced_motion="no-preference")
    page.goto("https://site-ui.invalid/worldcup.html?cat=chinese&go=1", wait_until="networkidle")
    page.wait_for_function(SPLASH_OPEN)
    seen = page.evaluate("""() => { const s = document.querySelector('#wcSplash');
      return {round: s.dataset.round, line: s.querySelector('.wc-gacha-line').textContent}; }""")
    check(seen == {"round": "start", "line": "중식 32강 뽑는 중…"}, ("the gacha plays for the asked category", seen))
    page.screenshot(path=str(ROOT / ".local/site-ui-shots/worldcup-go-gacha.png")) if (ROOT / ".local/site-ui-shots").is_dir() else None
    page.evaluate("localStorage.removeItem('babdoduk-worldcup')")
    page.emulate_media(reduced_motion="reduce")

    # A past row has no start screen, loads no world cup script and links to the page instead.
    page.clock.set_fixed_time(WC_ENDED)
    page.goto("https://site-ui.invalid/event.html", wait_until="networkidle")
    snap = page.evaluate(SNAP)
    check(not snap["embed"] and snap["link"] == "페이지 보기 →" and "js/worldcup.js" not in snap["scripts"] and snap["slim"] is None
          and "worldcup.html" == page.locator(".event-link[data-event-page]").get_attribute("href"),
          ("past: only the link, nothing loaded", snap["link"], snap["scripts"]))

    # The script not arriving leaves the link, not an empty card.
    page.clock.set_fixed_time(WC_RUNNING)
    page.route("**/js/worldcup-entry-data.js", lambda route: route.fulfill(status=404, body=""))
    page.goto("https://site-ui.invalid/event.html", wait_until="networkidle")
    snap = page.evaluate(SNAP)
    check(not snap["embed"] or not snap["intro"], "a failed load shows no half-built start screen")
    check(snap["link"] == "페이지 보기 →", ("a failed load falls back to the link", snap["link"]))
    page.unroute("**/js/worldcup-entry-data.js")
    return count


GATE_PREVIEW = "2026-10-13"


def gate_window():
    """The launch window the sync wrote into js/worldcup-gate.js."""
    source = (ROOT / "js/worldcup-gate.js").read_text(encoding="utf-8")
    return json.loads(re.search(r"window\.BABDODUK_WC_WINDOW = (\{.*\});", source).group(1))


def gate_preview(page):
    """Serve js/worldcup-gate.js with a lab `previewFrom` (GATE_PREVIEW) when the data carries none
    (production's data/content/events.json never does), so the lab override is still checked. Returns
    whether it did; the caller unroutes it after the override checks."""
    source = (ROOT / "js/worldcup-gate.js").read_text(encoding="utf-8")
    window = gate_window()
    if "previewFrom" in window:
        return False
    window["previewFrom"] = GATE_PREVIEW
    body = re.sub(r"window\.BABDODUK_WC_WINDOW = \{.*\};", lambda m: "window.BABDODUK_WC_WINDOW = " + json.dumps(window) + ";", source)
    page.route("**/js/worldcup-gate.js", lambda route: route.fulfill(content_type="application/javascript", body=body))
    return True


def gate_page(page, host, name, query=""):
    """A page of this site loaded as the production, lab or localhost host (served from the same files)."""
    scheme = "http" if host == "localhost" else "https"
    page.goto(f"{scheme}://{host}/{name}{query}", wait_until="networkidle")


GATE_SNAP = """() => { const shown = e => !!e && !e.hidden && getComputedStyle(e).display !== 'none' && e.getBoundingClientRect().width > 0;
  const q = s => document.querySelector(s);
  const row = q('.event-item[data-start="2026-10-16"]');
  return {phase: document.documentElement.getAttribute('data-wc-phase'),
    locked: shown(q('#wcLocked')), pill: q('.wc-locked-pill') && q('.wc-locked-pill').textContent.trim().replace(/\\s+/g, ' '),
    count: q('.wc-locked-count') && q('.wc-locked-count').textContent,
    start: shown(q('#wcStart')), resume: shown(q('#wcResume')), ended: shown(q('.wc-ended')),
    tiles: [...document.querySelectorAll('.wc-tile')].filter(shown).length,
    floaters: [...document.querySelectorAll('.wc-floater')].filter(shown).length,
    match: shown(q('#wcMatch')), intro: shown(q('#wcIntro')),
    saved: localStorage.getItem('babdoduk-worldcup'),
    state: row && row.querySelector('[data-event-state]').textContent, band: row && row.dataset.band,
    overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth}; }"""


# The mystery box (owner 2026-10-14): before the launch the tiles, the preview photos and the floating
# photos are blurred, inert or aria-hidden placeholders with no photo request; live and ended leave them alone.
MYSTERY_SNAP = """() => { const q = s => document.querySelector(s), all = s => [...document.querySelectorAll(s)];
  const shown = e => !!e && !e.hidden && getComputedStyle(e).display !== 'none' && e.getBoundingClientRect().width > 0;
  const blur = e => { const m = /blur\\(([\\d.]+)px\\)/.exec(getComputedStyle(e).filter); return m ? Number(m[1]) : 0; };
  const sat = e => { const m = /saturate\\(([\\d.]+)\\)/.exec(getComputedStyle(e).filter); return m ? Number(m[1]) : 1; };
  const body = q('#wcMysteryBody'), lock = q('#wcMysteryLock'), badge = q('.wc-mystery-badge');
  return {tilesBlur: blur(q('.wc-tiles')), tilesSat: sat(q('.wc-tiles')),
    previewBlur: blur(q('.wc-preview-photos')), floaterBlur: all('.wc-floater').filter(shown).map(blur),
    inert: !!body && body.inert, ariaHidden: body && body.getAttribute('aria-hidden'),
    pressed: all('.wc-tile[aria-pressed]').length, pressedTrue: all('.wc-tile[aria-pressed="true"]').length,
    previewImgs: all('#wcPreviewPhotos img').map(i => ({src: i.getAttribute('src'), alt: i.alt, id: i.getAttribute('data-id')})),
    floaterSrc: all('.wc-floater').filter(shown).map(i => i.getAttribute('src')),
    lock: shown(lock), badge: badge && shown(badge) && badge.textContent.trim().replace(/\\s+/g, ' '),
    sr: lock && lock.querySelector('.wc-sr').textContent, srHidden: lock && lock.getAttribute('aria-hidden'),
    badgeHidden: badge && badge.getAttribute('aria-hidden'),
    pointer: getComputedStyle(q('.wc-tiles')).pointerEvents}; }"""


def mystery_requests(page):
    """Start logging the dish photos (images/worldcup/*) a page requests; returns the list."""
    seen = []
    page.on("request", lambda request: seen.append(request.url) if "/images/worldcup/" in request.url else None)
    return seen


def worldcup_gate(page):
    """The launch gate (owner 2026-10-14, js/worldcup-gate.js): before 2026-10-16 the start screen is a teaser
    with a locked pill and a countdown and nothing plays, not even with go=1 or a saved game; from the first
    to the last day (23:59 Korea time) it is the game; after it worldcup.html plays on with a note and the
    news card is a past row. Lab and localhost, and only they, honour `previewFrom` and open it early.
    Every case fixes the page clock."""
    count = 0

    def check(ok, detail):
        nonlocal count
        assert ok, f"world cup gate: {detail}"
        count += 1

    cup = json.loads((ROOT / "data/content/worldcup.json").read_text(encoding="utf-8"))
    page.set_viewport_size({"width": 390, "height": 844})

    def snap(host, name, now, query=""):
        page.clock.set_fixed_time(now)
        gate_page(page, host, name, query)
        page.evaluate("localStorage.removeItem('babdoduk-lang')")
        return page.evaluate(GATE_SNAP)

    photos = mystery_requests(page)

    def mystery_hidden(shot, where):
        """Before the launch: blurred past reading, inert, no photo, one sentence for screen readers."""
        check(shot["tilesBlur"] >= 10 and shot["tilesSat"] < 1 and shot["previewBlur"] >= 8
              and shot["floaterBlur"] and all(b >= 8 for b in shot["floaterBlur"]),
              (where, "tiles, preview and floating photos are blurred", shot))
        check(shot["inert"] and shot["ariaHidden"] == "true", (where, "the blurred area is inert and aria-hidden", shot))
        check(shot["pressed"] == 0 and shot["pointer"] == "none", (where, "no tile is chosen or clickable", shot))
        check(len(shot["previewImgs"]) == 5 and all(i["src"] is None and i["alt"] == "" and i["id"] is None for i in shot["previewImgs"])
              and shot["floaterSrc"] and all(src is None for src in shot["floaterSrc"]),
              (where, "the preview and floating photos are placeholders with no src", shot))
        check(shot["lock"] and shot["badge"] in ("🔒 10/16 공개", "🔒 Opens Oct 16") and shot["badgeHidden"] == "true"
              and shot["sr"] in ("카테고리는 10/16에 공개돼요", "The categories are revealed on Oct 16.") and shot["srHidden"] is None,
              (where, "the lock badge is visible and a sentence is for screen readers", shot))

    def mystery_open(shot, where):
        """Live and ended: nothing blurred, the tiles work, the real photos are there, no lock."""
        check(shot["tilesBlur"] == 0 and shot["previewBlur"] == 0 and not any(shot["floaterBlur"]), (where, "unblurred", shot))
        check(not shot["inert"] and shot["ariaHidden"] is None and shot["pressedTrue"] == 1 and shot["pointer"] != "none",
              (where, "the tiles are interactive and one is chosen", shot))
        check(len(shot["previewImgs"]) == 5 and all((i["src"] or "").startswith("images/worldcup/") and i["alt"] for i in shot["previewImgs"])
              and shot["floaterSrc"] and all((src or "").startswith("images/worldcup/") for src in shot["floaterSrc"]) and not shot["lock"],
              (where, "the real photos load and no lock shows", shot))

    # worldcup.html before the launch: the teaser, locked, nothing playable.
    photos.clear()
    shot = snap(SITE_HOST, "worldcup.html", WC_SOON)
    mystery_hidden(page.evaluate(MYSTERY_SNAP), "worldcup.html")
    check(not photos, ("worldcup.html requests no dish photo before the launch", photos))
    check(shot["phase"] == "soon" and shot["locked"] and shot["pill"] == "🔒 10/16 오픈" and shot["count"] == "D-2 · 1일 2시간 남음",
          ("locked pill and countdown", shot))
    check(not shot["start"] and not shot["resume"] and not shot["match"] and shot["intro"] and shot["tiles"] == 9
          and shot["floaters"] == 4, ("the teaser stays, the start button is gone", shot))
    check(shot["overflow"] <= 0, ("no horizontal scroll", shot["overflow"]))
    # The mystery box takes neither a tap nor the keyboard: a tile is not chosen, and Tab never enters it.
    page.locator('.wc-tile[data-cat="korean"]').scroll_into_view_if_needed()
    tile = page.locator('.wc-tile[data-cat="korean"]').bounding_box()
    page.mouse.click(tile["x"] + tile["width"] / 2, tile["y"] + tile["height"] / 2)
    page.evaluate("document.activeElement && document.activeElement.blur(); window.scrollTo(0, 0)")
    entered = False
    for _ in range(14):
        page.keyboard.press("Tab")
        entered = entered or page.evaluate("!!document.activeElement.closest('#wcMysteryBody')")
    check(not entered and page.locator(".wc-tile[aria-pressed]").count() == 0 and page.locator("#wcPreview img[src]").count() == 0,
          "a tap or Tab does not reach the blurred tiles")
    page.evaluate("document.querySelector('#wcStart').click()")              # even a forced click starts nothing
    check(page.locator("#wcMatch").is_hidden() and not page.evaluate("localStorage.getItem('babdoduk-worldcup')"),
          "a forced start click does nothing")
    page.locator("#langToggle").click()
    shot = page.evaluate(GATE_SNAP)
    check(shot["pill"] == "🔒 Opens Oct 16" and shot["count"] == "D-2 · 1d 2h left", ("English", shot))
    mystery_hidden(page.evaluate(MYSTERY_SNAP), "worldcup.html English")
    check(not photos, ("a language switch loads no dish photo before the launch", photos))
    page.locator("#langToggle").click()
    for query in ("?cat=korean&go=1", "?go=1", "?cat=nope&go=1"):
        shot = snap(SITE_HOST, "worldcup.html", WC_SOON, query)
        check(shot["locked"] and shot["intro"] and not shot["match"] and not shot["saved"] and page.url.endswith("/worldcup.html"),
              ("go=1 does not start a game and the address is cleaned", query, shot))
    saved = worldcup_saved(cup, 16, 7, "korean")
    page.evaluate("s => localStorage.setItem('babdoduk-worldcup', JSON.stringify(s))", saved)
    page.reload(wait_until="networkidle")
    shot = page.evaluate(GATE_SNAP)
    check(shot["locked"] and not shot["resume"] and not shot["start"] and not shot["match"]
          and json.loads(shot["saved"])["game"]["entrants"] == saved["game"]["entrants"],
          ("a saved game is neither offered nor touched before the launch", shot))
    page.evaluate("localStorage.removeItem('babdoduk-worldcup')")
    shot = snap(SITE_HOST, "worldcup.html", WC_EVE)
    check(shot["locked"] and shot["count"] == "D-1 · 1분 남음", ("the last minute", shot))

    # The launch moment, read as Korea time: midnight there is the first moment, whatever the clock's zone.
    for now in (WC_OPENS, WC_RUNNING, WC_LAST):
        shot = snap(SITE_HOST, "worldcup.html", now)
        check(shot["phase"] == "live" and shot["start"] and not shot["locked"] and not shot["ended"], ("open", now, shot))
        mystery_open(page.evaluate(MYSTERY_SNAP), ("worldcup.html", now))
    shot = snap(SITE_HOST, "worldcup.html", WC_LAST, "?cat=korean&go=1")
    check(shot["match"] and json.loads(shot["saved"])["game"]["category"] == "korean", ("go=1 starts on the last day", shot))
    page.evaluate("localStorage.removeItem('babdoduk-worldcup')")
    # After the end: still playable, with a small note.
    shot = snap(SITE_HOST, "worldcup.html", WC_ENDED)
    check(shot["phase"] == "ended" and shot["start"] and shot["ended"] and not shot["locked"], ("after the end: playable with a note", shot))
    mystery_open(page.evaluate(MYSTERY_SNAP), ("worldcup.html", "ended"))
    check("이벤트 종료" in page.locator(".wc-ended").inner_text(), "the note says the event is over")
    shot = snap(SITE_HOST, "worldcup.html", WC_ENDED, "?cat=korean&go=1")
    check(shot["match"] and json.loads(shot["saved"])["game"]["category"] == "korean", "after the end go=1 still plays")
    page.evaluate("localStorage.removeItem('babdoduk-worldcup')")

    # The news card: before the launch the teaser with the locked pill, in the coming-up list.
    photos.clear()
    shot = snap(SITE_HOST, "event.html", WC_SOON)
    check(shot["band"] == "upcoming" and shot["state"] == "10/16 공개 예정" and shot["locked"] and not shot["start"] and shot["tiles"] == 9
          and shot["floaters"] == 4 and shot["pill"] == "🔒 10/16 오픈" and shot["count"] == "D-2 · 1일 2시간 남음",
          ("the event card is locked", shot))
    check(page.locator("#eventUpcoming .wc-embed").count() == 1 and shot["overflow"] <= 0, "in 지금, no horizontal scroll")
    mystery_hidden(page.evaluate(MYSTERY_SNAP), "event.html")
    check(not photos, ("event.html requests no dish photo before the launch", photos))
    page.locator("#langToggle").click()
    shot = page.evaluate(GATE_SNAP)
    check(shot["state"] == "Opens Oct 16" and shot["pill"] == "🔒 Opens Oct 16", ("English event card", shot))
    mystery_hidden(page.evaluate(MYSTERY_SNAP), "event.html English")
    page.locator("#langToggle").click()
    page.evaluate("document.querySelector('#wcStart').click()")
    check(page.url.endswith("/event.html"), "a forced start click on the card goes nowhere")
    shot = snap(SITE_HOST, "event.html", WC_RUNNING)
    check(shot["band"] == "now" and shot["state"].startswith("진행 중") and shot["start"] and not shot["locked"], ("running card", shot))
    mystery_open(page.evaluate(MYSTERY_SNAP), ("event.html", "running"))
    shot = snap(SITE_HOST, "event.html", WC_LAST)
    check(shot["band"] == "now" and shot["start"], ("running on the last day", shot))
    shot = snap(SITE_HOST, "event.html", WC_ENDED)
    check(shot["band"] == "past" and not shot["start"] and page.locator(".wc-embed").is_hidden()
          and page.locator("#eventList .event-link[data-event-page]").count() == 1, ("past card", shot))

    # Without a previewFrom in the data (production), no host opens it before the start.
    if "previewFrom" not in gate_window():
        for host in ("babdoduk.vercel.app", "babdoduk-lab.vercel.app", "localhost"):
            shot = snap(host, "worldcup.html", WC_SOON)
            check(shot["locked"] and not shot["start"], (host, "no previewFrom: locked", shot))
    synthetic = gate_preview(page)
    # The lab override: only on lab and localhost (previewFrom), never on production or another host.
    for host, early in (("babdoduk.vercel.app", False), (SITE_HOST, False), ("babdoduk-lab.vercel.app", True), ("localhost", True)):
        shot = snap(host, "worldcup.html", WC_SOON)
        check(shot["locked"] == (not early) and shot["start"] == early, (host, "worldcup.html", shot))
        (mystery_open if early else mystery_hidden)(page.evaluate(MYSTERY_SNAP), (host, "worldcup.html"))
        shot = snap(host, "event.html", WC_SOON)
        check(shot["locked"] == (not early) and shot["start"] == early and shot["band"] == ("now" if early else "upcoming")
              and shot["state"].startswith("진행 중" if early else "10/16 공개 예정"), (host, "event.html", shot))
        shot = snap(host, "worldcup.html", WC_SOON, "?cat=korean&go=1")
        check(shot["match"] == early, (host, "go=1", shot))
        page.evaluate("localStorage.removeItem('babdoduk-worldcup')")
    # Lab opens it from 2026-10-13, not before; and it still closes at the end like production.
    shot = snap("babdoduk-lab.vercel.app", "worldcup.html", "2026-10-12T23:59:00+09:00")
    check(shot["locked"] and shot["count"].startswith("D-"), ("lab before previewFrom", shot))
    shot = snap("babdoduk-lab.vercel.app", "worldcup.html", WC_ENDED)
    check(shot["ended"] and shot["start"], ("lab after the end", shot))
    if synthetic:
        page.unroute("**/js/worldcup-gate.js")
    source = (ROOT / "js/worldcup-gate.js").read_text(encoding="utf-8")
    check(source.count("'babdoduk-lab.vercel.app'") == 1 and "location.hostname" in source, "the gate names the lab host once")
    return count


def home_wc_promo(page):
    """The home page's 먹방 월드컵 promo (index.html): before the launch the countdown and a link to the news
    page, while it runs the 지금 하기 button for the game, after the end nothing; the same on lab with the
    override. It stays inside 390 px without pushing the hero or the calendar out. Fixed page clocks."""
    count = 0

    def check(ok, detail):
        nonlocal count
        assert ok, f"home world cup promo: {detail}"
        count += 1

    SNAP = """() => { const q = s => document.querySelector(s);
      const shown = e => !!e && !e.hidden && getComputedStyle(e).display !== 'none' && e.getBoundingClientRect().width > 0;
      const promo = q('.home-wc'), box = e => e.getBoundingClientRect();
      const soon = q('.home-wc-cta--soon'), live = q('.home-wc-cta--live');
      return {shown: shown(promo), title: q('.home-wc-title').textContent.trim(),
        states: [...document.querySelectorAll('.home-wc-state')].filter(shown).map(e => e.textContent.trim()),
        count: q('.home-wc-count').textContent, countShown: shown(q('.home-wc-count')),
        soon: shown(soon) && {href: soon.getAttribute('href'), text: soon.textContent.trim().replace(/\\s+/g, ' ')},
        live: shown(live) && {href: live.getAttribute('href'), text: live.textContent.trim().replace(/\\s+/g, ' ')},
        photos: [...document.querySelectorAll('.home-wc-photo')].map(i => i.naturalWidth > 0),
        photoSrc: [...document.querySelectorAll('.home-wc-photo')].map(i => i.getAttribute('src')),
        photoBlur: [...document.querySelectorAll('.home-wc-photo')].map(i => { const m = /blur\\(([\\d.]+)px\\)/.exec(getComputedStyle(i).filter); return m ? Number(m[1]) : 0; }),
        height: promo ? box(promo).height : 0, top: promo ? box(promo).top : 0,
        hero: box(q('#homeTitle')).top, cal: shown(q('#homeCal')), calTop: box(q('#homeCal')).top,
        overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth}; }"""

    home_photos = mystery_requests(page)

    def snap(host, now, size=(390, 844)):
        page.set_viewport_size({"width": size[0], "height": size[1]})
        page.clock.set_fixed_time(now)
        home_photos.clear()
        gate_page(page, host, "index.html")
        page.evaluate("localStorage.removeItem('babdoduk-lang')")
        return page.evaluate(SNAP)

    for width, height in ((390, 844), (360, 800), (1280, 800)):
        shot = snap(SITE_HOST, WC_SOON, (width, height))
        full = "D-2 · 1일 2시간 남음" if width >= 641 else "D-2"       # a phone keeps just the days
        visible = page.locator(".home-wc-count").inner_text().strip()
        check(shot["shown"] and shot["title"] == "🏆 밥도둑 먹방 월드컵" and shot["states"] == ["10/16 오픈!"]
              and shot["count"] == "D-2 · 1일 2시간 남음" and visible == full, (width, "before the launch", shot, visible))
        check(shot["soon"] and shot["soon"]["href"] == "event.html" and shot["soon"]["text"] == "자세히 보기 →" and not shot["live"],
              (width, "links to the news page", shot))
        check(not any(shot["photos"]) and shot["photoSrc"] == [None, None] and len(shot["photoBlur"]) == 2 and all(b >= 3 for b in shot["photoBlur"]),
              (width, "two blurred placeholders, no dish photo before the launch", shot["photos"], shot["photoSrc"], shot["photoBlur"]))
        check(not home_photos, (width, "no dish photo is requested before the launch", home_photos))
        # A phone: above the copy; wider, in the paper band under it. Either way before the calendar.
        order = shot["top"] < shot["hero"] if width < 721 else shot["hero"] < shot["top"]
        check(shot["overflow"] <= 0 and shot["cal"] and order and shot["top"] < shot["calTop"],
              (width, "in the hero band, the calendar stays", shot))
        check(shot["height"] <= (100 if width < 641 else 80), (width, "a compact band", shot["height"]))
        shot = snap(SITE_HOST, WC_RUNNING, (width, height))
        check(all(shot["photos"]) and len(shot["photos"]) == 2 and not any(shot["photoBlur"]),
              (width, "running: the two dish photos load, unblurred", shot["photos"], shot["photoBlur"]))
        check(shot["shown"] and shot["states"] == ["지금 진행 중 · 10/23까지"] and not shot["soon"] and not shot["countShown"]
              and shot["live"] == {"href": "worldcup.html", "text": "🎰 지금 하기"}, (width, "running", shot))
        check(shot["overflow"] <= 0 and shot["height"] <= (100 if width < 641 else 80), (width, "running: compact, no horizontal scroll", shot))
        shot = snap(SITE_HOST, WC_LAST, (width, height))
        check(shot["shown"] and shot["live"], (width, "still there on the last day", shot))
        shot = snap(SITE_HOST, WC_ENDED, (width, height))
        check(not shot["shown"] and shot["cal"] and shot["overflow"] <= 0, (width, "gone after the end", shot))
        check(page.locator(".home-top").evaluate("e => e.getBoundingClientRect().top") < 120, (width, "after the end the hero is back at the top"))

    # English, on the page's language switch.
    snap(SITE_HOST, WC_SOON)
    page.locator("#langToggle").click()
    shot = page.evaluate(SNAP)
    check(shot["title"] == "🏆 Food World Cup" and shot["states"] == ["Opens Oct 16!"] and shot["count"] == "D-2 · 1d 2h left"
          and shot["soon"]["text"] == "Preview →" and shot["overflow"] <= 0, ("English before the launch", shot))
    page.clock.set_fixed_time(WC_RUNNING)
    page.reload(wait_until="networkidle")
    shot = page.evaluate(SNAP)
    check(shot["states"] == ["Live now · until Oct 23"] and shot["live"]["text"] == "🎰 Play now" and shot["overflow"] <= 0,
          ("English running", shot))
    page.evaluate("localStorage.removeItem('babdoduk-lang')")

    # Keyboard: the button is reachable and its focus ring shows; the whole band is its click target.
    snap(SITE_HOST, WC_RUNNING)
    page.locator(".home-wc-cta--live").focus()
    check(page.evaluate("getComputedStyle(document.querySelector('.home-wc-cta--live'), '::after').outlineStyle") != "none",
          "visible focus on the promo button")
    box = page.locator(".home-wc").bounding_box()
    with page.expect_navigation() as navigation:
        page.mouse.click(box["x"] + box["width"] - 6, box["y"] + 6)
    check(urlparse(navigation.value.url).path == "/worldcup.html", "a click anywhere on the band follows its link")
    check(contrast("rgb(253, 230, 138)", "rgb(190, 24, 93)") >= 4.5 and contrast("rgb(157, 23, 77)", "rgb(255, 255, 255)") >= 4.5,
          "the state line and the button keep their contrast on the gradient")

    # Lab opens it early (previewFrom); production does not. Without one in the data (production),
    # no host does; the override then runs on a synthetic previewFrom.
    if "previewFrom" not in gate_window():
        for host in ("babdoduk.vercel.app", "babdoduk-lab.vercel.app", "localhost"):
            shot = snap(host, WC_SOON)
            check(shot["shown"] and not shot["live"] and shot["soon"] and shot["states"] == ["10/16 오픈!"],
                  (host, "no previewFrom: soon", shot))
    synthetic = gate_preview(page)
    for host, early in (("babdoduk.vercel.app", False), ("babdoduk-lab.vercel.app", True), ("localhost", True)):
        shot = snap(host, WC_SOON)
        check(all(shot["photos"]) == early and (not any(shot["photoBlur"]) if early else all(shot["photoBlur"])), (host, "promo photos", shot))
        check(shot["shown"] and bool(shot["live"]) == early and bool(shot["soon"]) == (not early)
              and shot["states"] == (["지금 진행 중 · 10/23까지"] if early else ["10/16 오픈!"]), (host, shot))
    if synthetic:
        page.unroute("**/js/worldcup-gate.js")
    return count


# Every round splash the page opens, in order: beforetoggle fires as showPopover() runs.
SPLASH_LOG = """() => { window.__splashes = [];
  document.querySelector('#wcSplash').addEventListener('beforetoggle', e => {
    if (e.newState === 'open') window.__splashes.push(e.target.dataset.round); }); }"""
SPLASH_OPEN = "document.querySelector('#wcSplash').matches(':popover-open')"
# The final's crash held still and seeked: fighter boxes off the stage from the hit to the end,
# the clash scale against the real card, card text under the VS at rest, the landing error.
SPLASH_GEOMETRY = """() => { const s = document.querySelector('#wcSplash'), all = s.getAnimations({subtree: true});
  const box = el => { const r = el.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; };
  const fighters = () => [...s.querySelectorAll('.wc-fighter')].map(box);
  const seek = t => all.forEach(a => { a.currentTime = t; });
  all.forEach(a => a.pause());
  let outside = 0;
  for (let t = 1100; t <= 1999; t += 20) {
    seek(t);
    outside += fighters().filter(b => b[0] < 0 || b[1] < 0 || b[2] > s.clientWidth || b[3] > s.clientHeight).length;
  }
  seek(1500);
  const real = [...document.querySelectorAll('.wc-card')].map(c => {    // where each card rests
    const was = [c.style.transition, c.style.transform];
    c.style.transition = 'none'; c.style.transform = 'none';
    const b = box(c);
    [c.style.transition, c.style.transform] = was;
    return b; });
  const vs = box(s.querySelector('.wc-splash-vs'));
  const scale = Math.min(...fighters().map(b => b[2] - b[0])) / (real[0][2] - real[0][0]);
  const covered = [...s.querySelectorAll('.wc-fighter-face .wc-card-name, .wc-fighter-face .wc-card-sub, .wc-fighter-face .wc-card-tags')]
    .filter(el => !el.hidden && el.textContent).map(box)
    .filter(b => !(b[2] <= vs[0] || b[0] >= vs[2] || b[3] <= vs[1] || b[1] >= vs[3])).length;
  seek(1999);
  const miss = Math.max(...fighters().flatMap((b, i) => b.map((v, k) => Math.abs(v - real[i][k]))));
  return {outside, scale: Math.round(scale * 100) / 100, covered, miss: Math.round(miss * 100) / 100}; }"""


def worldcup_saved(cup, entrants, winners, category=None):
    """A stored game `winners` picks into a round of `entrants`, as js/worldcup.js keeps it. Without
    `category` it is an older save (none recorded: the whole pool); with one, its dishes are drawn from it."""
    pool = [d for d in cup["dishes"] if category in (None, "all") or cup["categories"][d] == category]
    ids = pool[:entrants]
    game = {"entrants": ids, "winners": ids[0:winners * 2:2], "stack": [], "log": []}
    if category:
        game["category"] = category
    return {"v": 1, "set": f"{cup['size']}:" + ",".join(cup["dishes"]), "winners": [], "game": game}


def worldcup_play(page):
    """The menu world cup (worldcup.html): a whole bracket by keyboard, one undo, the winner kept
    only in this browser. The context runs with reduced motion, so each pick renders at once and no
    round splash opens; worldcup_splash plays them with motion."""
    count = 0

    def check(ok, detail):
        nonlocal count
        assert ok, f"worldcup.html: {detail}"
        count += 1

    cup = json.loads((ROOT / "data/content/worldcup.json").read_text(encoding="utf-8"))
    dishes, size = cup["dishes"], cup["size"]
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto("https://site-ui.invalid/worldcup.html", wait_until="networkidle")
    page.evaluate("localStorage.removeItem('babdoduk-worldcup')")
    page.reload(wait_until="networkidle")
    page.evaluate(SPLASH_LOG)
    page.locator("#wcStart").click()
    check(page.locator("#wcRound").inner_text() == "32강" and page.locator("#wcCount").inner_text() == "1 / 16"
          and page.evaluate("document.activeElement.classList.contains('wc-card')"), "the first match has focus on a card")
    first = page.locator(".wc-card").first.get_attribute("data-id")
    page.keyboard.press("Enter")
    check(page.locator("#wcCount").inner_text() == "2 / 16", "a pick moves to the next match")
    page.locator("#wcUndo").click()
    check(page.locator(".wc-card").first.get_attribute("data-id") == first and page.locator("#wcCount").inner_text() == "1 / 16",
          "undo returns to the same match")
    check(page.locator("#wcUndo").is_disabled(), "nothing to undo on the first match of a fresh game")
    # 처음부터 draws a new bracket, and 되돌리기 takes it back (owner 2026-10-13: no confirm step).
    page.locator(".wc-card").first.focus()
    page.keyboard.press("Enter")
    second = [page.locator(".wc-card").nth(i).get_attribute("data-id") for i in (0, 1)]
    page.locator("#wcRestart").click()
    check(page.locator("#wcCount").inner_text() == "1 / 16" and page.locator("#wcUndo").is_enabled(),
          "a restart draws a new bracket that undo can take back")
    page.locator(".wc-card").first.focus()
    page.keyboard.press("Enter")
    page.locator("#wcUndo").click()
    page.locator("#wcUndo").click()
    check([page.locator(".wc-card").nth(i).get_attribute("data-id") for i in (0, 1)] == second
          and page.locator("#wcCount").inner_text() == "2 / 16", "undo after a restart brings the earlier bracket back")
    page.locator("#wcUndo").click()
    check(page.locator(".wc-card").first.get_attribute("data-id") == first and page.locator("#wcUndo").is_disabled(),
          "and on to its first match, with nothing left to undo")
    page.locator(".wc-card").first.focus()
    on_first = "document.activeElement === document.querySelector('.wc-card')"
    for i in range(size - 1):
        if i:
            check(page.evaluate(on_first), ("after each pick focus is on the next match's first card", i))
        page.keyboard.press("Enter")
        if i == size // 2 + size // 4 - 1:              # the round of 16 just closed
            page.wait_for_function("document.getElementById('wcStatus').textContent.startsWith('8강 1번째 경기')")
            check(page.locator("#wcRound").inner_text() == "8강" and not page.evaluate(SPLASH_OPEN),
                  "with reduced motion the 8강 match comes at once, announced, without a splash")
    check(page.locator("#wcResult").is_visible() and page.evaluate("document.activeElement.id") == "wcWinner",
          "after the final the winner is shown and focused")
    check(page.evaluate("window.__splashes") == [], ("reduced motion: no round splash at all", page.evaluate("window.__splashes")))
    saved = page.evaluate("JSON.parse(localStorage.getItem('babdoduk-worldcup'))")
    check(saved["game"] is None and len(saved["winners"]) == 1 and saved["winners"][0]["id"] in dishes,
          ("the winner is kept in this browser only", saved["winners"]))
    check(page.locator("#wcHistoryList li").count() == 1, "the past winner is listed")
    return count


def worldcup_categories(page):
    """The world cup's categories (owner 2026-10-14): big tiles with an emoji and a count above the
    start button, toggled by keyboard, 아무거나 landing on another category, five photos of the very
    bracket the start then plays, a game drawn from the chosen category, the category shown while
    playing and on the result, kept by resume, and an older save without one read as the whole pool.
    Also the start screen itself: the owner's headline and tone line, and no notes under the button.
    The context runs with reduced motion: 아무거나 lands at once and no gacha opens."""
    count = 0

    def check(ok, detail):
        nonlocal count
        assert ok, f"worldcup.html categories: {detail}"
        count += 1

    def save(state):
        page.evaluate("s => localStorage.setItem('babdoduk-worldcup', JSON.stringify(s))", state)

    cup = json.loads((ROOT / "data/content/worldcup.json").read_text(encoding="utf-8"))
    cats = cup["categories"]
    korean = [d for d in cup["dishes"] if cats[d] == "korean"]
    stored = "JSON.parse(localStorage.getItem('babdoduk-worldcup')).game"
    chips = ("[...document.querySelectorAll('#wcCats .wc-tile[aria-pressed]')].map(c => [c.dataset.cat,"
             " c.querySelector('.wc-tile-name').textContent + c.querySelector('.wc-tile-n').textContent,"
             " c.getAttribute('aria-pressed'), c.querySelector('.wc-tile-emoji').textContent])")
    preview = "[...document.querySelectorAll('#wcPreviewPhotos img')].map(i => i.dataset.id)"
    for size in ((390, 844), (1280, 800)):
        page.set_viewport_size({"width": size[0], "height": size[1]})
        page.goto("https://site-ui.invalid/worldcup.html", wait_until="networkidle")
        page.evaluate("localStorage.removeItem('babdoduk-worldcup')")
        page.reload(wait_until="networkidle")
        got = page.evaluate(chips)
        check([c[0] for c in got] == ["all", "korean", "chinese", "japanese", "western", "world", "snack", "dessert"],
              ("the eight chips in order", got))
        check([c[1] for c in got] == ["전체763개", "한식268개", "중식75개", "일식75개", "양식132개", "아시아·세계86개",
                                      "분식·간식35개", "디저트·카페92개"], ("each tile carries its count", got))
        check([c[3] for c in got] == ["🎲", "🍚", "🥟", "🍣", "🍝", "🍜", "🍢", "🍰"], ("each tile its emoji", got))
        check([c[2] for c in got] == ["true"] + ["false"] * 7, ("전체 is chosen by default", got))
        check(page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (size, "no horizontal scroll with the tiles"))
        above = page.evaluate("document.querySelector('#wcCats').getBoundingClientRect().bottom <= "
                              "document.querySelector('#wcStart').getBoundingClientRect().top")
        check(above, "the tiles sit above the start button")
        board = page.evaluate("""() => { const t = [...document.querySelectorAll('#wcCats .wc-tile')];   // layout boxes: the chosen one is tilted
          return {n: t.length, cols: new Set(t.map(e => e.offsetLeft)).size, minH: Math.min(...t.map(e => e.offsetHeight)),
                  minW: Math.min(...t.map(e => e.offsetWidth))}; }""")
        check(board["n"] == 9 and board["cols"] == 3 and board["minH"] >= 88 and board["minW"] >= 80,
              (size, "nine big tiles on a 3-column board, roomy at a phone's width", board))
        intro = page.evaluate("""() => ({title: document.getElementById('wcIntroTitle').textContent,
          mark: document.querySelector('#wcIntroTitle .wc-hl').textContent,
          tone: document.querySelector('.wc-intro-tone').textContent,
          notes: document.querySelectorAll('#wcIntro .wc-note').length,
          text: document.getElementById('wcIntro').innerText})""")
        check(intro["title"] == "오늘의 32강, 뭐가 나올까?" and intro["mark"] == "32강"
              and intro["tone"] == "시험기간으로 지친 당신! 메뉴나 골라~", ("the owner's headline and tone line", intro))
        check(intro["notes"] == 0 and "이 브라우저에 저장돼요" not in intro["text"] and "익명으로 집계" not in intro["text"]
              and "무작위로 뽑아요" not in intro["text"], "no notes under the button any more")
        shown = page.evaluate(preview)
        check(len(shown) == 5 and len(set(shown)) == 5, ("five photos of the next draw", shown))
    page.set_viewport_size({"width": 390, "height": 844})

    # Tiles by keyboard: Tab reaches them, Space and Enter choose; the focus ring is visible.
    page.locator('#wcCats [data-cat="all"]').focus()
    page.keyboard.press("Tab")
    check(page.evaluate("document.activeElement.dataset.cat") == "korean", "Tab moves to the next tile")
    check(page.evaluate("getComputedStyle(document.activeElement).outlineStyle") != "none", "a focused tile shows a focus ring")
    page.keyboard.press("Space")
    got = page.evaluate(chips)
    check([c[0] for c in got if c[2] == "true"] == ["korean"], ("Space on 한식 chooses it alone", got))
    page.locator('#wcCats [data-cat="dessert"]').focus()
    page.keyboard.press("Enter")
    check([c[0] for c in page.evaluate(chips) if c[2] == "true"] == ["dessert"], "Enter chooses a tile too")
    # 아무거나 (reduced motion: at once) lands on another category and says which.
    for _ in range(3):
        before = [c[0] for c in page.evaluate(chips) if c[2] == "true"][0]
        page.locator('#wcCats [data-cat="random"]').focus()
        page.keyboard.press("Enter")
        after = [c[0] for c in page.evaluate(chips) if c[2] == "true"]
        page.wait_for_function("document.getElementById('wcStatus').textContent.endsWith('당첨!')")
        check(len(after) == 1 and after[0] != before and page.locator("#wcCats .wc-tile--random").get_attribute("aria-pressed") is None,
              ("아무거나 lands on one other category", before, after))
    page.locator('#wcCats [data-cat="korean"]').click()
    check(page.locator("#wcStartLabel").inner_text() == "32강 시작", "the start button still says 32강 시작")
    teased = page.evaluate(preview)
    check(len(teased) == 5 and all(cats[d] == "korean" for d in teased), ("the photos follow the chosen category", teased))

    # 32 cards, all from 한식, and the category on the round header; the five photos were really in it.
    page.locator("#wcStart").click()
    check(page.evaluate("window.__splashes || []") == [] and not page.evaluate(SPLASH_OPEN), "reduced motion: no start gacha")
    game = page.evaluate(stored)
    check(set(teased) <= set(game["entrants"]), ("이 중에서 나와요: the five photos are in the game", teased))
    check(len(game["entrants"]) == 32 and len(set(game["entrants"])) == 32 and set(game["entrants"]) <= set(korean)
          and game["category"] == "korean", ("32 distinct 한식 dishes are drawn", game["category"], len(game["entrants"])))
    check(page.locator("#wcGame").inner_text() == "한식 32강" and page.locator("#wcRound").inner_text() == "32강",
          ("the category shows over the round", page.locator("#wcGame").inner_text()))
    shown = [page.locator(".wc-card").nth(i).get_attribute("data-id") for i in (0, 1)]
    check(all(cats[d] == "korean" for d in shown), ("the cards on screen are 한식", shown))
    page.keyboard.press("Enter")

    # Resume keeps it, also after a reload.
    page.reload(wait_until="networkidle")
    resume = page.locator("#wcResume").inner_text()
    check("한식" in resume and page.locator('#wcCats [data-cat="korean"]').get_attribute("aria-pressed") == "true",
          ("the saved 한식 game is offered and its chip chosen", resume))
    page.locator("#wcResume").click()
    check(page.locator("#wcGame").inner_text() == "한식 32강" and page.locator("#wcCount").inner_text() == "2 / 16"
          and page.evaluate(stored)["category"] == "korean", "resuming plays the same 한식 game")
    # 처음부터 stays in the category.
    page.locator("#wcRestart").click()
    check(page.evaluate(stored)["category"] == "korean" and set(page.evaluate(stored)["entrants"]) <= set(korean),
          "a restart draws a new bracket from the same category")

    # English: the chips, the header and the resume label follow the language.
    page.locator("#langToggle").click()
    check(page.locator("#wcGame").inner_text() == "Korean · Round of 32", ("the header in English", page.locator("#wcGame").inner_text()))
    save(worldcup_saved(cup, 16, 7, "korean"))
    page.reload(wait_until="networkidle")
    got = page.evaluate(chips)
    check([c[1] for c in got] == ["All763 dishes", "Korean268 dishes", "Chinese75 dishes", "Japanese75 dishes", "Western132 dishes",
                                  "Asian & world86 dishes", "Snacks35 dishes", "Desserts & café92 dishes"], ("the tiles in English", got))
    check(page.locator("#wcIntroTitle").inner_text() == "What\u2019s in today\u2019s round of 32?"
          and page.locator("#wcIntroTitle .wc-hl").inner_text() == "round of 32", page.locator("#wcIntroTitle").inner_text())
    check("Korean" in page.locator("#wcResume").inner_text() and page.locator("#wcNew").is_visible()
          and page.locator("#wcStart").is_hidden(), ("a saved game: the big 이어하기 and a small 새로 시작", page.locator("#wcResume").inner_text()))
    page.locator("#langToggle").click()

    # An older save has no category: whole pool, readable, resumable.
    save(worldcup_saved(cup, 16, 7))
    page.reload(wait_until="networkidle")
    check(page.locator("#wcResume").is_visible() and "전체" in page.locator("#wcResume").inner_text()
          and page.locator('#wcCats [data-cat="all"]').get_attribute("aria-pressed") == "true", "an older save counts as 전체")
    page.locator("#wcResume").click()
    check(page.locator("#wcGame").inner_text() == "전체 32강" and page.locator("#wcCount").inner_text() == "8 / 8",
          "and resumes as 전체 32강")

    # The result shows the category too.
    save(worldcup_saved(cup, 2, 0, "korean"))
    page.reload(wait_until="networkidle")
    page.locator("#wcResume").click()
    page.keyboard.press("Enter")
    check(page.locator("#wcResult").is_visible() and page.locator("#wcResultGame").inner_text() == "한식 32강",
          ("the result names the category", page.locator("#wcResultGame").inner_text()))
    # Playing again keeps the category.
    page.locator("#wcAgain").click()
    check(page.evaluate(stored)["category"] == "korean", "다시 하기 plays the same category")

    # An unreadable category in a save is dropped rather than trusted.
    bad = worldcup_saved(cup, 16, 7, "korean")
    bad["game"]["category"] = "brunch"
    save(bad)
    page.reload(wait_until="networkidle")
    check(page.locator("#wcResume").is_hidden(), "a save with an unknown category is not offered")
    page.evaluate("localStorage.removeItem('babdoduk-worldcup')")
    return count


def worldcup_splash(page):
    """The round splash with motion (owner 2026-10-14): none for 16강; 8강 and 4강 a black stage
    with the round, above the navigation, the match already rendered, focused and announced
    beneath; the final adds the crash of the two finalists. Enter, Space, a held key or a tap
    skips it and never picks; played out (finish() on its animations, so no wall clock) it hands
    over to the match; a failing animation never blocks the game. Saved games are seeded just
    before each round closes, so only a handful of picks run with motion."""
    count = 0

    def check(ok, detail):
        nonlocal count
        assert ok, f"worldcup.html splash: {detail}"
        count += 1

    cup = json.loads((ROOT / "data/content/worldcup.json").read_text(encoding="utf-8"))
    page.emulate_media(reduced_motion="no-preference")
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto("https://site-ui.invalid/worldcup.html", wait_until="networkidle")
    stored = "JSON.parse(localStorage.getItem('babdoduk-worldcup')).game"
    on_first = "document.activeElement === document.querySelector('.wc-card')"
    closed = "!" + SPLASH_OPEN
    shown = "[...document.querySelectorAll('.wc-card')].every(c => getComputedStyle(c).opacity === '1')"

    def close_round(entrants):
        """Seed the last match of a round of `entrants`, resume, and pick it by keyboard."""
        page.evaluate("s => localStorage.setItem('babdoduk-worldcup', JSON.stringify(s))",
                      worldcup_saved(cup, entrants, entrants // 2 - 1))
        page.reload(wait_until="networkidle")
        page.evaluate(SPLASH_LOG)
        page.locator("#wcResume").click()
        page.locator(".wc-card").first.focus()
        page.keyboard.press("Enter")

    close_round(32)
    page.wait_for_function("document.getElementById('wcRound').textContent === '16강'")
    check(page.evaluate("window.__splashes") == [] and page.evaluate(on_first), "no splash for the round of 16")

    close_round(16)
    page.wait_for_function(SPLASH_OPEN)
    seen = page.evaluate(r"""() => { const s = document.querySelector('#wcSplash');
      const nav = document.querySelector('.site-nav').getBoundingClientRect();
      const top = document.elementFromPoint(nav.left + nav.width / 2, nav.top + nav.height / 2);
      return {round: s.dataset.round, title: s.querySelector('.wc-splash-title').textContent.replace(/\s/g, ' '), overNav: s.contains(top),
              fighters: s.querySelectorAll('.wc-fighter').length, hidden: s.getAttribute('aria-hidden')}; }""")
    check(seen == {"round": "8", "title": "8강 진출!", "overNav": True, "fighters": 0, "hidden": "true"},
          ("8강: the round alone on a stage above the navigation, hidden from screen readers", seen))
    check(page.locator("#wcRound").inner_text() == "8강" and page.evaluate(on_first),
          "the 8강 match is already rendered and focused under it")
    page.wait_for_function("document.getElementById('wcStatus').textContent.startsWith('8강 1번째 경기')")
    check(page.evaluate(SPLASH_OPEN), "and announced while the splash plays")
    page.keyboard.press("Enter")
    page.wait_for_function(closed)
    game = page.evaluate(stored)
    check(len(game["entrants"]) == 8 and game["winners"] == [] and page.evaluate(on_first)
          and page.locator("#wcCount").inner_text() == "1 / 4", ("Enter skips to the match without a pick", game["winners"]))

    close_round(8)
    page.wait_for_function(SPLASH_OPEN)
    check(page.evaluate("window.__splashes") == ["4"], "4강 gets the splash")
    page.keyboard.press(" ")
    page.wait_for_function(closed)
    game = page.evaluate(stored)
    check(len(game["entrants"]) == 4 and game["winners"] == [] and page.evaluate(on_first),
          ("Space skips without a pick, even on its release", game["winners"]))

    # A key held through the skip: its repeats are swallowed, so they never pick.
    close_round(8)
    page.wait_for_function(SPLASH_OPEN)
    page.keyboard.down("Enter")
    page.wait_for_function(closed)
    page.keyboard.down("Enter")                       # Playwright sends a second down as a repeat
    page.keyboard.down("Enter")
    page.keyboard.up("Enter")
    game = page.evaluate(stored)
    check(len(game["entrants"]) == 4 and game["winners"] == [] and page.evaluate(on_first),
          ("a held key skips once and never picks", game["winners"]))

    # A screen reader activates the card under the splash: that ends the splash, it is not a pick.
    # The splash is held still first and the click must end it within a second, long before its
    # safety timer would.
    close_round(8)
    page.wait_for_function(SPLASH_OPEN)
    page.evaluate("() => document.querySelector('#wcSplash').getAnimations({subtree: true}).forEach(a => a.pause())")
    page.evaluate("() => document.querySelector('.wc-card').click()")
    try:
        page.wait_for_function(closed, timeout=1000)
        ended = True
    except PlaywrightTimeoutError:
        ended = False
    game = page.evaluate(stored)
    check(ended and len(game["entrants"]) == 4 and game["winners"] == [],
          ("a click from assistive technology only ends it", ended, game["winners"]))

    close_round(4)
    page.wait_for_function(SPLASH_OPEN)
    crash = page.evaluate("""() => { const s = document.querySelector('#wcSplash');
      return {round: s.dataset.round, title: s.querySelector('.wc-splash-title').textContent,
              fighters: [...s.querySelectorAll('.wc-fighter-face .wc-card-name')].map(n => n.textContent),
              cards: [...document.querySelectorAll('.wc-card')].map(c => c.querySelector('.wc-card-name').textContent),
              hiddenCards: [...document.querySelectorAll('.wc-card')].every(c => c.style.opacity === '0'),
              vs: s.querySelector('.wc-splash-vs').textContent, flashes: s.querySelectorAll('.wc-splash-flash').length}; }""")
    check(crash["round"] == "2" and crash["title"] == "결승!" and crash["fighters"] == crash["cards"]
          and len(crash["cards"]) == 2 and crash["hiddenCards"] and crash["vs"] == "VS" and crash["flashes"] == 1,
          ("the final: the two finalists' doubles crash under a VS stamp, with one flash", crash))
    page.mouse.click(195, 422)                        # a tap in the middle, over where the cards are
    page.wait_for_function(closed)
    game = page.evaluate(stored)
    check(len(game["entrants"]) == 2 and game["winners"] == [] and page.evaluate(on_first) and page.evaluate(shown),
          ("a tap skips to the final without a pick, the cards shown again", game["winners"]))

    # The phone crash, on a 360 px screen: the finalists clash about 1.5x their size (on a
    # diagonal, a phone's pair already fills the width), stay on the screen from the hit to the
    # end, the VS never covers a name, and they land exactly on the real cards. Read in one call
    # with the splash held still and seeked, so no timer runs in between.
    page.set_viewport_size({"width": 360, "height": 800})
    close_round(4)
    page.wait_for_function(SPLASH_OPEN)
    geometry = page.evaluate(SPLASH_GEOMETRY)
    check(geometry["outside"] == 0 and 1.45 <= geometry["scale"] <= 1.7 and geometry["covered"] == 0 and geometry["miss"] < 1,
          ("phone crash: bigger, on the screen, VS clear of the names, landing on the cards", geometry))

    # Played out: finish() runs the splash to its end (no waiting on the clock).
    page.evaluate("document.querySelector('#wcSplash').getAnimations({subtree: true}).forEach(a => a.finish())")
    page.wait_for_function(closed)
    check(page.evaluate(on_first) and page.locator("#wcCount").inner_text() == "1 / 1" and page.evaluate(shown)
          and page.evaluate("document.querySelector('#wcSplash').childElementCount") == 0,
          "played out, the splash hands over to the final with focus on its first card")
    page.keyboard.press("Enter")
    check(page.locator("#wcResult").is_visible() and page.evaluate("document.activeElement.id") == "wcWinner",
          "and the final is played to the winner")
    page.set_viewport_size({"width": 390, "height": 844})

    # A splash that never finishes (held still here) still ends by itself and gives the match back.
    close_round(16)
    page.wait_for_function(SPLASH_OPEN)
    page.evaluate("() => document.querySelector('#wcSplash').getAnimations({subtree: true}).forEach(a => a.pause())")
    page.wait_for_function(closed, timeout=8000)
    check(page.evaluate(on_first) and page.evaluate(shown) and len(page.evaluate(stored)["entrants"]) == 8,
          "a stuck splash ends by itself, focus on the 8강 match")

    # Anything failing only takes the splash away: the match still comes and takes picks.
    page.evaluate("s => localStorage.setItem('babdoduk-worldcup', JSON.stringify(s))", worldcup_saved(cup, 16, 7))
    page.reload(wait_until="networkidle")
    page.evaluate("() => { Element.prototype.animate = () => { throw new Error('no animation'); }; }")
    page.locator("#wcResume").click()
    page.locator(".wc-card").first.focus()
    page.keyboard.press("Enter")
    page.wait_for_function("document.getElementById('wcRound').textContent === '8강'")
    check(page.evaluate(closed) and page.evaluate(on_first), "a failing splash leaves the 8강 match open")
    page.keyboard.press("Enter")
    check(len(page.evaluate(stored)["winners"]) == 1, "and its cards still take a pick")

    page.evaluate("localStorage.removeItem('babdoduk-worldcup')")
    page.emulate_media(reduced_motion="reduce")
    page.reload(wait_until="networkidle")
    return count

def worldcup_gacha(page):
    """The start gacha with motion (owner 2026-10-14): 32강 시작, 새로 시작, 처음부터 and 다시 하기 open
    it, 이어하기 never; the game is stored and its first match rendered, focused and announced
    beneath; six of the drawn dishes pour out; a key or a tap skips it without a pick; played out
    (finish(), no wall clock) it hands over to the match; reduced motion has none of it. The start
    screen's own motion is over within 5 s and moves only transform, scale and opacity."""
    count = 0

    def check(ok, detail):
        nonlocal count
        assert ok, f"worldcup.html gacha: {detail}"
        count += 1

    cup = json.loads((ROOT / "data/content/worldcup.json").read_text(encoding="utf-8"))
    stored = "JSON.parse(localStorage.getItem('babdoduk-worldcup')).game"
    on_first = "document.activeElement === document.querySelector('.wc-card')"
    closed = "!" + SPLASH_OPEN
    shown = "[...document.querySelectorAll('.wc-card')].every(c => getComputedStyle(c).opacity === '1')"
    page.emulate_media(reduced_motion="no-preference")
    for width, height in ((390, 844), (1280, 800)):
        page.set_viewport_size({"width": width, "height": height})
        page.goto("https://site-ui.invalid/worldcup.html", wait_until="networkidle")
        page.evaluate("localStorage.removeItem('babdoduk-worldcup')")
        page.reload(wait_until="networkidle")
        page.evaluate(SPLASH_LOG)
        motion = page.evaluate("""() => document.getAnimations().filter(a => a.effect && a.effect.target
          && a.effect.target.closest('#wcIntro')).map(a => {
          const t = a.effect.getComputedTiming(), k = a.effect.getKeyframes();
          return {end: t.endTime, props: [...new Set(k.flatMap(f => Object.keys(f)))]
            .filter(p => !['offset', 'computedOffset', 'easing', 'composite'].includes(p))}; })""")
        check(motion and max(m["end"] for m in motion) <= 5000, (width, "the arrival motion ends within 5 s", motion))
        check({p for m in motion for p in m["props"]} <= {"transform", "scale", "opacity"}, (width, "only transform, scale, opacity", motion))
        teased = page.evaluate("[...document.querySelectorAll('#wcPreviewPhotos img')].map(i => i.dataset.id)")
        page.locator("#wcStart").click()
        page.wait_for_function(SPLASH_OPEN)
        seen = page.evaluate("""() => { const s = document.querySelector('#wcSplash');
          return {round: s.dataset.round, line: s.querySelector('.wc-gacha-line').textContent,
                  ask: s.querySelector('.wc-gacha-ask').textContent, hidden: s.getAttribute('aria-hidden'),
                  caps: [...s.querySelectorAll('.wc-gacha-caps .wc-cap-photo')].map(i => i.getAttribute('src')),
                  duel: [...s.querySelectorAll('.wc-duelist img')].map(i => i.getAttribute('src')),
                  cards: [...document.querySelectorAll('.wc-card')].map(c => getComputedStyle(c).opacity)}; }""")
        game = page.evaluate(stored)
        photo = lambda d: cup["photos"][d]["image"]
        check(seen["round"] == "start" and seen["line"] == "전체 32강 뽑는 중…" and seen["ask"] == "너의 최애는?"
              and seen["hidden"] == "true", (width, "the gacha opens with its one line and its question", seen))
        check(seen["caps"] == [photo(d) for d in game["entrants"][2:8]] + [photo(d) for d in game["entrants"][:2]]
              and seen["duel"] == [photo(d) for d in game["entrants"][:2]], (width, "it pours the drawn dishes, the first two last"))
        check(set(teased) <= set(game["entrants"]) and game["winners"] == [], "the stored game is the bracket previewed")
        check(seen["cards"] == ["0", "0"] and page.evaluate(on_first) and page.locator("#wcRound").inner_text() == "32강",
              "under it the first match is rendered and focused, its cards waiting")
        page.wait_for_function("document.getElementById('wcStatus').textContent.startsWith('32강 1번째 경기')")
        page.keyboard.press("Enter")
        page.wait_for_function(closed)
        check(page.evaluate(stored)["winners"] == [] and page.evaluate(on_first) and page.evaluate(shown),
              (width, "Enter skips to the match without a pick"))

    # 처음부터 plays it again; a tap anywhere skips it, never a pick.
    page.locator("#wcRestart").click()
    page.wait_for_function(SPLASH_OPEN)
    page.mouse.click(640, 400)
    page.wait_for_function(closed)
    check(page.evaluate(stored)["winners"] == [] and page.evaluate(on_first) and page.evaluate(shown), "a tap skips it without a pick")
    # Played out, it lands on the match.
    page.locator("#wcRestart").click()
    page.wait_for_function(SPLASH_OPEN)
    page.evaluate("document.getAnimations().forEach(a => { if (a.effect && isFinite(a.effect.getComputedTiming().endTime)) a.finish(); })")
    page.wait_for_function(closed)
    check(page.evaluate(on_first) and page.evaluate(shown) and page.evaluate("document.querySelector('#wcSplash').childElementCount") == 0
          and page.evaluate(stored)["winners"] == [], "played out, it hands over to the first match")
    page.keyboard.press("Enter")
    page.wait_for_function("document.getElementById('wcCount').textContent === '2 / 16'")
    check(page.evaluate(stored)["winners"] != [], "and the match takes a pick")
    # 이어하기 never plays it.
    page.reload(wait_until="networkidle")
    page.evaluate(SPLASH_LOG)
    page.locator("#wcResume").click()
    check(page.evaluate("window.__splashes") == [] and page.evaluate(on_first) and page.locator("#wcCount").inner_text() == "2 / 16",
          "이어하기 goes straight to the match")
    # 새로 시작 under 이어하기 does.
    page.reload(wait_until="networkidle")
    page.evaluate(SPLASH_LOG)
    page.locator("#wcNew").click()
    page.wait_for_function(SPLASH_OPEN)
    check(page.evaluate("window.__splashes") == ["start"], "새로 시작 opens the gacha")
    page.keyboard.press("Escape")
    page.wait_for_function(closed)
    page.evaluate("localStorage.removeItem('babdoduk-worldcup')")
    page.set_viewport_size({"width": 390, "height": 844})
    page.emulate_media(reduced_motion="reduce")
    # Reduced motion: still pictures, a still button, and the match at once.
    page.reload(wait_until="networkidle")
    page.evaluate(SPLASH_LOG)
    check(page.evaluate("document.getAnimations().filter(a => a.effect && a.effect.target && a.effect.target.closest('#wcIntro')).length") == 0
          and page.locator(".wc-floater").count() >= 4,
          "reduced motion: the photos are there and nothing moves")
    page.locator("#wcStart").click()
    check(page.evaluate("window.__splashes") == [] and page.evaluate(on_first), "reduced motion: no gacha")
    page.evaluate("localStorage.removeItem('babdoduk-worldcup')")
    page.reload(wait_until="networkidle")
    return count


# Counts the AudioContexts a page makes; the real one is kept (headless Chromium plays it to no device).
WC_AUDIO = """(() => { const A = window.AudioContext; if (!A) return; let n = 0;
  class Counted extends A { constructor(...args) { super(...args); n++; window.__audio = this; } }
  window.AudioContext = Counted; window.webkitAudioContext = Counted; window.__audioContexts = () => n; })();"""
SOUND_STATE = """() => { const dock = document.getElementById('wcSoundDock'), b = document.getElementById('wcSound');
  const r = b.getBoundingClientRect(), top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
  return {shown: !dock.hidden && r.width >= 44 && r.height >= 44, pressed: b.getAttribute('aria-pressed'),
          label: b.getAttribute('aria-label'), text: b.querySelector('.wc-sound-label').textContent,
          onTop: !!top && b.contains(top), contexts: window.__audioContexts ? window.__audioContexts() : -1,
          state: window.__audio ? window.__audio.state : null, stored: localStorage.getItem('babdoduk-worldcup-sound'),
          splash: document.querySelector('#wcSplash').matches(':popover-open')}; }"""


def worldcup_sound(page):
    """The music toggle (owner 2026-10-14): original music and effects synthesized in the page, off on a
    first visit; the first press makes the one AudioContext; aria-pressed follows; the choice is kept
    (but reduced motion starts off every visit); in the start gacha the toggle sits above the scene and
    neither a tap nor Enter or Space on it skips the scene; the music sleeps with a hidden tab; before
    the launch the toggle works and nothing of the game starts. No page error throughout."""
    count = 0

    def check(ok, detail):
        nonlocal count
        assert ok, f"worldcup.html sound: {detail}"
        count += 1

    errors = []
    on_error = lambda exc: errors.append(str(exc)[:200])
    page.on("pageerror", on_error)
    state = lambda: page.evaluate(SOUND_STATE)
    stored = "JSON.parse(localStorage.getItem('babdoduk-worldcup')).game"
    running = "window.__audio && window.__audio.state === 'running'"
    try:
        page.add_init_script(WC_AUDIO)
        page.emulate_media(reduced_motion="no-preference")
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto("https://site-ui.invalid/worldcup.html", wait_until="networkidle")
        page.evaluate("localStorage.removeItem('babdoduk-worldcup'); localStorage.removeItem('babdoduk-worldcup-sound')")
        page.reload(wait_until="networkidle")
        s = state()
        check(s["shown"] and s["pressed"] == "false" and s["label"] == "배경음악 켜기/끄기" and s["text"] == "배경음악"
              and s["contexts"] == 0 and s["stored"] is None, ("a first visit: the toggle is there, off, and makes no audio", s))
        page.locator('.wc-tile[data-cat="korean"]').click()
        check(state()["contexts"] == 0, "a tile while sound is off makes no AudioContext")
        page.locator("#wcSound").click()
        page.wait_for_function(running)
        s = state()
        check(s["pressed"] == "true" and s["contexts"] == 1 and s["stored"] == "1", ("the press turns it on: one AudioContext", s))
        # In the start gacha the toggle is above the scene; neither a tap nor a key on it skips the scene.
        page.locator("#wcStart").click()
        page.wait_for_function(SPLASH_OPEN)
        page.evaluate("document.getAnimations().forEach(a => a.pause())")   # hold the scene still while it is pressed
        check(state()["onTop"], "the toggle sits above the gacha")
        page.locator("#wcSound").click()
        s = state()
        check(s["splash"] and s["pressed"] == "false" and s["stored"] == "0", ("a tap on it in the gacha turns it off, no skip", s))
        page.locator("#wcSound").click()
        page.keyboard.press("Enter")
        s = state()
        check(s["splash"] and s["pressed"] == "false" and s["contexts"] == 1, ("Enter on it toggles too, no skip", s))
        page.keyboard.press(" ")
        s = state()
        check(s["splash"] and s["pressed"] == "true" and s["contexts"] == 1, ("and Space, no skip, still one AudioContext", s))
        page.keyboard.press("Escape")
        page.wait_for_function("!" + SPLASH_OPEN)
        check(page.evaluate(stored)["winners"] == [] and state()["shown"], "the scene skips as before, without a pick; the toggle stays")
        page.locator(".wc-card").first.focus()
        page.keyboard.press("Enter")
        page.wait_for_function("document.getElementById('wcCount').textContent === '2 / 16'")
        check(state()["contexts"] == 1, "a pick plays its effect on the same AudioContext")
        # A hidden tab: the music sleeps, and wakes when the tab is back.
        page.evaluate("Object.defineProperty(document, 'hidden', {configurable: true, get: () => true});"
                      "document.dispatchEvent(new Event('visibilitychange'))")
        page.wait_for_function("window.__audio.state === 'suspended'")
        page.evaluate("delete document.hidden; document.dispatchEvent(new Event('visibilitychange'))")
        page.wait_for_function(running)
        check(state()["contexts"] == 1, "a hidden tab suspends it and its return resumes it")
        # The choice is kept: the next visit shows it on and starts at the first press anywhere.
        page.reload(wait_until="networkidle")
        s = state()
        check(s["pressed"] == "true" and s["contexts"] == 0, ("remembered on, nothing made before a press", s))
        page.locator(".wc-intro-title").click()
        page.wait_for_function(running)
        check(state()["contexts"] == 1, "the first press anywhere starts the remembered music")
        page.locator("#wcSound").click()
        page.wait_for_function("window.__audio.state === 'suspended'")
        check(state()["pressed"] == "false", "turned off, the music fades and the context sleeps")
        page.reload(wait_until="networkidle")
        s = state()
        check(s["pressed"] == "false" and s["stored"] == "0", ("turned off, it stays off", s))
        # Reduced motion: available, but off on every visit.
        page.evaluate("localStorage.setItem('babdoduk-worldcup-sound', '1')")
        page.emulate_media(reduced_motion="reduce")
        page.reload(wait_until="networkidle")
        s = state()
        check(s["shown"] and s["pressed"] == "false" and s["contexts"] == 0, ("reduced motion: there, but off", s))
        # English.
        page.evaluate("localStorage.setItem('babdoduk-lang', 'en')")
        page.reload(wait_until="networkidle")
        s = state()
        check(s["label"] == "Turn music on/off" and s["text"] == "Music", ("the toggle in English", s))
        page.evaluate("localStorage.setItem('babdoduk-lang', 'ko')")
        # Before the launch: the toggle works, and nothing of the game starts.
        page.clock.set_fixed_time(WC_SOON)
        page.evaluate("localStorage.removeItem('babdoduk-worldcup'); localStorage.removeItem('babdoduk-worldcup-sound')")
        page.reload(wait_until="networkidle")
        page.locator("#wcSound").click()
        page.wait_for_function(running)
        s = state()
        check(s["pressed"] == "true" and s["contexts"] == 1 and page.evaluate("document.documentElement.dataset.wcPhase") == "soon"
              and page.locator("#wcLocked").is_visible() and page.locator("#wcMatch").is_hidden()
              and not page.evaluate("localStorage.getItem('babdoduk-worldcup')") and not s["splash"],
              ("before the launch the toggle plays music and nothing of the game", s))
        check(not errors, ("no page error", errors[:3]))
    finally:
        page.remove_listener("pageerror", on_error)
        page.clock.set_fixed_time(WC_RUNNING)
        page.evaluate("localStorage.removeItem('babdoduk-worldcup'); localStorage.removeItem('babdoduk-worldcup-sound');"
                      "localStorage.setItem('babdoduk-lang', 'ko')")
        page.emulate_media(reduced_motion="reduce")
    return count


def worldcup_final_saved(cup, category):
    """A stored game at its final, with the whole bracket's log up to it (the last two entries are the
    semifinals), so the next pick ends it with a runner-up and two semifinalists. Returns (save, ids)."""
    pool = [d for d in cup["dishes"] if cup["categories"][d] == category]
    winner, finalist, semi_a, semi_b = pool[:4]
    filler = pool[4:]
    log = [[filler[i % len(filler)], filler[(i + 1) % len(filler)]] for i in range(0, 2 * (cup["size"] - 4), 2)]
    log += [[winner, semi_a], [finalist, semi_b]]
    game = {"entrants": [winner, finalist], "winners": [], "stack": [], "log": log, "category": category}
    save = {"v": 1, "set": f"{cup['size']}:" + ",".join(cup["dishes"]), "winners": [], "game": game}
    return save, (winner, finalist, semi_a, semi_b)


def png_size(data):
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


# The story card's preview, redrawn on a fresh canvas and exported: works only for an untainted image.
STORY_SNAP = """() => { const img = document.getElementById('wcStoryPreview'), q = s => document.querySelector(s);
  let exported = null, pixel = null;
  if (img && !img.hidden && img.naturalWidth) {
    const c = document.createElement('canvas'); c.width = img.naturalWidth; c.height = img.naturalHeight;
    const ctx = c.getContext('2d'); ctx.drawImage(img, 0, 0);
    try { exported = c.toDataURL('image/png').slice(0, 22); pixel = [...ctx.getImageData(540, 20, 1, 1).data]; } catch (e) { exported = 'tainted: ' + e.name; }
  }
  return {width: img.naturalWidth, height: img.naturalHeight, hidden: img.hidden, src: img.getAttribute('src'), alt: img.alt,
    busy: q('#wcStory').getAttribute('aria-busy'), exported, pixel,
    save: q('#wcSaveImage').innerText.replace(/\\s+/g, ' ').trim(), share: q('#wcShare').innerText.replace(/\\s+/g, ' ').trim(),
    hint: q('.wc-story-hint').innerText, toast: q('#wcShareStatus').textContent,
    toastShown: q('#wcShareStatus').classList.contains('is-shown'), role: q('#wcShareStatus').getAttribute('role')}; }"""
# Every string the story card draws, recorded (the card is pixels): the credit line must carry no names.
CARD_TEXT_SPY = """() => { window.__cardText = [];
  if (window.__cardSpy) return; window.__cardSpy = true;
  const draw = CanvasRenderingContext2D.prototype.fillText;
  CanvasRenderingContext2D.prototype.fillText = function (text, ...rest) { window.__cardText.push(String(text)); return draw.call(this, text, ...rest); }; }"""
# Web Share and the clipboard, recorded instead of performed; `touch` makes the page see a phone.
SHARE_STUB = """([touch, files, fail]) => { window.__shared = []; window.__copied = [];
  const mm = window.__realMatchMedia || (window.__realMatchMedia = window.matchMedia.bind(window));
  window.matchMedia = q => q === '(pointer: coarse)' ? {matches: touch, media: q, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}} : mm(q);
  navigator.canShare = d => !d.files || files;
  navigator.share = d => { window.__shared.push({files: (d.files || []).map(f => ({name: f.name, type: f.type, size: f.size})),
    text: d.text || null, url: d.url || null, title: d.title || null});
    return fail ? Promise.reject(new DOMException('stub', fail)) : Promise.resolve(); };
  navigator.clipboard.writeText = t => { window.__copied.push(t); return Promise.resolve(); }; }"""
FRIEND_SNAP = """() => { const q = s => document.querySelector(s), shown = e => !!e && !e.hidden && e.getBoundingClientRect().width > 0;
  return {banner: shown(q('#wcFriend')), text: q('#wcFriendText').textContent, photo: q('#wcFriendPhoto').getAttribute('src'),
    photoShown: shown(q('#wcFriendPhoto')), pressed: [...document.querySelectorAll('.wc-tile[aria-pressed="true"]')].map(t => t.dataset.cat),
    match: shown(q('#wcMatch')), start: shown(q('#wcStart')), locked: shown(q('#wcLocked')), saved: localStorage.getItem('babdoduk-worldcup'),
    query: location.search, overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth}; }"""


def worldcup_share(page):
    """The world cup's sharing (owner 2026-10-14, docs/WORLDCUP_SHARE.md): the winner's 1080x1920 story
    card is drawn at once and previewed (an untainted canvas); 스토리 이미지 저장 downloads the PNG on a
    computer and hands the file to the share sheet on a phone; 공유하기 shares the file, the text and the
    friend link on a phone (the text and the link when files cannot go), copies the link on a computer;
    "저장했어요" and "링크를 복사했어요" are toasts read out once. The friend link shows its banner and its
    category, ignores what is not in the pool, never starts a game and stays locked before the launch."""
    count = 0

    def check(ok, detail):
        nonlocal count
        assert ok, f"worldcup.html sharing: {detail}"
        count += 1

    cup = json.loads((ROOT / "data/content/worldcup.json").read_text(encoding="utf-8"))
    errors = []

    def on_error(error):
        errors.append(str(error))

    page.on("pageerror", on_error)
    page.clock.set_fixed_time(WC_RUNNING)
    page.set_viewport_size({"width": 1280, "height": 900})
    save, (winner, finalist, semi_a, semi_b) = worldcup_final_saved(cup, "korean")
    page.goto("https://site-ui.invalid/worldcup.html", wait_until="networkidle")
    page.evaluate("s => { localStorage.setItem('babdoduk-worldcup', JSON.stringify(s)); localStorage.removeItem('babdoduk-lang'); }", save)
    page.reload(wait_until="networkidle")
    page.locator("#wcResume").click()
    page.evaluate(CARD_TEXT_SPY)
    page.locator(f'.wc-card[data-id="{winner}"]').click()
    check(page.locator("#wcResult").is_visible() and page.locator("#wcWinner").inner_text() == cup_name(winner),
          "the last pick of the final shows the winner")
    page.wait_for_function("() => { const i = document.getElementById('wcStoryPreview'); return !i.hidden && i.naturalWidth > 0; }")
    card_photos = [cup["photos"][d] for d in (winner, finalist, semi_a, semi_b)]

    def card_credit_ok(texts, line):
        """One short credit line, no photographer or licence on the card; the page lists them all."""
        lines = [t for t in texts if "Wikimedia" in t]
        return (lines == [line] and all(p["author"] not in t and p["license"] not in t for p in card_photos for t in texts)
                and not any("CC BY" in t for t in texts))

    check(card_credit_ok(page.evaluate("window.__cardText"), "📷 Wikimedia Commons · 사진 출처 babdoduk.vercel.app/worldcup.html"),
          ("the card's one credit line names no photographer", page.evaluate("window.__cardText")))
    # The result screen lists the author and licence, linked, of the four photos on the card.
    page.locator("#wcCredits summary").click()
    items = page.locator("#wcCreditsList li").evaluate_all(
        "els => els.map(li => ({text: li.innerText, links: [...li.querySelectorAll('a')].map(a => [a.textContent, a.href])}))")
    check(page.locator("#wcCredits summary").inner_text() == "사진 출처" and page.locator("#wcCredits").evaluate("el => el.open")
          and len(items) == 4, ("the credits disclosure lists the 4 photos", items))
    for item, dish, photo in zip(items, (winner, finalist, semi_a, semi_b), card_photos):
        check(cup_name(dish) in item["text"] and photo["author"] in item["text"] and photo["license"] in item["text"]
              and item["links"] == [[photo["author"], photo["source"]], [photo["license"], photo["licenseUrl"]]],
              ("author and licence, with links, for " + dish, item))
    check(page.evaluate("""() => [...document.querySelectorAll('#wcCreditsList a')].every(a => a.target === '_blank' && /noopener/.test(a.rel))"""),
          "the credit links open in a new tab safely")
    snap = page.evaluate(STORY_SNAP)
    check(snap["width"] == 1080 and snap["height"] == 1920 and snap["busy"] is None and snap["src"].startswith("blob:"),
          ("the story card is drawn at once, 1080x1920, and previewed", snap))
    check(snap["exported"] == "data:image/png;base64," and snap["pixel"] and snap["pixel"][3] == 255 and snap["pixel"][0] > snap["pixel"][1],
          ("the canvas is untainted (toDataURL works) and the background is the brand's pink", snap))
    check(snap["save"].replace(" ", "") == "📥스토리이미지저장" and snap["share"].replace(" ", "") == "📤공유하기"
          and snap["hint"] == "인스타 스토리: 공유하기 → Instagram → 스토리" and snap["alt"].endswith(cup_name(winner)),
          ("the two buttons, the Instagram hint and the preview's text", snap))
    check(snap["role"] == "status", "the toast is a status region")
    friend_url = f"https://site-ui.invalid/worldcup.html?from={winner}&cat=korean"
    # A computer: the PNG is downloaded; 공유하기 copies the friend link. Neither opens a share sheet.
    page.evaluate(SHARE_STUB, [False, True, None])
    with page.expect_download() as download:
        page.locator("#wcSaveImage").click()
    data = Path(download.value.path()).read_bytes()
    check(png_size(data) == (1080, 1920) and download.value.suggested_filename == "babdoduk-worldcup-story.png",
          ("스토리 이미지 저장 downloads the 1080x1920 PNG", png_size(data)))
    page.wait_for_function("document.getElementById('wcShareStatus').textContent === '저장했어요'")
    check(page.evaluate("document.getElementById('wcShareStatus').classList.contains('is-shown')"), "저장했어요 shows as a toast")
    page.locator("#wcShare").click()
    page.wait_for_function("document.getElementById('wcShareStatus').textContent === '링크를 복사했어요'")
    check(page.evaluate("window.__copied") == [friend_url] and page.evaluate("window.__shared") == [],
          ("a computer copies the friend link (this host), no share sheet", page.evaluate("window.__copied")))
    # Keyboard: both buttons are reachable and show a focus ring.
    page.locator("#wcSaveImage").focus()
    page.keyboard.press("Tab")
    check(page.evaluate("document.activeElement.id") == "wcShare"
          and page.evaluate("getComputedStyle(document.activeElement).outlineStyle") != "none",
          "Tab moves from 저장 to 공유하기 with a visible focus ring")
    # A phone: the share sheet gets the PNG, the text and the link; 저장 hands over the file alone.
    page.evaluate(SHARE_STUB, [True, True, None])
    page.locator("#wcShare").click()
    page.wait_for_function("window.__shared.length === 1")
    shared = page.evaluate("window.__shared")[0]
    check(shared["files"] and shared["files"][0]["type"] == "image/png" and shared["files"][0]["size"] > 50_000
          and shared["url"] == friend_url and cup_name(winner) in shared["text"] and "한식" in shared["text"],
          ("공유하기 on a phone shares the PNG file, the text and the friend link", shared))
    page.locator("#wcSaveImage").click()
    page.wait_for_function("window.__shared.length === 2")
    shared = page.evaluate("window.__shared")[1]
    check(len(shared["files"]) == 1 and shared["files"][0]["type"] == "image/png" and shared["text"] is None and shared["url"] is None,
          ("스토리 이미지 저장 on a phone opens the share sheet with the file alone", shared))
    page.evaluate(SHARE_STUB, [True, False, None])                 # a browser that cannot share files
    page.locator("#wcShare").click()
    page.wait_for_function("window.__shared.length === 1")
    shared = page.evaluate("window.__shared")[0]
    check(shared["files"] == [] and shared["url"] == friend_url and shared["text"], ("without file sharing: the text and the link", shared))
    page.evaluate(SHARE_STUB, [True, True, "AbortError"])            # closing the sheet says nothing
    page.evaluate("document.getElementById('wcShareStatus').textContent = ''")
    page.locator("#wcShare").click()
    page.wait_for_timeout(200)
    check(page.evaluate("window.__copied") == [] and page.evaluate("document.getElementById('wcShareStatus').textContent") == "",
          "a cancelled share sheet is not an error")
    page.evaluate(SHARE_STUB, [True, True, "NotAllowedError"])       # a refused share falls back to the link
    page.locator("#wcShare").click()
    page.wait_for_function("window.__copied.length === 1")
    check(page.evaluate("window.__copied") == [friend_url], "a refused share copies the friend link instead")
    # English: the card is drawn again in English.
    before = page.evaluate("document.getElementById('wcStoryPreview').src")
    page.evaluate(CARD_TEXT_SPY)
    page.locator("#langToggle").click()
    page.wait_for_function("b => { const i = document.getElementById('wcStoryPreview'); return !i.hidden && i.src !== b && i.naturalWidth === 1080; }", arg=before)
    check(page.locator("#wcSaveImage").inner_text().strip().endswith("Save story image")
          and page.evaluate("document.getElementById('wcStoryPreview').alt").startswith("Story image preview"),
          "a language switch redraws the card and the buttons in English")
    check(card_credit_ok(page.evaluate("window.__cardText"), "📷 Wikimedia Commons · photo credits at babdoduk.vercel.app/worldcup.html"),
          ("the English card's one credit line names no photographer", page.evaluate("window.__cardText")))
    check(page.locator("#wcCredits summary").inner_text() == "Photo credits" and page.locator("#wcCreditsList li").count() == 4,
          "the credits are listed in English too")
    page.locator("#langToggle").click()
    page.evaluate("localStorage.removeItem('babdoduk-lang')")

    # The friend link: a banner and the category, never a game.
    page.set_viewport_size({"width": 390, "height": 844})

    def friend(query):
        page.goto("https://site-ui.invalid/worldcup.html" + query, wait_until="networkidle")
        page.evaluate("localStorage.removeItem('babdoduk-worldcup')")
        page.reload(wait_until="networkidle")
        return page.evaluate(FRIEND_SNAP)

    shot = friend(f"?from={finalist}&cat=korean")
    check(shot["banner"] and shot["text"] == f"친구의 최애는 {cup_name(finalist)}! 🏆 너도 해봐" and shot["photoShown"]
          and shot["photo"] == f"images/worldcup/{finalist}.jpg", ("the friend's banner with the dish and its photo", shot))
    check(shot["pressed"] == ["korean"] and not shot["match"] and shot["start"] and not shot["saved"] and shot["overflow"] <= 0,
          ("the friend's category is chosen and nothing starts", shot))
    page.locator("#langToggle").click()
    check(page.locator("#wcFriendText").inner_text().startswith("Your friend"), "the banner in English")
    page.locator("#langToggle").click()
    shot = friend(f"?from={finalist}&cat=nope")
    check(shot["banner"] and shot["pressed"] == ["all"], ("an unknown category is ignored, the banner stays", shot))
    shot = friend("?from=not-a-dish&cat=japanese")
    check(not shot["banner"] and shot["pressed"] == ["japanese"], ("a dish outside the pool is ignored", shot))
    shot = friend("?from=%3Cimg%3E&cat=%3Cb%3E")
    check(not shot["banner"] and shot["pressed"] == ["all"] and not shot["match"], ("nonsense is ignored", shot))
    # Before the launch: the banner, no photo request, the game locked.
    photos = mystery_requests(page)
    page.clock.set_fixed_time(WC_SOON)
    shot = friend(f"?from={finalist}&cat=korean")
    check(shot["banner"] and not shot["photoShown"] and shot["photo"] is None and shot["locked"] and not shot["start"]
          and not shot["match"] and not shot["saved"], ("before the launch the banner shows and the game stays locked", shot))
    check(not photos, ("no dish photo is requested before the launch", photos))
    page.evaluate("document.querySelector('#wcStart').click()")
    check(page.locator("#wcMatch").is_hidden(), "a forced start does nothing before the launch")
    page.clock.set_fixed_time(WC_RUNNING)
    page.evaluate("localStorage.removeItem('babdoduk-worldcup')")
    page.remove_listener("pageerror", on_error)
    check(not errors, ("no page errors", errors))
    return count


def cup_name(dish):
    """The Korean name of a catalog dish."""
    return page_names()[dish][0]


_NAMES = {}


def page_names():
    if not _NAMES:
        for pack in json.loads((ROOT / "data/foods/catalog.json").read_text(encoding="utf-8"))["packs"]:
            for item in json.loads((ROOT / pack["src"]).read_text(encoding="utf-8")).get("items") or []:
                _NAMES[item["id"]] = (item.get("nameKo") or "", item.get("nameEn") or "")
    return _NAMES


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
          and page.locator("#homeCal").get_attribute("data-state") == "error", "home names unavailable data")
    cal_text = page.locator("#homeCal").inner_text()
    check("불러오지 못했어요" in cal_text and not any(word in cal_text for word in ("일정 없음", "기록 없음", "예정된 꽁밥이 없어요"))
          and page.locator("#homeCal .hc-dot").count() == 0 and page.locator("#homeCalAll").get_attribute("href") == "ggongbab.html#free",
          ("a failed schedule is not an empty one", cal_text))
    check(page.locator(".home-hero h1").is_visible() and page.locator(".home-actions .btn-primary").is_visible()
          and page.locator("#homeShelf > li[data-banner]").count() == len(SHELF), "hero and shelf survive missing data")
    check(page.locator("#homeFeature").is_hidden() and page.locator(".home-desks a").count() == 4
          and page.locator(".home-read .explore-card").is_visible() and page.locator(".home-news-row").count() == 2
          and page.locator(".home-news-story").is_visible(),
          "reading and news groups keep their links, with no invented edition")
    page.goto("https://site-ui.invalid/ggongbab.html", wait_until="networkidle")
    page.locator("#foodHubFree .gg-state").first.wait_for()
    counts = page.locator(".gg-counts").inner_text()
    check("확인 중" not in counts and "실패" in counts, ("hub counts report failure, not loading", counts))
    page.locator('.gg-archive-state[data-archive-state="error"]').wait_for()
    check(page.locator("[data-gg-retry]").count() == 1 and page.locator(".gg-past").count() == 0,
          "past listings fail on their own: the live retry stays, and no record is invented")
    page.goto("https://site-ui.invalid/mukbang.html", wait_until="networkidle")
    check(page.locator("#mgEditionStatus").is_visible(), "magazine says the edition did not load")
    text = page.locator("main").inner_text()
    check("min read" not in text and "ISSUE 01" not in text and "2026.09.12" not in text,
          "no invented edition metadata")
    check("밥도둑 데스크" not in text and not page.locator("a.mg-story, .mg-story--desk").count()
          and page.locator(".mg-lane-empty").count() == 4 and page.locator("#featured").is_hidden(),
          "a failed edition shows no stand-in stories: four quiet lane notes and no hero")
    page.unroute("**/data/**")
    return count

# ---------------------------------------------------------------------------------------------------
# Site guardian: the shared chrome is identical on every public page (structure, destinations, computed
# footer styles and the transition into the footer), in both languages and at desktop and phone widths.
# ---------------------------------------------------------------------------------------------------
# choose.html is a redirect to mukbang.html#what and food.html is lab-only, so neither is a guarded public page.
GUARD_PAGES = ["index.html", "ggongbab.html", "mukbang.html", "event.html", "history.html"]
GUARD_SIZES = [(1440, 900), (390, 844), (360, 800)]
NAV_DIRECT = ["ggongbab.html", "mukbang.html", "event.html"]
NAV_MORE = ["history.html",
            "https://naver.me/5NeqUPzI", "https://www.instagram.com/babdodukms/"]
FOOTER_LINKS = ["ggongbab.html", "mukbang.html", "event.html", "history.html"]
CHROME = r"""() => {
  const pick = (el, props) => { const s = getComputedStyle(el); return Object.fromEntries(props.map(p => [p, s.getPropertyValue(p)])); };
  const root = document.documentElement, body = document.body, footer = document.querySelector('.site-footer');
  const r = footer.getBoundingClientRect();
  return {
    direct: [...document.querySelectorAll('.nav-mega-row > .site-nav-direct')].map(a => a.getAttribute('href')),
    more: [...document.querySelectorAll('#navMorePanel > a')].map(a => a.getAttribute('href')),
    current: [...document.querySelectorAll('.site-nav [aria-current="page"]')].map(a => a.getAttribute('href')),
    home: document.getElementById('navHome').getAttribute('href'),
    footerLinks: [...footer.querySelectorAll('a')].map(a => a.getAttribute('href')),
    footerText: footer.innerText.replace(/\s+/g, ' ').trim(),
    styles: {
      nav: pick(document.querySelector('.site-nav'), ['height', 'position', 'background-color', 'font-family']),
      footer: pick(footer, ['background-color', 'padding-top', 'padding-bottom', 'margin-top', 'color', 'font-family', 'position', 'z-index']),
      inner: pick(footer.querySelector('.site-footer-inner'), ['max-width', 'padding-left', 'padding-right']),
      hr: pick(footer.querySelector('.footer-apple-hr'), ['border-top-color', 'border-top-width', 'margin-bottom']),
      main: pick(footer.querySelector('.footer-apple-main'), ['font-size', 'line-height', 'grid-template-columns']),
      fine: pick(footer.querySelector('.footer-apple-fine'), ['font-size', 'color', 'border-top-color', 'padding-top'])
    },
    context: {below: root.scrollHeight - (r.bottom + scrollY), width: Math.round(r.width), viewport: root.clientWidth,
              bodyPadding: getComputedStyle(body).paddingBottom, bodyMargin: getComputedStyle(body).marginBottom},
    overflow: Math.max(root.scrollWidth - root.clientWidth, body.scrollWidth - body.clientWidth)
  };
}"""


def site_guardian(page):
    """Cross-page chrome consistency: nav, footer, footer context, overflow, console errors, broken resources."""
    count = 0

    def check(ok, detail):
        nonlocal count
        if not ok:
            raise AssertionError(f"site guardian: {detail}", detail)  # detail: (where, component, values)
        count += 1

    errors, broken = [], []
    on_error = lambda exc: errors.append(str(exc)[:160])
    on_console = lambda msg: errors.append(msg.text[:160]) if msg.type == "error" and "Failed to load resource" not in msg.text else None
    on_response = lambda res: broken.append(f"{res.status} {res.url}") if (
        res.status >= 400 and urlparse(res.url).hostname == "site-ui.invalid" and not res.url.endswith("/favicon.ico")) else None
    page.on("pageerror", on_error)
    page.on("console", on_console)
    page.on("response", on_response)
    try:
        for lang in ("ko", "en"):
            for width, height in GUARD_SIZES:
                page.set_viewport_size({"width": width, "height": height})
                page.goto("https://site-ui.invalid/index.html", wait_until="domcontentloaded")
                page.evaluate("lang => localStorage.setItem('babdoduk-lang', lang)", lang)
                reference = None
                for name in GUARD_PAGES:
                    errors.clear()
                    broken.clear()
                    page.goto("https://site-ui.invalid/" + name, wait_until="networkidle")
                    chrome = page.evaluate(CHROME)
                    where = f"{name} {lang} {width}x{height}"
                    check(chrome["direct"] == NAV_DIRECT and chrome["more"] == NAV_MORE, (where, "nav structure and destinations", chrome["direct"], chrome["more"]))
                    check(chrome["current"] == ([] if name == "index.html" else [name]), (where, "one current-page marker", chrome["current"]))
                    check(chrome["home"] == ("#" if name == "index.html" else "index.html"), (where, "wordmark destination"))
                    check(chrome["footerLinks"] == FOOTER_LINKS, (where, "footer destinations", chrome["footerLinks"]))
                    check(abs(chrome["context"]["below"]) < 1 and chrome["context"]["bodyPadding"] == "0px"
                          and chrome["context"]["bodyMargin"] == "0px", (where, "no strip of canvas below the footer", chrome["context"]))
                    check(chrome["context"]["width"] == chrome["context"]["viewport"], (where, "full-width footer", chrome["context"]))
                    check(chrome["styles"]["footer"]["background-color"] == "rgba(0, 0, 0, 0)",
                          (where, "the footer sits on the page canvas on every page", chrome["styles"]["footer"]))
                    check(chrome["overflow"] <= 0, (where, "no horizontal overflow", chrome["overflow"]))
                    check(not errors, (where, "no JS or console errors", errors[:3]))
                    check(not broken, (where, "no broken resources", broken[:3]))
                    text = chrome["footerText"]
                    check(("Contact" in text and "문의" not in text) if lang == "en" else ("문의" in text and "Contact" not in text),
                          (where, "the footer contact label follows the language", text[:90]))
                    if reference is None:
                        reference = chrome
                    else:
                        check(chrome["footerText"] == reference["footerText"], (where, "same footer text as index"))
                        for part, values in chrome["styles"].items():
                            check(values == reference["styles"][part], (where, f"{part} computed style matches index",
                                  {k: (v, reference["styles"][part][k]) for k, v in values.items() if v != reference["styles"][part][k]}))
        page.evaluate("localStorage.setItem('babdoduk-lang', 'ko')")
    finally:
        page.remove_listener("pageerror", on_error)
        page.remove_listener("console", on_console)
        page.remove_listener("response", on_response)
    return count


# ---------------------------------------------------------------------------------------------------
# Visual regression for the shared chrome. Golden images live in tests/visual/chrome and change only
# with an explicit owner approval note (see docs/VISUAL_BASELINES.md); a mismatch never re-baselines.
# ---------------------------------------------------------------------------------------------------
BASELINE_ROOT = ROOT / "tests/visual/chrome"
PARTS = ("nav", "footer", "footer-context")


def baseline_platform():
    """Pixels are only comparable within one OS and browser build, so each keeps its own approved set."""
    os_name = {"win32": "windows", "linux": "linux", "darwin": "macos"}.get(sys.platform, sys.platform)
    return f"{os_name}-{BROWSER}"


def expected_shots():
    return [f"{Path(name).stem}-{lang}-{width}-{part}.png" for lang in ("ko", "en") for width, _ in VISUAL_SIZES
            for name in GUARD_PAGES for part in PARTS]


def refuse_in_ci(action):
    if IN_CI:
        raise SystemExit(f"refusing to {action} in CI: baselines change only with an owner-approved local "
                         "command (docs/VISUAL_BASELINES.md)")


def write_manifest(folder, approval, source):
    (folder / "BASELINES.json").write_text(json.dumps({
        "approval": approval, "platform": folder.name, "source": source, "images": len(expected_shots()),
        "fixed_now": FIXED_NOW, "sizes": VISUAL_SIZES, "pages": GUARD_PAGES, "parts": PARTS,
        "context_above_px": CONTEXT_ABOVE}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def failure_summary(failures):
    """Name page, language, viewport and component for every failed image (.local and the CI job summary)."""
    rows = ["| image | page | lang | viewport | component | problem |", "|---|---|---|---|---|---|"]
    for file_name, problem in failures:
        m = re.match(r"(\w+)-(ko|en)-(\d+)-(nav|footer|footer-context)\.png$", file_name)
        page, lang, width, part = m.groups() if m else ("?", "?", "?", "?")
        rows.append(f"| {file_name} | {page}.html | {lang} | {width}px | {part} | {problem} |")
    text = (f"## Shared chrome visual check: {len(failures)} image(s) failed ({baseline_platform()})\n\n"
            + "\n".join(rows) + "\n\nActual renders and diff images: `.local/visual-diff/`. "
            "Do not re-baseline to pass; see docs/VISUAL_BASELINES.md.\n")
    (DIFF_DIR / "SUMMARY.md").write_text(text, encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as out:
            out.write(text)
DIFF_DIR = ROOT / ".local/visual-diff"
VISUAL_SIZES = [(1440, 900), (390, 844)]
FIXED_NOW = "2026-09-28T10:00:00+09:00"
CONTEXT_ABOVE = 180
# Motion off, and the 2% film-grain overlay hidden: it is decoration, and its noise would make every
# baseline incompressible without telling anything about layout, surfaces or spacing.
STILL = ("*, *::before, *::after { animation: none !important; transition: none !important; caret-color: transparent !important; }"
         " body::after { display: none !important; }")
FIXTURES = {
    "data/ggongbab/latest.json": {"generatedAt": "2026-09-28T09:00:00+09:00", "timezone": "Asia/Seoul", "count": 0, "events": []},
    "data/ggongbab/archive/index.json": {"generatedAt": "2026-09-28T09:00:00+09:00", "timezone": "Asia/Seoul",
                                         "windowDays": 30, "count": 0, "events": []},
    "data/kaist-menu/latest.json": {"date": "2026-09-28", "restaurants": [{"id": "r1", "name": "Fixture",
                                    "lunch": {"items": ["밥", "국"], "price": "5,000원"}}]},
    "data/food-log.json": {"currency": "KRW", "entries": [{"date": "2026-09-10", "total": 9000, "items": []}]},
}


def visual_route(route):
    path = unquote(urlparse(route.request.url).path).lstrip("/")
    if path in FIXTURES:
        route.fulfill(json=FIXTURES[path])
    elif path.startswith("data/magazine/"):
        route.fulfill(status=404, body="")  # the desk fallback is static; editions change daily
    else:
        route.fallback()


def image_diff(expected, actual):
    """Fraction of pixels whose largest channel difference exceeds 24/255 (antialiasing jitter stays below)."""
    import numpy as np
    from PIL import Image

    a = np.asarray(Image.open(expected).convert("RGB"), dtype=np.int16)
    b = np.asarray(Image.open(actual).convert("RGB"), dtype=np.int16)
    if a.shape != b.shape:
        return 1.0, None
    mask = np.abs(a - b).max(axis=2) > 24
    diff = np.zeros_like(a, dtype=np.uint8)
    diff[mask] = (220, 30, 30)
    return float(mask.mean()), Image.fromarray(diff)


def chrome_visual(page, update=False, approval=None):
    """Nav, footer and footer-context screenshots against the approved golden images of this platform."""
    count = 0
    if update:
        refuse_in_ci("rewrite chrome baselines")
        if not approval:
            raise SystemExit("refusing to rewrite baselines without --approval (see docs/VISUAL_BASELINES.md)")
    shots = []
    page.clock.set_fixed_time(FIXED_NOW)
    page.route("**/*", visual_route)
    page.emulate_media(reduced_motion="reduce")
    try:
        for lang in ("ko", "en"):
            for width, height in VISUAL_SIZES:
                page.set_viewport_size({"width": width, "height": height})
                page.goto("https://site-ui.invalid/index.html", wait_until="domcontentloaded")
                page.evaluate("lang => localStorage.setItem('babdoduk-lang', lang)", lang)
                for name in GUARD_PAGES:
                    page.goto("https://site-ui.invalid/" + name, wait_until="networkidle")
                    page.add_style_tag(content=STILL)
                    page.evaluate("document.fonts.ready")
                    page.wait_for_timeout(150)
                    stem = f"{Path(name).stem}-{lang}-{width}"
                    box = page.evaluate("""() => { const r = document.querySelector('.site-footer').getBoundingClientRect();
                      return {top: r.top + scrollY, height: r.height, width: document.documentElement.clientWidth}; }""")
                    targets = {
                        "nav": lambda: page.locator(".site-nav").screenshot(animations="disabled"),
                        "footer": lambda: page.locator(".site-footer").screenshot(animations="disabled"),
                        "footer-context": lambda: page.screenshot(full_page=True, animations="disabled", clip={
                            "x": 0, "y": max(0, box["top"] - CONTEXT_ABOVE), "width": box["width"],
                            "height": box["height"] + min(CONTEXT_ABOVE, box["top"])}),
                    }
                    for part, take in targets.items():
                        shots.append((f"{stem}-{part}.png", take()))
    finally:
        page.unroute("**/*", visual_route)
    folder = BASELINE_ROOT / baseline_platform()
    if update:
        folder.mkdir(parents=True, exist_ok=True)
        for old in folder.glob("*.png"):
            old.unlink()
        for file_name, data in shots:
            (folder / file_name).write_bytes(data)
        write_manifest(folder, approval, f"rendered locally by check_site_ui.py ({BROWSER})")
        return len(shots)
    failures = []
    shutil.rmtree(DIFF_DIR, ignore_errors=True)
    DIFF_DIR.mkdir(parents=True, exist_ok=True)
    for file_name, data in shots:
        expected = folder / file_name
        actual = DIFF_DIR / file_name
        actual.write_bytes(data)  # kept for review whenever the image fails
        if not expected.is_file():
            failures.append((file_name, f"no approved baseline for {folder.name}"))
            continue
        ratio, diff = image_diff(expected, actual)
        if ratio > 0.002:
            failures.append((file_name, f"{ratio:.2%} of pixels differ"))
            if diff is not None:
                diff.save(DIFF_DIR / file_name.replace(".png", ".diff.png"))
        else:
            actual.unlink()
        count += 1
    if failures:
        failure_summary(failures)
    assert not failures, ("shared chrome changed visually; review .local/visual-diff and follow "
                          "docs/VISUAL_BASELINES.md before approving new baselines",
                          [f"{name}: {problem}" for name, problem in failures[:8]])
    return count


def run_checks(screenshots=False):
    report = {"pages": public_pages(), "sizes": SIZES, "results": {}, "checks": 0}
    with sync_playwright() as pw:
        browser = launch(pw)
        context = new_context(browser)
        api_attempts = []
        context.on("request", lambda req: api_attempts.append(req.url)
                   if req.resource_type in ("fetch", "xhr", "eventsource")
                   and urlparse(req.url).hostname not in SERVED_HOSTS else None)
        page = context.new_page()
        # WebSockets bypass routing and emit no request event; record every attempt.
        page.on("websocket", lambda ws: api_attempts.append(ws.url))
        for size in SIZES:
            for name in report["pages"]:
                result = inspect_page(page, name, size, ROOT / ".local/site-ui-shots" if screenshots else None)
                report["results"][f"{name}:{size[0]}x{size[1]}"] = result
                report["checks"] += result["checks"]
        report["checks"] += magazine_tools(page)
        report["checks"] += magazine_sparse(page)
        report["checks"] += magazine_edition_time(page)
        report["checks"] += release_contracts(page)
        report["checks"] += home_summary(page)
        report["checks"] += home_hero_shelf(page)
        report["checks"] += event_bands(page)
        # The world cup runs from 2026-10-16 (js/worldcup-gate.js): its checks own a context whose page
        # clock is fixed (inside the window unless a check sets another), so nothing depends on today.
        cup_context = new_context(browser)
        cup_context.on("request", lambda req: api_attempts.append(req.url)
                       if req.resource_type in ("fetch", "xhr", "eventsource")
                       and urlparse(req.url).hostname not in SERVED_HOSTS else None)
        cup_page = cup_context.new_page()
        cup_page.on("websocket", lambda ws: api_attempts.append(ws.url))
        cup_page.clock.set_fixed_time(WC_RUNNING)
        report["checks"] += event_entry(cup_page)
        report["checks"] += worldcup_play(cup_page)
        report["checks"] += worldcup_categories(cup_page)
        report["checks"] += worldcup_splash(cup_page)
        report["checks"] += worldcup_gacha(cup_page)
        report["checks"] += worldcup_sound(cup_page)
        report["checks"] += worldcup_share(cup_page)
        report["checks"] += worldcup_gate(cup_page)
        report["checks"] += home_wc_promo(cup_page)
        cup_context.close()
        report["checks"] += history_archive(page)
        report["checks"] += food_provenance(page)
        report["checks"] += structure_and_failures(page)
        report["checks"] += site_guardian(page)
        # High contrast must defer to the system; custom colors/widths must not
        # leak from either the standards or WebKit rule sets.
        page.emulate_media(forced_colors="active")
        check = page.evaluate(MEASURE)
        assert check["scrollbarColor"] == "auto"
        assert check["width"] == "auto"
        report["checks"] += 2
        assert not api_attempts, ("static pages attempted a live API request", api_attempts[:5])
        report["checks"] += 1
        # Last: it fixes the page clock and data for deterministic screenshots. Its baselines exist
        # per OS and browser build (baseline_platform); the tests workflow, which has none, skips
        # it explicitly, and ui-guardian compares them in the container they were rendered in.
        page.emulate_media(forced_colors="none")
        if os.environ.get("BABDODUK_CHROME_VISUAL") != "skip":
            report["checks"] += chrome_visual(page)
        browser.close()
    return report


def guardian_summary(exc, shot):
    """A guardian failure joins the visual summary with the page it stopped on and a capture of that page."""
    detail = exc.args[1] if len(exc.args) > 1 else str(exc)
    where = str(detail[0]) if isinstance(detail, tuple) and detail else "?"
    m = re.match(r"(\S+) (ko|en) (\d+)x(\d+)$", where)
    name, lang, width = (m.group(1), m.group(2), m.group(3) + "px") if m else ("?", "?", "?")
    component = str(detail[1]) if isinstance(detail, tuple) and len(detail) > 1 else str(detail)[:120]
    problem = str(detail[2:] if isinstance(detail, tuple) else detail).replace("|", "/").replace("\n", " ")[:300]
    DIFF_DIR.mkdir(parents=True, exist_ok=True)
    capture = f"guardian-{Path(name).stem}-{lang}-{width}.png"
    if shot:
        (DIFF_DIR / capture).write_bytes(shot)
    text = (f"## Site guardian failed ({baseline_platform()})\n\n| capture | page | lang | viewport | component | problem |\n"
            f"|---|---|---|---|---|---|\n| {capture if shot else '-'} | {name} | {lang} | {width} | {component} | {problem} |\n\n"
            "The guardian stops at its first failure; fix it and rerun to see any later ones.\n")
    summary = DIFF_DIR / "SUMMARY.md"
    summary.write_text(text + ("\n" + summary.read_text(encoding="utf-8") if summary.is_file() else ""), encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as out:
            out.write(text)


def run_chrome_checks():
    """The shared-chrome gate alone: site guardian and visual comparison. This is what CI runs.

    Both parts always run, so one failed run shows every changed image and the guardian's finding."""
    report = {"platform": baseline_platform(), "checks": 0}
    failed = []
    with sync_playwright() as pw:
        browser = launch(pw)
        page = new_context(browser).new_page()
        guardian_error, shot = None, None
        try:
            report["guardian"] = site_guardian(page)
        except AssertionError as exc:
            guardian_error = exc
            shot = page.screenshot(full_page=True)  # the page and viewport the guardian stopped on
            failed.append(exc.args[0])
        try:
            report["visual"] = chrome_visual(page)
        except AssertionError as exc:
            failed.append(f"visual: {exc}")
        browser.close()
    if guardian_error is not None:
        guardian_summary(guardian_error, shot)  # after chrome_visual, which resets .local/visual-diff
    assert not failed, failed
    report["checks"] = report["guardian"] + report["visual"]
    return report


def update_chrome_baselines(approval):
    """Rewrite this platform's golden chrome screenshots. Only after an owner-approved visual change."""
    refuse_in_ci("rewrite chrome baselines")
    with sync_playwright() as pw:
        browser = launch(pw)
        written = chrome_visual(new_context(browser).new_page(), update=True, approval=approval)
        browser.close()
    return written


def adopt_chrome_baselines(source, platform, approval):
    """Install renders made elsewhere (for example a failed CI run's artifact) as a platform's approved set."""
    refuse_in_ci("adopt chrome baselines")
    if not approval:
        raise SystemExit("refusing to adopt baselines without --approval (see docs/VISUAL_BASELINES.md)")
    source = Path(source)
    names = expected_shots()
    missing = [name for name in names if not (source / name).is_file()]
    if missing:
        raise SystemExit(f"{source} lacks {len(missing)} of {len(names)} renders, e.g. {missing[:3]}")
    folder = BASELINE_ROOT / platform
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("*.png"):
        old.unlink()
    for name in names:
        shutil.copyfile(source / name, folder / name)
    write_manifest(folder, approval, f"adopted from {source.name}")
    return len(names)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--screenshots", action="store_true")
    parser.add_argument("--update-chrome-baselines", action="store_true",
                        help="rewrite tests/visual/chrome after an owner-approved visual change")
    parser.add_argument("--approval", help="who approved the visual change, and where (required to change baselines)")
    parser.add_argument("--chrome-only", action="store_true", help="run only the site guardian and the visual check (CI)")
    parser.add_argument("--adopt-chrome-baselines", metavar="DIR", help="install renders from DIR as approved baselines")
    parser.add_argument("--platform", help="baseline set for --adopt-chrome-baselines, e.g. linux-chromium")
    args = parser.parse_args()
    if args.update_chrome_baselines:
        print(f"wrote {update_chrome_baselines(args.approval)} baseline images for {baseline_platform()}")
    elif args.adopt_chrome_baselines:
        if not args.platform:
            raise SystemExit("--adopt-chrome-baselines needs --platform")
        print(f"adopted {adopt_chrome_baselines(args.adopt_chrome_baselines, args.platform, args.approval)} images as {args.platform}")
    elif args.chrome_only:
        print(json.dumps(run_chrome_checks(), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(run_checks(args.screenshots), ensure_ascii=False, indent=2))
