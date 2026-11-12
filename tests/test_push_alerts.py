"""별 누른 꽁밥 30분 전 알림 (docs/PUSH_ALERTS.md): supabase/migrations/014_push_alerts.sql, the sender
(scripts/push/send.js, scripts/push/webpush.js), the service worker (sw.js) and the browser half
(js/ggongbab-push.js with js/ggongbab.js and js/my.js).

The SQL is read statically and, where the optional `pgserver` and `psycopg` packages are installed, applied to
a throwaway PostgreSQL (never a real Supabase project). The sender runs under Node with fetch replaced and a
fake clock; its encryption is checked against the worked example of RFC 8291 and decrypted again the way a
browser would. The pages run in Chrome with a stand-in push service, permission prompt and service worker:
nothing leaves this machine. A real phone receiving a real alert is checked by hand (NOT TESTED here).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "supabase/migrations/014_push_alerts.sql").read_text(encoding="utf-8")
PUSH_JS = (ROOT / "js/ggongbab-push.js").read_text(encoding="utf-8")
ENDPOINT = "https://web.push.apple.com/QF" + "x" * 60
P256DH = "B" + "A" * 86
AUTH = "A" * 22


def node(script, *args, timeout=30):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    out = subprocess.run(["node", "-e", script, *args], capture_output=True, text=True, timeout=timeout, cwd=ROOT)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


# --- the database ---------------------------------------------------------------------------------------
def test_browsers_get_two_checking_functions_and_the_sender_reads_with_the_backend_key():
    assert "alter table public.push_devices enable row level security;" in SQL
    assert "revoke all on table public.push_devices from public, anon, authenticated, service_role;" in SQL
    assert re.findall(r"grant ([a-z, ]+) on table public\.push_devices to ([a-z_]+);", SQL) == [("select, update, delete", "service_role")]
    granted = re.findall(r"grant execute on function public\.([a-z_]+)\([^)]*\) to ([a-z, ]+);", SQL)
    assert granted == [("push_device_save", "anon, authenticated"), ("push_device_remove", "anon, authenticated")]
    for name in ("push_device_save", "push_device_remove"):
        body = SQL.split(f"create or replace function public.{name}(", 1)[1].split("$$;", 1)[0]
        assert "security definer" in body and "set search_path = ''" in body, name
    columns = SQL.split("create table if not exists public.push_devices (", 1)[1].split(");", 1)[0]
    for private in ("user_id", "email", "ip", "name"):
        assert not re.search(rf"^\s*{private}\b", columns, re.M), private
    assert not re.search(r"sb_secret_|eyJ[A-Za-z0-9_-]{20,}", SQL)


@pytest.fixture(scope="module")
def db():
    pgserver = pytest.importorskip("pgserver")
    psycopg = pytest.importorskip("psycopg")
    from tests.test_accounts_db import SHIM
    server = pgserver.get_server(tempfile.mkdtemp(prefix="babdoduk-push-"), cleanup_mode="delete")
    uri = server.get_uri()
    with psycopg.connect(uri, autocommit=True) as admin:
        admin.execute(SHIM)
        admin.execute("do $$ begin if not exists (select 1 from pg_roles where rolname = 'service_role') then "
                      "create role service_role nologin; end if; end $$;")
        admin.execute(SQL)
        admin.execute(SQL)  # applying twice is harmless
    yield psycopg, uri
    server.cleanup()


def test_a_device_turns_on_updates_its_list_and_turns_off(db):
    psycopg, uri = db
    from tests.test_accounts_db import As
    anon = As(psycopg, uri)
    save = "select public.push_device_save(%s, %s, %s, %s, %s, %s)"
    site = "https://babdoduk-lab.vercel.app"
    assert anon.q(save, (ENDPOINT, P256DH, AUTH, ["lunch", "x#2", "bad id!", "lunch"], "ko", site)) == [(True,)]
    with psycopg.connect(uri, autocommit=True) as admin:
        rows = admin.execute("select events, lang, site from public.push_devices where endpoint = %s", (ENDPOINT,)).fetchall()
    assert rows == [(sorted(["lunch", "x#2"]), "ko", site)], "odd ids are dropped, repeats kept once"
    anon.q(save, (ENDPOINT, P256DH, AUTH, ["wed"], "en", site))
    with psycopg.connect(uri, autocommit=True) as admin:
        assert admin.execute("select events, lang from public.push_devices").fetchall() == [(["wed"], "en")]
    # Only real push services, well-formed keys, our own sites and two languages.
    for bad in (("https://evil.example/x", P256DH, AUTH, "ko", site), (ENDPOINT, "short", AUTH, "ko", site),
                (ENDPOINT, P256DH, "!" * 22, "ko", site), (ENDPOINT + "2", P256DH, AUTH, "fr", site),
                (ENDPOINT + "3", P256DH, AUTH, "ko", "https://evil.example")):
        assert anon.fails(save, (bad[0], bad[1], bad[2], ["lunch"], bad[3], bad[4])), bad
    assert anon.fails("select * from public.push_devices")
    assert anon.fails("delete from public.push_devices")
    assert anon.q("select public.push_device_remove(%s)", (ENDPOINT,)) == [(True,)]
    assert anon.q("select public.push_device_remove(%s)", (ENDPOINT,)) == [(False,)]
    anon.close()


def test_new_devices_are_capped_but_a_known_one_can_always_update(db):
    psycopg, uri = db
    from tests.test_accounts_db import As
    with psycopg.connect(uri, autocommit=True) as admin:
        admin.execute("delete from public.push_devices")
        admin.execute(f"insert into public.push_devices (endpoint, p256dh, auth, site) select "
                      f"'https://fcm.googleapis.com/fcm/send/n' || g, '{P256DH}', '{AUTH}', 'https://www.babdodukms.com' "
                      f"from generate_series(1, 500) g")
    anon = As(psycopg, uri)
    save = "select public.push_device_save(%s, %s, %s, %s, 'ko', 'https://www.babdodukms.com')"
    assert anon.fails(save, ("https://fcm.googleapis.com/fcm/send/new", P256DH, AUTH, ["a"]))
    assert anon.q(save, ("https://fcm.googleapis.com/fcm/send/n7", P256DH, AUTH, ["a"])) == [(True,)]
    anon.close()
    with psycopg.connect(uri, autocommit=True) as admin:
        admin.execute("delete from public.push_devices")


# --- encryption and signature ---------------------------------------------------------------------------
CRYPTO = r"""
const crypto = require('crypto');
const w = require('./scripts/push/webpush.js');
// RFC 8291 Appendix A: the standard's own worked example, byte for byte.
const example = w.b64u(w.encrypt('When I grow up, I want to be a watermelon',
  'BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4',
  'BTBZMqHH6r4Tts7J_aSIgg', { salt: 'DGv6ra1nlYgDCS1FRnbzlw', senderPrivateKey: 'yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw' }));
