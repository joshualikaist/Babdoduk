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



# --- 016: only the newest connection shows the events (owner 2026-11-19) ------------------------------
CONNECT = (ROOT / "supabase/migrations/016_calendar_connect.sql").read_text(encoding="utf-8")


def test_the_connection_functions_are_closed_like_013():
    """A second 연결 on the iPhone made a second calendar with the same list ("동일한 행사가 두개 뜨는거지")."""
    assert re.findall(r"grant execute on function ([^;]+) to anon", CONNECT) == ["public.calendar_feed_events(text)"]
    assert re.findall(r"grant execute on function ([^;]+) to authenticated;", CONNECT) == ["public.my_calendar_link()"]
    assert "revoke all on function public.calendar_new_token() from public, anon, authenticated;" in CONNECT
    for name in ("my_calendar_link", "calendar_feed_events"):
        body = CONNECT.split(f"create or replace function public.{name}(", 1)[1].split("$$;", 1)[0]
        assert "set search_path = ''" in body and "security definer" in body, name
    read = CONNECT.split("create or replace function public.calendar_feed_events(", 1)[1].split("$$;", 1)[0]
    assert "returns table (event_id text, saved_at timestamptz, seen jsonb)" in read   # api/cal.js is unchanged
    for private in ("email", "display_name", "raw_user_meta_data"):
        assert private not in CONNECT, private
    assert not re.search(r"grant [a-z, ]+ on table", CONNECT) and "service_role" not in CONNECT


@pytest.fixture(scope="module")
def db16():
    pgserver = pytest.importorskip("pgserver")
    psycopg = pytest.importorskip("psycopg")
    if not ACCOUNTS_FILE.is_file():
        pytest.skip("supabase/migrations/011_accounts.sql is not on this branch")
    from tests.test_accounts_db import PGCRYPTO, SHIM
    server = pgserver.get_server(tempfile.mkdtemp(prefix="babdoduk-calconnect-"), cleanup_mode="delete")
    uri = server.get_uri()
    with psycopg.connect(uri, autocommit=True) as admin:
        admin.execute(SHIM)
        admin.execute(ACCOUNTS_FILE.read_text(encoding="utf-8").replace(PGCRYPTO, ""))
        admin.execute(SQL.replace(PGCRYPTO, ""))
        admin.execute(CONNECT)
        admin.execute(CONNECT)   # applying twice is harmless
    yield psycopg, uri
    server.cleanup()


