"""Synthetic JS + real renderer tests. Every browser request is intercepted."""
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urlparse
from uuid import UUID

import pytest
from playwright.sync_api import sync_playwright

from ggongbab.public_feed import PUBLIC_COLUMNS, to_snapshot_event

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "js/ggongbab-public-feed.js"
CONFIG = "window.BABDODUK_PUBLIC_FEED_CONFIG={SUPABASE_URL:'https://public.invalid',SUPABASE_PUBLISHABLE_KEY:'sb_publishable_SYNTHETIC'};"
NOW = datetime.fromisoformat("2026-09-23T09:00:00+09:00")


def row(number=1, **changes):
    return {"id": str(UUID(int=number)), "title": f"Public lunch {number}", "summary": "Campus lunch",
            "start_at": "2026-09-23T12:00:00+09:00", "end_at": "2026-09-23T13:00:00+09:00",
            "date_text": "", "time_text": "", "location_name": "N1", "building": "N1", "room": "101",
            "food_provided": "true", "food_type": "meal", "food_description": "Lunch",
            "organizer": "Campus", "eligibility": "All", "registration_required": "unknown",
            "registration_deadline": None, "registration_url": "", "source_types": ["portal"],
            "confidence": 0.9, "content_revision": "r1", "updated_at": "2026-09-23T00:00:00Z", **changes}


MOCK_CLIENT = """(() => {
  window.feedTest = {rows: [], selects: [], channels: [], creates: 0, removes: 0, active: 0, maxActive: 0, disconnected: 0};
  const t = window.feedTest;
  window.supabase = {createClient(url, key, options) {
    t.creates++; t.options = options;
    return {
      realtime: {disconnect() { t.disconnected++; }},
      from(table) {
        const call = {table, order: []}; t.selects.push(call);
        return {
          select(columns) { call.columns = columns; return this; },
          order(field) { call.order.push(field); return this; },
          range(start, end) { call.start = start; call.end = end; return this; },
          async abortSignal() {
            if (t.failSelect) return {error: true};
            return {data: t.rows.slice(call.start, call.end + 1)};
          }
        };
      },
      channel() {
        t.active++; t.maxActive = Math.max(t.maxActive, t.active);
        const ch = {
          on(event, filter, cb) { Object.assign(ch, {event, filter, cb}); return ch; },
          subscribe(cb) { ch.status = cb; queueMicrotask(() => cb(t.failSubscribe ? 'CHANNEL_ERROR' : 'SUBSCRIBED')); return ch; }
        };
        t.channels.push(ch); return ch;
      },
      async removeChannel() { t.removes++; t.active--; }
    };
  }};
  t.change = (eventType, data) => t.channels.at(-1).cb(eventType === 'DELETE' ? {eventType, old: data} : {eventType, new: data});
})();"""


