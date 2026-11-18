"""마이 밥도둑, Phase 2 (docs/MY_BABDODUK.md) in the browser: optional sign-in on my.html, the automatic
guest merge with undo, the account's saved free-food list on my.html and on the food hub, the private
display name, signing out, clearing data and leaving with a fresh sign-in.

A fake Supabase client is installed as window.supabase before any page script runs, so the pinned SDK
is never fetched and no real project is called. Its tables live in this test browser's localStorage and
follow the same own-rows rule as supabase/migrations/011_accounts.sql (tested against PostgreSQL in
tests/test_accounts_db.py). Sign-in redirects are recorded, not followed: real Google and Kakao logins
are checked by hand on a phone (NOT TESTED here).
"""
import json
from datetime import datetime, timedelta, timezone
import re
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
HOST = "my-babdoduk.invalid"
NOW = "2026-11-09T09:00:00+09:00"
SAVED_KEY = "babdoduk-ggongbab-saved"
TOKEN_KEY = "sb-myjglfynhnptlclawlcc-auth-token"
UID = "11111111-1111-4111-8111-111111111111"
CONFIG = (ROOT / "js/babdoduk-auth-config.js").read_text(encoding="utf-8")
ON = f"window.BABDODUK_AUTH_CONFIG = {{enabled: true, hosts: ['{HOST}']}};"
OFF = f"window.BABDODUK_AUTH_CONFIG = {{enabled: false, hosts: ['{HOST}']}};"
GOOGLE_ID = "123456789012-synthetictestclientid.apps.googleusercontent.com"
GOOGLE_REQUESTS = []   # Google sign-in addresses the page went to (the fake network aborts them)
ON_GOOGLE = f"window.BABDODUK_AUTH_CONFIG = {{enabled: true, hosts: ['{HOST}'], googleClientId: '{GOOGLE_ID}'}};"


def ev(event_id, start, end, title=None):
    return {"id": event_id, "title": title or f"{event_id} 행사", "summary": "", "startAt": start, "endAt": end,
            "dateText": "", "timeText": "", "location": {"name": "E11 강의실", "building": "E11", "room": "101호"},
            "food": {"provided": "true", "type": "meal", "description": "샌드위치"}, "organizer": "", "eligibility": "",
            "registration": {"required": "unknown", "deadline": None, "url": ""}, "confidence": 0.95,
            "sources": [{"type": "dooray", "name": "Dooray"}]}


LUNCH = ev("lunch", "2026-11-09T12:00:00+09:00", "2026-11-09T13:00:00+09:00", "점심 세미나")
WED = ev("wed", "2026-11-11T17:00:00+09:00", "2026-11-11T18:00:00+09:00", "수요 간담회")
OLD = ev("oldone", "2026-11-05T12:00:00+09:00", "2026-11-05T13:00:00+09:00", "지난 세미나")
LIVE = {"schemaVersion": 1, "generatedAt": "2026-11-09T08:30:00+09:00", "timezone": "Asia/Seoul", "events": [LUNCH, WED]}
ARCHIVE = {"generatedAt": "2026-11-09T08:30:00+09:00", "windowDays": 30, "events": [OLD]}


def seen(event, place="E11 강의실"):
    return {"title": event["title"], "startAt": event["startAt"], "endAt": event["endAt"], "place": place}


def local(*items):
    return json.dumps({"v": 1, "items": [{"id": e["id"], "savedAt": at, "seen": seen(e)} for e, at in items]})


