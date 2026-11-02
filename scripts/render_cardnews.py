#!/usr/bin/env python3
"""The weekly 꽁밥 card news (owner 2026-11-01, docs/CARDNEWS.md): a cover and one card for each weekday,
Monday to Friday, 1080x1350 (4:5, an Instagram carousel), drawn from the published 꽁밥 list.

    python scripts/render_cardnews.py                      # this week (from Saturday on: the next week)
    python scripts/render_cardnews.py --week 2026-11-02    # the week starting that Monday

It writes data/cardnews/<monday>/1.png .. 6.png and puts the week first in data/cardnews/index.json,
which the lab page cardnews.html shows. Only what the list already publishes goes on a card (the
reviewed events of data/ggongbab/latest.json): a value it does not have is left out, never guessed,
and no source poster is reproduced. Drawing needs Chrome through Playwright (BABDODUK_BROWSER).
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from content_labels import labels  # noqa: E402

FEED = ROOT / "data" / "ggongbab" / "latest.json"
OUT = ROOT / "data" / "cardnews"
KST = timezone(timedelta(hours=9))
WIDTH, HEIGHT = 1080, 1350
DAYS = ("월", "화", "수", "목", "금")
DAY_NAMES = ("월요일", "화요일", "수요일", "목요일", "금요일")
PER_CARD = 4          # events on one day's card; more become "외 N개 더"
DENSE_FROM = 3        # from this many events a day's card uses the tighter layout
KEEP_WEEKS = 26

esc = html.escape


def monday_of(day: date) -> date:
    """The week a run is for: this week's Monday, or from Saturday on the coming one."""
    start = day - timedelta(days=day.weekday())
    return start + timedelta(days=7) if day.weekday() >= 5 else start


def kst_day(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).astimezone(KST).date().isoformat()
    except (TypeError, ValueError):
        return ""


def days(feed: dict, monday: date) -> list[list[dict]]:
    """The list's events by the Korean day they start on, Monday to Friday, each day by start time."""
    out = [[] for _ in range(5)]
    for event in sorted(feed.get("events") or [], key=lambda e: e.get("startAt") or ""):
        day = kst_day(event.get("startAt") or "")
        for i in range(5):
            if day == (monday + timedelta(days=i)).isoformat():
                out[i].append(event)
    return out


def place(event: dict) -> str:
    loc = event.get("location") or {}
    text = " ".join(part for part in (loc.get("building") or "", loc.get("room") or "") if part).strip()
    return text or (loc.get("name") or "").strip()


def seoul(event: dict) -> bool:
    """An event away from the Daejeon campus (owner 2026-11-02: kept, with a 서울 mark)."""
    loc = event.get("location") or {}
    return "서울" in " ".join(str(loc.get(k) or "") for k in ("name", "building", "room"))


def clock(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).astimezone(KST).strftime("%H:%M")
    except (TypeError, ValueError):
        return ""


def times(event: dict) -> tuple[str, str]:
    start, end = event.get("startAt") or "", event.get("endAt") or ""
    begin = clock(start)
    finish = clock(end) if end and kst_day(end) == kst_day(start) else ""
    return begin, finish if finish != begin else ""


def food(event: dict, names: dict) -> str:
    item = event.get("food") or {}
    return names.get(item.get("type") or "", "") if item.get("provided") == "true" else ""


def audience(event: dict) -> str:
    who = event.get("audience") or {}
    return (who.get("text") or "").strip() if who.get("basis") == "stated" else ""