def test_node_controller_suite():
    result = subprocess.run(["node", "--test", "tests/ggongbab/public_feed.test.cjs"], cwd=ROOT,
                            capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("provided", ["true", "false", "unknown"])
def test_python_js_mapping_parity(provided):
    source = row(food_provided=provided, registration_required=provided,
                 start_at="2026-09-23T03:00:00.123Z", end_at=None,
                 registration_deadline="2026-09-22T23:00:00Z",
                 source_types=["dooray", "dooray_mailbox", "kaist_public", "manual", "portal"])
    result = subprocess.run(["node", "-e",
        "const f=require('./js/ggongbab-public-feed.js');process.stdin.on('data',d=>process.stdout.write(JSON.stringify(f.mapRow(JSON.parse(d)))));"],
        cwd=ROOT, input=json.dumps(source), capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert result.returncode == 0
    assert json.loads(result.stdout) == to_snapshot_event(source)


def test_static_browser_security_contract():
    code = SCRIPT.read_text(encoding="utf-8")
    browser_files = [SCRIPT, ROOT / "js/ggongbab.js", ROOT / "js/ggongbab-select.js",
                     ROOT / "js/ggongbab-public-config.js", ROOT / "ggongbab.html",
                     ROOT / "lab-ggongbab.html", ROOT / "index.html"]
    public_source = "\n".join(path.read_text(encoding="utf-8") for path in browser_files)
    for forbidden in ("SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY", "JSESSIONID",
                      "raw_items", "ai_parse_runs", "event_sources", "event_conflicts",
                      "agent_heartbeats", "ingest_runs", "ggongbab_public_feed_state"):
        assert forbidden not in public_source
    assert re.findall(r"var TABLE = '([^']+)'", code) == ["ggongbab_public_events"]
    assert re.findall(r"client\.from\(([^)]+)\)", code) == ["TABLE"]
    assert tuple(re.search(r"var COLUMNS = '([^']+)'", code)[1].split(",")) == PUBLIC_COLUMNS
    assert not re.search(r"\.(insert|update|upsert|rpc)\s*\(", code)
    assert re.findall(r"([\w.]+)\.delete\(", code) == ["collection"]  # local Map, not DB
    assert ".innerHTML" not in code and "eval(" not in code
    assert "@2.116.0/dist/umd/supabase.js" in code
    assert "script.integrity = 'sha384-" in code
    config = (ROOT / "js/ggongbab-public-config.js").read_text(encoding="utf-8")
    assert re.findall(r"^  ([A-Z_]+):", config, re.M) == ["SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY"]


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        yield browser
        browser.close()


@pytest.fixture
def ui(browser):
    context = browser.new_context(timezone_id="Asia/Seoul", locale="ko-KR")
    page = context.new_page()
    # Dedicated synthetic integration clock; production/checker clocks unchanged.
    page.clock.install(time=NOW)
    state = {"config": True, "requests": [], "errors": [], "snapshot": {
        "generatedAt": "2026-09-23T09:00:00+09:00", "events": [to_snapshot_event(row(9))]}}

    def route(request):
        parsed = urlparse(request.request.url)
        state["requests"].append((parsed.hostname, parsed.path))
        if parsed.hostname != "app.invalid":
            request.abort()
        elif parsed.path == "/js/ggongbab-public-config.js":
            request.fulfill(content_type="application/javascript", body=CONFIG if state["config"] else "")
        elif parsed.path in ("/data/ggongbab/latest.json", "/.local/ggongbab-preview.json"):
            request.fulfill(json=state["snapshot"])
        else:
            file = (ROOT / parsed.path.lstrip("/")).resolve()
            if ROOT in file.parents and file.is_file() and not any(part.startswith(".") for part in Path(parsed.path).parts):
                request.fulfill(path=str(file))
            else:
                request.fulfill(status=404, body="")

    page.route("**/*", route)
    page.on("pageerror", lambda e: state["errors"].append(str(e)))
    state["page"] = page

    def open_page(rows=None, path="/lab-ggongbab.html", init="", mock=True):
        if mock:
            page.add_init_script(MOCK_CLIENT + "\nfeedTest.rows=" + json.dumps(rows if rows is not None else [row()]) + ";" + init)
        page.goto("https://app.invalid" + path)
        return page

    state["open"] = open_page
    yield state
    assert not state["errors"]
    context.close()


def ids(page):
    return page.locator(".gg-card").evaluate_all("els => els.map(el => el.dataset.id)")


def emit(page, kind, data):
    page.evaluate("([kind,data]) => feedTest.change(kind,data)", [kind, data])


def test_browser_select_subscription_and_timestamp(ui):
    page = ui["open"]()
    page.locator(".gg-card").wait_for()
    assert ids(page) == [row()["id"]]
    assert page.locator(".gg-updated").count() == 0
    assert page.evaluate("feedTest.selects.every(c => c.table === 'ggongbab_public_events')")
    assert page.evaluate("feedTest.selects[0].columns").split(",") == list(PUBLIC_COLUMNS)
    assert page.evaluate("feedTest.channels[0].filter") == {"event": "*", "schema": "public", "table": "ggongbab_public_events"}
    assert page.evaluate("feedTest.options.auth") == {"persistSession": False, "autoRefreshToken": False, "detectSessionInUrl": False}
    assert not any(path == "/data/ggongbab/latest.json" for host, path in ui["requests"])
    assert not any(host == "public.invalid" for host, path in ui["requests"])


def test_browser_insert_update_revision_and_delete_recalculates_ui(ui):
    page = ui["open"]([row(1), row(2, start_at="2026-09-23T15:00:00+09:00")])
    page.locator(".gg-card").first.wait_for()
    emit(page, "INSERT", row(3, start_at="2026-09-24T12:00:00+09:00"))
    assert len(ids(page)) == 3 and page.locator(".gg-day").count() == 2
    emit(page, "UPDATE", row(1, content_revision="r2", title="New title"))
    assert page.locator('[data-featured] .gg-title').inner_text() == "New title"
    page.evaluate("window.originalCard=document.querySelector('.gg-card')")
    emit(page, "UPDATE", row(1, content_revision="r2", updated_at="2026-09-24T00:00:00Z"))
    assert page.evaluate("originalCard === document.querySelector('.gg-card')")
    emit(page, "DELETE", {"id": row(1)["id"]})
    assert page.locator("[data-featured]").get_attribute("data-id") == row(2)["id"]
    assert "1" in page.locator(".gg-radar-count").inner_text()
    assert "1" in page.locator("#foodHubTabFree").inner_text()
    emit(page, "DELETE", {"id": row(2)["id"]})
    assert page.locator("[data-featured]").count() == 0
    assert page.locator(".gg-day").count() == 1
    assert "가뭄" in page.locator(".gg-radar-title").inner_text()
    emit(page, "DELETE", {"id": row(3)["id"]})
    assert page.locator(".gg-day").count() == 0 and ids(page) == []


def test_browser_filters_language_tab_and_cafeteria_survive_updates(ui):
    page = ui["open"]()
    page.locator(".gg-card").wait_for()
    page.locator('[data-group="when"][data-value="tomorrow"]').click()
    page.locator('[data-group="food"][data-value="snack"]').click()
    page.locator("#langToggle").click()
    page.locator("#foodHubTabMenu").click()
    emit(page, "INSERT", row(2))
    assert page.locator('[data-group="when"][data-value="tomorrow"]').get_attribute("aria-pressed") == "true"
    assert page.locator('[data-group="food"][data-value="snack"]').get_attribute("aria-pressed") == "true"
    assert page.locator("#foodHubTabMenu").get_attribute("aria-selected") == "true"
    assert page.locator("#foodHubFree").is_hidden()
    assert page.evaluate("babdodukGetLang()") == "en"
    assert page.locator("#foodHubMenu").is_visible()
    assert page.locator("[data-km-meal]").count() > 0
    assert page.evaluate("feedTest.channels.length") == 1


def test_browser_expiry_and_unsafe_content(ui):
    page = ui["open"]([row(1, title='<img src=x onerror="window.bad=true">', summary="<script>bad()</script>",
                                  registration_url="javascript:alert(1)", registration_required="true"),
                          row(2, end_at="2026-09-23T08:59:00+09:00"),
                          row(3, food_provided="unknown"), row(4, food_provided="false")])
    page.locator(".gg-card").wait_for()
    assert ids(page) == [row()["id"]]
    assert "<img" in page.locator(".gg-title").inner_text()
    assert page.locator(".gg-card img, .gg-card script, .gg-btn--primary").count() == 0
    assert not page.evaluate("window.bad === true")
    page.clock.fast_forward(5 * 3600000)
    assert ids(page) == []


@pytest.mark.parametrize("failure", ["config", "library", "select", "subscribe", "websocket"])
def test_browser_failures_use_snapshot(ui, failure):
    if failure == "config": ui["config"] = False
    if failure == "websocket": ui["page"].add_init_script("window.WebSocket=undefined;")
    page = ui["open"](init={"select": "feedTest.failSelect=true;", "subscribe": "feedTest.failSubscribe=true;"}.get(failure, ""),
                      mock=failure not in ("library", "websocket"))
    page.locator(".gg-card").wait_for()
    assert ids(page) == [row(9)["id"]]
    assert page.locator(".gg-updated").count() == 1
    assert not page.locator("#foodHubFree .gg-state").count()


@pytest.mark.parametrize("path", ["/lab-ggongbab.html?fixture=1", "/lab-ggongbab.html?preview=1",
                                   "/ggongbab.html?fixture=1", "/ggongbab.html?preview=1"])
def test_browser_query_isolation(ui, path):
    page = ui["open"](path=path)
    page.locator(".food-hub-tabs").wait_for()
    assert page.evaluate("feedTest.creates") == 0
    assert page.evaluate("feedTest.channels.length") == 0
    assert not any(host in ("public.invalid", "cdn.jsdelivr.net") for host, _ in ui["requests"])


def test_browser_localhost_preview_isolation(ui):
    # Intercept localhost as well; no server or real preview data is read.
    page = ui["page"]
    page.route("http://localhost/**", lambda route: route.fulfill(
        json=ui["snapshot"]) if urlparse(route.request.url).path == "/.local/ggongbab-preview.json" else route.fulfill(
            content_type="application/javascript", body=CONFIG) if urlparse(route.request.url).path == "/js/ggongbab-public-config.js" else route.fulfill(
                path=str(ROOT / urlparse(route.request.url).path.lstrip("/"))))
    page.add_init_script(MOCK_CLIENT)
    page.goto("http://localhost/lab-ggongbab.html?preview=1")
    page.locator(".gg-card").wait_for()
    assert page.evaluate("feedTest.creates") == 0
    assert page.evaluate("feedTest.channels.length") == 0


def test_browser_disconnect_keeps_feed_reconnect_replaces_full_set(ui):
    page = ui["open"]()
    page.locator(".gg-card").wait_for()
    page.evaluate("feedTest.channels.at(-1).status('CHANNEL_ERROR')")
    assert ids(page) == [row()["id"]]
    page.evaluate("feedTest.rows=[]")
    page.clock.run_for(1100)
    page.wait_for_function("feedTest.selects.length >= 3")
    assert ids(page) == []
    assert page.evaluate("feedTest.maxActive") == 1
    assert page.evaluate("feedTest.removes") == 1


def test_browser_snapshot_recovery_replaces_collection(ui):
    page = ui["open"](init="feedTest.failSelect=true;")
    page.locator(".gg-card").wait_for()
    assert ids(page) == [row(9)["id"]]
    page.evaluate("feedTest.failSelect=false")
    page.clock.run_for(1100)
    page.wait_for_function("document.querySelector('.gg-updated') === null")
    assert ids(page) == [row()["id"]]


def test_browser_page_lifecycle_cleanup_and_recovery(ui):
    page = ui["open"]()
    page.locator(".gg-card").wait_for()
    page.evaluate("window.dispatchEvent(new Event('pagehide'))")
    page.wait_for_function("feedTest.active === 0")
    page.evaluate("feedTest.rows=[]; window.dispatchEvent(new Event('pageshow'))")
    page.wait_for_function("feedTest.selects.length >= 3")
    assert ids(page) == []
    assert page.evaluate("feedTest.maxActive") == 1


def test_browser_visibility_pauses_and_reconciles(ui):
    page = ui["open"]()
    page.locator(".gg-card").wait_for()
    page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,value:true}); document.dispatchEvent(new Event('visibilitychange'))")
    page.wait_for_function("feedTest.active === 0")
    page.evaluate("feedTest.rows=[]; Object.defineProperty(document,'hidden',{configurable:true,value:false}); document.dispatchEvent(new Event('visibilitychange'))")
    page.wait_for_function("feedTest.selects.length >= 3")
    assert ids(page) == []
    assert page.evaluate("feedTest.maxActive") == 1
