"""내 꽁밥 캘린더 구독 (docs/CALENDAR_FEED.md): supabase/migrations/013_calendar_feed.sql and api/cal.js.

The SQL is read statically and, where the optional `pgserver` and `psycopg` packages are installed, applied
to a throwaway PostgreSQL with the stand-in auth schema of tests/test_accounts_db.py (never a real Supabase
project). The feed function runs under Node with fetch replaced, so nothing leaves this machine.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "supabase/migrations/013_calendar_feed.sql").read_text(encoding="utf-8")
# The accounts migration (011) is kept on lab; main applies it but does not carry the file, so the database
# tests below run where it exists and skip elsewhere.
ACCOUNTS_FILE = ROOT / "supabase/migrations/011_accounts.sql"


def test_the_table_is_closed_and_only_two_functions_are_open():
    assert "alter table public.calendar_feeds enable row level security;" in SQL
    assert "revoke all on table public.calendar_feeds from public, anon, authenticated;" in SQL
    assert not re.search(r"grant [a-z, ]+ on table", SQL), "no table grants"
    assert re.findall(r"grant execute on function ([^;]+) to anon", SQL) == ["public.calendar_feed_events(text)"]
    assert re.findall(r"grant execute on function ([^;]+) to authenticated;", SQL) == ["public.my_calendar_feed(boolean)"]
    for name in ("my_calendar_feed", "calendar_feed_events"):
        body = SQL.split(f"create or replace function public.{name}(", 1)[1].split("$$;", 1)[0]
        assert "set search_path = ''" in body and "security definer" in body, name
    read = SQL.split("create or replace function public.calendar_feed_events(", 1)[1].split("$$;", 1)[0]
    assert "returns table (event_id text, saved_at timestamptz, seen jsonb)" in read
    for private in ("email", "display_name", "raw_user_meta_data"):
        assert private not in read, private
    assert "service_role" not in SQL and not re.search(r"sb_secret_|eyJ[A-Za-z0-9_-]{20,}", SQL)


# --- a real PostgreSQL ------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def db():
    pgserver = pytest.importorskip("pgserver")
    psycopg = pytest.importorskip("psycopg")
    if not ACCOUNTS_FILE.is_file():
        pytest.skip("supabase/migrations/011_accounts.sql is not on this branch")
    ACCOUNTS = ACCOUNTS_FILE.read_text(encoding="utf-8")
    from tests.test_accounts_db import PGCRYPTO, SHIM
    server = pgserver.get_server(tempfile.mkdtemp(prefix="babdoduk-calfeed-"), cleanup_mode="delete")
    uri = server.get_uri()
    with psycopg.connect(uri, autocommit=True) as admin:
        admin.execute(SHIM)
        admin.execute(ACCOUNTS.replace(PGCRYPTO, ""))
        admin.execute(SQL.replace(PGCRYPTO, ""))
        admin.execute(SQL.replace(PGCRYPTO, ""))  # applying twice is harmless
    yield psycopg, uri
    server.cleanup()


def test_a_token_reads_only_its_owners_stars_and_a_new_one_stops_the_old(db):
    psycopg, uri = db
    from tests.test_accounts_db import As, new_user
    a, b = new_user(psycopg, uri), new_user(psycopg, uri)
    ua, ub, anon = As(psycopg, uri, a), As(psycopg, uri, b), As(psycopg, uri)
    ua.q("insert into public.saved_events (user_id, event_id, seen) values (%s, 'lunch', '{\"title\": \"점심\"}')", (a,))
    ub.q("insert into public.saved_events (user_id, event_id) values (%s, 'other')", (b,))
    token = ua.q("select public.my_calendar_feed()")[0][0]
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", token) and ua.q("select public.my_calendar_feed()")[0][0] == token
    rows = anon.q("select event_id, seen from public.calendar_feed_events(%s)", (token,))
    assert rows == [("lunch", {"title": "점심"})]
    assert anon.q("select * from public.calendar_feed_events(%s)", ("x" * 43,)) == []
    assert anon.q("select * from public.calendar_feed_events(%s)", ("bad",)) == []
    assert anon.fails("select * from public.calendar_feeds") and ua.fails("select * from public.calendar_feeds")
    assert anon.fails("select public.my_calendar_feed()")
    fresh = ua.q("select public.my_calendar_feed(true)")[0][0]
    assert fresh != token and anon.q("select * from public.calendar_feed_events(%s)", (token,)) == []
    assert [r[0] for r in anon.q("select event_id from public.calendar_feed_events(%s)", (fresh,))] == ["lunch"]
    with psycopg.connect(uri, autocommit=True) as admin:
        admin.execute("delete from auth.users where id = %s", (a,))
    assert anon.q("select * from public.calendar_feed_events(%s)", (fresh,)) == []   # gone with the account
    for c in (ua, ub, anon):
        c.close()


# --- the feed function ------------------------------------------------------------------------------
RUN = r"""
const cal = require(process.argv[1]);
const data = JSON.parse(process.argv[2]);
global.fetch = async (url, options) => {
  calls.push([url, options && options.body ? JSON.parse(options.body) : null]);
  if (url.includes('/rest/v1/rpc/calendar_feed_events')) return { ok: data.rpcOk, json: async () => data.saved };
  if (url.endsWith('/data/ggongbab/latest.json')) return { ok: true, json: async () => data.feed };
  return { ok: false, json: async () => null };
};
const calls = [];
const res = { headers: {}, setHeader(k, v) { this.headers[k] = v; }, end(body) { this.body = body; } };
cal({ url: '/api/cal?t=' + data.token, headers: { host: 'babdoduk-lab.vercel.app' } }, res).then(() => {
  console.log(JSON.stringify({ status: res.statusCode, headers: res.headers, body: res.body, calls }));
});
"""
TOKEN = "A" * 43


def feed_event(eid, start, title):
    return {"id": eid, "title": title, "startAt": start, "endAt": None, "status": "published",
            "location": {"building": "E11", "room": "", "name": ""}, "food": {"provided": "true"},
            "publication": {"public": True}}


def run(saved, feed, token=TOKEN, rpc_ok=True):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    args = json.dumps({"saved": saved, "feed": feed, "token": token, "rpcOk": rpc_ok})
    out = subprocess.run(["node", "-e", RUN, str(ROOT / "api/cal.js"), args], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_the_feed_lists_the_stars_with_current_times_and_a_30_minute_alert():
    from tests.test_ggongbab_live import LIVE
    live = LIVE["events"][0]
    saved = [{"event_id": live["id"], "saved_at": "2026-11-08T00:00:00Z", "seen": {"title": "옛 제목"}},
             {"event_id": "gone", "saved_at": "2026-11-08T00:00:00Z",
              "seen": {"title": "목록에서 빠진 행사", "startAt": "2026-12-01T12:00:00+09:00", "place": "N1"}},
             {"event_id": "notime", "saved_at": "2026-11-08T00:00:00Z", "seen": {"title": "시간 없음"}}]
    out = run(saved, LIVE)
    assert out["status"] == 200 and out["headers"]["Content-Type"] == "text/calendar; charset=utf-8"
    assert out["headers"]["Cache-Control"] == "private, no-store"
    body = out["body"]
    assert body.startswith("BEGIN:VCALENDAR\r\n") and body.endswith("END:VCALENDAR\r\n")
    assert "X-WR-CALNAME:밥도둑 내 꽁밥" in body and body.count("BEGIN:VEVENT") == 2
    assert f"UID:{live['id']}@babdodukms.com" in body and "옛 제목" not in body, "the current listing wins"
    assert "SUMMARY:목록에서 빠진 행사" in body and "LOCATION:N1" in body
    assert body.count("TRIGGER:-PT30M") == 2 and "시간 없음" not in body
    assert "https://babdoduk-lab.vercel.app/ggongbab.html?e=" in body
    rpc = [c for c in out["calls"] if "rpc" in c[0]]
    assert rpc == [["https://myjglfynhnptlclawlcc.supabase.co/rest/v1/rpc/calendar_feed_events", {"p_token": TOKEN}]]


def test_a_bad_token_is_not_found_and_a_database_failure_says_try_later():
    assert run([], {"events": []}, token="short")["status"] == 404
    out = run(None, {"events": []}, rpc_ok=False)
    assert out["status"] == 503 and out["headers"]["Retry-After"] == "300"


def test_the_address_routes_to_the_function_with_the_site_code_bundled():
    config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    route = next(r for r in config["routes"] if r.get("dest", "").startswith("/api/cal"))
    assert re.fullmatch(route["src"], "/cal/" + TOKEN + ".ics") and route["dest"] == "/api/cal?t=$1"
    files = config["functions"]["api/cal.js"]["includeFiles"]
    for name in ("js/ggongbab-select.js", "js/ggongbab-live.js", "js/ggongbab-public-config.js"):
        assert name in files
    source = (ROOT / "api/cal.js").read_text(encoding="utf-8")
    assert "SUPABASE_PUBLISHABLE_KEY" in source and not re.search(r"sb_secret_|service_role", source)


def test_a_past_star_stays_in_the_calendar():
    # Owner 2026-11-12: after its day a star leaves the saved lists, but the calendar keeps the event.
    saved = [{"event_id": "lastweek", "saved_at": "2026-11-01T00:00:00Z",
              "seen": {"title": "지난주 세미나", "startAt": "2026-11-03T12:00:00+09:00", "endAt": "2026-11-03T13:00:00+09:00", "place": "E11"}}]
    body = run(saved, {"events": []})["body"]
    assert "SUMMARY:지난주 세미나" in body and body.count("BEGIN:VEVENT") == 1
