# -*- coding: utf-8 -*-
"""Backend side of the 먹방 월드컵 statistics (supabase/migrations/005_worldcup_stats.sql).

    python scripts/worldcup_stats.py seed    # add every pool dish (data/content/worldcup.json) with zero counts
    python scripts/worldcup_stats.py check   # how many dishes are counted and how many games were recorded

`seed` only inserts missing dishes (ignore-duplicates): existing counts are never touched, so it is
safe to run again after the pool grows. It needs SUPABASE_URL and SUPABASE_SECRET_KEY (environment
or the checkout's .env, never printed). Output is counts only. docs/WORLDCUP_STATS.md.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POOL = ROOT / "data" / "content" / "worldcup.json"


def settings(env: dict | None = None) -> tuple[str, str]:
    env = dict(os.environ if env is None else env)
    dotenv = ROOT / ".env"
    if dotenv.is_file():                       # the environment wins over the file
        for line in dotenv.read_text(encoding="utf-8").splitlines():
            name, sep, value = line.strip().partition("=")
            if sep and not name.startswith("#"):
                env.setdefault(name.strip(), value.strip().strip('"').strip("'"))
    url, key = env.get("SUPABASE_URL", "").rstrip("/"), env.get("SUPABASE_SECRET_KEY", "")
    if not url.startswith("https://") or not key:
        raise SystemExit("SUPABASE_URL / SUPABASE_SECRET_KEY missing")
    return url, key


def request(url: str, key: str, method: str, path: str, body=None, prefer: str = ""):
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Accept": "application/json",
               "Content-Type": "application/json"}
    if prefer:
        headers["Prefer"] = prefer
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(f"{url}/rest/v1/{path}", data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"{method} {path.split('?')[0]}: HTTP {exc.code}") from None   # no response text
    return json.loads(raw) if raw else None


def pool() -> list[str]:
    return json.loads(POOL.read_text(encoding="utf-8"))["dishes"]


def seed(call) -> int:
    dishes = pool()
    for start in range(0, len(dishes), 200):
        call("POST", "worldcup_dish_stats", [{"dish_id": d} for d in dishes[start:start + 200]],
             "resolution=ignore-duplicates,return=minimal")
    counted = call("GET", "worldcup_dish_stats?select=dish_id")
    missing = set(dishes) - {row["dish_id"] for row in counted or []}
    print(f"pool {len(dishes)} | counted dishes {len(counted or [])} | pool dishes missing {len(missing)}")
    return 1 if missing else 0


def check(call) -> int:
    rows = call("GET", "worldcup_dish_stats?select=dish_id,matches,wins,entries,titles") or []
    totals = call("GET", "worldcup_totals?select=games") or [{}]
    print(f"counted dishes {len(rows)} | games {totals[0].get('games', 0)} | "
          f"matches {sum(r['matches'] for r in rows) // 2} | pool {len(pool())}")
    return 0


def main(argv=None, call=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=["seed", "check"])
    args = parser.parse_args(argv)
    if call is None:
        url, key = settings()
        call = lambda method, path, body=None, prefer="": request(url, key, method, path, body, prefer)
    return seed(call) if args.command == "seed" else check(call)


if __name__ == "__main__":
    sys.exit(main())