// A fresh browser key pair, and the browser's side of the decryption.
const ua = crypto.createECDH('prime256v1'); ua.generateKeys();
const auth = crypto.randomBytes(16);
const body = w.encrypt(JSON.stringify({ title: '🍚 점심' }), w.b64u(ua.getPublicKey()), w.b64u(auth));
const salt = body.subarray(0, 16), rs = body.readUInt32BE(16), idlen = body[20];
const sender = body.subarray(21, 21 + idlen), sealed = body.subarray(21 + idlen);
const hk = (ikm, s, info, n) => Buffer.from(crypto.hkdfSync('sha256', ikm, s, info, n));
const ikm = hk(ua.computeSecret(sender), auth, Buffer.concat([Buffer.from('WebPush: info\0'), ua.getPublicKey(), sender]), 32);
const d = crypto.createDecipheriv('aes-128-gcm', hk(ikm, salt, Buffer.from('Content-Encoding: aes128gcm\0'), 16),
  hk(ikm, salt, Buffer.from('Content-Encoding: nonce\0'), 12));
d.setAuthTag(sealed.subarray(sealed.length - 16));
const plain = Buffer.concat([d.update(sealed.subarray(0, sealed.length - 16)), d.final()]);
// VAPID: the JWT verifies with the public key, for the push service's origin, within 24 hours.
const keys = w.generateKeys();
const header = w.vapidAuthorization('https://web.push.apple.com/abc', keys, 'https://www.babdodukms.com', Date.parse('2026-11-12T00:00:00Z'));
const m = header.match(/^vapid t=([^.]+)\.([^.]+)\.([^,]+), k=(.+)$/);
const pub = w.unb64u(keys.publicKey);
const key = crypto.createPublicKey({ format: 'jwk', key: { kty: 'EC', crv: 'P-256', x: w.b64u(pub.subarray(1, 33)), y: w.b64u(pub.subarray(33)) } });
const ok = crypto.verify('sha256', Buffer.from(m[1] + '.' + m[2]), { key, dsaEncoding: 'ieee-p1363' }, w.unb64u(m[3]));
console.log(JSON.stringify({ example, rs, idlen, plain: plain.toString(), ok, claims: JSON.parse(w.unb64u(m[2])), k: m[4] === keys.publicKey,
  keyLens: [w.unb64u(keys.publicKey).length, w.unb64u(keys.privateKey).length] }));
