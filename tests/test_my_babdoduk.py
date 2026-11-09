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
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

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
    linkIdentity(o) { const db = load(); db.calls.push(['link', o.provider, o.options.redirectTo]); save(db); return Promise.resolve({ data: {}, error: null }); },
    signOut(o) { const db = load(); db.calls.push(['signout', o && o.scope]); db.user = null; save(db); localStorage.removeItem('""" + TOKEN_KEY + r"""'); return Promise.resolve({ error: null }); }
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


def open_page(browser, path="my.html", db=None, storage=None, enabled=True, lang="ko", size=(390, 844), ua=None):
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
    for key, value in (storage or {}).items():
        init.append(f"if (!sessionStorage.getItem('__s_{key}')) {{ localStorage.setItem({json.dumps(key)}, {json.dumps(value)}); sessionStorage.setItem('__s_{key}', '1'); }}")
    context.add_init_script(" ".join(init) + FAKE)
    sdk_requests = []

    def handle(route):
        url = urlparse(route.request.url)
        if "supabase" in route.request.url and url.hostname != HOST:
            sdk_requests.append(route.request.url)
            return route.abort()
        if url.hostname != HOST:
            return route.abort()
        name = unquote(url.path).lstrip("/")
        if name == "data/ggongbab/latest.json":
            return route.fulfill(json=LIVE)
        if name == "data/ggongbab/archive/index.json":
            return route.fulfill(json=ARCHIVE)
        if name == "js/babdoduk-auth-config.js":
            return route.fulfill(content_type="application/javascript", body=ON if enabled else OFF)
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


def test_on_for_lab_only_and_never_on_production():
    # On since 2026-11-10 (owner: providers set up, 011 applied); production hosts are never listed.
    assert re.search(r"enabled:\s*true", CONFIG)
    hosts = re.search(r"hosts:\s*Object\.freeze\(\[([^\]]*)\]\)", CONFIG).group(1)
    for host in ("babdodukms.com", "babdoduk.vercel.app"):
        assert host not in hosts
    assert "babdoduk-lab.vercel.app" in hosts
    for name in ("js/babdoduk-account.js", "js/babdoduk-auth-config.js", "js/my.js"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "sb_secret_" not in text and "service_role" not in text, name
    vercel = (ROOT / "vercel.json").read_text(encoding="utf-8")
    assert "my\\\\.html" in vercel, "my.html answers 404 off babdoduk-lab"


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
    assert "이 브라우저에만 저장돼요" in page.locator("#ggSaved").inner_text() or page.locator("#ggSaved").count() == 1
    assert errors == []
    context.close()


def test_signed_out_offers_both_providers_with_a_full_page_redirect(browser):
    context, page, errors, _ = open_page(browser)
    wait_view(page, "로그인하면 이렇게 돼요")
    text = app_text(page)
    assert "KAIST 인증은 필요 없어요" in text and "참여 조건은 행사마다 달라요" in text
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
        {"user_id": "someone-else", "event_id": "wed", "saved_at": "2026-11-08T12:00:00Z", "seen": seen(WED)}],
        "saved_places": [{"user_id": UID, "place_id": "p1", "status": "want", "memo": "비밀"},
                         {"user_id": UID, "place_id": "p2", "status": "again", "memo": ""}],
        "profiles": [{"user_id": UID, "display_name": "도둑"}]}
    context, page, errors, _ = open_page(browser, db={"user": user(), "tables": tables})
    wait_view(page, "저장한 꽁밥")
    rows = page.locator(".my-row").evaluate_all("els => els.map(el => [el.className, el.innerText])")
    assert [r[0] for r in rows] == ["my-row is-upcoming", "my-row is-missing", "my-row is-ended"]
    assert "변경됨" in rows[0][1] and "목록에서 빠짐" in rows[1][1] and "지난 꽁밥" in rows[2][1]
    assert "수요 간담회" not in app_text(page), "another user's row never shows"
    assert "취소" not in rows[1][1]
    assert page.locator(".my-row.is-upcoming a").get_attribute("href") == f"https://{HOST}/ggongbab.html?e=lunch"
    counts = page.locator(".my-counts").inner_text()
    assert re.search(r"가고 싶어\s*1", counts) and re.search(r"또 갈래\s*1", counts)
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
    assert "계정에 저장돼요" in page.locator("#ggSaved").inner_text()
    assert page.locator('#ggSaved a[href="my.html"]').count() == 1
    assert page.evaluate(f"localStorage.getItem('{SAVED_KEY}')") == guest
    toast = page.locator(".gg-toast")
    toast.wait_for(state="attached")
    page.wait_for_function("() => (document.querySelector('.gg-toast') || {}).textContent.includes('계정에 저장돼요')")
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
    page.wait_for_function("() => document.querySelector('#ggSaved').innerText.includes('계정 목록을 불러오지 못해')")
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
    wait_view(page, "로그인하면 이렇게 돼요")
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
