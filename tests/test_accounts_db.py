"""마이 밥도둑 accounts (docs/MY_BABDODUK.md): supabase/migrations/011_accounts.sql.

Two layers. The static tests always run and read the SQL. The database tests apply the migration to a
throwaway local PostgreSQL with a small stand-in for Supabase's auth schema and roles (anon,
authenticated, auth.uid() from request.jwt.claim.sub) and then act as different users. They run only
where the optional `pgserver` and `psycopg` packages are installed (not in the default dev venv), and
skip otherwise; they never touch a real Supabase project.
"""
from __future__ import annotations

import re
import tempfile
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "supabase/migrations/011_accounts.sql").read_text(encoding="utf-8")
TABLES = ("profiles", "saved_events", "saved_places", "place_lists", "place_list_items")


# ---------------------------------------------------------------------------------------------------
# Static reading
# ---------------------------------------------------------------------------------------------------
def test_every_table_denies_by_default_and_only_signed_in_users_get_rights():
    for table in TABLES:
        assert f"alter table public.{table} enable row level security;" in SQL, table
        assert re.search(rf"create policy {table}_own on public\.{table} for all to authenticated", SQL), table
    assert "revoke all on table public.profiles, public.saved_events, public.saved_places," in SQL
    grants = re.findall(r"grant ([a-z, ]+) on table ([^;]+) to ([a-z_, ]+);", SQL)
    assert grants, "the table grants"
    for _, _, roles in grants:
        assert roles.strip() == "authenticated", roles
    assert " to anon" not in SQL.replace("to anon, authenticated;", ""), "anon gets only the public list read"


def test_the_only_public_function_returns_a_title_and_place_ids():
    anon = re.findall(r"grant execute on function ([^;]+) to anon", SQL)
    assert anon == ["public.public_place_list(text)"]
    body = SQL.split("create or replace function public.public_place_list", 1)[1].split("$$;", 1)[0]
    assert "'title', l.title" in body and "'places'" in body
    for private in ("user_id", "memo", "status", "display_name", "email"):
        assert private not in body.split("from public.place_lists l", 1)[0], private


def test_definer_functions_pin_the_search_path_and_check_the_caller():
    for name in re.findall(r"create or replace function (public\.[a-z_]+)\(", SQL):
        body = SQL.split(f"create or replace function {name}(", 1)[1].split("$$;", 1)[0]
        assert "set search_path = ''" in body, name
        if "security definer" in body and name != "public.public_place_list":
            assert "auth.uid()" in body, name


def test_the_service_key_and_no_secret_appear():
    assert "service_role" not in SQL
    assert not re.search(r"sb_secret_|eyJ[A-Za-z0-9_-]{20,}", SQL)


# ---------------------------------------------------------------------------------------------------
# A real PostgreSQL
# ---------------------------------------------------------------------------------------------------
SHIM = """
do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then create role anon nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then create role authenticated nologin; end if;
end $$;
create schema if not exists auth;
create schema if not exists extensions;
create table if not exists auth.users (
  id uuid primary key, email text, last_sign_in_at timestamptz, raw_user_meta_data jsonb default '{}'::jsonb
);
create or replace function auth.uid() returns uuid language sql stable as
  $f$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $f$;
grant usage on schema auth, extensions, public to anon, authenticated;
grant execute on function auth.uid() to anon, authenticated;
-- pgserver ships without pgcrypto; Supabase has it. A stand-in for the one function the migration uses.
create or replace function extensions.gen_random_bytes(n integer) returns bytea language sql volatile as
  $f$ select decode(string_agg(lpad(to_hex((random() * 255)::int), 2, '0'), ''), 'hex') from generate_series(1, n) $f$;
"""
PGCRYPTO = "create extension if not exists pgcrypto with schema extensions;"


