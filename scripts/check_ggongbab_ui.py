"""Local fixture/preview screenshots and executable layout/security checks."""
from __future__ import annotations

import argparse
import json
import threading
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".local" / "ui-shots"
SIZES = [(390, 844), (430, 932), (1440, 900)]
SELECTORS = {"nav": ".site-nav", "page": ".ggongbab-page-wrap", "hero": ".gg-hero",
             "tabs": ".food-hub-tabs", "radar": ".gg-radar",
             "filter": ".gg-filters", "day": ".gg-day", "card": ".gg-card",
             "top": ".gg-card-top", "title": ".gg-title", "actions": ".gg-actions",
             "menuCard": ".km-card"}


class LocalHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if any(part.startswith(".") for part in Path(path).parts) and path != "/.local/ggongbab-preview.json":
            self.send_error(404)
            return
        super().do_GET()

    def list_directory(self, path):
        self.send_error(404)
        return None


@contextmanager
def local_server(port=0):
    server = ThreadingHTTPServer(("127.0.0.1", port), partial(LocalHandler, directory=str(ROOT)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def rectangles(page):
    return page.evaluate("""selectors => Object.fromEntries(Object.entries(selectors).map(([key, sel]) => {
      const el = document.querySelector(sel); if (!el) return [key, null];
      const r = el.getBoundingClientRect();
      return [key, {x:Math.round(r.x), y:Math.round(r.y), w:Math.round(r.width), h:Math.round(r.height)}];
    }))""", SELECTORS)


def near(actual, expected):
    assert abs(actual - expected) <= 2, (actual, expected)


def reset_storage(page):
    page.evaluate("""() => {
      localStorage.removeItem('babdoduk-ggongbab-filter');
      localStorage.removeItem('babdoduk-foodhub-tab');
      localStorage.removeItem('babdoduk-menu-meal');
      localStorage.removeItem('babdoduk-menu-favorites');
    }""")


def hub_layout(page, width, report):
    page.locator(".food-hub-tabs").wait_for()
    page.locator(".gg-radar").wait_for()
    r = rectangles(page)
    if width < 720:
        near(r["radar"]["x"], 16)
        near(r["radar"]["w"], width - 32)
        near(r["tabs"]["x"], 16)
        near(r["tabs"]["w"], width - 32)
    else:
        near(r["page"]["x"], 360)
        near(r["page"]["w"], 720)
        near(r["radar"]["x"], 384)
        near(r["radar"]["w"], 672)
        near(r["tabs"]["x"], 384)
        near(r["tabs"]["w"], 672)
    assert page.locator(".food-hub-tab").count() == 2
    assert "풍년" in page.locator(".gg-radar-title").inner_text()
    assert page.locator("[data-featured]").count() == 1
    report["checks"] += 8


def hub_menu_flow(page, width, report):
    page.locator("#foodHubTabMenu").click()
    page.locator("#foodHubMenu").wait_for()
    assert page.locator("#foodHubTabMenu").get_attribute("aria-selected") == "true"
    assert page.locator("#foodHubFree").is_hidden()
    page.locator('[data-km-meal="lunch"]').click()
    assert page.locator('[data-km-meal="lunch"]').get_attribute("aria-pressed") == "true"
    page.locator(".km-card").first.wait_for()
    assert "영업 중" not in page.inner_text("body")
    page.evaluate("localStorage.setItem('babdoduk-menu-favorites', JSON.stringify(['east1']))")
    page.locator("#foodHubTabMenu").click()
    page.reload()
    page.locator("#foodHubTabMenu").click()
    page.locator('[data-km-meal="lunch"]').click()
    page.locator(".km-card").first.wait_for()
    assert page.locator(".km-card").first.get_attribute("data-km-id") == "east1"
    expander = page.locator('[data-km-id="icc"] [data-km-expand]')
    expander.click()
    assert expander.get_attribute("aria-expanded") == "true"
    assert page.locator('[data-km-id="icc"] .km-items li').count() >= 8
    if width >= 720:
        boxes = page.locator(".km-card").evaluate_all(
            "els => els.slice(0,2).map(el => { const r = el.getBoundingClientRect(); return {x:r.x,w:r.width}; })")
        near(round(boxes[0]["w"]), 330)
        near(round(boxes[1]["w"]), 330)
        near(round(boxes[0]["x"] + boxes[0]["w"] + 12), round(boxes[1]["x"]))
        report["checks"] += 3
    page.locator("#foodHubTabFree").click()
    assert page.locator("#foodHubTabFree").get_attribute("aria-selected") == "true"
    report["checks"] += 8


def run_checks(preview=False):
    OUT.mkdir(parents=True, exist_ok=True)
    report = {"fixture": {}, "preview": {}, "production": {}, "checks": 0}
    with local_server() as base, sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(timezone_id="Asia/Seoul", locale="ko-KR", reduced_motion="reduce")
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(type(error).__name__))
        for width, height in SIZES:
            page.set_viewport_size({"width": width, "height": height})
            page.goto(base + "/lab-ggongbab.html?fixture=1")
            reset_storage(page)
            page.goto(base + "/lab-ggongbab.html?fixture=1&debug-layout=1")
            page.locator(".gg-card").first.wait_for()
            page.locator(".gg-radar").wait_for()
            page.evaluate("document.fonts.ready")
            page.wait_for_timeout(150)
            hub_layout(page, width, report)
            r = rectangles(page)
            if width < 720:
                near(r["page"]["w"], width)
                near(r["card"]["x"], 16)
                near(r["card"]["w"], width - 32)
                near(r["filter"]["x"], 0)
                near(r["filter"]["w"], width)
            else:
                near(r["page"]["x"], 360)
                near(r["filter"]["x"], 360)
                near(r["filter"]["w"], 720)
                near(r["card"]["x"], 384)
                near(r["card"]["w"], 672)
            assert page.evaluate("document.documentElement.scrollWidth") <= width
            report["checks"] += 6
            for selector in (".gg-title", ".gg-summary"):
                assert page.locator(selector).first.evaluate("el => getComputedStyle(el).overflow") == "hidden"
                report["checks"] += 1
            page.screenshot(path=str(OUT / f"ggongbab-{width}x{height}.png"))
            report["fixture"][f"{width}x{height}"] = r
            page.evaluate("window.scrollTo(0, 450)")
            page.wait_for_timeout(100)
            sticky = rectangles(page)
            near(sticky["filter"]["y"], sticky["nav"]["h"])
            report["checks"] += 1
            page.locator('[data-group="when"][data-value="all"]').click()
            assert page.locator(".gg-card").count() == 10
            assert page.locator('[data-id="fixture-7"] .gg-title').evaluate(
                "el => el.scrollHeight > el.clientHeight && el.clientHeight <= 48")
            assert page.locator('[data-id="fixture-8"] .gg-summary').evaluate(
                "el => el.scrollHeight > el.clientHeight && el.clientHeight <= 42")
            assert not page.locator('[data-id="fixture-5"] .gg-btn--primary').count()
            assert page.evaluate("document.documentElement.scrollWidth") <= width
            assert page.locator('.gg-actions').evaluate_all("els => els.every(el => [...el.children].every(btn => btn.getBoundingClientRect().right <= el.closest('.gg-card').getBoundingClientRect().right))")
            assert page.locator('[data-id="fixture-0"] .gg-source').inner_text() == "KAIST 메일"
            assert page.locator('[data-id="fixture-1"] .gg-source').inner_text() == "KAIST 포탈"
            assert page.locator('[data-id="fixture-2"] .gg-source').inner_text() == "KAIST 공식 공지"
            assert page.locator('[data-id="fixture-3"] .gg-source').inner_text() == "밥도둑 등록"
            report["checks"] += 10
            page.evaluate("window.scrollTo(0, 0)")
            hub_menu_flow(page, width, report)
            reset_storage(page)
            if preview:
                page.goto(base + "/lab-ggongbab.html?preview=1")
                page.wait_for_function("document.querySelector('.gg-updated') || document.querySelector('.gg-state')")
                assert not page.get_by_text("Preview 데이터가 아직 없습니다.").count()
                page.evaluate("document.fonts.ready")
                page.wait_for_timeout(100)
                report["preview"][f"{width}x{height}"] = rectangles(page)
                page.screenshot(path=str(OUT / f"ggongbab-preview-{width}x{height}.png"))
                assert page.evaluate("document.documentElement.scrollWidth") <= width
                report["checks"] += 2
        # Public host: serve the same lab files without making any network call
        # to an actual public deployment. No .local request may be attempted.
        requests = []
        page.on("request", lambda req: requests.append(urlparse(req.url).path))
        def public_route(route):
            path = ROOT / urlparse(route.request.url).path.lstrip("/")
            if path.is_file() and ROOT in path.resolve().parents:
                route.fulfill(path=str(path))
            else:
                route.fulfill(status=404, body="")
        page.route("https://preview.invalid/**", public_route)
        page.goto("https://preview.invalid/lab-ggongbab.html?preview=1")
        page.get_by_text("Preview mode is available only on localhost.").wait_for()
        assert not any(path.startswith("/.local/") for path in requests)
        report["checks"] += 1
        # Normal mode still fetches the public feed; unsafe food states never
        # become public cards or inflate hero counts.
        from datetime import datetime, timedelta, timezone
        future = (datetime.now(timezone(timedelta(hours=9))) + timedelta(days=8)).isoformat()
        events = [{"id": state, "title": state, "startAt": future,
                   "food": {"provided": state}, "registration": {}} for state in ("true", "false", "unknown")]
        events.append({**events[0], "id": "review", "needs_review": True})
        events[0]["registration"] = {"required": "true", "deadline": "2020-01-01T00:00:00+09:00", "url": "https://example.org/register"}
        events[0]["location"] = {"building": "N1", "room": "101호", "name": "N1 101호"}
        page.goto(base + "/lab-ggongbab.html?fixture=1")
        reset_storage(page)
        requests.clear()
        page.route("**/data/ggongbab/latest.json", lambda route: route.fulfill(json={"events": events}))
        page.goto(base + "/lab-ggongbab.html")
        page.locator(".gg-card").first.wait_for()
        assert page.locator('[data-group="when"][data-value="all"]').get_attribute("aria-pressed") == "true"
        page.locator('[data-group="when"][data-value="all"]').click()
        assert page.locator(".gg-card").count() == 1
        assert "/data/ggongbab/latest.json" in requests
        assert not page.locator(".gg-diagnostic-toggle").count()
        assert not page.locator('.gg-btn--primary').count()
        assert "N1 · 101호 · N1" not in page.locator('.gg-place').inner_text()
        assert not errors, errors
        report["checks"] += 7
        page.evaluate("localStorage.setItem('babdoduk-ggongbab-filter', JSON.stringify({when:'today',food:'all'}))")
        page.reload()
        page.locator('#foodHubFree .gg-state').first.wait_for()
        assert page.locator('[data-group="when"][data-value="today"]').get_attribute("aria-pressed") == "true"
        page.evaluate("localStorage.removeItem('babdoduk-ggongbab-filter')")
        report["checks"] += 1
        # Preview diagnostics only render allowlisted numeric counters, even if
        # an unexpected local payload contains sensitive-looking extra fields.
        page.route("**/.local/ggongbab-preview.json", lambda route: route.fulfill(json={
            "events": [events[0]], "_preview": {"publicCount": 1, "subject": "PRIVATE_TEST", "aiCalls": "PRIVATE_TEST"}}))
        page.goto(base + "/lab-ggongbab.html?preview=1")
        page.locator('.gg-card').first.wait_for()
        page.locator('.gg-diagnostic-toggle').click()
        assert "PRIVATE_TEST" not in page.locator('.gg-diagnostic-panel').inner_text()
        assert page.locator('.gg-diagnostic-panel dd').all_text_contents() == ["1"]
        report["checks"] += 2
        page.unroute("**/.local/ggongbab-preview.json")
        page.route("**/.local/ggongbab-preview.json", lambda route: route.fulfill(status=404, body=""))
        page.goto(base + "/lab-ggongbab.html?preview=1")
        page.get_by_text("Preview 데이터가 아직 없습니다.").wait_for()
        assert "--preview-feed" in page.locator('.gg-state code').inner_text()
        report["checks"] += 1
        page.unroute("**/.local/ggongbab-preview.json")
        page.goto(base + "/lab-ggongbab.html?fixture=1")
        reset_storage(page)
        page.goto(base + "/lab-ggongbab.html?fixture=1")
        page.locator(".gg-radar").wait_for()
        assert page.evaluate("BabdodukKaistMenu.defaultMeal(new Date('2026-09-20T09:00:00+09:00'))") == "breakfast"
        assert page.evaluate("BabdodukKaistMenu.defaultMeal(new Date('2026-09-20T11:00:00+09:00'))") == "lunch"
        assert page.evaluate("BabdodukKaistMenu.defaultMeal(new Date('2026-09-20T15:30:00+09:00'))") == "dinner"
        assert page.evaluate("localStorage.getItem('babdoduk-foodhub-tab')") in (None, "free")
        page.locator("#foodHubTabMenu").click()
        assert page.evaluate("localStorage.getItem('babdoduk-foodhub-tab')") == "menu"
        report["checks"] += 5
        page.goto(base + "/lab-ggongbab.html?fixture=1&stale-menu=1")
        page.locator("#foodHubTabMenu").click()
        page.locator("[data-km-stale]").wait_for()
        assert "학식 업데이트 중" in page.locator(".gg-counts").inner_text()
        assert page.locator("#foodHubMenu h2").count() == 0 or "오늘" not in page.locator("#foodHubMenu h2").inner_text()
        page.locator("[data-km-stale-toggle]").click()
        page.locator(".km-card").first.wait_for()
        assert "최근 학식" in page.locator("#foodHubMenu h2").inner_text()
        report["checks"] += 3
        from datetime import datetime, timedelta, timezone
        now_kst = datetime.now(timezone(timedelta(hours=9)))
        soon = (now_kst + timedelta(hours=2)).replace(microsecond=0).isoformat()
        later = (now_kst + timedelta(hours=4)).replace(microsecond=0).isoformat()
        drought = {"events": []}
        one = {"events": [{"id": "one", "title": "one", "startAt": soon, "endAt": later,
                           "food": {"provided": "true", "type": "meal", "description": "점심"},
                           "sources": [{"type": "dooray"}]}]}
        page.unroute("**/data/ggongbab/latest.json")
        page.route("**/data/ggongbab/latest.json", lambda route: route.fulfill(json=drought))
        reset_storage(page)
        page.goto(base + "/lab-ggongbab.html")
        page.locator(".gg-radar-title").wait_for()
        assert "가뭄" in page.locator(".gg-radar-title").inner_text()
        page.locator('.km-cta[data-hub-tab="menu"]').click()
        assert page.locator("#foodHubTabMenu").get_attribute("aria-selected") == "true"
        page.locator("#foodHubTabFree").click()
        report["checks"] += 3
        page.route("**/data/ggongbab/latest.json", lambda route: route.fulfill(json=one))
        page.route("**/data/kaist-menu/latest.json", lambda route: route.fulfill(status=404, body=""))
        page.goto(base + "/lab-ggongbab.html")
        page.locator(".gg-card").first.wait_for()
        assert "한 끼" in page.locator(".gg-radar-title").inner_text()
        page.locator("#foodHubTabMenu").click()
        page.get_by_text("오늘 메뉴를 불러오지 못했어요.").wait_for()
        page.locator("#foodHubTabFree").click()
        assert page.locator(".gg-card").count() >= 1
        report["checks"] += 3
        page.unroute("**/data/kaist-menu/latest.json")
        page.unroute("**/data/ggongbab/latest.json")
        page.route("**/data/ggongbab/latest.json", lambda route: route.fulfill(json={"events": events}))
        # Production page. It carries no lab affordances, so fixture and preview
        # are not merely hidden - they are unreachable, and the page can only
        # ever read the public feed.
        page.unroute("**/.local/ggongbab-preview.json")
        local_hits = []
        page.route("**/.local/**", lambda route: (local_hits.append(route.request.url),
                                                  route.fulfill(status=404, body="")))
        for width, height in SIZES:
            page.set_viewport_size({"width": width, "height": height})
            for query in ("", "?fixture=1", "?preview=1", "?fixture=1&debug-layout=1"):
                requests.clear()
                page.goto(base + "/ggongbab.html" + query)
                page.locator(".gg-card").first.wait_for()
                page.locator('[data-group="when"][data-value="all"]').click()
                # Only the explicit-food, not-under-review event is public. The
                # false, unknown and needs_review rows must never render.
                assert page.locator(".gg-card").count() == 1, query
                assert page.locator(".gg-card").first.get_attribute("data-id") == "true"
                assert "/data/ggongbab/latest.json" in requests
                assert not local_hits, local_hits
                assert not page.locator(".gg-diagnostic-toggle").count()
                assert not page.locator(".lab-fork-ribbon").count()
                assert not page.evaluate("document.body.hasAttribute('data-gg-lab')")
                assert not page.locator('meta[name="robots"]').count()
                assert page.title() == "오늘 뭐 먹지? · 밥도둑 Babdoduk"
                assert page.evaluate("document.documentElement.scrollWidth") <= width
                report["checks"] += 10
            report["production"][f"{width}x{height}"] = rectangles(page)
            page.screenshot(path=str(OUT / f"ggongbab-prod-{width}x{height}.png"))
        assert not errors, errors
        report["checks"] += 1
        browser.close()
    (OUT / "layout-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--serve", action="store_true", help="serve the local lab safely on loopback")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if args.serve:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), partial(LocalHandler, directory=str(ROOT)))
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    else:
        run_checks(args.preview)
