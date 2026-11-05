"""오늘 뭐 먹지's taste counts (owner 2026-11-05, 방법 A; lab): the contract in
supabase/migrations/010_pick_stats.sql and scripts/pick_stats.py. Static reading of the SQL and a fake
server; never a live database. The page side is scripts/check_site_ui.py pick_tools."""
import re
from pathlib import Path

import page_content
import pick_stats

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "supabase/migrations/010_pick_stats.sql").read_text(encoding="utf-8")
POOL = list(page_content.pick_pool())


def statement(pattern):
    return re.findall(pattern, SQL, re.I | re.S)


def test_every_table_has_row_level_security_and_browsers_only_read_counts():
    for table in ("pick_dish_stats", "pick_secret", "pick_rate"):
        assert f"alter table public.{table} enable row level security;" in SQL, table
        assert re.search(rf"revoke all on table public\.{table} from public, anon, authenticated", SQL), table
    grants = statement(r"grant ([a-z, ]+) on table public\.(\w+) to ([a-z_, ]+);")
    browser = [(what, table) for what, table, who in grants if "anon" in who or "authenticated" in who]
    assert browser == [("select", "pick_dish_stats")]
    assert not statement(r"grant [^;]* on table public\.pick_(secret|rate)")          # never readable


def test_the_only_browser_write_is_the_checking_function():
    assert "security definer set search_path = pg_catalog, public" in SQL
    assert "grant execute on function public.pick_record(text, text) to anon, authenticated, service_role;" in SQL
    assert len(statement(r"create or replace function")) == 1
    for code in ("PICK_INVALID_SIGNAL", "PICK_UNKNOWN_DISH", "PICK_RATE_LIMITED"):
        assert f"raise exception '{code}'" in SQL, code
    assert "p_signal not in ('draw', 'like', 'reroll')" in SQL
    assert "if recorded > 120 then" in SQL and "interval '1 day'" in SQL
    # One signal moves one count of one dish by one.
    assert re.search(r"draws = draws \+ \(p_signal = 'draw'\)::int,\s+likes = likes \+ \(p_signal = 'like'\)::int,\s+"
                     r"rerolls = rerolls \+ \(p_signal = 'reroll'\)::int", SQL)


def test_no_identity_or_free_text_is_kept():
    stored = statement(r"create table if not exists public\.(\w+) \((.*?)\n\);")
    columns = {table: [c for c in re.findall(r"^\s+(\w+) ", body, re.M) if c != "primary"] for table, body in stored}
    assert columns["pick_dish_stats"] == ["dish_id", "draws", "likes", "rerolls", "updated_at"]
    assert columns["pick_rate"] == ["client_hash", "window_start", "signals"]
    assert "extensions.digest((select salt from public.pick_secret) || current_date::text || forwarded" in SQL
    assert re.search(r"values \(client, date_trunc\('hour', now\(\)\), 1\)", SQL)


class Fake:
    def __init__(self, counted=()):
        self.rows = {d: {"dish_id": d, "draws": 9, "likes": 4, "rerolls": 3} for d in counted}
        self.calls = []

    def __call__(self, method, path, body=None, prefer=""):
        self.calls.append((method, path, prefer))
        if method == "POST" and path == "pick_dish_stats":
            assert prefer.startswith("resolution=ignore-duplicates")
            for row in body:
                assert set(row) == {"dish_id"}                       # never a count
                self.rows.setdefault(row["dish_id"], {"dish_id": row["dish_id"], "draws": 0, "likes": 0, "rerolls": 0})
            return None
        if path.startswith("pick_dish_stats"):
            return list(self.rows.values())
        raise AssertionError(path)


def test_the_pool_is_the_photographed_staples_the_page_draws():
    assert 20 <= len(POOL) == len(set(POOL))
    carried = (ROOT / "js/pick-photos.js").read_text(encoding="utf-8")
    assert all(f'"{dish}":' in carried for dish in POOL)


def test_seed_adds_missing_dishes_and_keeps_existing_counts(capsys):
    fake = Fake(counted=POOL[:3])
    assert pick_stats.main(["seed"], call=fake) == 0
    assert set(fake.rows) == set(POOL) and fake.rows[POOL[0]]["likes"] == 4
    assert sum(1 for c in fake.calls if c[0] == "POST") == -(-len(POOL) // 200)
    assert capsys.readouterr().out.strip() == f"pool {len(POOL)} | counted dishes {len(POOL)} | pool dishes missing 0"


def test_check_prints_counts_only(capsys):
    assert pick_stats.main(["check"], call=Fake(counted=POOL[:2])) == 0
    out = capsys.readouterr().out
    assert out.startswith("counted dishes 2 | draws 18 | likes 8 | rerolls 6") and "sb_" not in out
