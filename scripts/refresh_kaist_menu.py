# -*- coding: utf-8 -*-
"""Fetch KAIST official cafeteria HTML into data/kaist-menu/.

Writes, for the current KST week (Monday-Sunday):
  data/kaist-menu/YYYY-MM-DD.json   one validated daily payload per date that has a menu
  data/kaist-menu/latest.json       TODAY's payload only (compatibility for home/choose/hub)
  data/kaist-menu/week.json         a small index: which dates have a menu and how many places

Bounded collection (docs/KAIST_MENU.md): the first run of a week (or --full-week) fetches all
seven days; later runs refresh today and the remaining days of the week only. 8 restaurants per
date, one request each, a short pause between requests, and a failure breaker. A known-good
daily file is never replaced by an empty or failed result.
"""
from __future__ import annotations

import argparse
import html as htmlmod
import json
import os
import re
import ssl
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "kaist-menu"
UA = "BabdodukMenu/1.0 (+https://github.com/joshualikaist/Babdoduk)"
KST = timezone(timedelta(hours=9))
TIMEZONE = "Asia/Seoul"
BASE = "https://www.kaist.ac.kr/kr/html/campus/053001.html"

# Day states. AVAILABLE: a validated menu for that date. NOT_PUBLISHED_YET: every restaurant
# answered with an empty official table. FETCH_FAILED: no usable answer and nothing saved.
# STALE_SAVED_DATA: this run could not confirm the day, so the previously saved file stays.
AVAILABLE = "AVAILABLE"
NOT_PUBLISHED_YET = "NOT_PUBLISHED_YET"
FETCH_FAILED = "FETCH_FAILED"
STALE_SAVED_DATA = "STALE_SAVED_DATA"

REQUEST_PAUSE_SECONDS = 0.25
MAX_CONSECUTIVE_FAILURES = 8        # one date's worth of restaurants: the site is down, stop
RUN_BUDGET_SECONDS = 480            # later dates keep their saved files

# Codes taken from official ActFodlst('...') on 053001.html — not guessed.
RESTAURANTS = [
    {"id": "fclt", "name": "카이마루 N11", "building": "N11"},
    {"id": "west", "name": "서맛골 W2", "building": "W2"},
    {"id": "east1", "name": "동맛골 학생식당 E5", "building": "E5"},
    {"id": "east2", "name": "동맛골 교직원식당 E5", "building": "E5"},
    {"id": "emp", "name": "교수회관 N6", "building": "N6"},
    {"id": "icc", "name": "문지캠퍼스", "building": "문지"},
    {"id": "hawam", "name": "화암 기숙사", "building": "화암"},
    {"id": "seoul", "name": "서울캠퍼스", "building": "서울"},
]
MEALS = ("breakfast", "lunch", "dinner")

NOTE = re.compile(r"^(\*|안녕하세요|운영시간|금액|알레르기|인스타|주말)")
ALLERGEN = re.compile(r"^\(?\d+(?:\s*,\s*\d+)*\)?$")
PRICE = re.compile(r"(\d{1,3}(?:,\d{3})*\s*원)")
# An explicit calorie line, not a suffix match inside a thousands-separated
# number, allergen list, price, or promotional sentence.
KCAL = re.compile(r"^(?:(?:총\s*칼로리|총\s*열량|칼로리|열량)\s*[:：]?\s*)?"
                  r"(\d{1,3}(?:,\d{3})+|\d+)\s*kcal\s*$", re.I)
BR = re.compile(r"<br\s*/?>", re.I)
TAG = re.compile(r"<[^>]+>")


class MenuParseError(ValueError):
    """The official page no longer has the menu table: an upstream change, never 'no meals'."""


def now_kst() -> datetime:
    return datetime.now(KST)


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=25, context=ctx) as res:
        return res.read().decode("utf-8", "replace")


