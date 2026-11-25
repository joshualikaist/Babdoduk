# -*- coding: utf-8 -*-
"""How the site is used, as totals only (owner 2026-11-20: "내 사이트를 언제 제일 많이 이용하는지, 어디
콘텐츠가 반응이 좋은지. 별 누르는 꽁밥이 무엇인지"; docs/USAGE_STATS.md).

    python scripts/usage_stats.py report [--days 28] [--site prod|lab|all] [--out FILE]
    python scripts/usage_stats.py pages     # let every page of this checkout be counted (visit_pages)

Run on the operations PC with the backend key, like scripts/pick_stats.py: SUPABASE_URL and
SUPABASE_SECRET_KEY come from the environment or the checkout's .env and are never printed.

What it reads, and nothing else (READS below; tests/test_usage_stats.py holds it to that):
  visit_counts                          hour, site, page, lang, device, views (018: no person in it)
  saved_events                          event_id, saved_at - never the account or the saved snapshot
  saved_places                          place_id, status - never the account or the memo
  push_devices                          events - never the device address or its keys
  pick_dish_stats, worldcup_dish_stats  per-dish counts, already anonymous
Names come from this checkout's public files (data/ggongbab, data/foods, data/places, data/content).

A number that comes from people's own saves (stars, alerts, 먹킷리스트) and is below MIN_CELL is shown as
"5 미만", so a small count never points at someone (privacy policy, 통계). Visit counts hold no person and
are shown as they are. The report is plain Korean Markdown.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

KST = timezone(timedelta(hours=9))
MIN_CELL = 5
PAGE_SIZE = 1000
SITES = {"prod": ("www.babdodukms.com", "babdoduk.vercel.app"), "lab": ("babdoduk-lab.vercel.app",)}
SITES["all"] = SITES["prod"] + SITES["lab"]
WEEKDAYS = "월화수목금토일"
DEVICES = {"phone": "휴대폰", "tablet": "태블릿", "computer": "컴퓨터"}
LANGS = {"ko": "한국어", "en": "영어"}
PLACE_STATUS = {"want": "가고 싶어", "been": "가봤어", "again": "또 갈래"}
READS = {
    "visit_counts": {"hour", "site", "page", "lang", "device", "views"},
    "saved_events": {"event_id", "saved_at"},
    "saved_places": {"place_id", "status"},
    "push_devices": {"events"},
    "pick_dish_stats": {"dish_id", "draws", "likes", "rerolls"},
    "worldcup_dish_stats": {"dish_id", "matches", "wins", "entries", "titles"},
}


# --- reading ----------------------------------------------------------------------------------------
def rows(call, table: str, columns: str, filters: str = "", order: str = "") -> list[dict]:
    """Every row of one read, page by page; refuses a column outside READS."""
    asked = set(columns.split(","))
    if table not in READS or not asked <= READS[table]:
        raise ValueError(f"not allowed: {table}({columns})")
    out, offset = [], 0
    while True:
        path = f"{table}?select={columns}{filters}&order={order or columns.split(',')[0] + '.asc'}&limit={PAGE_SIZE}&offset={offset}"
        page = call("GET", path) or []
        out.extend(page)
        if len(page) < PAGE_SIZE:
            return out
        offset += PAGE_SIZE


def when(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(KST)


# --- names from the public files ----------------------------------------------------------------------
def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def event_names(root: Path = ROOT) -> dict:
    """event id -> (title, KST start, food type label) from the published feed and its archive."""
    labels = read_json(root / "data/content/labels.json", {}).get("freeFood", {})
    names = {}
    for name in ("data/ggongbab/archive/index.json", "data/ggongbab/latest.json"):
        for ev in read_json(root / name, {}).get("events", []):
            food = (ev.get("food") or {}).get("type") or ""
            start = ev.get("startAt")
            names[str(ev.get("id"))] = (ev.get("title") or "", when(start) if start else None,
                                        (labels.get(food) or {}).get("ko", ""))
    return names


def page_names(root: Path = ROOT) -> dict:
    out = {}
    for page in sorted(root.glob("*.html")):
        title = re.search(r"<title>(.*?)</title>", page.read_text(encoding="utf-8"), re.S)
        out[page.stem] = re.sub(r"\s+", " ", title.group(1)).strip() if title else page.stem
    return out


def dish_names(root: Path = ROOT) -> dict:
    out = {}
    for pack in sorted((root / "data/foods/packs").glob("*.json")):
        for item in read_json(pack, {}).get("items", []):
            out[item.get("id")] = item.get("nameKo") or item.get("id")
    return out


def place_names(root: Path = ROOT) -> dict:
    out = {r.get("id"): r.get("name") for r in read_json(root / "data/content/labels.json", {}).get("restaurants", [])}
    for place in read_json(root / "data/places/latest.json", {}).get("places", []):
        out[place.get("id")] = place.get("name") or place.get("id")
    return out


# --- writing ---------------------------------------------------------------------------------------------
def shown(n: int, people: bool = True) -> str:
    return f"{MIN_CELL} 미만" if people and n < MIN_CELL else f"{n:,}"


def bars(counter: Counter, keys, label, people: bool) -> list[str]:
    top = max([counter.get(k, 0) for k in keys] + [1])
    lines = []
    for k in keys:
        n = counter.get(k, 0)
        bar = "█" * round(12 * n / top) if not (people and n < MIN_CELL) else ""
        lines.append(f"| {label(k)} | {shown(n, people)} | {bar} |")
    return ["| 구분 | 수 | |", "| --- | ---: | --- |"] + lines


def ranked(counter: Counter, label, people: bool, limit: int) -> list[str]:
    lines = ["| 순위 | 항목 | 수 |", "| ---: | --- | ---: |"]
    for i, (key, n) in enumerate(counter.most_common(limit), 1):
        lines.append(f"| {i} | {label(key)} | {shown(n, people)} |")
    return lines if len(lines) > 2 else ["아직 없어요."]


def visits_section(call, since: datetime, site: str, pages: dict) -> list[str]:
    out = ["## 1. 방문 수", "", "페이지를 연 횟수예요. 한 사람이 여러 번 열면 여러 번 세요. 누가 봤는지는 남지 않아요.", ""]
    try:
        data = rows(call, "visit_counts", "hour,site,page,lang,device,views",
                    f"&hour=gte.{since.astimezone(timezone.utc).isoformat()}",
                    "hour.asc,site.asc,page.asc,lang.asc,device.asc")
    except SystemExit as exc:
        return out + [f"읽지 못했어요 ({exc}). 018을 적용했는지 확인해 주세요.", ""]
    data = [r for r in data if r.get("site") in SITES[site]]
    if not data:
        return out + ["아직 센 기록이 없어요. 018을 적용하고 사이트에 올린 뒤부터 쌓여요.", ""]
    hours, days, by_page, by_device, by_lang = Counter(), Counter(), Counter(), Counter(), Counter()
    for r in data:
        at, n = when(r["hour"]), int(r.get("views") or 0)
        hours[at.hour] += n
        days[at.weekday()] += n
        by_page[r["page"]] += n
        by_device[r["device"]] += n
        by_lang[r["lang"]] += n
    out += [f"모두 {sum(hours.values()):,}번 열렸어요.", "", "### 시간대별", ""]
    out += bars(hours, range(24), lambda h: f"{h}시", people=False)
    out += ["", "### 요일별", ""] + bars(days, range(7), lambda d: WEEKDAYS[d], people=False)
    out += ["", "### 페이지별", ""] + ranked(by_page, lambda p: pages.get(p, p), people=False, limit=20)
    out += ["", "### 기기와 언어", ""]
    out += [f"- {DEVICES.get(k, k)}: {n:,}" for k, n in by_device.most_common()]
    out += [f"- {LANGS.get(k, k)}: {n:,}" for k, n in by_lang.most_common()] + [""]
    return out


def stars_section(call, since: datetime, events: dict) -> list[str]:
    out = ["## 2. 별 누른 꽁밥", "", f"이 기간에 누른 별이에요. {MIN_CELL}개 미만은 숫자를 감춰요.", ""]
    try:
        data = rows(call, "saved_events", "event_id,saved_at", f"&saved_at=gte.{since.astimezone(timezone.utc).isoformat()}",
                    "saved_at.asc,event_id.asc")
    except SystemExit as exc:
        return out + [f"읽지 못했어요 ({exc}).", ""]
    if not data:
        return out + ["아직 없어요.", ""]
    per_event, per_food, hours, days = Counter(), Counter(), Counter(), Counter()
    for r in data:
        base = str(r["event_id"]).split("#", 1)[0]
        per_event[base] += 1
        per_food[(events.get(base) or ("", None, ""))[2] or "모름"] += 1
        at = when(r["saved_at"])
        hours[at.hour] += 1
        days[at.weekday()] += 1

    def title(eid):
        name, start, food = events.get(eid) or ("", None, "")
        if not name:
            return "제목을 찾지 못한 꽁밥"
        day = f"{start:%m/%d} {WEEKDAYS[start.weekday()]}" if start else ""
        return " · ".join(x for x in (name, day, food) if x)

    out += [f"모두 {shown(len(data))}개예요.", "", "### 많이 누른 꽁밥", ""] + ranked(per_event, title, True, 15)
    out += ["", "### 음식 종류별", ""] + ranked(per_food, str, True, 12)
    out += ["", "### 별 누른 시간대", ""] + bars(hours, range(24), lambda h: f"{h}시", people=True)
    out += ["", "### 별 누른 요일", ""] + bars(days, range(7), lambda d: WEEKDAYS[d], people=True) + [""]
    return out


def alerts_section(call, events: dict) -> list[str]:
    out = ["## 3. 알림 켠 꽁밥", "", "지금 알림이 켜진 꽁밥이에요(기기 수).", ""]
    try:
        data = rows(call, "push_devices", "events", order="events.asc")
    except SystemExit as exc:
        return out + [f"읽지 못했어요 ({exc}).", ""]
    per_event = Counter(str(e).split("#", 1)[0] for r in data for e in set(r.get("events") or []))
    label = lambda eid: (events.get(eid) or ("제목을 찾지 못한 꽁밥",))[0] or "제목을 찾지 못한 꽁밥"
    return out + [f"알림을 켠 기기는 {shown(len(data))}대예요.", ""] + ranked(per_event, label, True, 10) + [""]


def places_section(call, places: dict) -> list[str]:
    out = ["## 4. 먹킷리스트", "", "식당마다 지금 담긴 상태예요(전체 기간).", ""]
    try:
        data = rows(call, "saved_places", "place_id,status", order="place_id.asc,status.asc")
    except SystemExit as exc:
        return out + [f"읽지 못했어요 ({exc}).", ""]
    if not data:
        return out + ["아직 없어요.", ""]
    total, status = Counter(), defaultdict(Counter)
    for r in data:
        total[r["place_id"]] += 1
        status[r["place_id"]][r["status"]] += 1
    out += ["| 순위 | 식당 | 모두 | " + " | ".join(PLACE_STATUS.values()) + " |", "| ---: | --- | ---: | ---: | ---: | ---: |"]
    for i, (pid, n) in enumerate(total.most_common(15), 1):
        cells = " | ".join(shown(status[pid].get(s, 0)) for s in PLACE_STATUS)
        out.append(f"| {i} | {places.get(pid) or pid} | {shown(n)} | {cells} |")
    return out + [""]


def dishes_section(call, dishes: dict) -> list[str]:
    out = ["## 5. 메뉴 뽑기와 음식 월드컵", "", "처음부터 쌓인 숫자예요. 원래 누군지 모르게 세고 있어요.", ""]
    name = lambda d: dishes.get(d, d)
    try:
        pick = rows(call, "pick_dish_stats", "dish_id,draws,likes,rerolls")
        likes = Counter({r["dish_id"]: int(r.get("likes") or 0) for r in pick if r.get("likes")})
        out += ["### 메뉴 뽑기에서 \"이거 먹을래요\"를 많이 받은 음식", ""] + ranked(likes, name, False, 10) + [""]
    except SystemExit as exc:
        out += [f"메뉴 뽑기를 읽지 못했어요 ({exc}).", ""]
    try:
        cup = rows(call, "worldcup_dish_stats", "dish_id,matches,wins,entries,titles")
        titles = Counter({r["dish_id"]: int(r.get("titles") or 0) for r in cup if r.get("titles")})
        out += ["### 음식 월드컵 우승을 많이 한 음식", ""] + ranked(titles, name, False, 10) + [""]
    except SystemExit as exc:
        out += [f"음식 월드컵을 읽지 못했어요 ({exc}).", ""]
    return out


def report(call, days: int = 28, site: str = "prod", now: datetime | None = None, root: Path = ROOT) -> str:
    now = (now or datetime.now(KST)).astimezone(KST)
    since = (now - timedelta(days=days)).replace(minute=0, second=0, microsecond=0)
    where = {"prod": "실제 사이트", "lab": "시험 사이트", "all": "두 사이트 모두"}[site]
    events = event_names(root)
    lines = ["# 밥도둑 이용 통계", "",
             f"{since:%Y-%m-%d %H시}부터 {now:%Y-%m-%d %H시}까지 {days}일 · 방문 수는 {where} 기준 · 한국 시간", ""]
    lines += visits_section(call, since, site, page_names(root))
    lines += stars_section(call, since, events)
    lines += alerts_section(call, events)
    lines += places_section(call, place_names(root))
    lines += dishes_section(call, dish_names(root))
    return "\n".join(lines).rstrip() + "\n"


def add_pages(call, root: Path = ROOT) -> int:
    pages = sorted(p.stem for p in root.glob("*.html") if p.stem != "panel")
    call("POST", "visit_pages", [{"page": p} for p in pages], "resolution=ignore-duplicates,return=minimal")
    counted = {r["page"] for r in call("GET", "visit_pages?select=page") or []}
    missing = sorted(set(pages) - counted)
    print(f"pages {len(pages)} | counted {len(counted)} | missing {len(missing)}")
    return 1 if missing else 0


def main(argv=None, call=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=["report", "pages"])
    parser.add_argument("--days", type=int, default=28)
    parser.add_argument("--site", choices=sorted(SITES), default="prod")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    if call is None:
        from worldcup_stats import request, settings
        url, key = settings()
        call = lambda method, path, body=None, prefer="": request(url, key, method, path, body, prefer)
    if args.command == "pages":
        return add_pages(call)
    text = report(call, max(1, args.days), args.site)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"saved {args.out}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