def test_the_newest_connection_is_the_only_one_that_shows_the_events(db16):
    psycopg, uri = db16
    from tests.test_accounts_db import As, new_user
    a, b = new_user(psycopg, uri), new_user(psycopg, uri)
    ua, ub, anon = As(psycopg, uri, a), As(psycopg, uri, b), As(psycopg, uri)
    ua.q("insert into public.saved_events (user_id, event_id) values (%s, 'lunch')", (a,))
    ub.q("insert into public.saved_events (user_id, event_id) values (%s, 'other')", (b,))
    stars = lambda token: [r[0] for r in anon.q("select event_id from public.calendar_feed_events(%s)", (token,))]

    # An account that subscribed before 016 (013's address, maybe twice on the phone) keeps working ...
    old = ua.q("select public.my_calendar_feed()")[0][0]
    assert stars(old) == ["lunch"]
    first = ua.q("select public.my_calendar_link()")[0][0]
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", first["link"]) and first["link"] != old
    assert first["read_at"] is not None and first["linked_at"] is None          # read through the old address
    assert ua.q("select public.my_calendar_link()")[0][0]["link"] == first["link"]  # one address until it is used
    # ... until the new address is read once: from then on only it lists the stars, the old one is empty.
    assert stars(first["link"]) == ["lunch"]
    assert stars(old) == [] and stars(first["link"]) == ["lunch"]
    now = ua.q("select public.my_calendar_link()")[0][0]
    assert now["link"] not in (old, first["link"]) and now["read_at"] and now["linked_at"]
    assert ua.q("select public.my_calendar_feed()")[0][0] == first["link"]       # 013's function: the live one
    # Connecting again (다시 연결) never leaves two live copies.
    assert stars(now["link"]) == ["lunch"] and stars(first["link"]) == []
    # A new account starts with a link and no read; other accounts are untouched; anon cannot ask for a link.
    fresh = ub.q("select public.my_calendar_link()")[0][0]
    assert fresh["read_at"] is None and fresh["linked_at"] is None and stars(fresh["link"]) == ["other"]
    assert anon.fails("select public.my_calendar_link()") and ua.fails("select public.calendar_new_token()")
    assert anon.fails("select * from public.calendar_feeds")
    with psycopg.connect(uri, autocommit=True) as admin:
        admin.execute("delete from auth.users where id = %s", (a,))
    assert stars(now["link"]) == []   # gone with the account
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
cal({ url: '/api/cal?t=' + data.token, headers: data.headers || { host: 'babdoduk-lab.vercel.app' } }, res).then(() => {
  console.log(JSON.stringify({ status: res.statusCode, headers: res.headers, body: res.body, calls }));
});
"""
TOKEN = "A" * 43


def feed_event(eid, start, title):
    return {"id": eid, "title": title, "startAt": start, "endAt": None, "status": "published",
            "location": {"building": "E11", "room": "", "name": ""}, "food": {"provided": "true"},
            "publication": {"public": True}}


def run(saved, feed, token=TOKEN, rpc_ok=True, headers=None):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    args = json.dumps({"saved": saved, "feed": feed, "token": token, "rpcOk": rpc_ok, "headers": headers})
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


ENTRIES = r"""
const cal = require(process.argv[1]);
const d = JSON.parse(process.argv[2]);
console.log(JSON.stringify(cal.entries(d.saved, d.feed, d.archive, new Date(d.now)).map((ev) => ev.id)));
"""


def entry_ids(saved, feed, archive, now):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    args = json.dumps({"saved": saved, "feed": feed, "archive": archive, "now": now})
    out = subprocess.run(["node", "-e", ENTRIES, str(ROOT / "api/cal.js"), args], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_a_star_whose_listing_was_withdrawn_before_it_happened_leaves_the_calendar():
    # Owner 2026-11-24: "빠진거는 알아서 별표에서도 빠져야지". The clock is fixed: 2026-11-24 10:00 KST.
    now = "2026-11-24T01:00:00Z"
    live = feed_event("aaaaaaaa-1111-4222-8333-444444444444", "2026-11-26T12:00:00+09:00", "다음 세미나")
    archived = feed_event("bbbbbbbb-1111-4222-8333-444444444444", "2026-11-20T12:00:00+09:00", "지난 세미나")
    saved = [
        {"event_id": live["id"], "seen": {"title": "다음 세미나", "startAt": live["startAt"]}},
        {"event_id": archived["id"], "seen": {"title": "지난 세미나", "startAt": archived["startAt"]}},
        {"event_id": "withdrawn", "seen": {"title": "빠진 행사", "startAt": "2026-11-27T12:00:00+09:00"}},
        {"event_id": "lastweek", "seen": {"title": "지난주 행사", "startAt": "2026-11-17T12:00:00+09:00",
                                          "endAt": "2026-11-17T13:00:00+09:00"}},
    ]
    feed, archive = {"events": [live]}, {"events": [archived]}
    # Both lists read: the withdrawn listing is left out; a listing that already happened stays.
    assert entry_ids(saved, feed, archive, now) == [live["id"], archived["id"], "lastweek"]
    # A list that could not be read never takes an event away: every star keeps its own copy.
    every = [live["id"], archived["id"], "withdrawn", "lastweek"]
    assert entry_ids(saved, feed, None, now) == every
    assert entry_ids(saved, None, archive, now) == every


def test_the_feed_is_read_only_from_our_own_sites_whatever_the_request_names():
    # security audit 2026-11-13: x-forwarded-host / host never choose where the server fetches from.
    from tests.test_ggongbab_live import LIVE
    saved = [{"event_id": LIVE["events"][0]["id"], "saved_at": "2026-11-08T00:00:00Z", "seen": {}}]
    for headers, origin in (({"host": "evil.example", "x-forwarded-host": "evil.example"}, "https://www.babdodukms.com"),
                            ({"host": "babdoduk-lab.vercel.app", "x-forwarded-host": "169.254.169.254"}, "https://www.babdodukms.com"),
                            ({"host": "x", "x-forwarded-host": "babdoduk-git-branch.vercel.app"}, "https://www.babdodukms.com"),
                            ({"host": "x", "x-forwarded-host": "babdoduk.vercel.app.evil.example"}, "https://www.babdodukms.com"),
                            ({}, "https://www.babdodukms.com"),
                            ({"x-forwarded-host": "BabdodukMS.com"}, "https://babdodukms.com"),
                            ({"host": "babdoduk.vercel.app"}, "https://babdoduk.vercel.app"),
                            ({"host": "babdoduk-lab.vercel.app"}, "https://babdoduk-lab.vercel.app")):
        out = run(saved, LIVE, headers=headers)
        assert out["status"] == 200, headers
        fetched = [c[0] for c in out["calls"] if "rpc" not in c[0]]
        assert fetched == [origin + "/data/ggongbab/latest.json", origin + "/data/ggongbab/archive/index.json"], headers
        links = set(re.findall(r"https://[^/\s]+/ggongbab\.html", out["body"].replace("\r\n ", "")))
        assert links == {origin + "/ggongbab.html"}, headers


def test_an_empty_list_fetches_no_feed():
    out = run([], {"events": []})
    assert out["status"] == 200 and out["body"].count("BEGIN:VEVENT") == 0
    assert [c[0] for c in out["calls"] if "rpc" not in c[0]] == []


def test_a_lone_carriage_return_never_ends_a_calendar_line():
    # security audit 2026-11-13: icsEscape turns CRLF, a lone CR and a lone LF alike into the text \n, so a
    # title, place or note can never start a property of its own (here a forged ATTACH or a second event).
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    script = r"""
const { L } = require(process.argv[1]).siteCode();
const ev = { id: 'cr', title: 'a\rATTACH:https://evil.example/x\r\nb\nc', startAt: '2026-11-20T12:00:00+09:00',
             endAt: null, location: { name: 'N1\rEND:VEVENT\rBEGIN:VEVENT' }, food: { provided: 'true' } };