def clean_line(raw: str) -> str:
    text = TAG.sub(" ", htmlmod.unescape(raw or ""))
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    text = text.replace("<!--", " ").replace("-->", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_cell(raw: str) -> dict:
    chunks = [clean_line(part) for part in BR.split(raw)]
    items = []
    price = ""
    kcal = ""
    hours = ""
    for line in chunks:
        if not line or NOTE.match(line) or ALLERGEN.match(line):
            continue
        if line in {"-->", "<!--"} or line.startswith("-->"):
            continue
        price_m = PRICE.search(line)
        if price_m and not price:
            price = price_m.group(1).replace(" ", "")
        kcal_m = KCAL.fullmatch(line)
        if kcal_m:
            kcal = f"{int(kcal_m.group(1).replace(',', ''))} kcal"
            continue
        if re.fullmatch(r"조식|중식|석식", line.split("(")[0].strip()):
            continue
        if re.search(r"\d+:\d+", line) and not items:
            hours = line
            continue
        if line.endswith("미운영") or "운영없음" in line.replace(" ", ""):
            continue
        if price_m and PRICE.sub("", line).strip() in {"", "원"}:
            continue
        if len(line) < 2:
            continue
        items.append(line)
    return {"hours": hours, "items": items[:16], "price": price, "kcal": kcal}


def menu_cells(page: str) -> Optional[list]:
    """The three meal cells of the official menu table, or None when the table is missing."""
    page = re.sub(r"<!--.*?-->", " ", page, flags=re.S)
    tables = re.findall(r"<table[^>]*class=\"table\"[\s\S]*?</table>", page, re.I)
    if not tables:
        return None
    return re.findall(r"<td[^>]*>([\s\S]*?)</td>", tables[0], re.I)


def parse_meals(page: str) -> dict:
    tds = menu_cells(page)
    if tds is None:
        return {}
    meals = {}
    for idx, key in enumerate(MEALS):
        meals[key] = parse_cell(tds[idx]) if idx < len(tds) else {"items": [], "price": "", "kcal": ""}
    return meals


def fetch_restaurant(code: str, date_s: str, fetcher: Callable[[str], str] = None) -> dict:
    """One official page. An unpublished date still renders the table with three empty cells;
    a page without that table is an upstream change and raises instead of meaning 'no meals'."""
    url = BASE + "?" + urllib.parse.urlencode({"dvs_cd": code, "stt_dt": date_s})
    page = (fetcher or fetch)(url)
    cells = menu_cells(page)
    if cells is None or len(cells) < len(MEALS):
        raise MenuParseError("menu table missing")
    return parse_meals(page)


# --- week ------------------------------------------------------------------------------
def kst_today(now: Optional[datetime] = None) -> date:
    """Today in KST, whatever the host timezone is."""
    now = now or now_kst()
    if now.tzinfo is None:
        raise ValueError("an aware datetime is required")
    return now.astimezone(KST).date()


def week_of(day: date) -> list[date]:
    """Monday to Sunday of the week containing `day`."""
    monday = day - timedelta(days=day.weekday())
    return [monday + timedelta(days=offset) for offset in range(7)]


def day_path(out: Path, day: date) -> Path:
    return out / f"{day.isoformat()}.json"


def has_menu(resto: dict) -> bool:
    return any(((resto or {}).get(meal) or {}).get("items") for meal in MEALS)


def read_day(out: Path, day: date) -> Optional[dict]:
    """A saved daily payload that is valid for exactly this date, else None."""
    try:
        data = json.loads(day_path(out, day).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("date") != day.isoformat():
        return None
    restaurants = data.get("restaurants")
    if not isinstance(restaurants, list) or not any(has_menu(row) for row in restaurants):
        return None
    return data


def read_week(out: Path) -> Optional[dict]:
    try:
        data = json.loads((out / "week.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".kaist-", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def dumps(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


class Budget:
    """Stops a run that is not getting answers: consecutive failures or elapsed time."""

    def __init__(self, clock: Callable[[], float] = time.monotonic, seconds: float = RUN_BUDGET_SECONDS,
                 max_failures: int = MAX_CONSECUTIVE_FAILURES):
        self.clock, self.deadline, self.max_failures = clock, clock() + seconds, max_failures
        self.consecutive = 0
        self.requests = 0

    def exhausted(self) -> bool:
        return self.consecutive >= self.max_failures or self.clock() >= self.deadline

    def record(self, ok: bool) -> None:
        self.requests += 1
        self.consecutive = 0 if ok else self.consecutive + 1


def collect_day(day: date, *, fetcher: Callable[[str], str], budget: Budget,
                pause: Callable[[], None] = lambda: time.sleep(REQUEST_PAUSE_SECONDS)) -> tuple[list, dict]:
    """Fetch one date for every restaurant. Returns (restaurants with a menu, coverage)."""
    date_s = day.isoformat()
    fetched, failed, restaurants = [], [], []
    for row in RESTAURANTS:
        if budget.exhausted():
            failed.append(row["id"])
            continue
        try:
            meals = fetch_restaurant(row["id"], date_s, fetcher)
        except Exception as exc:  # noqa: BLE001 - class name only; public workflow logs
            print(f"[warn] kaist {date_s} {row['id']}: {exc.__class__.__name__}")
            failed.append(row["id"])
            budget.record(False)
        else:
            fetched.append(row["id"])
            budget.record(True)
            entry = {"id": row["id"], "name": row["name"], "building": row["building"]}
            entry.update({meal: meals.get(meal) or {} for meal in MEALS})
            if has_menu(entry):
                restaurants.append(entry)
        if budget.requests and not budget.exhausted():
            pause()
    return restaurants, {"requested": len(RESTAURANTS), "fetched": len(fetched), "failed": failed}


def decide(day: date, restaurants: list, coverage: dict, saved: Optional[dict],
           fetched_at: datetime) -> tuple[str, Optional[dict]]:
    """The day's state and the payload to write (None keeps whatever is saved)."""
    failed = coverage["failed"]
    if restaurants:
        carried = []
        if failed and saved:
            by_id = {row.get("id"): row for row in saved.get("restaurants", [])}
            for rid in failed:
                if rid in by_id and has_menu(by_id[rid]):
                    restaurants = restaurants + [by_id[rid]]
                    carried.append(rid)
        order = {row["id"]: idx for idx, row in enumerate(RESTAURANTS)}
        restaurants = sorted(restaurants, key=lambda row: order.get(row.get("id"), len(order)))
        payload = {
            "date": day.isoformat(),
            "dateLabel": f"{day.month}월 {day.day}일",
            "fetchedAt": fetched_at.isoformat(timespec="seconds"),
            "source": BASE,
            "status": AVAILABLE,
            "coverage": dict(coverage, carried=carried),
            "restaurants": restaurants,
        }
        return AVAILABLE, payload
    if saved:
        # Nothing new that proves the saved menu wrong: keep it, and say it was not re-confirmed.
        return STALE_SAVED_DATA, None
    if failed:
        return FETCH_FAILED, None
    return NOT_PUBLISHED_YET, None


def plan(today: date, week_index: Optional[dict], full_week: bool = False) -> list[date]:
    """First run of a week (or a manual full refresh): all seven days. Otherwise today and
    the rest of the week; completed past days are not fetched again."""
    week = week_of(today)
    if full_week or not week_index or week_index.get("weekStart") != week[0].isoformat():
        return week
    return [day for day in week if day >= today]


def week_entry(out: Path, day: date, status: Optional[str], previous: Optional[dict]) -> dict:
    """One day of week.json. `status` is this run's decision, or None when the day was not
    fetched (a completed past day): then the saved file and the previous index decide."""
    saved = read_day(out, day)
    if status is None:
        before = (previous or {}).get("status")
        if saved:
            status = before if before in (AVAILABLE, STALE_SAVED_DATA) else AVAILABLE
        else:
            status = before if before in (NOT_PUBLISHED_YET, FETCH_FAILED) else NOT_PUBLISHED_YET
    count = sum(1 for row in (saved or {}).get("restaurants", []) if has_menu(row))
    return {"date": day.isoformat(), "available": saved is not None, "restaurantCount": count,
            "status": status, "fetchedAt": (saved or {}).get("fetchedAt")}


def refresh(out: Path = OUT, *, now: Optional[datetime] = None, fetcher: Callable[[str], str] = fetch,
            full_week: bool = False, budget: Optional[Budget] = None,
            pause: Callable[[], None] = lambda: time.sleep(REQUEST_PAUSE_SECONDS)) -> dict:
    """Refresh the current week. Returns a summary; writes dated files, latest.json and week.json."""
    now = now or now_kst()
    today = kst_today(now)
    week = week_of(today)
    budget = budget or Budget()
    previous_index = read_week(out)
    same_week = bool(previous_index and previous_index.get("weekStart") == week[0].isoformat())
    previous_days = {row.get("date"): row for row in (previous_index or {}).get("days", [])} if same_week else {}
    statuses: dict[str, str] = {}
    for day in plan(today, previous_index, full_week):
        saved = read_day(out, day)
        restaurants, coverage = collect_day(day, fetcher=fetcher, budget=budget, pause=pause)
        status, payload = decide(day, restaurants, coverage, saved, now)
        if payload is not None:
            atomic_write(day_path(out, day), dumps(payload))
        statuses[day.isoformat()] = status
        print(f"kaist {day.isoformat()} {status} restaurants={len((payload or saved or {}).get('restaurants', []))}"
              f" fetched={coverage['fetched']}/{coverage['requested']}")
    today_saved = read_day(out, today)
    if today_saved is not None:
        # latest.json keeps meaning TODAY: byte-identical to today's dated file.
        text = day_path(out, today).read_text(encoding="utf-8")
        latest = out / "latest.json"
        if not latest.exists() or latest.read_text(encoding="utf-8") != text:
            atomic_write(latest, text)
    index = {
        "weekStart": week[0].isoformat(),
        "weekEnd": week[-1].isoformat(),
        "generatedAt": now.astimezone(KST).isoformat(timespec="seconds"),
        "timezone": TIMEZONE,
        "days": [week_entry(out, day, statuses.get(day.isoformat()), previous_days.get(day.isoformat()))
                 for day in week],
    }
    atomic_write(out / "week.json", dumps(index))
    return {"today": today.isoformat(), "todayAvailable": today_saved is not None,
            "requests": budget.requests, "statuses": statuses}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Refresh this week's KAIST cafeteria menus.")
    parser.add_argument("--full-week", action="store_true",
                        help="fetch Monday-Sunday again, including completed past days")
    args = parser.parse_args(argv)
    summary = refresh(full_week=args.full_week)
    print(f"kaist requests={summary['requests']} today={summary['today']}")
    if not summary["todayAvailable"]:
        print("[warn] kaist has no usable menu for today; keeping previous latest.json")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