FAKE = r"""
(() => {
  const KEY = '__fakedb';
  const load = () => JSON.parse(localStorage.getItem(KEY) || 'null') ||
    { user: null, tables: { saved_events: [], saved_places: [], profiles: [] }, calls: [], fail: {} };
  const save = (db) => localStorage.setItem(KEY, JSON.stringify(db));
  const EVENT_ID = /^[A-Za-z0-9_-]{1,80}(#[0-9]{1,2})?$/;
  const keyOf = { saved_events: 'event_id', saved_places: 'place_id', profiles: 'user_id' };
  function query(table) {
    const filters = []; let op = 'select', payload = null, single = false, order = null;
    const run = () => {
      const db = load(); const uid = db.user && db.user.id;
      db.calls.push([table, op]);
      if (!uid || db.fail[table] || db.fail[table + ':' + op]) { save(db); return { data: null, error: { message: 'refused' } }; }
      const rows = db.tables[table] = db.tables[table] || [];
      const hit = rows.filter(r => r.user_id === uid && filters.every(f => f(r)));
      let data = null;
      if (op === 'select') {
        data = hit.map(r => Object.assign({}, r));
        if (order) data.sort((a, b) => (a[order[0]] < b[order[0]] ? -1 : 1) * (order[1] ? 1 : -1));
        if (single) data = data[0] || null;
      } else if (op === 'insert') {
        const row = Object.assign({}, payload);
        const k = keyOf[table];
        if (row.user_id !== uid || rows.some(r => r.user_id === uid && r[k] === row[k])) { save(db); return { data: null, error: { message: 'rls' } }; }
        rows.push(row);
      } else if (op === 'update') {
        hit.forEach(r => Object.assign(r, payload));
      } else if (op === 'delete') {
        db.tables[table] = rows.filter(r => hit.indexOf(r) === -1);
      } else if (op === 'upsert') {
        const row = Object.assign({}, payload);
        const had = rows.find(r => r.user_id === uid);
        if (row.user_id !== uid) { save(db); return { data: null, error: { message: 'rls' } }; }
        if (had) Object.assign(had, row); else rows.push(row);
      }
      save(db);
      return { data, error: null };
    };
    const b = {
      select() { return b; }, limit() { return b; },
      order(col, o) { order = [col, !!(o && o.ascending)]; return b; },
      eq(col, v) { filters.push(r => r[col] === v); return b; },
      in(col, vs) { filters.push(r => vs.indexOf(r[col]) !== -1); return b; },
      insert(row) { op = 'insert'; payload = row; return b; },
      update(p) { op = 'update'; payload = p; return b; },
      delete() { op = 'delete'; return b; },
      upsert(row) { op = 'upsert'; payload = row; return b; },
      maybeSingle() { single = true; return b; },
      then(ok, no) { return Promise.resolve().then(run).then(ok, no); }
    };
    return b;
  }
  function rpc(name, args) {
    return Promise.resolve().then(() => {
      const db = load(); const uid = db.user && db.user.id;
      db.calls.push(['rpc', name, args || null]);
      if (!uid || db.fail['rpc:' + name]) { save(db); return { data: null, error: { message: 'refused' } }; }
      let data = null;
      if (name === 'merge_saved_events') {
        let added = 0;
        (args.p_items || []).forEach(item => {
          if (!item || !EVENT_ID.test(String(item.id || ''))) return;
          const had = db.tables.saved_events.find(r => r.user_id === uid && r.event_id === item.id);
          if (had) { if (item.savedAt < had.saved_at) had.saved_at = item.savedAt; return; }
          db.tables.saved_events.push({ user_id: uid, event_id: item.id, saved_at: item.savedAt, seen: item.seen || {} });
          added += 1;
        });
        data = added;
      } else if (name === 'merge_saved_places') {
        let added = 0; const conflicts = [];
        (args.p_items || []).forEach(item => {
          const had = db.tables.saved_places.find(r => r.user_id === uid && r.place_id === item.id);
          if (had) { if ((item.memo || '').trim() && item.memo !== had.memo) conflicts.push(item.id); return; }
          db.tables.saved_places.push({ user_id: uid, place_id: item.id, status: item.status, memo: item.memo || '' });
          added += 1;
        });
        data = { added, conflicts };
      } else if (name === 'my_calendar_link') {
        // 016_calendar_connect.sql: present only when a test gives db.calLink; otherwise the function is missing.
        if (!db.calLink) { save(db); return { data: null, error: { message: 'Could not find the function', code: 'PGRST202' } }; }
        data = db.calLink;
      } else if (name === 'my_calendar_feed') {
        db.feeds = db.feeds || {};
        if (!db.feeds[uid] || args.p_new) db.feeds[uid] = (args.p_new ? 'N' : 'T').repeat(43);
        data = db.feeds[uid];
      } else if (name === 'delete_my_saved_data') {
        ['saved_events', 'saved_places'].forEach(t => { db.tables[t] = db.tables[t].filter(r => r.user_id !== uid); });
      } else if (name === 'delete_my_account') {
        if (Date.now() - Date.parse(db.user.last_sign_in_at) > 10 * 60 * 1000) { save(db); return { data: null, error: { message: 'sign in again' } }; }
        Object.keys(db.tables).forEach(t => { db.tables[t] = db.tables[t].filter(r => r.user_id !== uid); });
        db.deleted = uid;
      }
      save(db);
      return { data, error: null };
    });
  }
  const auth = {
    getSession() {
      const db = load();
      if (db.fail.session) return Promise.resolve({ data: { session: null }, error: { message: 'down' } });
      return Promise.resolve({ data: { session: db.user ? { user: db.user } : null }, error: null });
    },
    signInWithOAuth(o) { const db = load(); db.calls.push(['oauth', o.provider, o.options.redirectTo]); save(db); return Promise.resolve({ data: {}, error: null }); },
    signInWithIdToken(o) { const db = load(); db.calls.push(['idtoken', o.provider, o.token, o.nonce]);
      if (!db.fail.idtoken) db.user = db.signInAs; save(db);
      return Promise.resolve(db.fail.idtoken ? { data: null, error: { message: 'Bad ID token' } } : { data: {}, error: null }); },
    linkIdentity(o) { const db = load();
      if (o.token) { db.calls.push(['link-token', o.provider, o.token, o.nonce]); save(db); return Promise.resolve({ data: {}, error: null }); }
      db.calls.push(['link', o.provider, o.options.redirectTo]); save(db);
      return Promise.resolve(db.fail.link ? { data: null, error: { message: 'Manual linking is disabled' } } : { data: {}, error: null }); },
    signOut(o) { const db = load(); db.calls.push(['signout', o && o.scope]);
      // Like supabase-js 2.116: the local session goes even when the server call fails.
      if (db.fail.signoutKeep) { save(db); return Promise.resolve({ error: { message: 'down' } }); }
      db.user = null; save(db); localStorage.removeItem('""" + TOKEN_KEY + r"""');
      return Promise.resolve({ error: db.fail.signout ? { message: 'server down' } : null }); }
  };
  window.supabase = { createClient(url, key, opts) {
    const db = load(); db.calls.push(['client', url, key, opts]); save(db);
    return { auth, from: query, rpc };
  } };
})();
"""


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        chrome = pw.chromium.launch(channel="chrome", headless=True)
        yield chrome
        chrome.close()


def user(signed_in="2026-11-09T08:55:00+09:00", providers=("kakao",), name="밥친구"):
    return {"id": UID, "last_sign_in_at": signed_in, "user_metadata": {"nickname": name} if name else {},
            "identities": [{"provider": p} for p in providers], "app_metadata": {"providers": list(providers)}}


def open_page(browser, path="my.html", db=None, storage=None, enabled=True, lang="ko", size=(390, 844), ua=None,
              google=False, session=None):
    options = {"viewport": {"width": size[0], "height": size[1]}, "timezone_id": "Asia/Seoul", "service_workers": "block"}
    if ua:
        options["user_agent"] = ua
    context = browser.new_context(**options)
    init = [f"localStorage.setItem('babdoduk-lang', '{lang}');", "localStorage.setItem('babdoduk-notice-ggongbab-live', '1');"]
    state = {"user": None, "tables": {"saved_events": [], "saved_places": [], "profiles": []}, "calls": [], "fail": {}}
    state.update(db or {})
    init.append(f"if (!localStorage.getItem('__fakedb')) localStorage.setItem('__fakedb', {json.dumps(json.dumps(state))});")
    if state["user"]:
        init.append(f"if (!sessionStorage.getItem('__seeded')) {{ localStorage.setItem('{TOKEN_KEY}', '{{}}'); sessionStorage.setItem('__seeded', '1'); }}")
    for key, value in (session or {}).items():
        init.append(f"if (!sessionStorage.getItem('__ss_{key}')) {{ sessionStorage.setItem({json.dumps(key)}, {json.dumps(value)}); sessionStorage.setItem('__ss_{key}', '1'); }}")
    for key, value in (storage or {}).items():
        init.append(f"if (!sessionStorage.getItem('__s_{key}')) {{ localStorage.setItem({json.dumps(key)}, {json.dumps(value)}); sessionStorage.setItem('__s_{key}', '1'); }}")
    context.add_init_script(" ".join(init) + FAKE)
    sdk_requests = []
    google_requests = GOOGLE_REQUESTS

    def handle(route):
        url = urlparse(route.request.url)
        if "supabase" in route.request.url and url.hostname != HOST:
            sdk_requests.append(route.request.url)
            return route.abort()
        if url.hostname != HOST:
            if url.hostname == "accounts.google.com":
                google_requests.append(route.request.url)
                return route.fulfill(status=204, body="")   # "no content": the tab stays on my.html
            return route.abort()
        name = unquote(url.path).lstrip("/")
        if name == "data/ggongbab/latest.json":
            return route.fulfill(json=LIVE)
        if name == "data/ggongbab/archive/index.json":
            return route.fulfill(json=ARCHIVE)
        if name == "js/babdoduk-auth-config.js":
            return route.fulfill(content_type="application/javascript", body=(ON_GOOGLE if google else ON) if enabled else OFF)
        if name == "js/ggongbab-public-feed.js":
            return route.fulfill(content_type="application/javascript", body="")
        if name.startswith("data/"):
            return route.fulfill(status=404, body="")
        file = (ROOT / name).resolve()
        if file.is_file() and ROOT in file.parents:
            return route.fulfill(path=str(file))
        return route.fulfill(status=404, body="")

    context.route("**/*", handle)
    page = context.new_page()
    page.clock.set_fixed_time(NOW)
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(f"https://{HOST}/{path}", wait_until="networkidle")
    return context, page, errors, sdk_requests