CSS = """
* { box-sizing: border-box }
body { margin: 0; background: #ddd; font-family: 'Noto Sans CJK KR', 'Noto Sans KR', sans-serif; color: #1e1d1a }
.card { width: 1080px; height: 1350px; background: #f7f4ee; position: relative; overflow: hidden; display: flex; flex-direction: column;
        padding: 88px 80px 64px; word-break: keep-all; overflow-wrap: anywhere }
.band { position: absolute; left: 0; right: 0; top: 0; height: 18px;
        background: linear-gradient(90deg, #f472b6, #a78bfa 30%, #60a5fa 55%, #34d399 80%, #fbbf24) }
.kicker { font-size: 26px; font-weight: 700; letter-spacing: .14em; color: #8a8579; margin: 0 }
.foot { margin-top: auto; display: flex; justify-content: space-between; align-items: flex-end; gap: 24px; font-size: 24px; color: #6f6a60 }
.foot b { color: #1e1d1a; font-weight: 800 }
.foot small { display: block; font-size: 21px; color: #8a8579; margin-top: 6px }
.page { font-weight: 700; color: #8a8579; font-family: 'DejaVu Sans', 'Noto Sans CJK KR', sans-serif }
.cover h1 { font-size: 168px; line-height: 1.02; font-weight: 900; letter-spacing: -.04em; margin: 44px 0 0 }
.cover h1 span { display: inline-block; background: #fce7f3; padding: 0 18px; margin-left: -18px; border-radius: 24px }
.range { font-size: 40px; font-weight: 700; margin: 36px 0 0; color: #3b3832 }
.strip { display: grid; grid-template-columns: repeat(5, 1fr); gap: 16px; margin: 72px 0 0 }
.day { background: #fffdf8; border: 2px solid #e6e0d4; border-radius: 28px; padding: 26px 0 30px; text-align: center }
.day .w { font-size: 34px; font-weight: 800 }
.day .d { font-size: 26px; color: #6f6a60; margin-top: 4px }
.day .n { width: 96px; height: 96px; border-radius: 50%; margin: 22px auto 0; display: grid; place-items: center;
          font-size: 48px; font-weight: 900; background: #be185d; color: #fff }
.day.zero .n { background: transparent; color: #b5ae9f; border: 3px dashed #d6cfc0; font-size: 40px }
.total { font-size: 44px; font-weight: 800; margin: 56px 0 0; letter-spacing: -.02em }
.total em { font-style: normal; color: #be185d }
.swipe { font-size: 30px; color: #6f6a60; margin: 14px 0 0 }
.head { display: flex; align-items: baseline; gap: 26px; margin: 34px 0 0 }
.head .date { font-size: 150px; font-weight: 900; letter-spacing: -.05em; line-height: 1 }
.head .name { font-size: 56px; font-weight: 800 }
.head .count { margin-left: auto; font-size: 30px; font-weight: 800; color: #be185d; background: #fce7f3; padding: 12px 26px; border-radius: 999px }
.list { margin: 52px 0 0; display: flex; flex-direction: column; gap: 22px }
.ev { background: #fffdf8; border: 2px solid #e6e0d4; border-radius: 28px; padding: 30px 34px; display: grid;
      grid-template-columns: 168px 1fr; gap: 0 28px; align-items: start }
.ev > div { min-width: 0 }
.ev .t { font-size: 46px; font-weight: 900; color: #be185d; line-height: 1.05; letter-spacing: -.01em;
         font-family: 'DejaVu Sans', 'Noto Sans CJK KR', sans-serif }
.ev .t small { display: block; font-size: 26px; font-weight: 700; color: #8a8579; margin-top: 8px }
.ev h2 { margin: 0; font-size: 40px; line-height: 1.28; font-weight: 800; letter-spacing: -.02em;
         display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden }
.ev .meta { margin-top: 14px; display: flex; flex-wrap: wrap; gap: 10px 14px; align-items: center; font-size: 27px; color: #57524a }
.ev .pill { background: #fce7f3; color: #9d174d; font-weight: 800; padding: 6px 18px; border-radius: 999px; font-size: 25px }
.ev .pill.away { background: #e0ecff; color: #1d4ed8 }
.ev .where { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap }
.ev .who { width: 100%; font-size: 25px; color: #6f6a60; white-space: nowrap; overflow: hidden; text-overflow: ellipsis }
.dense .head .date { font-size: 124px }
.dense .head .name { font-size: 48px }
.dense .list { margin-top: 40px; gap: 16px }
.dense .ev { padding: 24px 30px; grid-template-columns: 150px 1fr }
.dense .ev .t { font-size: 40px }
.dense .ev h2 { font-size: 34px; line-height: 1.3 }
.dense .ev .meta { margin-top: 10px; font-size: 25px }
.dense .ev .pill { font-size: 23px; padding: 4px 16px }
.dense .ev .who { font-size: 23px }
.more { font-size: 30px; font-weight: 700; color: #57524a; margin: 26px 0 0; text-align: right }
.empty { margin: 60px 0 0; background: #fffdf8; border: 2px dashed #d6cfc0; border-radius: 32px; padding: 80px 60px; text-align: center }
.empty p { margin: 0 }
.empty .big { font-size: 52px; font-weight: 900; letter-spacing: -.02em }
.empty .sub { font-size: 32px; color: #57524a; margin-top: 22px; line-height: 1.5 }
.empty .tip { display: inline-block; margin-top: 44px; font-size: 30px; font-weight: 800; color: #9d174d; background: #fce7f3; padding: 16px 30px; border-radius: 999px }
"""


def foot(n: int) -> str:
    return ('<div class="foot"><div><b>밥도둑 Babdoduk</b> · babdoduk.vercel.app'
            '<small>일정은 바뀔 수 있어요. 자세한 내용은 사이트에서 확인하세요.</small></div>'
            f'<div class="page">{n} / 6</div></div>')


def cover(monday: date, by_day: list[list[dict]]) -> str:
    friday = monday + timedelta(days=4)
    strip = "".join(
        f'<div class="day{"" if by_day[i] else " zero"}"><div class="w">{DAYS[i]}</div>'
        f'<div class="d">{(monday + timedelta(days=i)).month}.{(monday + timedelta(days=i)).day}</div>'
        f'<div class="n">{len(by_day[i]) or "–"}</div></div>' for i in range(5))
    total = sum(len(d) for d in by_day)
    return ('<section class="card cover"><div class="band"></div><p class="kicker">BABDODUK · KAIST FOOD</p>'
            '<h1>이번 주<br /><span>꽁밥</span></h1>'
            f'<p class="range">{monday.month}월 {monday.day}일(월) – {friday.month}월 {friday.day}일(금)</p>'
            f'<div class="strip">{strip}</div><p class="total">이번 주 꽁밥 <em>{total}개</em></p>'
            f'<p class="swipe">넘겨서 요일별로 확인하세요 →</p>{foot(1)}</section>')