@pytest.fixture(scope="module")
def db():
    pgserver = pytest.importorskip("pgserver")
    psycopg = pytest.importorskip("psycopg")
    folder = tempfile.mkdtemp(prefix="babdoduk-accounts-")
    server = pgserver.get_server(folder, cleanup_mode="delete")
    uri = server.get_uri()
    with psycopg.connect(uri, autocommit=True) as admin:
        admin.execute(SHIM)
        assert PGCRYPTO in SQL
        local = SQL.replace(PGCRYPTO, "")
        admin.execute(local)
        admin.execute(local)  # applying twice is harmless
    yield psycopg, uri
    server.cleanup()


class As:
    """A connection acting as anon or as one signed-in user."""

    def __init__(self, psycopg, uri, user=None):
        self.psycopg = psycopg
        self.conn = psycopg.connect(uri, autocommit=True)
        role = "authenticated" if user else "anon"
        self.conn.execute(f"set role {role}")
        self.conn.execute("select set_config('request.jwt.claim.sub', %s, false)", (str(user or ""),))

    def q(self, sql, args=()):
        cur = self.conn.execute(sql, args)
        return cur.fetchall() if cur.description else cur.rowcount

    def fails(self, sql, args=()):
        try:
            self.conn.execute(sql, args)
        except self.psycopg.Error:
            return True
        return False

    def close(self):
        self.conn.close()


def new_user(psycopg, uri, signed_in="now()"):
    uid = uuid.uuid4()
    with psycopg.connect(uri, autocommit=True) as admin:
        admin.execute(f"insert into auth.users (id, last_sign_in_at) values (%s, {signed_in})", (uid,))
    return uid


def test_anon_reads_and_writes_nothing(db):
    psycopg, uri = db
    a = new_user(psycopg, uri)
    alice = As(psycopg, uri, a)
    alice.q("insert into public.saved_events (user_id, event_id) values (%s, 'ev1')", (a,))
    anon = As(psycopg, uri)
    for table in TABLES:
        assert anon.fails(f"select * from public.{table}"), table
    assert anon.fails("insert into public.saved_events (user_id, event_id) values (%s, 'x')", (a,))
    for fn in ("merge_saved_events('[]')", "merge_saved_places('[]')", "delete_my_saved_data()", "delete_my_account()"):
        assert anon.fails(f"select public.{fn}"), fn
    alice.close(); anon.close()


def test_a_user_sees_and_changes_only_their_own_rows(db):
    psycopg, uri = db
    a, b = new_user(psycopg, uri), new_user(psycopg, uri)
    alice, bob = As(psycopg, uri, a), As(psycopg, uri, b)
    alice.q("insert into public.saved_events (user_id, event_id) values (%s, 'ev-a')", (a,))
    alice.q("insert into public.saved_places (user_id, place_id, status, memo) values (%s, 'p1', 'want', 'secret memo')", (a,))
    alice.q("insert into public.profiles (user_id, display_name) values (%s, '앨리스')", (a,))
    assert bob.q("select count(*) from public.saved_events")[0][0] == 0
    assert bob.q("select count(*) from public.saved_places")[0][0] == 0
    assert bob.q("select count(*) from public.profiles")[0][0] == 0
    assert bob.q("update public.saved_places set memo = 'x' where user_id = %s", (a,)) == 0
    assert bob.q("delete from public.saved_events where user_id = %s", (a,)) == 0
    assert bob.fails("insert into public.saved_events (user_id, event_id) values (%s, 'planted')", (a,))
    assert alice.fails("update public.saved_places set user_id = %s where place_id = 'p1'", (b,))
    assert alice.q("select memo from public.saved_places") == [("secret memo",)]
    assert alice.fails("insert into public.saved_events (user_id, event_id) values (%s, 'bad id!')", (a,))
    alice.close(); bob.close()