def fakedb(page):
    return page.evaluate("JSON.parse(localStorage.getItem('__fakedb'))")


def app_text(page):
    return page.locator("#myApp").inner_text()


def wait_view(page, text):
    page.wait_for_function("t => document.getElementById('myApp').innerText.includes(t)", arg=text)


def test_on_for_lab_and_production():
    # On since 2026-11-10 on lab (owner: providers set up, 011 applied) and on production since 2026-11-11
    # (owner: "로그인은 푸시 및 배포가 안된거임? 이거까지 했어야지").
    assert re.search(r"enabled:\s*true", CONFIG)
    hosts = re.findall(r"'([^']+)'", re.search(r"hosts:\s*Object\.freeze\(\[([^\]]*)\]\)", CONFIG).group(1))
    assert {"www.babdodukms.com", "babdodukms.com", "babdoduk.vercel.app", "babdoduk-lab.vercel.app"} <= set(hosts)
    for name in ("js/babdoduk-account.js", "js/babdoduk-auth-config.js", "js/my.js"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "sb_secret_" not in text and "service_role" not in text, name
    vercel = (ROOT / "vercel.json").read_text(encoding="utf-8")
    assert "my\\\\.html" not in vercel, "my.html is served on every host"


def test_turned_off_the_pages_load_no_sign_in_client(browser):
    context, page, errors, sdk = open_page(browser, enabled=False, storage={SAVED_KEY: local((LUNCH, "2026-11-08T10:00:00Z"))})
    wait_view(page, "로그인은 준비 중이에요")
    assert "저장한 꽁밥 1개" in app_text(page)
    assert not [c for c in fakedb(page)["calls"] if c[0] == "client"] and not sdk
    page.goto(f"https://{HOST}/ggongbab.html", wait_until="networkidle")
    page.locator(".gg-card").first.wait_for()
    assert not [c for c in fakedb(page)["calls"] if c[0] == "client"]
    assert errors == []
    context.close()


def test_a_guest_on_the_hub_never_loads_the_client_even_when_turned_on(browser):
    context, page, errors, sdk = open_page(browser, path="ggongbab.html")
    page.locator(".gg-card").first.wait_for()
    assert not [c for c in fakedb(page)["calls"] if c[0] == "client"] and not sdk
    page.locator('.gg-card[data-id="lunch"] .gg-save').click()
    assert json.loads(page.evaluate(f"localStorage.getItem('{SAVED_KEY}')"))["items"][0]["id"] == "lunch"
    assert page.locator("#ggSaved").count() == 1  # copy cleanup, owner 2026-11-12: no "this browser only" line
    assert errors == []
    context.close()


def test_signed_out_offers_both_providers_with_a_full_page_redirect(browser):
    context, page, errors, _ = open_page(browser)
    wait_view(page, "카카오로 계속하기")
    text = app_text(page)
    # Owner 2026-11-12: "필요없는 글 다 삭제해줘": the sign-in card holds the buttons, little else.
    assert "KAIST" not in text and "이렇게 돼요" not in text and "저장한 꽁밥이 없어요" not in text
    client = [c for c in fakedb(page)["calls"] if c[0] == "client"][0]
    assert client[1] == "https://myjglfynhnptlclawlcc.supabase.co" and client[2].startswith("sb_publishable_")
    assert client[3]["auth"]["flowType"] == "pkce" and client[3]["auth"]["persistSession"] is True
    page.get_by_role("button", name="카카오로 계속하기").click()
    page.wait_for_function("() => JSON.parse(localStorage.getItem('__fakedb')).calls.some(c => c[0] === 'oauth')")
    page.reload(wait_until="networkidle")
    wait_view(page, "Google로 계속하기")
    page.get_by_role("button", name="Google로 계속하기").click()
    page.wait_for_function("() => JSON.parse(localStorage.getItem('__fakedb')).calls.filter(c => c[0] === 'oauth').length === 2")
    oauth = [c for c in fakedb(page)["calls"] if c[0] == "oauth"]
    assert oauth == [["oauth", "kakao", f"https://{HOST}/my.html"], ["oauth", "google", f"https://{HOST}/my.html"]]
    for button in page.locator(".my-login-btn").all():
        box = button.bounding_box()
        assert box["height"] >= 44
    assert errors == []
    context.close()


def test_inside_the_talk_app_google_becomes_open_in_the_default_browser(browser):
    ua = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36 KAKAOTALK 10.4.0"
    context, page, errors, _ = open_page(browser, ua=ua)
    wait_view(page, "카카오로 계속하기")
    assert page.get_by_role("button", name="Google로 계속하기").count() == 0
    link = page.get_by_role("link", name="기본 브라우저로 열기")
    assert link.get_attribute("href").startswith("kakaotalk://web/openExternal?url=")
    assert errors == []
    context.close()


TALK_UA = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36 KAKAOTALK 10.4.0"


def test_linking_the_other_login_and_what_the_talk_app_shows_instead(browser):
    # A normal browser: the missing provider is offered, with a full-page redirect back to my.html.
    context, page, errors, _ = open_page(browser, db={"user": user()})
    wait_view(page, "Google 로그인도 연결")
    page.get_by_role("button", name="Google 로그인도 연결").click()
    page.wait_for_function("() => JSON.parse(localStorage.getItem('__fakedb')).calls.some(c => c[0] === 'link')")
    assert [c for c in fakedb(page)["calls"] if c[0] == "link"] == [["link", "google", f"https://{HOST}/my.html?next=linked"]]
    assert errors == []
    context.close()
    # Supabase's manual linking turned off: the refusal is said, not swallowed.
    context, page, errors, _ = open_page(browser, db={"user": user(), "fail": {"link": True}})
    wait_view(page, "Google 로그인도 연결")
    page.get_by_role("button", name="Google 로그인도 연결").click()
    page.wait_for_function("() => document.getElementById('myToast').textContent.includes('연결할 수 없어요')")
    assert errors == []
    context.close()
    # Inside the talk app Google is refused, so the button gives way to the default-browser link.
    context, page, errors, _ = open_page(browser, db={"user": user()}, ua=TALK_UA)
    wait_view(page, "카카오톡에선 Google 연결이 안 돼요")  # copy cleanup, owner 2026-11-12
    assert page.get_by_role("button", name="Google 로그인도 연결").count() == 0
    link = page.get_by_role("link", name="기본 브라우저로 열기")
    assert link.count() == 1
    assert link.get_attribute("href") == "kakaotalk://web/openExternal?url=" + quote(f"https://{HOST}/my.html", safe="")
    assert errors == []
    context.close()
    # Signed in with Google inside the talk app: linking kakao still works there, so it stays a button.
    context, page, errors, _ = open_page(browser, db={"user": user(providers=("google",))}, ua=TALK_UA)
    wait_view(page, "카카오 로그인도 연결")
    assert page.get_by_role("link", name="기본 브라우저로 열기").count() == 0
    assert errors == []
    context.close()


def test_a_link_that_came_back_with_an_error_is_not_called_a_success(browser):
    context, page, errors, _ = open_page(browser, db={"user": user()})
    page.goto(f"https://{HOST}/my.html?next=linked&error=server_error&error_code=identity_already_exists", wait_until="networkidle")
    page.wait_for_function("() => document.getElementById('myToast').textContent.length > 0")
    toast = page.locator("#myToast").inner_text()
    assert "연결할 수 없어요" in toast and "연결했어요" not in toast
    context.close()
    context, page, errors, _ = open_page(browser, db={"user": user()})
    page.goto(f"https://{HOST}/my.html?next=linked", wait_until="networkidle")
    page.wait_for_function("() => document.getElementById('myToast').textContent.length > 0")
    assert "연결했어요" in page.locator("#myToast").inner_text()
    assert errors == []
    context.close()


def test_a_failed_login_says_so(browser):
    context, page, errors, _ = open_page(browser)
    page.goto(f"https://{HOST}/my.html?error=access_denied&error_description=x", wait_until="networkidle")
    wait_view(page, "로그인하지 못했어요")
    assert page.locator(".my-alert[role=alert]").count() == 1
    context.close()


def test_signing_in_merges_the_guest_list_once_keeps_the_account_copy_and_can_undo(browser):
    server_lunch = {"user_id": UID, "event_id": "lunch", "saved_at": "2026-11-08T12:00:00Z",
                    "seen": {"title": "서버에 저장된 제목", "startAt": LUNCH["startAt"], "endAt": LUNCH["endAt"], "place": "E11 강의실"}}
    guest = local((LUNCH, "2026-11-07T10:00:00Z"), (WED, "2026-11-08T10:00:00Z"))
    context, page, errors, _ = open_page(browser, db={"user": user(), "tables": {"saved_events": [server_lunch], "saved_places": [], "profiles": []}},
                                         storage={SAVED_KEY: guest})
    wait_view(page, "계정에 합쳤어요")
    assert "꽁밥 1개" in page.locator(".my-merge").inner_text()
    rows = {r["event_id"]: r for r in fakedb(page)["tables"]["saved_events"]}
    assert set(rows) == {"lunch", "wed"}
    assert rows["lunch"]["seen"]["title"] == "서버에 저장된 제목" and rows["lunch"]["saved_at"] == "2026-11-07T10:00:00Z"
    assert page.evaluate(f"localStorage.getItem('{SAVED_KEY}')") == guest, "the browser copy is never rewritten"
    assert "밥친구님, 반가워요" in app_text(page)
    page.reload(wait_until="networkidle")
    wait_view(page, "저장한 꽁밥")
    assert page.locator(".my-merge").count() == 0, "the same browser list merges once"
    assert len([c for c in fakedb(page)["calls"] if c[:2] == ["rpc", "merge_saved_events"]]) == 1
    # A new sign-in on a fresh browser state merges again, and 되돌리기 takes out exactly what it added.
    page.evaluate("localStorage.removeItem('babdoduk-account-merged')")
    page.evaluate("""() => { const db = JSON.parse(localStorage.getItem('__fakedb'));
        db.tables.saved_events = db.tables.saved_events.filter(r => r.event_id === 'lunch');
        localStorage.setItem('__fakedb', JSON.stringify(db)); }""")
    page.reload(wait_until="networkidle")
    wait_view(page, "계정에 합쳤어요")
    page.get_by_role("button", name="되돌리기").click()
    wait_view(page, "저장한 꽁밥")
    page.wait_for_function("() => !document.querySelector('.my-merge')")
    assert [r["event_id"] for r in fakedb(page)["tables"]["saved_events"]] == ["lunch"]
    assert errors == []
    context.close()


def test_the_account_list_shows_upcoming_past_and_missing_without_calling_anything_cancelled(browser):
    ghost = {"title": "사라진 행사", "startAt": "2026-11-12T12:00:00+09:00", "endAt": "2026-11-12T13:00:00+09:00", "place": "N1"}
    tables = {"saved_events": [
        {"user_id": UID, "event_id": "lunch", "saved_at": "2026-11-08T12:00:00Z", "seen": dict(seen(LUNCH), place="N1 다른 곳")},
        {"user_id": UID, "event_id": "oldone", "saved_at": "2026-11-04T12:00:00Z", "seen": seen(OLD)},
        {"user_id": UID, "event_id": "ghost", "saved_at": "2026-11-08T12:00:00Z", "seen": ghost},
        {"user_id": UID, "event_id": "morning", "saved_at": "2026-11-08T12:00:00Z",
         "seen": {"title": "아침 행사", "startAt": "2026-11-09T07:00:00+09:00", "endAt": "2026-11-09T08:00:00+09:00", "place": "N1"}},
        {"user_id": "someone-else", "event_id": "wed", "saved_at": "2026-11-08T12:00:00Z", "seen": seen(WED)}],
        "saved_places": [{"user_id": UID, "place_id": "p1", "status": "want", "memo": "비밀"},
                         {"user_id": UID, "place_id": "p2", "status": "again", "memo": ""}],
        "profiles": [{"user_id": UID, "display_name": "도둑"}]}
    context, page, errors, _ = open_page(browser, db={"user": user(), "tables": tables})
    wait_view(page, "저장한 꽁밥")
    rows = page.locator(".my-row").evaluate_all("els => els.map(el => [el.className, el.innerText])")
    assert [r[0] for r in rows] == ["my-row is-upcoming", "my-row is-ended"]
    assert "변경됨" in rows[0][1] and "지난 꽁밥" in rows[1][1] and "아침 행사" in rows[1][1]
    # Owner 2026-11-24 ("빠진거는 알아서 별표에서도 빠져야지"): a listing that left both public lists before it was
    # over loses its star by itself, so it also leaves the subscribed calendar.
    assert "사라진 행사" not in app_text(page) and "목록에서 빠짐" not in app_text(page)
    page.wait_for_function("() => !JSON.parse(localStorage.getItem('__fakedb')).tables.saved_events.some((r) => r.event_id === 'ghost')")
    # Owner 2026-11-12: from the day after its event a star leaves the list; the row stays for the calendar.
    assert "지난 세미나" not in app_text(page)
    assert "수요 간담회" not in app_text(page), "another user's row never shows"
    assert "취소" not in app_text(page)
    assert page.locator(".my-row.is-upcoming a").get_attribute("href") == f"https://{HOST}/ggongbab.html?e=lunch"
    # The restaurant list belongs to 밥약 메이커, which is lab-only: production shows no counts card
    # and never asks for them.
    assert page.locator(".my-counts").count() == 0 and "먹킷리스트" not in app_text(page)
    assert not [c for c in fakedb(page)["calls"] if "saved_places" in json.dumps(c) and "select" in json.dumps(c)]
    assert "비밀" not in page.content(), "memos stay out of this page"
    assert "도둑님, 반가워요" in app_text(page)
    assert errors == []
    context.close()


def test_the_hub_saves_to_the_account_and_leaves_the_browser_list_alone(browser):
    guest = local((OLD, "2026-11-04T10:00:00Z"))
    context, page, errors, _ = open_page(browser, path="ggongbab.html", db={"user": user()},
                                         storage={SAVED_KEY: guest, "babdoduk-account-merged": json.dumps({"v": 1, "users": {UID: "2026-11-09T00:00:00Z"}})})
    page.locator(".gg-card").first.wait_for()
    page.wait_for_function("() => document.querySelector('#ggSaved') === null || true")
    page.locator('.gg-card[data-id="lunch"] .gg-save').click()
    page.wait_for_function("() => JSON.parse(localStorage.getItem('__fakedb')).tables.saved_events.length === 1")
    assert page.locator("#ggSaved").count() == 1
    page.locator("[data-gg-saved]").click()
    assert "마이 밥도둑" in page.locator("#ggSaved").inner_text()  # copy cleanup, owner 2026-11-12: the account line is only the link now
    assert page.locator('#ggSaved a[href="my.html"]').count() == 1
    assert page.evaluate(f"localStorage.getItem('{SAVED_KEY}')") == guest
    toast = page.locator(".gg-toast")
    toast.wait_for(state="attached")
    page.wait_for_function("() => (document.querySelector('.gg-toast') || {}).textContent.includes('저장했어요')")  # copy cleanup, owner 2026-11-12
    # A refused write is undone on screen and said out loud.
    page.evaluate("""() => { const db = JSON.parse(localStorage.getItem('__fakedb')); db.fail['saved_events:insert'] = true;
        localStorage.setItem('__fakedb', JSON.stringify(db)); }""")
    page.locator('.gg-card[data-id="wed"] .gg-save').click()
    page.wait_for_function("() => document.querySelector('.gg-toast').textContent.includes('저장하지 못했어요')")
    assert page.locator('.gg-card[data-id="wed"] .gg-save').get_attribute("aria-pressed") == "false"
    assert [r["event_id"] for r in fakedb(page)["tables"]["saved_events"]] == ["lunch"]
    assert errors == []
    context.close()


def test_when_the_account_cannot_load_the_hub_keeps_the_browser_list_and_says_so(browser):
    guest = local((LUNCH, "2026-11-08T10:00:00Z"))
    context, page, errors, _ = open_page(browser, path="ggongbab.html", db={"user": user(), "fail": {"session": True}},
                                         storage={SAVED_KEY: guest})
    page.locator(".gg-card").first.wait_for()
    page.wait_for_function("() => !!document.querySelector('#ggSaved')")
    page.locator("[data-gg-saved]").click()
    page.wait_for_function("() => document.querySelector('#ggSaved').innerText.includes('계정 목록을 불러오지 못했어요')")  # copy cleanup, owner 2026-11-12
    assert page.locator('.gg-card[data-id="lunch"] .gg-save').get_attribute("aria-pressed") == "true"
    assert errors == []
    context.close()


def test_the_private_name_can_be_changed_and_signing_out_keeps_this_browser_list(browser):
    guest = local((LUNCH, "2026-11-08T10:00:00Z"))
    context, page, errors, _ = open_page(browser, db={"user": user(name="")}, storage={SAVED_KEY: guest})
    wait_view(page, "로그인했어요")
    page.get_by_role("button", name="바꾸기").click()
    page.locator("#myName").fill("  새 이름  ")
    page.get_by_role("button", name="저장", exact=True).click()
    wait_view(page, "새 이름님, 반가워요")
    assert fakedb(page)["tables"]["profiles"] == [{"user_id": UID, "display_name": "새 이름"}]
    page.get_by_role("button", name="로그아웃").first.click()
    wait_view(page, "카카오로 계속하기")
    assert ["signout", "local"] in fakedb(page)["calls"]
    assert page.evaluate(f"localStorage.getItem('{SAVED_KEY}')") == guest
    assert errors == []
    context.close()


def test_clearing_saved_data_keeps_the_account_and_can_clear_this_browser_too(browser):
    tables = {"saved_events": [{"user_id": UID, "event_id": "lunch", "saved_at": "2026-11-08T12:00:00Z", "seen": seen(LUNCH)}],
              "saved_places": [{"user_id": UID, "place_id": "p1", "status": "want", "memo": ""}], "profiles": []}
    context, page, errors, _ = open_page(browser, db={"user": user(), "tables": tables},
                                         storage={SAVED_KEY: local((LUNCH, "2026-11-08T10:00:00Z")),
                                                  "babdoduk-account-merged": json.dumps({"v": 1, "users": {UID: "2026-11-09T00:00:00Z"}})})
    wait_view(page, "저장한 데이터 지우기")
    page.get_by_role("button", name="저장한 데이터 지우기").click()
    page.get_by_label("이 브라우저에 저장한 목록도 지우기").check()
    page.get_by_role("button", name="모두 지우기").click()
    wait_view(page, "아직 저장한 꽁밥이 없어요")
    db = fakedb(page)
    assert ["rpc", "delete_my_saved_data", None] in db["calls"]
    assert db["tables"]["saved_events"] == [] and db["user"] is not None
    assert page.evaluate(f"localStorage.getItem('{SAVED_KEY}')") is None
    assert errors == []
    context.close()


def test_leaving_needs_a_fresh_sign_in_and_a_tick(browser):
    stale = user(signed_in="2026-11-09T07:00:00+09:00")
    context, page, errors, _ = open_page(browser, db={"user": stale})
    wait_view(page, "탈퇴하기")
    page.get_by_role("button", name="탈퇴하기").click()
    wait_view(page, "본인 확인을 위해")
    assert page.get_by_role("button", name="탈퇴하기").count() == 0
    page.get_by_role("button", name="카카오로 다시 로그인").click()
    page.wait_for_function("() => JSON.parse(localStorage.getItem('__fakedb')).calls.some(c => c[0] === 'oauth')")
    assert [c for c in fakedb(page)["calls"] if c[0] == "oauth"] == [["oauth", "kakao", f"https://{HOST}/my.html?next=leave"]]
    context.close()

    tables = {"saved_events": [{"user_id": UID, "event_id": "lunch", "saved_at": "2026-11-08T12:00:00Z", "seen": seen(LUNCH)}],
              "saved_places": [], "profiles": []}
    context, page, errors, _ = open_page(browser, path="my.html?next=leave", db={"user": user(), "tables": tables})
    wait_view(page, "모두 지워지는 것을 확인했어요")
    assert page.evaluate("location.search") == "", "the return marker is cleaned from the address"
    page.get_by_role("button", name="탈퇴하기").click()
    page.wait_for_function("() => document.getElementById('myToast').textContent.includes('확인란')")
    assert not [c for c in fakedb(page)["calls"] if c[:2] == ["rpc", "delete_my_account"]]
    page.get_by_label("모두 지워지는 것을 확인했어요").check()
    page.get_by_role("button", name="탈퇴하기").click()
    wait_view(page, "탈퇴했어요")
    db = fakedb(page)
    assert db.get("deleted") == UID and db["tables"]["saved_events"] == []
    assert page.evaluate(f"localStorage.getItem('{TOKEN_KEY}')") is None
    assert errors == []
    context.close()


def test_a_saved_event_is_removed_right_here_and_comes_back_if_the_server_refuses(browser):
    """Owner 2026-11-12: the filled star on 마이 밥도둑 removes a saved event without going to 오늘의 꽁밥."""
    tables = {"saved_events": [
        {"user_id": UID, "event_id": "lunch", "saved_at": "2026-11-08T12:00:00Z", "seen": seen(LUNCH)},
        {"user_id": UID, "event_id": "wed", "saved_at": "2026-11-04T12:00:00Z", "seen": seen(WED)}],
        "saved_places": [], "profiles": []}
    context, page, errors, _ = open_page(browser, db={"user": user(), "tables": tables})
    wait_view(page, "저장한 꽁밥")
    stars = page.locator("[data-my-unstar]")
    assert stars.count() == 2 and stars.first.get_attribute("aria-pressed") == "true"
    assert stars.first.get_attribute("aria-label").startswith("저장 취소: ")
    stars.first.click()
    page.wait_for_function("() => JSON.parse(localStorage.getItem('__fakedb')).tables.saved_events.length === 1")
    assert [r["event_id"] for r in fakedb(page)["tables"]["saved_events"]] == ["wed"]
    assert page.locator(".my-row").count() == 1 and "저장한 꽁밥 1" in page.locator("#mySavedTitle").inner_text()
    assert page.evaluate("document.activeElement.getAttribute('data-my-unstar')") == "wed"
    page.wait_for_function("() => document.getElementById('myToast').textContent === '저장을 취소했어요'")
    # The server refuses: the row comes back and the page says so.
    page.evaluate("""() => { const db = JSON.parse(localStorage.getItem('__fakedb')); db.fail['saved_events:delete'] = true;
                             localStorage.setItem('__fakedb', JSON.stringify(db)); }""")
    page.locator("[data-my-unstar]").click()
    page.wait_for_function("() => document.querySelectorAll('.my-row').length === 1")
    page.wait_for_function("() => document.getElementById('myToast').textContent.includes('저장하지 못했어요')")
    assert [r["event_id"] for r in fakedb(page)["tables"]["saved_events"]] == ["wed"]
    assert page.locator(".my-fine a[href='ggongbab.html']").inner_text() == "오늘의 꽁밥에서 더 저장하기"
    assert errors == []
    context.close()


IPHONE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
          "Version/18.0 Mobile/15E148 Safari/604.1")


