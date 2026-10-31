"""꽁밥 제보 (lab, docs/GGONGBAB_TIPS.md): the rights and limits in supabase/migrations/007_ggongbab_tips.sql
and the browser contract of js/ggongbab-tips.js. Static reading only; never a live database.
scripts/check_site_ui.py tip_board plays the page against a fake client."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "supabase/migrations/007_ggongbab_tips.sql").read_text(encoding="utf-8")
JS = (ROOT / "js/ggongbab-tips.js").read_text(encoding="utf-8")
PAGE = (ROOT / "tip.html").read_text(encoding="utf-8")
TABLES = ("ggongbab_tips", "ggongbab_tip_board", "ggongbab_tip_secret", "ggongbab_tip_rate")


def statement(pattern):
    return re.findall(pattern, SQL, re.I | re.S)


def columns():
    stored = statement(r"create table if not exists public\.(\w+) \((.*?)\n\);")
    return {table: [c for c in re.findall(r"^\s+(\w+) ", body, re.M) if c != "primary"] for table, body in stored}


def test_every_table_has_row_level_security_and_browsers_only_read_the_board():
    for table in TABLES:
        assert f"alter table public.{table} enable row level security;" in SQL, table
        assert re.search(rf"revoke all on table public\.{table} from public, anon, authenticated", SQL), table
    grants = statement(r"grant ([a-z, ]+) on table public\.(\w+) to ([a-z_, ]+);")
    browser = [(what, table) for what, table, who in grants if "anon" in who or "authenticated" in who]
    assert browser == [("select", "ggongbab_tip_board")]
    assert ("select, update", "ggongbab_tips", "service_role") in grants
    assert not statement(r"grant [^;]* on table public\.ggongbab_tip_(secret|rate)")       # never readable
    policies = statement(r"create policy (\w+) on public\.(\w+) for (\w+) to ([a-z_, ]+) using")
    assert policies == [("ggongbab_tip_board_read", "ggongbab_tip_board", "select", "anon, authenticated")]


def test_the_stored_columns_are_the_contract_and_the_board_holds_no_private_field():
    found = columns()
    assert found["ggongbab_tips"] == ["id", "created_at", "title", "place", "event_date", "time_text", "food", "details",
                                      "link", "image_count", "client_hash", "status", "notified_at", "reviewed_at",
                                      "dooray_post_id"]
    assert found["ggongbab_tip_board"] == ["id", "title", "place", "event_date", "time_text", "food", "accepted_at"]
    assert found["ggongbab_tip_rate"] == ["client_hash", "window_start", "tips"]
    assert "status text not null default 'new' check (status in ('new', 'accepted', 'rejected'))" in SQL
    assert "id uuid primary key references public.ggongbab_tips (id) on delete cascade" in SQL
    # The address only ever enters a salted digest with the Korean date; only the digest is stored.
    assert "extensions.digest((select salt from public.ggongbab_tip_secret) || today::text || forwarded" in SQL
    assert "values (client, date_trunc('hour', now()), 1)" in SQL


def test_the_only_browser_writes_are_the_checking_function_and_photo_uploads():
    functions = statement(r"create or replace function public\.(\w+)\(")
    assert functions == ["ggongbab_submit_tip", "ggongbab_tip_upload_allowed"]
    assert SQL.count("security definer set search_path = pg_catalog, public") == 2
    assert ("grant execute on function public.ggongbab_submit_tip(text, text, date, text, text, text, text, text) "
            "to anon, authenticated, service_role;") in SQL
    assert "grant execute on function public.ggongbab_tip_upload_allowed(text) to anon, authenticated, service_role;" in SQL
    assert SQL.count("revoke all on function") == 2
    assert "returns uuid language plpgsql" in SQL


def test_the_function_checks_every_field_and_limits_how_often():
    body = SQL[SQL.index("create or replace function public.ggongbab_submit_tip"):SQL.index("revoke all on function public.ggongbab_submit_tip")]
    honeypot = body.index("if btrim(coalesce(p_hp, '')) <> '' then\n    return gen_random_uuid();")
    assert honeypot < body.index("raise exception 'TIP_INVALID'") < body.index("insert into public.ggongbab_tip_rate")
    for rule in ("char_length(v_title) not between 2 and 80", "char_length(v_place) not between 1 and 80",
                 "p_event_date not between today - 1 and today + 60", "char_length(v_time) > 40",
                 "char_length(v_food) > 120", "char_length(v_details) > 1000", "char_length(v_link) > 300",
                 "v_link !~ '^https?://[^[:space:]]+$'", "today date := (now() at time zone 'Asia/Seoul')::date"):
        assert rule in body, rule
    assert "if recorded > 5 then\n    raise exception 'TIP_RATE_LIMITED';" in body
    assert "where created_at > now() - interval '1 day') >= 60 then\n    raise exception 'TIP_RATE_LIMITED';" in body
    assert "delete from public.ggongbab_tip_rate where window_start < now() - interval '1 day';" in body
    assert body.rstrip().endswith("return tip_id;\nend;\n$$;")


def test_photos_go_to_a_private_bucket_insert_only_for_a_fresh_tip():
    assert ("values ('ggongbab-tip-images', 'ggongbab-tip-images', false, 5242880, "
            "array['image/jpeg', 'image/png', 'image/webp'])") in SQL
    assert "on conflict (id) do update set public = false" in SQL
    policies = statement(r"create policy (\w+) on storage\.objects for (\w+) to ([a-z_, ]+)\s")
    assert policies == [("ggongbab_tip_images_insert", "insert", "anon, authenticated"),
                        ("ggongbab_tip_images_backend", "all", "service_role")]
    assert ("with check (bucket_id = 'ggongbab-tip-images' and public.ggongbab_tip_upload_allowed(name));") in SQL
    check = SQL[SQL.index("create or replace function public.ggongbab_tip_upload_allowed"):SQL.index("revoke all on function public.ggongbab_tip_upload_allowed")]
    assert r"'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/[123]\.(jpg|png|webp)$'" in check
    assert "t.status = 'new'" in check and "t.created_at > now() - interval '15 minutes'" in check
    assert "o.bucket_id = 'ggongbab-tip-images' and o.name like folder || '/%') < 3;" in check
    # The name is checked before it is cast, so a bad name is refused rather than an error.
    assert check.index("return false;") < check.index("folder::uuid")


def test_the_page_script_uses_only_the_public_paths():
    for forbidden in ("SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY", "service_role", "ggongbab_tips'",
                      ".innerHTML", "eval(", "getPublicUrl", "createSignedUrl"):
        assert forbidden not in JS, forbidden
    assert re.findall(r"storage\.from\(BUCKET\)\.(\w+)\(", JS) == ["upload"]     # never read, list or remove photos
    assert re.findall(r"var (SUBMIT|BOARD|BUCKET) = '([^']+)'", JS) == [
        ("SUBMIT", "ggongbab_submit_tip"), ("BOARD", "ggongbab_tip_board"), ("BUCKET", "ggongbab-tip-images")]
    assert re.findall(r"\.rpc\(([^,]+),", JS) == ["SUBMIT"]
    assert re.findall(r"\.from\(([A-Z]+)\)", JS) == ["BUCKET", "BOARD"]
    assert not re.search(r"\.(insert|update|upsert|delete)\s*\(", JS)
    assert "upsert: false" in JS
    board = re.search(r"var BOARD_COLUMNS = '([^']+)'", JS)[1].split(",")
    assert board == columns()["ggongbab_tip_board"]
    # The same pinned client build as the public feed, with its integrity hash.
    feed = (ROOT / "js/ggongbab-public-feed.js").read_text(encoding="utf-8")
    assert re.search(r"var SDK_URL = '([^']+)'", JS)[1] == re.search(r"var SDK_URL = '([^']+)'", feed)[1]
    assert re.search(r"var SDK_INTEGRITY = '(sha384-[^']+)'", JS)[1] == re.search(r"script\.integrity = '(sha384-[^']+)'", feed)[1]
    # The page limits match the function's.
    for name, low, high in (("title", 2, 80), ("place", 1, 80), ("time_text", 0, 40), ("food", 0, 120), ("details", 0, 1000)):
        assert re.search(rf"{name}: \{{ input: '\w+', error: '\w+', min: {low}, max: {high},", JS), name
    assert "var MAX_PHOTOS = 3;" in JS and "var MAX_BYTES = 5 * 1024 * 1024;" in JS


def test_the_page_is_lab_only_and_never_republishes_photos():
    assert '<meta name="robots" content="noindex, nofollow" />' in PAGE
    assert PAGE.index('<script src="js/ggongbab-public-config.js"></script>') < PAGE.index('<script src="js/ggongbab-tips.js"></script>')
    assert 'id="tipHp"' in PAGE and 'tabindex="-1"' in PAGE
    assert 'accept="image/jpeg,image/png,image/webp"' in PAGE
    # The board renders text facts only: no image element is ever built from a row.
    assert "createElement('img')" in JS and JS.count("createElement('img')") == 1     # the local preview only
    assert "img.src = photo.url;" in JS