def test_guest_merge_adds_only_missing_events_and_keeps_the_account_copy(db):
    psycopg, uri = db
    a = new_user(psycopg, uri)
    alice = As(psycopg, uri, a)
    alice.q("""insert into public.saved_events (user_id, event_id, saved_at, seen)
               values (%s, 'kept', '2026-11-05T00:00:00Z', '{"title":"server"}')""", (a,))
    items = ('[{"id":"kept","savedAt":"2026-11-01T00:00:00Z","seen":{"title":"browser"}},'
             '{"id":"new#2","savedAt":"2026-11-02T00:00:00Z","seen":{"title":"n"}},'
             '{"id":"new#2","savedAt":"2026-11-03T00:00:00Z"},'
             '{"id":"bad id"},{"nope":1},"text"]')
    assert alice.q("select public.merge_saved_events(%s::jsonb)", (items,)) == [(1,)]
    rows = dict((r[0], r[1:]) for r in alice.q(
        "select event_id, seen->>'title', to_char(saved_at at time zone 'UTC', 'YYYY-MM-DD') from public.saved_events"))
    assert rows == {"kept": ("server", "2026-11-01"), "new#2": ("n", "2026-11-02")}
    assert alice.q("select public.merge_saved_events('[]'::jsonb)") == [(0,)]
    assert alice.fails("select public.merge_saved_events('{}'::jsonb)")
    alice.close()


def test_guest_merge_for_places_reports_memo_conflicts_without_overwriting(db):
    psycopg, uri = db
    a = new_user(psycopg, uri)
    alice = As(psycopg, uri, a)
    alice.q("insert into public.saved_places (user_id, place_id, status, memo) values (%s, 'p1', 'been', 'account memo')", (a,))
    alice.q("insert into public.saved_places (user_id, place_id, status, memo) values (%s, 'p2', 'want', '')", (a,))
    items = ('[{"id":"p1","status":"again","memo":"browser memo"},{"id":"p2","status":"again","memo":""},'
             '{"id":"p3","status":"want","memo":"m3"},{"id":"p4","status":"bogus"}]')
    out = alice.q("select public.merge_saved_places(%s::jsonb)", (items,))[0][0]
    assert out == {"added": 1, "conflicts": ["p1"]}
    rows = {r[0]: r[1:] for r in alice.q("select place_id, status, memo from public.saved_places")}
    assert rows == {"p1": ("been", "account memo"), "p2": ("want", ""), "p3": ("want", "m3")}
    alice.close()


def test_a_shared_list_shows_only_its_title_and_place_ids_and_stops_when_unshared(db):
    psycopg, uri = db
    a, b = new_user(psycopg, uri), new_user(psycopg, uri)
    alice, bob, anon = As(psycopg, uri, a), As(psycopg, uri, b), As(psycopg, uri)
    list_id = alice.q("insert into public.place_lists (user_id, title) values (%s, '어은동 점심') returning id", (a,))[0][0]
    alice.q("insert into public.place_list_items (list_id, place_id) values (%s, 'p1'), (%s, 'p2')", (list_id, list_id))
    assert bob.fails("insert into public.place_list_items (list_id, place_id) values (%s, 'planted')", (list_id,))
    assert bob.fails("select public.set_place_list_sharing(%s, true)", (list_id,))
    assert alice.fails("update public.place_lists set is_public = true where id = %s", (list_id,)), "public needs a slug"
    slug = alice.q("select public.set_place_list_sharing(%s, true)", (list_id,))[0][0]
    assert re.fullmatch(r"[A-Za-z0-9_-]{22}", slug)
    shared = anon.q("select public.public_place_list(%s)", (slug,))[0][0]
    assert shared == {"title": "어은동 점심", "places": ["p1", "p2"]}
    assert anon.q("select public.public_place_list('not-a-slug')") == [(None,)]
    assert alice.q("select public.set_place_list_sharing(%s, false)", (list_id,)) == [(None,)]
    assert anon.q("select public.public_place_list(%s)", (slug,)) == [(None,)]
    again = alice.q("select public.set_place_list_sharing(%s, true)", (list_id,))[0][0]
    assert again != slug and anon.q("select public.public_place_list(%s)", (slug,)) == [(None,)]
    alice.close(); bob.close(); anon.close()