def test_the_calendar_card_is_for_iphone_only_and_says_no_more_than_it_must(browser):
    """Owner 2026-11-12: set up once, then every star shows in the iPhone calendar (docs/CALENDAR_FEED.md).
    A laptop needs no calendar link and Android gets the 30-minute alert; no talk about addresses.
    Owner 2026-11-19 ("구독은 쌓여 ... 다른 방식을 찾아내봐"): the button installs a configuration profile that
    replaces itself, in three short steps. Before 016 the card uses 013's address and cannot know the state."""
    tables = {"saved_events": [], "saved_places": [], "profiles": []}
    context, page, errors, _ = open_page(browser, db={"user": user(), "tables": tables}, ua=IPHONE)
    wait_view(page, "아이폰 캘린더 연결")
    link = page.locator("[data-my-cal]")
    assert link.inner_text() == "아이폰 캘린더에 연결하기"
    assert link.get_attribute("href") == f"/cal/{'T' * 43}.mobileconfig"
    assert link.bounding_box()["height"] >= 44
    card = page.locator("section[aria-labelledby='myCalTitle']").inner_text()
    assert "주소" not in card and "구글" not in card and "한 번만" in card
    assert page.locator("#myCal .my-steps li").count() == 3 and "프로필이 다운로드됨" in card and "하나만 남아요" in card
    assert "사파리가 잠깐" not in card
    tap_calendar(page)
    wait_view(page, "설치를 기다리는 중")
    card = page.locator("#myCal").inner_text()
    assert "프로필이 다운로드됨" in card and page.locator("#myCal .my-cal-btn").count() == 0
    assert page.locator("#myCal [data-my-cal]").inner_text() == "프로필 다시 받기"
    page.reload()
    wait_view(page, "설치를 기다리는 중")   # the tap is remembered in this browser
    assert errors == []
    context.close()
    # Students use Chrome (owner 2026-11-19, "학생들 사파리 안써"): there the button hands just the profile's
    # address to Safari, and if the page is still in front a moment later it offers the file itself.
    chrome = IPHONE.replace("Version/18.0 Mobile/15E148 Safari", "CriOS/131.0.0.0 Mobile/15E148 Safari")
    context, page, errors, _ = open_page(browser, db={"user": user(), "tables": tables}, ua=chrome)
    wait_view(page, "사파리가 잠깐 열려요")
    link = page.locator("#myCal .my-cal-btn")
    assert link.get_attribute("href") == f"x-safari-https://{HOST}/cal/{'T' * 43}.mobileconfig"
    assert "크롬으로 돌아오면" in page.locator("#myCal").inner_text()
    tap_calendar(page)
    wait_view(page, "설치를 기다리는 중")
    assert page.locator("[data-my-cal-file]").count() == 0          # not before the handoff had its moment
    wait_view(page, "사파리가 열리지 않았어요.")
    file = page.locator("[data-my-cal-file]")
    assert file.get_attribute("href") == f"/cal/{'T' * 43}.mobileconfig" and file.bounding_box()["height"] >= 44
    assert "파일 앱" in page.locator("#myCal").inner_text()
    assert errors == []
    context.close()
    for ua in (None, "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36"):
        context, page, errors, _ = open_page(browser, db={"user": user(), "tables": tables}, ua=ua)
        wait_view(page, "저장한 꽁밥")
        assert page.locator("[data-my-cal]").count() == 0 and "캘린더" not in app_text(page) and errors == []
        context.close()
    # Before the database has the function (013 not applied), the card stays away.
    context, page, errors, _ = open_page(browser, db={"user": user(), "tables": tables, "fail": {"rpc:my_calendar_feed": True}}, ua=IPHONE)
    wait_view(page, "저장한 꽁밥")
    assert page.locator("[data-my-cal]").count() == 0 and errors == []
    context.close()


