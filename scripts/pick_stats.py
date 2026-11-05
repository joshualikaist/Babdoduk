# -*- coding: utf-8 -*-
"""Backend side of 오늘 뭐 먹지's taste counts (supabase/migrations/010_pick_stats.sql).

    python scripts/pick_stats.py seed    # add every dish the machine can draw with zero counts
    python scripts/pick_stats.py check   # how many dishes are counted and the totals

The pool is scripts/page_content.py pick_pool (the photographed delivery staples js/pick.js draws).
`seed` only inserts missing dishes (ignore-duplicates): existing counts are never touched, so it is
safe to run again after the pool changes. It needs SUPABASE_URL and SUPABASE_SECRET_KEY (environment
or the checkout's .env, never printed). Output is counts only. docs/PICK_STATS.md.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import page_content  # noqa: E402
from worldcup_stats import request, settings  # noqa: E402  (the same backend call and settings)


def pool() -> list[str]:
    return list(page_content.pick_pool())


def seed(call) -> int:
    dishes = pool()
    for start in range(0, len(dishes), 200):
        call("POST", "pick_dish_stats", [{"dish_id": d} for d in dishes[start:start + 200]],
             "resolution=ignore-duplicates,return=minimal")
    counted = call("GET", "pick_dish_stats?select=dish_id")
    missing = set(dishes) - {row["dish_id"] for row in counted or []}
    print(f"pool {len(dishes)} | counted dishes {len(counted or [])} | pool dishes missing {len(missing)}")
    return 1 if missing else 0


def check(call) -> int:
    rows = call("GET", "pick_dish_stats?select=dish_id,draws,likes,rerolls") or []
    print(f"counted dishes {len(rows)} | draws {sum(r['draws'] for r in rows)} | likes {sum(r['likes'] for r in rows)} | "
          f"rerolls {sum(r['rerolls'] for r in rows)} | pool {len(pool())}")
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