def test_limits_stop_a_runaway_client(db):
    psycopg, uri = db
    a = new_user(psycopg, uri)
    alice = As(psycopg, uri, a)
    alice.q("insert into public.saved_events (user_id, event_id) select %s, 'e' || g from generate_series(1, 300) g", (a,))
    assert alice.fails("insert into public.saved_events (user_id, event_id) values (%s, 'one-more')", (a,))
    for i in range(20):
        alice.q("insert into public.place_lists (user_id, title) values (%s, %s)", (a, f"list {i}"))
    assert alice.fails("insert into public.place_lists (user_id, title) values (%s, 'too many')", (a,))
    alice.close()


def test_clearing_saved_data_keeps_the_account_and_other_users(db):
    psycopg, uri = db
    a, b = new_user(psycopg, uri), new_user(psycopg, uri)
    alice, bob = As(psycopg, uri, a), As(psycopg, uri, b)
    for who, uid in ((alice, a), (bob, b)):
        who.q("insert into public.saved_events (user_id, event_id) values (%s, 'e1')", (uid,))
        who.q("insert into public.saved_places (user_id, place_id, status) values (%s, 'p1', 'want')", (uid,))
        who.q("insert into public.profiles (user_id, display_name) values (%s, 'n')", (uid,))
    alice.q("select public.delete_my_saved_data()")
    assert alice.q("select count(*) from public.saved_events")[0][0] == 0
    assert alice.q("select count(*) from public.saved_places")[0][0] == 0
    assert alice.q("select count(*) from public.profiles")[0][0] == 1
    assert bob.q("select count(*) from public.saved_events")[0][0] == 1
    alice.close(); bob.close()


def test_leaving_needs_a_fresh_sign_in_and_removes_everything(db):
    psycopg, uri = db
    stale = new_user(psycopg, uri, signed_in="now() - interval '2 hours'")
    fresh, other = new_user(psycopg, uri), new_user(psycopg, uri)
    s, f, o = As(psycopg, uri, stale), As(psycopg, uri, fresh), As(psycopg, uri, other)
    s.q("insert into public.saved_events (user_id, event_id) values (%s, 'e1')", (stale,))
    assert s.fails("select public.delete_my_account()"), "an old session cannot delete the account"
    assert s.q("select count(*) from public.saved_events")[0][0] == 1
    f.q("insert into public.saved_events (user_id, event_id) values (%s, 'e1')", (fresh,))
    f.q("insert into public.saved_places (user_id, place_id, status, memo) values (%s, 'p1', 'want', 'm')", (fresh,))
    lid = f.q("insert into public.place_lists (user_id, title) values (%s, 'l') returning id", (fresh,))[0][0]
    f.q("insert into public.place_list_items (list_id, place_id) values (%s, 'p1')", (lid,))
    f.q("insert into public.profiles (user_id) values (%s)", (fresh,))
    o.q("insert into public.saved_events (user_id, event_id) values (%s, 'e1')", (other,))
    f.q("select public.delete_my_account()")
    with psycopg.connect(uri, autocommit=True) as admin:
        assert admin.execute("select count(*) from auth.users where id = %s", (fresh,)).fetchone()[0] == 0
        for table in ("profiles", "saved_events", "saved_places", "place_lists"):
            n = admin.execute(f"select count(*) from public.{table} where user_id = %s", (fresh,)).fetchone()[0]
            assert n == 0, table
        assert admin.execute("select count(*) from public.place_list_items where list_id = %s", (lid,)).fetchone()[0] == 0
        assert admin.execute("select count(*) from public.saved_events where user_id = %s", (other,)).fetchone()[0] == 1
        assert admin.execute("select count(*) from auth.users where id = %s", (stale,)).fetchone()[0] == 1
    s.close(); f.close(); o.close()