def tap_calendar(page, selector="[data-my-cal]"):
    """Taps the profile link without leaving the page (the browser under test has no Settings app)."""
    page.evaluate("""() => window.addEventListener('click', e => {
        if (e.target.closest('[data-my-cal]')) e.preventDefault(); }, true)""")
    page.locator(selector).first.click()


def iso_ago(hours):
    """A time before the pages' fixed clock (NOW), never the wall clock."""
    return (datetime.fromisoformat(NOW) - timedelta(hours=hours)).astimezone(timezone.utc).isoformat()


def test_the_calendar_card_shows_the_connection_like_a_setting(browser):
    """Owner 2026-11-19 ("gmail 같은것처럼 이거 설정할 수 있게 해봐", "로직을 전면 수정해", "구독은 쌓여"): with 016 the
    card says whether the calendar is connected and when it last checked, and offers the big button only when it
    is not. A tap waits for the calendar's first read and turns into 연결됨 by itself; installing again replaces
    the profile, so it never leaves a second calendar. An old webcal subscription still read (017) is named."""
    tables = {"saved_events": [], "saved_places": [], "profiles": []}
    fresh = {"link": "L" * 43, "read_at": None, "linked_at": None}
    context, page, errors, _ = open_page(browser, db={"user": user(), "tables": tables, "calLink": fresh}, ua=IPHONE)
    wait_view(page, "아이폰 캘린더 연결")
    assert page.locator("#myCal .my-cal-btn").get_attribute("href") == f"/cal/{'L' * 43}.mobileconfig"
    tap_calendar(page)
    wait_view(page, "설치를 기다리는 중")
    # The phone installed the profile and read the address: the server now offers the next one.
    page.evaluate("""(at) => { const db = JSON.parse(localStorage.getItem('__fakedb'));
        db.calLink = { link: 'M'.repeat(43), read_at: at, linked_at: at }; localStorage.setItem('__fakedb', JSON.stringify(db));
        document.dispatchEvent(new Event('visibilitychange')); }""", iso_ago(0.1))
    wait_view(page, "연결됨")
    card = page.locator("#myCal").inner_text()
    assert "다시 설치할 필요 없어요" in card and "캘린더가 마지막으로 확인한 때:" in card and "하나만 남아요" in card
    # The nearest thing to a 동기화 button (owner 2026-11-19): it opens the Calendar app, where pulling the list
    # down reads the new stars at once; no website can make the iPhone refresh by itself.
    opener = page.locator("#myCal [data-my-cal-open]")
    assert opener.get_attribute("href") == "calshow://" and opener.inner_text() == "캘린더 열기"
    assert opener.bounding_box()["height"] >= 44 and "목록을 아래로 당기면" in card
    assert "VPN 및 기기 관리" in card and "프로필 제거" in card
    assert page.locator("#myCal .my-cal-btn").count() == 0 and page.locator("#myCal .my-cal-leftover").count() == 0
    again = page.locator("#myCal [data-my-cal]")
    assert again.count() == 1 and again.get_attribute("href") == f"/cal/{'M' * 43}.mobileconfig"
    assert again.inner_text() == "캘린더에 안 보이면 다시 설치" and again.bounding_box()["height"] >= 44
    page.wait_for_function("() => document.getElementById('myToast').textContent.includes('캘린더가 연결됐어요')")
    assert errors == []
    context.close()
    # Connected, and an old webcal subscription still read today: the card says which calendar to delete.
    on = {"link": "N" * 43, "read_at": iso_ago(2), "linked_at": iso_ago(48), "leftover_at": iso_ago(1)}
    context, page, errors, _ = open_page(browser, db={"user": user(), "tables": tables, "calLink": on}, ua=IPHONE)
    wait_view(page, "연결됨")
    note = page.locator("#myCal .my-cal-leftover").inner_text()
    assert "예전 구독이 휴대폰에 남아 있어요." in note and '"밥도둑 내 꽁밥"' in note and '"밥도둑 꽁밥"' in note
    assert page.locator("#myCal .my-cal-btn").count() == 0 and errors == []
    # Owner 2026-11-19: deleted, yet the note stayed. 지웠어요 hides it, also after a reload.
    page.locator("[data-my-cal-leftover-ok]").click()
    page.wait_for_function("() => !document.querySelector('#myCal .my-cal-leftover')")
    page.reload()
    wait_view(page, "연결됨")
    assert page.locator("#myCal .my-cal-leftover").count() == 0 and errors == []
    context.close()
    # A read of the old address right when the new one took over is part of the switch, not a leftover.
    switch = dict(on, linked_at=iso_ago(1), leftover_at=iso_ago(0.95))
    context, page, errors, _ = open_page(browser, db={"user": user(), "tables": tables, "calLink": switch}, ua=IPHONE)
    wait_view(page, "연결됨")
    assert page.locator("#myCal .my-cal-leftover").count() == 0 and errors == []
    context.close()
    # The old subscription stopped reading hours ago: no note.
    gone = dict(on, leftover_at=iso_ago(7))
    context, page, errors, _ = open_page(browser, db={"user": user(), "tables": tables, "calLink": gone}, ua=IPHONE)
    wait_view(page, "연결됨")
    assert page.locator("#myCal .my-cal-leftover").count() == 0 and errors == []
    context.close()
    # No read for days: the profile was probably removed, so the button is back.
    stale = {"link": "S" * 43, "read_at": iso_ago(24 * 10), "linked_at": iso_ago(24 * 20)}
    context, page, errors, _ = open_page(browser, db={"user": user(), "tables": tables, "calLink": stale}, ua=IPHONE)
    wait_view(page, "한동안 확인이 없었어요")
    assert page.locator("#myCal .my-cal-btn").inner_text() == "다시 설치하기" and errors == []
    context.close()