console.log(JSON.stringify(L.icsText(ev, { details: 'd\re', stamp: '2026-11-13T00:00:00Z' })));
"""
    out = subprocess.run(["node", "-e", script, str(ROOT / "api/cal.js")], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    ics = json.loads(out.stdout)
    body = ics[:-2]                                         # the file ends with one CRLF
    assert "\r" not in body.replace("\r\n", "") and "\n" not in body.replace("\r\n", ""), "only CRLF ends a line"
    lines = ics.replace("\r\n ", "").split("\r\n")
    assert not any(line.startswith("ATTACH") for line in lines)
    assert lines.count("BEGIN:VEVENT") == 1 and lines.count("END:VEVENT") == 1
    assert "SUMMARY:a\\nATTACH:https://evil.example/x\\nb\\nc" in lines
    assert "LOCATION:N1\\nEND:VEVENT\\nBEGIN:VEVENT" in lines and "DESCRIPTION:d\\ne" in lines


# --- the profile and old subscriptions (owner 2026-11-19, "구독은 쌓여 ... 다른 방식을 찾아내봐") --------------
LEFTOVER = (ROOT / "supabase/migrations/017_calendar_leftover.sql").read_text(encoding="utf-8")


def test_the_iphone_connection_is_a_profile_that_replaces_itself():
    """A website cannot delete a webcal subscription, so every second 연결 left a calendar behind. A configuration
    profile with one fixed PayloadIdentifier replaces the installed one instead (Apple: the identifier "is used
    to determine whether a new profile should replace an existing one or should be added")."""
    import plistlib
    first = run([], None, token=TOKEN + "&profile=1", headers={"host": "www.babdodukms.com"})
    second = run([], None, token="B" * 43 + "&profile=1", headers={"host": "babdoduk-lab.vercel.app"})
    assert first["status"] == 200 and first["calls"] == []          # nothing is read, and no calendar read is counted
    assert first["headers"]["Content-Type"].startswith("application/x-apple-aspen-config")
    assert first["headers"]["Cache-Control"] == "private, no-store" and first["headers"]["X-Robots-Tag"] == "noindex"
    a, b = (plistlib.loads(r["body"].encode("utf-8")) for r in (first, second))
    assert a["PayloadType"] == "Configuration" and a["PayloadIdentifier"] == b["PayloadIdentifier"] == "com.babdodukms.calendar"
    assert a["PayloadUUID"] != b["PayloadUUID"] and a["PayloadRemovalDisallowed"] is False
    sub = a["PayloadContent"][0]
    assert sub["PayloadType"] == "com.apple.subscribedcalendar.account" and sub["SubCalAccountUseSSL"] is True
    assert sub["PayloadIdentifier"] == "com.babdodukms.calendar.subscription"
    assert sub["SubCalAccountHostName"] == f"https://www.babdodukms.com/cal/{TOKEN}.ics"
    assert sub["SubCalAccountDescription"] == "밥도둑 꽁밥"   # not 밥도둑 내 꽁밥, the old webcal calendars' name
    assert b["PayloadContent"][0]["SubCalAccountHostName"] == f"https://babdoduk-lab.vercel.app/cal/{'B' * 43}.ics"
    forged = run([], None, token=TOKEN + "&profile=1", headers={"host": "evil.example"})
    assert "https://www.babdodukms.com/cal/" in forged["body"] and "evil" not in forged["body"]
    config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    route = next(r for r in config["routes"] if r.get("dest", "") == "/api/cal?t=$1&profile=1")
    assert re.fullmatch(route["src"], f"/cal/{TOKEN}.mobileconfig") and not re.fullmatch(route["src"], "/cal/short.mobileconfig")


def test_an_old_address_shows_one_notice_asking_to_delete_it():
    out = run([{"event_id": "babdoduk:retired", "saved_at": "2026-11-19T00:00:00Z", "seen": None}], None)
    assert out["status"] == 200 and len(out["calls"]) == 1          # no feed is fetched for it
    body = out["body"]
    assert body.count("BEGIN:VEVENT") == 1 and "X-WR-CALNAME:밥도둑 지난 구독 · 지워 주세요" in body
    unfolded = body.replace("\r\n ", "")
    assert "SUMMARY:밥도둑 지난 구독 · 지워 주세요" in unfolded and "DTSTART;VALUE=DATE:" in unfolded
    assert "VALARM" not in body and all(len(line.encode()) <= 75 for line in body.split("\r\n"))


def test_the_leftover_functions_are_closed_like_016():
    assert re.findall(r"grant execute on function ([^;]+) to anon", LEFTOVER) == ["public.calendar_feed_events(text)"]
    assert re.findall(r"grant execute on function ([^;]+) to authenticated;", LEFTOVER) == ["public.my_calendar_link()"]
    assert "revoke all on table public.calendar_feed_retired from public, anon, authenticated;" in LEFTOVER
    assert "alter table public.calendar_feed_retired enable row level security;" in LEFTOVER
    assert not re.search(r"grant [a-z, ]+ on table", LEFTOVER) and "service_role" not in LEFTOVER


@pytest.fixture(scope="module")
def db17():
    pgserver = pytest.importorskip("pgserver")
    psycopg = pytest.importorskip("psycopg")
    if not ACCOUNTS_FILE.is_file():
        pytest.skip("supabase/migrations/011_accounts.sql is not on this branch")
    from tests.test_accounts_db import PGCRYPTO, SHIM
    server = pgserver.get_server(tempfile.mkdtemp(prefix="babdoduk-calleftover-"), cleanup_mode="delete")
    uri = server.get_uri()
    with psycopg.connect(uri, autocommit=True) as admin:
        admin.execute(SHIM)
        admin.execute(ACCOUNTS_FILE.read_text(encoding="utf-8").replace(PGCRYPTO, ""))
        admin.execute(SQL.replace(PGCRYPTO, ""))
        admin.execute(CONNECT)
        admin.execute(LEFTOVER)
        admin.execute(LEFTOVER)   # applying twice is harmless
    yield psycopg, uri
    server.cleanup()


def test_an_old_subscription_is_marked_and_reported(db17):
    psycopg, uri = db17
    from tests.test_accounts_db import As, new_user
    a = new_user(psycopg, uri)
    ua, anon = As(psycopg, uri, a), As(psycopg, uri)
    ua.q("insert into public.saved_events (user_id, event_id) values (%s, 'lunch')", (a,))
    rows = lambda token: [r[0] for r in anon.q("select event_id from public.calendar_feed_events(%s)", (token,))]
    old = ua.q("select public.my_calendar_feed()")[0][0]          # the webcal subscription of before
    assert rows(old) == ["lunch"]
    link = ua.q("select public.my_calendar_link()")[0][0]
    assert link["leftover_at"] is None
    assert rows(link["link"]) == ["lunch"]                          # the profile's first read: the new live address
    assert rows(old) == ["babdoduk:retired"]                        # the old subscription is told to go
    now = ua.q("select public.my_calendar_link()")[0][0]
    assert now["leftover_at"] is not None and now["read_at"] is not None
    assert rows("Z" * 43) == []                                     # an address that never existed: nothing
    assert anon.fails("select * from public.calendar_feed_retired") and ua.fails("select * from public.calendar_feed_retired")
    with psycopg.connect(uri, autocommit=True) as admin:
        admin.execute("delete from auth.users where id = %s", (a,))
    assert rows(old) == [] and rows(link["link"]) == []             # gone with the account
    ua.close(); anon.close()
