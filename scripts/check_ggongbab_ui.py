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
             "filter": ".gg-filters", "day": ".gg-day", "card": ".gg-card",
             "top": ".gg-card-top", "title": ".gg-title", "actions": ".gg-actions"}


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
            page.evaluate("localStorage.removeItem('babdoduk-ggongbab-filter')")
            page.goto(base + "/lab-ggongbab.html?fixture=1&debug-layout=1")
            page.locator(".gg-card").first.wait_for()
            page.evaluate("document.fonts.ready")
            page.wait_for_timeout(150)
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
            report["checks"] += 6
            page.evaluate("window.scrollTo(0, 0)")
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
        page.evaluate("localStorage.removeItem('babdoduk-ggongbab-filter')")
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
        page.locator('.gg-state').wait_for()
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
                assert page.title() == "꽁밥 안내 · 밥도둑 Babdoduk"
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