@pytest.mark.parametrize("width", [360, 390, 768, 1440])
def test_english_and_widths(browser, width):
    tables = {"saved_events": [{"user_id": UID, "event_id": "lunch", "saved_at": "2026-11-08T12:00:00Z", "seen": seen(LUNCH)}],
              "saved_places": [], "profiles": []}
    context, page, errors, _ = open_page(browser, db={"user": user(providers=("google",), name="Grace Hopper Very Long Name Indeed")},
                                         lang="en", size=(width, 900))
    wait_view(page, "Saved free food")
    text = app_text(page)
    assert "Hi, Grace Hopper" in text and "Also sign in with Kakao" in text and "Delete account" in text
    assert not re.search(r"[가-힣]", text.replace("점심 세미나", "")), "every label is translated"
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    small = page.locator("#myApp button, #myApp a").evaluate_all(
        "els => els.filter(e => e.offsetParent && e.getBoundingClientRect().height < 24).map(e => e.outerHTML.slice(0, 80))")
    assert small == []
    for button in page.locator("#myApp button").all():
        if button.is_visible():
            assert button.bounding_box()["height"] >= 44, button.inner_text()
    assert errors == []
    context.close()


def google_hop(page):
    """The address the page sent Google to, parsed, after pressing a Google button."""
    from urllib.parse import parse_qs
    page.wait_for_function("() => sessionStorage.getItem('babdoduk-google-pending')")
    for _ in range(50):
        if GOOGLE_REQUESTS:
            break
        page.wait_for_timeout(100)
    url = GOOGLE_REQUESTS[-1]
    return urlparse(url), {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


def test_google_comes_back_to_our_page_so_its_window_names_our_site(browser):
    """Owner 2026-11-18: the same button, but Google's window should show our address, not
    myjglfynhnptlclawlcc.supabase.co. Google answers to my.html with an ID token (no secret)."""
    import hashlib
    GOOGLE_REQUESTS.clear()
    context, page, errors, _ = open_page(browser, google=True)
    wait_view(page, "Google로 계속하기")
    page.get_by_role("button", name="Google로 계속하기").click(no_wait_after=True)
    url, q = google_hop(page)
    assert (url.scheme, url.hostname, url.path) == ("https", "accounts.google.com", "/o/oauth2/v2/auth")
    assert q["client_id"] == GOOGLE_ID and q["redirect_uri"] == f"https://{HOST}/my.html"
    assert q["response_type"] == "id_token" and q["scope"] == "openid email profile" and q["prompt"] == "select_account"
    pending = json.loads(page.evaluate("sessionStorage.getItem('babdoduk-google-pending')"))
    assert pending["state"] == q["state"] and pending["mode"] == "signin"
    assert hashlib.sha256(pending["nonce"].encode()).hexdigest() == q["nonce"]
    assert not [c for c in fakedb(page)["calls"] if c[0] == "oauth"]    # Supabase's redirect is not used
    assert errors == []
    context.close()


def pending(mode="signin", next="", state="S" * 43, at_ms=None):
    return json.dumps({"state": state, "nonce": "N" * 43, "mode": mode, "next": next, "at": at_ms or 4102444800000})


def test_googles_answer_signs_in_and_leaves_no_token_in_the_address(browser):
    context, page, errors, _ = open_page(browser, path="my.html#state=" + "S" * 43 + "&id_token=h.p.s&authuser=0",
                                         google=True, db={"signInAs": user(providers=("google",))},
                                         session={"babdoduk-google-pending": pending()})
    wait_view(page, "로그인")
    page.wait_for_function("() => JSON.parse(localStorage.getItem('__fakedb')).calls.some(c => c[0] === 'idtoken')")
    call = [c for c in fakedb(page)["calls"] if c[0] == "idtoken"][0]
    assert call == ["idtoken", "google", "h.p.s", "N" * 43]
    assert "id_token" not in page.url and "#" not in page.url
    assert page.evaluate("sessionStorage.getItem('babdoduk-google-pending')") is None
    # The page then reads the account as after any sign-in.
    page.wait_for_function("() => document.getElementById('myApp').textContent.includes('로그아웃')")
    assert errors == []
    context.close()


def test_googles_answer_links_rechecks_and_refuses_a_stranger(browser):
    # Linking: the token goes to linkIdentity and the page says it worked.
    context, page, errors, _ = open_page(browser, path="my.html#state=" + "S" * 43 + "&id_token=h.p.s",
                                         google=True, db={"user": user()}, session={"babdoduk-google-pending": pending("link", "linked")})
    page.wait_for_function("() => document.getElementById('myToast').textContent.includes('연결했어요')")
    assert [c for c in fakedb(page)["calls"] if c[0] == "link-token"] == [["link-token", "google", "h.p.s", "N" * 43]]
    assert errors == []
    context.close()
    # Re-checking before leaving comes back to the leave panel.
    context, page, errors, _ = open_page(browser, path="my.html#state=" + "S" * 43 + "&id_token=h.p.s", google=True,
                                         db={"user": user(providers=("google",)), "signInAs": user(providers=("google",))},
                                         session={"babdoduk-google-pending": pending("signin", "leave")})
    page.wait_for_selector("#myLeaveQ")
    assert errors == []
    context.close()
    # An answer this browser did not ask for (another state) is not used, and says sign-in failed.
    context, page, errors, _ = open_page(browser, path="my.html#state=" + "X" * 43 + "&id_token=h.p.s",
                                         google=True, session={"babdoduk-google-pending": pending()})
    wait_view(page, "로그인하지 못했어요")
    assert not [c for c in fakedb(page)["calls"] if c[0] in ("idtoken", "link-token")]
    assert "id_token" not in page.url
    assert errors == []
    context.close()
    # Google refused (the person closed it): the same message, nothing sent to Supabase.
    context, page, errors, _ = open_page(browser, path="my.html#state=" + "S" * 43 + "&error=access_denied",
                                         google=True, session={"babdoduk-google-pending": pending()})
    wait_view(page, "로그인하지 못했어요")
    assert not [c for c in fakedb(page)["calls"] if c[0] == "idtoken"]
    assert errors == []
    context.close()


def test_the_google_link_button_also_goes_through_our_page(browser):
    GOOGLE_REQUESTS.clear()
    context, page, errors, _ = open_page(browser, google=True, db={"user": user()})
    wait_view(page, "Google 로그인도 연결")
    page.get_by_role("button", name="Google 로그인도 연결").click(no_wait_after=True)
    url, q = google_hop(page)
    assert q["redirect_uri"] == f"https://{HOST}/my.html" and url.path == "/o/oauth2/v2/auth"
    assert json.loads(page.evaluate("sessionStorage.getItem('babdoduk-google-pending')"))["mode"] == "link"
    assert not [c for c in fakedb(page)["calls"] if c[0] == "link"]
    assert errors == []
    context.close()


def test_signing_out_works_even_when_the_server_call_fails(browser):
    """2026-11-18 check: the SDK drops this browser's session even if the logout call fails; the page
    must then show the signed-out view, not "저장하지 못했어요" over a stale account."""
    context, page, errors, _ = open_page(browser, db={"user": user(), "fail": {"signout": True}})
    wait_view(page, "로그아웃")
    page.get_by_role("button", name="로그아웃").first.click()
    wait_view(page, "카카오로 계속하기")
    page.wait_for_function("() => document.getElementById('myToast').textContent.includes('로그아웃했어요')")
    assert page.evaluate(f"localStorage.getItem('{TOKEN_KEY}')") is None
    assert errors == []
    context.close()
    # A session that really stayed is still a failure, said as one.
    context, page, errors, _ = open_page(browser, db={"user": user(), "fail": {"signoutKeep": True}})
    wait_view(page, "로그아웃")
    page.get_by_role("button", name="로그아웃").first.click()
    page.wait_for_function("() => document.getElementById('myToast').textContent.includes('로그아웃하지 못했어요')")
    assert "카카오로 계속하기" not in page.locator("#myApp").inner_text()
    assert errors == []
    context.close()