"""


def test_the_message_is_encrypted_as_the_standard_says_and_signed_with_our_key():
    out = node(CRYPTO)
    assert out["example"] == ("DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6Tlz"
                              "AC8wEqKK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN")
    assert out["rs"] == 4096 and out["idlen"] == 65
    assert out["plain"] == json.dumps({"title": "🍚 점심"}, ensure_ascii=False, separators=(",", ":")) + "\x02"
    assert out["ok"] and out["k"] and out["keyLens"] == [65, 32]
    assert out["claims"]["aud"] == "https://web.push.apple.com" and out["claims"]["sub"] == "https://www.babdodukms.com"
    from datetime import datetime, timezone
    assert out["claims"]["exp"] - datetime(2026, 11, 12, tzinfo=timezone.utc).timestamp() == 12 * 3600


# --- the sender -------------------------------------------------------------------------------------------
SEND = r"""
const send = require('./scripts/push/send.js');
const w = require('./scripts/push/webpush.js');
const data = JSON.parse(process.argv[1]);
const calls = [];
const fakeFetch = async (url, init) => {
  init = init || {};
  calls.push({ url, method: init.method || 'GET', headers: init.headers || {}, body: init.body && !Buffer.isBuffer(init.body) ? init.body : null,
               bytes: Buffer.isBuffer(init.body) ? init.body.length : 0 });
  if (url.endsWith('/latest.json')) return data.feedOk ? { ok: true, status: 200, json: async () => data.feed } : { ok: false, status: 503 };
  if (url.includes('/rest/v1/push_devices?select=')) return { ok: true, status: 200, json: async () => data.devices };
  if (url.includes('/rest/v1/push_devices?endpoint=')) return { ok: true, status: 204 };
  return { ok: false, status: data.pushStatus[url] || 201 };
};
(async () => {
  const runs = [];
  for (const now of data.nows) {
    runs.push(await send.run({ nowMs: Date.parse(now), fetchImpl: fakeFetch, env: { SUPABASE_URL: 'https://p.supabase.co', SUPABASE_SECRET_KEY: 'sb_secret_TEST' },
      keys: w.generateKeys(), sentFile: data.sentFile, feeds: ['https://site/data/ggongbab/latest.json'], log: () => {} }));
  }
  const due = send.dueEvents(data.feed, Date.parse(data.nows[0])).map((ev) => ev.id);
  const msg = send.message(data.feed.events[0], { lang: data.lang, site: 'https://babdoduk-lab.vercel.app' }, Date.parse(data.nows[0]));
  console.log(JSON.stringify({ runs, calls, due, msg }));
})().catch((err) => { console.error(err); process.exit(1); });
"""


def feed_event(eid, start, title, building="E11"):
    return {"id": eid, "title": title, "startAt": start, "endAt": None, "location": {"building": building, "room": "101호", "name": ""},
            "food": {"provided": "true", "type": "meal"}, "sources": [{"type": "dooray"}]}


FEED = {"events": [feed_event("soon", "2026-11-12T12:00:00+09:00", "점심 세미나"),
                   feed_event("later", "2026-11-12T13:00:00+09:00", "오후 간담회"),
                   feed_event("past", "2026-11-12T11:00:00+09:00", "끝난 행사"),
                   dict(feed_event("review", "2026-11-12T12:10:00+09:00", "검토 중"), needs_review=True)]}


def run_sender(tmp_path, nows, devices, push_status=None, lang="ko", feed_ok=True, feed=FEED):
    data = {"nows": nows, "devices": devices, "feed": feed, "feedOk": feed_ok, "pushStatus": push_status or {},
            "sentFile": str(tmp_path / "sent.json"), "lang": lang}
    return node(SEND, json.dumps(data))


def device(endpoint=ENDPOINT, events=("soon",), lang="ko"):
    # Any valid browser key will do for sending; this is the receiver key of the RFC 8291 example.
    return {"endpoint": endpoint, "p256dh": "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4",
            "auth": "BTBZMqHH6r4Tts7J_aSIgg", "events": list(events), "lang": lang, "site": "https://babdoduk-lab.vercel.app", "failures": 0}


def test_only_starred_listings_due_within_30_minutes_alert_and_each_only_once(tmp_path):
    out = run_sender(tmp_path, ["2026-11-12T11:31:00+09:00", "2026-11-12T11:33:00+09:00"], [device(events=("soon", "later"))])
    assert out["due"] == ["soon"], "the listing starting in 29 minutes; not the later one, the past one or one under review"
    first, second = out["runs"]
    assert first == {"due": 1, "devices": 1, "sent": 1, "gone": 0, "refused": 0, "later": 0}
    assert second["sent"] == 0, "the second run two minutes later sends nothing new"
    pushes = [c for c in out["calls"] if c["url"] == ENDPOINT]
    assert len(pushes) == 1
    h = pushes[0]["headers"]
    assert h["Content-Encoding"] == "aes128gcm" and h["Urgency"] == "high" and h["Authorization"].startswith("vapid t=")
    assert 1700 <= int(h["TTL"]) <= 1800 and pushes[0]["bytes"] > 86
    lookup = [c for c in out["calls"] if "push_devices?select=" in c["url"]]
    assert "events=ov." in lookup[0]["url"] and "%22soon%22" in lookup[0]["url"]
    assert lookup[0]["headers"]["apikey"] == "sb_secret_TEST"
    sent = json.loads((tmp_path / "sent.json").read_text())
    assert len(sent) == 1 and ENDPOINT not in json.dumps(sent), "the record keeps a hash, never the address"
    assert out["msg"] == {"title": "🍚 점심 세미나", "body": "29분 뒤 시작 · 12:00 · E11 · 101호",
                          "url": "https://babdoduk-lab.vercel.app/ggongbab.html?e=soon", "tag": "gg-soon"}


def test_nothing_due_reads_no_database_and_a_moved_listing_follows_the_new_time(tmp_path):
    out = run_sender(tmp_path, ["2026-11-12T10:00:00+09:00"], [device()])
    assert out["runs"][0]["due"] == 0 and [c["url"] for c in out["calls"]] == ["https://site/data/ggongbab/latest.json"]
    moved = {"events": [feed_event("soon", "2026-11-12T15:00:00+09:00", "점심 세미나")]}
    out = run_sender(tmp_path, ["2026-11-12T11:31:00+09:00"], [device()], feed=moved)
    assert out["runs"][0]["sent"] == 0, "the star's old time is never used"
    out = run_sender(tmp_path, ["2026-11-12T11:31:00+09:00"], [device()], feed_ok=False)
    assert out["runs"][0].get("feed") is False and not [c for c in out["calls"] if "supabase" in c["url"]]


def test_a_gone_device_is_forgotten_and_a_busy_service_is_retried(tmp_path):
    gone = "https://fcm.googleapis.com/fcm/send/gone"
    busy = "https://fcm.googleapis.com/fcm/send/busy"
    out = run_sender(tmp_path, ["2026-11-12T11:31:00+09:00", "2026-11-12T11:33:00+09:00"],
                     [device(gone), device(busy, lang="en")], push_status={gone: 410, busy: 503})
    first, second = out["runs"]
    assert first["gone"] == 1 and first["later"] == 1 and second["later"] == 1, "busy is tried again on the next run"
    deletes = [c for c in out["calls"] if c["method"] == "DELETE"]
    assert len(deletes) == 2 and all("endpoint=eq." + "https%3A%2F%2Ffcm.googleapis.com%2Ffcm%2Fsend%2Fgone" in c["url"] for c in deletes)
    english = run_sender(tmp_path, ["2026-11-12T11:31:00+09:00"], [], lang="en")["msg"]
    assert english["body"] == "Starts in 29 min · 12:00 · E11 · 101호"


def test_the_sender_needs_its_own_key_and_never_prints_one(tmp_path):
    source = (ROOT / "scripts/push/send.js").read_text(encoding="utf-8")
    assert not re.search(r"console\.\w+\([^;]*(keys|privateKey|env\.SUPABASE_SECRET_KEY|endpoint\))", source)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "BABDODUK_ENV": str(tmp_path / ".env"),
           "BABDODUK_PUSH_KEYS": str(tmp_path / "none"), "BABDODUK_PUSH_PUBLIC": str(tmp_path / "public.txt")}
    (tmp_path / ".env").write_text("SUPABASE_URL=https://p.supabase.co\nSUPABASE_SECRET_KEY='sb_secret_ABC'\n")
    nodebin = shutil.which("node")
    if not nodebin:
        pytest.skip("node is not installed")
    out = subprocess.run([nodebin, "scripts/push/send.js"], capture_output=True, text=True, cwd=ROOT, env=env, timeout=30)
    assert out.returncode == 1 and "keygen" in out.stderr and "sb_secret_ABC" not in out.stdout + out.stderr
    keygen = subprocess.run([nodebin, "scripts/push/keygen.js"], capture_output=True, text=True, cwd=ROOT,
                            env=dict(env, BABDODUK_PUSH_KEYS=str(tmp_path / "keys")), timeout=30)
    assert keygen.returncode == 0, keygen.stderr
    keys = json.loads((tmp_path / "keys").read_text())
    assert keys["privateKey"] not in keygen.stdout and keys["publicKey"] in keygen.stdout
    assert oct((tmp_path / "keys").stat().st_mode & 0o777) == "0o600"
    again = subprocess.run([nodebin, "scripts/push/keygen.js"], capture_output=True, text=True, cwd=ROOT,
                           env=dict(env, BABDODUK_PUSH_KEYS=str(tmp_path / "keys")), timeout=30)
    assert again.returncode == 0 and json.loads((tmp_path / "keys").read_text()) == keys, "an existing key is kept"
    assert (tmp_path / "public.txt").read_text().strip() == keys["publicKey"]


def test_the_service_worker_only_shows_alerts_and_opens_our_own_pages():
    sw = (ROOT / "sw.js").read_text(encoding="utf-8")
    assert "addEventListener('fetch'" not in sw and "caches." not in sw, "no caching, page loads untouched"
    assert "showNotification" in sw and "url.origin === self.location.origin" in sw
    timer = (ROOT / "scripts/push/babdoduk-push.timer").read_text(encoding="utf-8")
    assert "OnCalendar=*:0/2" in timer
    vercel = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    sw_route = next(r for r in vercel["routes"] if r.get("src") == "/sw\\.js")
    assert sw_route["headers"]["Cache-Control"] == "no-cache" and sw_route["continue"] is True


# --- the pages ------------------------------------------------------------------------------------------
LAB = "babdoduk-lab.vercel.app"
NOW = "2026-11-09T09:00:00+09:00"
IPHONE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
          "Version/18.0 Mobile/15E148 Safari/604.1")
TEST_KEY = "B" + "C" * 86

# A stand-in for the push service, the permission question and the service worker. `push` = false leaves
# them out, like iPhone Safari outside the home-screen app.
FAKE_PUSH = r"""
(() => {
  const cfg = window.__pushCfg;
  const P = window.__push = { calls: [], permission: cfg.permission, sub: null };
  if (cfg.standalone) Object.defineProperty(navigator, 'standalone', { value: true, configurable: true });
  if (!cfg.push) {
    try { delete window.PushManager; } catch (e) {}
    Object.defineProperty(window, 'PushManager', { value: undefined, configurable: true });
    return;
  }
  const sub = () => ({ endpoint: 'https://web.push.apple.com/QFAKE', unsubscribe() { P.calls.push(['unsubscribe']); P.sub = null; return Promise.resolve(true); },
    toJSON() { return { endpoint: this.endpoint, keys: { p256dh: 'B' + 'A'.repeat(86), auth: 'A'.repeat(22) } }; } });
  const pushManager = { getSubscription() { return Promise.resolve(P.sub); },
    subscribe(o) { P.calls.push(['subscribe', o.userVisibleOnly, o.applicationServerKey.length]); P.sub = sub(); return Promise.resolve(P.sub); } };
  let registered = !!cfg.subscribed;
  if (cfg.subscribed) P.sub = sub();
  const reg = { pushManager };
  Object.defineProperty(navigator, 'serviceWorker', { configurable: true, value: {
    register(url, o) { P.calls.push(['register', url, o.scope]); registered = true; return Promise.resolve(reg); },
    get ready() { return Promise.resolve(reg); },
    getRegistration() { return Promise.resolve(registered ? reg : undefined); } } });
  window.PushManager = function () {};
  window.Notification = { get permission() { return P.permission; },
    requestPermission() { P.calls.push(['permission']); P.permission = cfg.answer; return Promise.resolve(cfg.answer); } };
})();
"""


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        chrome = pw.chromium.launch(channel="chrome", headless=True)
        yield chrome
        chrome.close()


def open_site(browser, path="ggongbab.html#saved", host=LAB, ua=IPHONE, push=True, standalone=True, permission="default",
              answer="granted", subscribed=False, storage=None, account=None, rpc_status=200):
    from tests.test_my_babdoduk import ARCHIVE, LIVE, TOKEN_KEY
    context = browser.new_context(viewport={"width": 390, "height": 844}, timezone_id="Asia/Seoul", service_workers="block", user_agent=ua)
    cfg = {"push": push, "standalone": standalone, "permission": permission, "answer": answer, "subscribed": subscribed}
    init = ["localStorage.setItem('babdoduk-lang', 'ko');", "localStorage.setItem('babdoduk-notice-ggongbab-live', '1');",
            f"window.__pushCfg = {json.dumps(cfg)};"]
    for key, value in (storage or {}).items():
        init.append(f"if (!sessionStorage.getItem('__s_{key}')) {{ localStorage.setItem({json.dumps(key)}, {json.dumps(value)}); sessionStorage.setItem('__s_{key}', '1'); }}")
    script = " ".join(init) + FAKE_PUSH
    if account:
        from tests.test_my_babdoduk import FAKE
        state = {"user": account, "tables": {"saved_events": [], "saved_places": [], "profiles": []}, "calls": [], "fail": {}}
        script += (f"if (!localStorage.getItem('__fakedb')) localStorage.setItem('__fakedb', {json.dumps(json.dumps(state))});"
                   f"localStorage.setItem('{TOKEN_KEY}', '{{}}');" + FAKE)
    context.add_init_script(script)
    rpcs = []

    def handle(route):
        url = urlparse(route.request.url)
        if url.hostname and url.hostname.endswith(".supabase.co") and "/rest/v1/rpc/push_device_" in url.path:
            rpcs.append([url.path.rsplit("/", 1)[1], json.loads(route.request.post_data or "{}"), dict(route.request.headers)])
            return route.fulfill(status=rpc_status, content_type="application/json", body="true")
        if url.hostname != host:
            return route.abort()
        name = unquote(url.path).lstrip("/")
        if name == "data/ggongbab/latest.json":
            return route.fulfill(json=LIVE)
        if name == "data/ggongbab/archive/index.json":
            return route.fulfill(json=ARCHIVE)
        if name == "js/ggongbab-public-feed.js":
            return route.fulfill(content_type="application/javascript", body="")
        if name == "js/ggongbab-push.js":
            return route.fulfill(content_type="application/javascript",
                                 body=PUSH_JS.replace("var VAPID_PUBLIC_KEY = '';", f"var VAPID_PUBLIC_KEY = '{TEST_KEY}';").replace(
                                     "var VAPID_PUBLIC_KEY = '" + PUSH_KEY + "';", f"var VAPID_PUBLIC_KEY = '{TEST_KEY}';"))
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
    page.goto(f"https://{host}/{path}", wait_until="networkidle")
    return context, page, errors, rpcs


PUSH_KEY = (re.search(r"var VAPID_PUBLIC_KEY = '([^']*)';", PUSH_JS) or [None, ""])[1]


def calls(page):
    return page.evaluate("window.__push ? window.__push.calls : []")


def toast(page):
    return page.locator(".gg-toast").inner_text()


def wait_rpc(page, rpcs, n):
    for _ in range(40):
        if len(rpcs) >= n:
            return
        page.wait_for_timeout(100)
    raise AssertionError(f"expected {n} calls, got {rpcs}")


def test_the_public_key_is_set_or_the_feature_stays_hidden():
    assert PUSH_KEY == "" or re.fullmatch(r"B[A-Za-z0-9_-]{86}", PUSH_KEY)
    hosts = re.search(r"var HOSTS = \[([^\]]*)\];", PUSH_JS).group(1)
    assert re.findall(r"'([^']+)'", hosts) == ["babdoduk-lab.vercel.app"], "lab only until promoted"
    assert "sb_secret_" not in PUSH_JS and "service_role" not in PUSH_JS


def test_the_home_screen_app_asks_after_the_first_star_and_keeps_the_list_current(browser):
    context, page, errors, rpcs = open_site(browser)
    star = page.locator('.gg-card[data-id="lunch"] .gg-save')
    star.click()
    ask = page.locator("#pushAsk")
    ask.wait_for()
    assert page.locator("#pushAskTitle").inner_text() == "별 누른 꽁밥, 30분 전에 알려 드릴까요?"
    assert page.locator("#starCalAsk").count() == 0, "the push question replaces the calendar question here"
    ask.locator(".starcal-yes").click()
    wait_rpc(page, rpcs, 1)
    assert calls(page)[:3] == [["permission"], ["register", "/sw.js", "/"], ["subscribe", True, 65]]
    name, body, headers = rpcs[0]
    assert name == "push_device_save" and body["p_events"] == ["lunch"] and body["p_lang"] == "ko"
    assert body["p_site"] == "https://babdoduk-lab.vercel.app" and body["p_endpoint"] == "https://web.push.apple.com/QFAKE"
    assert headers["apikey"].startswith("sb_publishable_")
    page.wait_for_function("() => document.querySelector('.gg-toast').innerText.includes('30분 전에 알림이 와요')")
    toggle = page.locator("[data-gg-push]")
    toggle.wait_for()
    assert toggle.get_attribute("aria-pressed") == "true" and "켜짐" in toggle.inner_text()
    # Unstarring updates the server's list; the second star is not asked about again.
    page.locator('.gg-card[data-id="wed"] .gg-save').click()
    wait_rpc(page, rpcs, 2)
    assert sorted(rpcs[1][1]["p_events"]) == ["lunch", "wed"] and page.locator("#pushAsk").count() == 0
    assert "30분 전에 알림이 와요" in toast(page)
    page.locator('.gg-card[data-id="lunch"] .gg-save').click()
    wait_rpc(page, rpcs, 3)
    assert rpcs[2][1]["p_events"] == ["wed"]
    # Turning off: the browser's subscription first, then the server row.
    page.locator("[data-gg-push]").click()
    wait_rpc(page, rpcs, 4)
    assert rpcs[3][0] == "push_device_remove" and rpcs[3][1] == {"p_endpoint": "https://web.push.apple.com/QFAKE"}
    assert ["unsubscribe"] in calls(page)
    page.wait_for_function("() => document.querySelector('[data-gg-push]').getAttribute('aria-pressed') === 'false'")
    assert errors == []
    context.close()


def test_no_to_the_question_or_a_refused_permission_never_subscribes(browser):
    context, page, errors, rpcs = open_site(browser)
    page.locator('.gg-card[data-id="lunch"] .gg-save').click()
    page.locator("#pushAsk .starcal-no").click()
    assert "알림은 켜지 않을게요" in toast(page) and calls(page) == [] and rpcs == []
    assert page.locator("[data-gg-push]").get_attribute("aria-pressed") == "false"
    context.close()
    context, page, errors, rpcs = open_site(browser, answer="denied")
    page.locator('.gg-card[data-id="lunch"] .gg-save').click()
    page.locator("#pushAsk .starcal-yes").click()
    page.wait_for_function("() => document.querySelector('.gg-toast').innerText.includes('알림이 막혀 있어요')")
    assert calls(page) == [["permission"]] and rpcs == []
    assert "휴대폰 설정의 알림" in page.locator(".gg-saved-body").inner_text()
    assert errors == []
    context.close()


def test_a_server_refusal_undoes_the_subscription_so_on_is_never_a_lie(browser):
    context, page, errors, rpcs = open_site(browser, rpc_status=400)
    page.locator('.gg-card[data-id="lunch"] .gg-save').click()
    page.locator("#pushAsk .starcal-yes").click()
    page.wait_for_function("() => document.querySelector('.gg-toast').innerText.includes('알림을 켜지 못했어요')")
    assert calls(page)[-1] == ["unsubscribe"] and page.locator("[data-gg-push]").get_attribute("aria-pressed") == "false"
    assert errors == []
    context.close()


def test_iphone_safari_points_to_the_home_screen_and_other_hosts_show_nothing(browser):
    from tests.test_my_babdoduk import LUNCH, local
    saved = {"babdoduk-ggongbab-saved": local((LUNCH, "2026-11-08T10:00:00Z"))}
    context, page, errors, rpcs = open_site(browser, push=False, standalone=False, storage=saved)
    body = page.locator(".gg-saved-body")
    body.wait_for()
    assert "홈 화면에 추가한 밥도둑으로 열면" in body.inner_text() and page.locator("[data-gg-push]").count() == 0
    page.locator('.gg-card[data-id="wed"] .gg-save').click()
    assert page.locator("#pushAsk").count() == 0, "Safari gets the calendar question as before"
    context.close()
    context, page, errors, rpcs = open_site(browser, host="www.babdodukms.com", storage=saved)
    page.locator(".gg-saved-body").wait_for()
    assert page.locator("[data-gg-push]").count() == 0 and "홈 화면" not in page.locator(".gg-saved-body").inner_text()
    page.locator('.gg-card[data-id="wed"] .gg-save').click()
    assert page.locator("#pushAsk").count() == 0 and calls(page) == [] and rpcs == []
    assert errors == []
    context.close()


def test_a_subscribed_browser_resends_its_list_once_a_day_not_on_every_visit(browser):
    from tests.test_my_babdoduk import LUNCH, local
    saved = {"babdoduk-ggongbab-saved": local((LUNCH, "2026-11-08T10:00:00Z"))}
    context, page, errors, rpcs = open_site(browser, subscribed=True, permission="granted", storage=saved)
    wait_rpc(page, rpcs, 1)
    assert rpcs[0][1]["p_events"] == ["lunch"]
    page.reload(wait_until="networkidle")
    page.wait_for_timeout(300)
    assert len(rpcs) == 1, "the same list on the same day is not sent again"
    assert errors == []
    context.close()


def test_my_babdoduk_turns_alerts_on_and_off_for_this_phone(browser):
    from tests.test_my_babdoduk import user
    context, page, errors, rpcs = open_site(browser, path="my.html", account=user())
    card = page.locator("section[aria-labelledby='myPushTitle']")
    card.wait_for()
    assert "별 누른 꽁밥이 시작하기 30분 전에" in card.inner_text()
    card.locator("[data-my-push]").click()
    wait_rpc(page, rpcs, 1)
    assert rpcs[0][0] == "push_device_save"
    page.wait_for_function("() => document.querySelector('[data-my-push]').getAttribute('aria-pressed') === 'true'")
    assert "켜져 있어요" in card.inner_text()
    card.locator("[data-my-push]").click()
    wait_rpc(page, rpcs, 2)
    page.wait_for_function("() => document.querySelector('[data-my-push]').getAttribute('aria-pressed') === 'false'")
    assert rpcs[1][0] == "push_device_remove" and errors == []
    context.close()
