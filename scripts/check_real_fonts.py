"""Real-font responsive smoke: public pages with the real web font, at phone and desktop widths.

The offline gates (check_site_ui.py, check_ggongbab_ui.py) block web fonts on purpose, so they
stay deterministic, but they cannot see overflow that only appears with the real Noto Sans KR
metrics. It happened in production: English filter chips on the food hub overflowed at 390
and 360 px. This separate command loads each public page in Korean and English and reports:

  PASS  every capture loaded the web font, and nothing overflowed or threw  (exit 0)
  FAIL  horizontal overflow or a page error, fonts or not                   (exit 1)
  SKIP  the web font did not load, so a clean result would prove nothing    (exit 3)

Pages come from this checkout through the loopback server in check_ggongbab_ui.py. Only
Google Fonts may be fetched from the internet; every other external request is aborted.
Free-food data (live and past listings) is synthetic, with long Korean and English text, so
coverage does not depend on what the feed holds today. It needs the network, so it is not part
of `python -m pytest tests`.

    python scripts/check_real_fonts.py
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from check_ggongbab_ui import local_server

PAGES = ["index.html", "ggongbab.html", "event.html", "mukbang.html", "history.html", "food.html"]
SIZES = [(390, 844), (360, 800), (1440, 900)]
FONT_HOSTS = {"fonts.googleapis.com", "fonts.gstatic.com"}
FONT_FAMILY = "Noto Sans KR"
EXIT = {"PASS": 0, "FAIL": 1, "SKIP": 3}
LONG_KO = "캠퍼스 진로 탐색과 융합 연구 협력 그리고 함께하는 따뜻한 식사에 관한 아주 긴 제목"
LONG_EN = "Interdisciplinary research open house with a generously long English title"

MEASURE = """family => {
  const root = document.documentElement, body = document.body;
  const faces = [...document.fonts].filter(f => f.family.replace(/["']/g, '') === family);
  return {
    root: root.scrollWidth - root.clientWidth,
    body: body.scrollWidth - body.clientWidth,
    font: faces.some(f => f.status === 'loaded'),
    wide: [...body.querySelectorAll('*')].filter(el => {
      const r = el.getBoundingClientRect();
      return r.width && r.right > root.clientWidth + 1 && !el.closest('.site-nav');
    }).map(el => el.tagName.toLowerCase() + '.' + String(el.className).split(' ')[0]).slice(0, 4)
  };
}"""


def verdict(results: list[dict]) -> str:
    """FAIL on any overflow or page error; otherwise PASS only if every capture proved its font."""
    if any(r["overflow"] > 0 or r["errors"] for r in results):
        return "FAIL"
    if not results or not all(r["font"] for r in results):
        return "SKIP"
    return "PASS"


def synthetic_feeds(now: datetime) -> tuple[dict, dict]:
    def event(event_id, start, title, **extra):
        return {"id": event_id, "title": title, "summary": f"{LONG_KO}. {LONG_EN}.",
                "startAt": start.isoformat(), "endAt": (start + timedelta(hours=1)).isoformat(),
                "location": {"building": "N1", "room": "101호", "name": "KI빌딩 퓨전홀"},
                "food": {"provided": "true", "type": "lunchbox", "description": "점심 도시락"},
                "organizer": LONG_KO, "eligibility": LONG_EN,
                "sources": [{"type": "kaist_public", "name": "KAIST 공지", "url": "https://example.org/notice"}], **extra}

    live = {"generatedAt": now.isoformat(), "events": [
        event("rf-today", now + timedelta(hours=1), LONG_KO,
              registration={"required": "true", "url": "https://example.org/register", "deadline": None}),
        event("rf-later", now + timedelta(days=3), LONG_EN)]}
    past = {"generatedAt": now.isoformat(), "windowDays": 30, "events": [
        event(f"rf-past-{i}", now - timedelta(days=i + 1, hours=2), LONG_EN if i % 2 else LONG_KO) for i in range(6)]}
    return live, past


def run(pages=PAGES, sizes=SIZES) -> dict:
    now = datetime.now(timezone(timedelta(hours=9))).replace(microsecond=0)
    live, past = synthetic_feeds(now)
    results: list[dict] = []
    font_responses = {"ok": 0, "failed": 0}
    with local_server() as base, sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True, ignore_default_args=["--hide-scrollbars"],
                                     args=["--disable-features=OverlayScrollbar,FluentOverlayScrollbar"])
        context = browser.new_context(timezone_id="Asia/Seoul", locale="ko-KR", service_workers="block")

        def route(request_route):
            url = urlparse(request_route.request.url)
            if url.hostname in ("127.0.0.1", "localhost") or url.hostname in FONT_HOSTS:
                request_route.continue_()
            else:
                request_route.abort()

        context.route("**/*", route)
        context.route("**/data/ggongbab/latest.json", lambda r: r.fulfill(json=live))
        context.route("**/data/ggongbab/archive/index.json", lambda r: r.fulfill(json=past))
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(type(error).__name__ + ": " + str(error)[:120]))

        def on_response(response):
            if urlparse(response.url).hostname in FONT_HOSTS:
                font_responses["ok" if response.ok else "failed"] += 1

        page.on("response", on_response)
        page.on("requestfailed", lambda req: font_responses.__setitem__("failed", font_responses["failed"] + 1)
                if urlparse(req.url).hostname in FONT_HOSTS else None)
        for lang in ("ko", "en"):
            for width, height in sizes:
                page.set_viewport_size({"width": width, "height": height})
                page.goto(base + "/index.html")
                page.evaluate("lang => localStorage.setItem('babdoduk-lang', lang)", lang)
                for name in pages:
                    errors.clear()
                    page.goto(f"{base}/{name}", wait_until="networkidle")
                    page.evaluate("document.fonts.ready")
                    page.wait_for_timeout(200)
                    m = page.evaluate(MEASURE, FONT_FAMILY)
                    results.append({"page": name, "lang": lang, "size": f"{width}x{height}",
                                    "overflow": max(m["root"], m["body"], 0), "font": m["font"],
                                    "wide": m["wide"], "errors": list(errors)})
        browser.close()
    status = verdict(results)
    return {"status": status, "captures": len(results), "fontLoaded": sum(r["font"] for r in results),
            "fontResponses": font_responses,
            "problems": [r for r in results if r["overflow"] > 0 or r["errors"] or not r["font"]]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.parse_args()
    try:
        report = run()
    except Exception as exc:  # the browser or the loopback server could not start
        print(json.dumps({"status": "SKIP", "reason": type(exc).__name__ + ": " + str(exc)[:200]}, indent=2))
        print("real-font smoke: SKIP (could not run)")
        return EXIT["SKIP"]
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"real-font smoke: {report['status']} ({report['captures']} captures, "
          f"web font loaded in {report['fontLoaded']}/{report['captures']}, "
          f"font responses ok {report['fontResponses']['ok']} failed {report['fontResponses']['failed']})")
    return EXIT[report["status"]]


if __name__ == "__main__":
    sys.exit(main())