def day_card(i: int, day: date, events: list[dict], names: dict) -> str:
    head = (f'<div class="head"><span class="date">{day.month}.{day.day}</span><span class="name">{DAY_NAMES[i]}</span>'
            + (f'<span class="count">꽁밥 {len(events)}개</span>' if events else "") + "</div>")
    if not events:
        body = ('<div class="empty"><p class="big">아직 알려진 꽁밥이 없어요</p>'
                '<p class="sub">새로 올라오면 사이트의<br />오늘의 꽁밥에 바로 떠요.</p>'
                '<p class="tip">꽁밥을 봤다면 제보해 주세요</p></div>')
    else:
        rows = []
        for event in events[:PER_CARD]:
            begin, finish = times(event)
            meta = []
            if food(event, names):
                meta.append(f'<span class="pill">{esc(food(event, names))}</span>')
            if seoul(event):
                meta.append('<span class="pill away">서울</span>')
            if place(event):
                meta.append(f'<span class="where">📍 {esc(place(event))}</span>')
            if audience(event) and len(events) < PER_CARD:
                meta.append(f'<span class="who">대상 · {esc(audience(event))}</span>')
            rows.append(f'<article class="ev"><div class="t">{esc(begin)}{f"<small>~ {esc(finish)}</small>" if finish else ""}</div>'
                        f'<div><h2>{esc(event.get("title") or "")}</h2><div class="meta">{"".join(meta)}</div></div></article>')
        body = '<div class="list">' + "".join(rows) + "</div>"
        if len(events) > PER_CARD:
            body += f'<p class="more">외 {len(events) - PER_CARD}개 더 · 사이트에서 확인하세요</p>'
    dense = " dense" if len(events) >= DENSE_FROM else ""
    return (f'<section class="card{dense}"><div class="band"></div><p class="kicker">이번 주 꽁밥 · {DAYS[i]}</p>'
            f'{head}{body}{foot(i + 2)}</section>')


def build(feed: dict, monday: date, names: dict | None = None) -> str:
    """The six cards as one HTML document (a <section class="card"> each)."""
    names = names if names is not None else {k: v["ko"] for k, v in labels()["freeFood"].items()}
    by_day = days(feed, monday)
    cards = [cover(monday, by_day)] + [day_card(i, monday + timedelta(days=i), by_day[i], names) for i in range(5)]
    return f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><style>{CSS}</style></head><body>{"".join(cards)}</body></html>'


def render(document: str, folder: Path) -> list[Path]:
    from playwright.sync_api import sync_playwright
    folder.mkdir(parents=True, exist_ok=True)
    channel = os.environ.get("BABDODUK_BROWSER", "chrome")
    paths = [folder / f"{n}.png" for n in range(1, 7)]
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=None if channel == "chromium" else channel, headless=True)
        page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1)
        page.set_content(document, wait_until="load")
        page.evaluate("document.fonts.ready")
        cards = page.locator(".card").all()
        if len(cards) != 6:
            raise SystemExit(f"expected 6 cards, found {len(cards)}")
        for card, path in zip(cards, paths):
            card.screenshot(path=str(path))
        browser.close()
    return paths


def entry(feed: dict, monday: date, now: datetime) -> dict:
    by_day = days(feed, monday)
    return {"week": monday.isoformat(), "renderedAt": now.isoformat(timespec="seconds"),
            "feedGeneratedAt": feed.get("generatedAt"), "counts": [len(d) for d in by_day],
            "total": sum(len(d) for d in by_day),
            "images": [f"data/cardnews/{monday.isoformat()}/{n}.png" for n in range(1, 7)]}


def write_index(out: Path, item: dict) -> dict:
    """The week first, replacing an earlier run of the same week; at most KEEP_WEEKS weeks."""
    path = out / "index.json"
    weeks = json.loads(path.read_text(encoding="utf-8")).get("weeks", []) if path.exists() else []
    weeks = [item] + [w for w in weeks if w.get("week") != item["week"]]
    weeks.sort(key=lambda w: w["week"], reverse=True)
    index = {"schemaVersion": 1, "weeks": weeks[:KEEP_WEEKS]}
    path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return index


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--week", type=date.fromisoformat, help="the Monday of the week (default: this or the coming week)")
    parser.add_argument("--feed", type=Path, default=FEED)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    now = datetime.now(KST)
    monday = args.week or monday_of(now.date())
    if monday.weekday() != 0:
        raise SystemExit("--week must be a Monday")
    feed = json.loads(args.feed.read_text(encoding="utf-8"))
    paths = render(build(feed, monday), args.out / monday.isoformat())
    item = entry(feed, monday, now)
    write_index(args.out, item)
    print(json.dumps({"week": item["week"], "counts": item["counts"], "images": [str(p) for p in paths]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
