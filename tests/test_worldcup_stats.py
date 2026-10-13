"""먹방 월드컵 stage 2 (lab): the statistics contract in supabase/migrations/005_worldcup_stats.sql and
scripts/worldcup_stats.py. Static reading of the SQL and a fake server; never a live database."""
import json
import re
from pathlib import Path

import pytest

import worldcup_stats

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "supabase/migrations/005_worldcup_stats.sql").read_text(encoding="utf-8")
POOL = json.loads((ROOT / "data/content/worldcup.json").read_text(encoding="utf-8"))["dishes"]


def statement(pattern):
    return re.findall(pattern, SQL, re.I | re.S)


def test_every_table_has_row_level_security_and_browsers_only_read_counts():
    for table in ("worldcup_dish_stats", "worldcup_totals", "worldcup_secret", "worldcup_rate"):
        assert f"alter table public.{table} enable row level security;" in SQL, table
        assert re.search(rf"revoke all on table public\.{table} from public, anon, authenticated", SQL), table
    grants = statement(r"grant ([a-z, ]+) on table public\.(\w+) to ([a-z_, ]+);")
    browser = [(what, table) for what, table, who in grants if "anon" in who or "authenticated" in who]
    assert browser == [("select", "worldcup_dish_stats"), ("select", "worldcup_totals")]
    assert not statement(r"grant [^;]* on table public\.worldcup_(secret|rate)")      # never readable


def test_the_only_browser_write_is_the_validating_function():
    assert "security definer set search_path = pg_catalog, public" in SQL
    assert "grant execute on function public.worldcup_record_game(integer, jsonb) to anon, authenticated, service_role;" in SQL
    assert len(statement(r"create or replace function")) == 1
    for code in ("WORLDCUP_INVALID_SIZE", "WORLDCUP_INVALID_MATCHES", "WORLDCUP_INVALID_MATCH",
                 "WORLDCUP_INVALID_BRACKET", "WORLDCUP_UNKNOWN_DISH", "WORLDCUP_RATE_LIMITED"):
        assert f"raise exception '{code}'" in SQL, code
    assert "if recorded > 30 then" in SQL and "interval '1 day'" in SQL


def test_no_identity_or_free_text_is_kept():
    stored = statement(r"create table if not exists public\.(\w+) \((.*?)\n\);")
    columns = {table: [c for c in re.findall(r"^\s+(\w+) ", body, re.M) if c != "primary"] for table, body in stored}
    assert columns["worldcup_dish_stats"] == ["dish_id", "matches", "wins", "entries", "titles", "updated_at"]
    assert columns["worldcup_totals"] == ["singleton", "games", "updated_at"]
    assert columns["worldcup_rate"] == ["client_hash", "window_start", "games"]
    # The address only ever enters a salted digest with the day; it is never stored as such.
    assert "extensions.digest((select salt from public.worldcup_secret) || current_date::text || forwarded" in SQL
    assert re.search(r"values \(client, date_trunc\('hour', now\(\)\), 1\)", SQL)    # only the digest is stored


class Fake:
    def __init__(self, counted=()):
        self.rows = {d: {"dish_id": d, "matches": 9, "wins": 4, "entries": 3, "titles": 1} for d in counted}
        self.calls = []

    def __call__(self, method, path, body=None, prefer=""):
        self.calls.append((method, path, prefer))
        if method == "POST" and path == "worldcup_dish_stats":
            assert prefer.startswith("resolution=ignore-duplicates")
            for row in body:
                assert set(row) == {"dish_id"}                       # never a count
                self.rows.setdefault(row["dish_id"], {"dish_id": row["dish_id"], "matches": 0, "wins": 0,
                                                      "entries": 0, "titles": 0})
            return None
        if path.startswith("worldcup_dish_stats"):
            return list(self.rows.values())
        if path.startswith("worldcup_totals"):
            return [{"games": 7}]
        raise AssertionError(path)


def test_seed_adds_missing_dishes_and_keeps_existing_counts(capsys):
    fake = Fake(counted=POOL[:3])
    assert worldcup_stats.main(["seed"], call=fake) == 0
    assert set(fake.rows) == set(POOL) and fake.rows[POOL[0]]["matches"] == 9
    assert sum(1 for c in fake.calls if c[0] == "POST") == -(-len(POOL) // 200)
    assert capsys.readouterr().out.strip() == f"pool {len(POOL)} | counted dishes {len(POOL)} | pool dishes missing 0"


def test_check_prints_counts_only(capsys):
    assert worldcup_stats.main(["check"], call=Fake(counted=POOL[:2])) == 0
    out = capsys.readouterr().out
    assert out.startswith("counted dishes 2 | games 7 | matches 9") and "sb_" not in out


def test_settings_read_the_environment_first_and_refuse_a_missing_key():
    assert worldcup_stats.settings({"SUPABASE_URL": "https://x.example.co/", "SUPABASE_SECRET_KEY": "k"}) == ("https://x.example.co", "k")
    with pytest.raises(SystemExit):
        worldcup_stats.settings({"SUPABASE_URL": "http://insecure", "SUPABASE_SECRET_KEY": "k"})
