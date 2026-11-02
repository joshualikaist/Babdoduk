#!/usr/bin/env python3
"""The weekly 꽁밥 card news (owner 2026-11-01, docs/CARDNEWS.md): a cover and one card for each weekday
that has events, Monday to Friday, 1080x1350 (4:5, an Instagram carousel), drawn from the published
꽁밥 list with the template in inputs/cardnews/ (template.json: wording, colors, rules; card.css: layout).

    python scripts/render_cardnews.py                      # this week (from Saturday on: the next week)
    python scripts/render_cardnews.py --week 2026-11-02    # the week starting that Monday
    python scripts/render_cardnews.py --week 2026-11-02 --send   # and send them to the owner's Telegram

It writes data/cardnews/<monday>/1.png, 2.png, ... and puts the week first in data/cardnews/index.json,
which the lab page cardnews.html shows. Only what the list already publishes goes on a card (the
reviewed events of data/ggongbab/latest.json): a value it does not have is left out, never guessed,
and no source poster is reproduced. An event known only from a reader tip stays on the site and is
not made a card (owner 2026-11-02); a weekday without events gets no card. Drawing needs Chrome
through Playwright (BABDODUK_BROWSER).
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from content_labels import labels  # noqa: E402

FEED = ROOT / "data" / "ggongbab" / "latest.json"
OUT = ROOT / "data" / "cardnews"
TEMPLATE = ROOT / "inputs" / "cardnews" / "template.json"
CARD_CSS = ROOT / "inputs" / "cardnews" / "card.css"
PAGE = "https://babdoduk-lab.vercel.app/cardnews.html"
KST = timezone(timedelta(hours=9))
WIDTH, HEIGHT = 1080, 1350
DAYS = ("월", "화", "수", "목", "금")
DAY_NAMES = ("월요일", "화요일", "수요일", "목요일", "금요일")
KEEP_WEEKS = 26
TELEGRAM_API = "https://api.telegram.org"

esc = html.escape


def template() -> dict:
    return json.loads(TEMPLATE.read_text(encoding="utf-8"))


def fill(pattern: str, **values) -> str:
    for name, value in values.items():
        pattern = pattern.replace("{" + name + "}", str(value))
    return pattern


def monday_of(day: date) -> date:
    """The week a run is for: this week's Monday, or from Saturday on the coming one."""
    start = day - timedelta(days=day.weekday())
    return start + timedelta(days=7) if day.weekday() >= 5 else start


def kst_day(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).astimezone(KST).date().isoformat()
    except (TypeError, ValueError):
        return ""


def tip_only(event: dict) -> bool:
    kinds = {source.get("type") for source in event.get("sources") or [] if isinstance(source, dict)}
    return kinds == {"tip"}


def days(feed: dict, monday: date, rules: dict) -> list[list[dict]]:
    """The list's events by the Korean day they start on, Monday to Friday, each day by start time."""
    out = [[] for _ in range(5)]
    for event in sorted(feed.get("events") or [], key=lambda e: e.get("startAt") or ""):
        if rules.get("skipTipOnly", True) and tip_only(event):
            continue
        day = kst_day(event.get("startAt") or "")
        for i in range(5):
            if day == (monday + timedelta(days=i)).isoformat():
                out[i].append(event)
    return out


def shown_days(by_day: list[list[dict]], rules: dict) -> list[int]:
    return [i for i in range(5) if by_day[i] or not rules.get("skipEmptyDays", True)]


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


def week_range(monday: date) -> str:
    friday = monday + timedelta(days=4)
    return f"{monday.month}월 {monday.day}일(월) – {friday.month}월 {friday.day}일(금)"


def foot(tpl: dict, n: int, total: int) -> str:
    f = tpl["footer"]
    return (f'<div class="foot"><div><b>{esc(f["brand"])}</b> · {esc(f["site"])}<small>{esc(f["note"])}</small></div>'
            f'<div class="page">{n} / {total}</div></div>')


def cover(tpl: dict, monday: date, by_day: list[list[dict]], total_cards: int) -> str:
    c = tpl["cover"]
    strip = "".join(
        f'<div class="day{"" if by_day[i] else " zero"}"><div class="w">{DAYS[i]}</div>'
        f'<div class="d">{(monday + timedelta(days=i)).month}.{(monday + timedelta(days=i)).day}</div>'
        f'<div class="n">{len(by_day[i]) or "–"}</div></div>' for i in range(5))
    total = sum(len(d) for d in by_day)
    count = esc(fill(c["total"], n=total)).replace(f"{total}개", f"<em>{total}개</em>", 1)
    return (f'<section class="card cover"><div class="band"></div><p class="kicker">{esc(c["kicker"])}</p>'
            f'<h1>{esc(c["headline"])}<br /><span>{esc(c["headlineMark"])}</span></h1>'
            f'<p class="range">{week_range(monday)}</p><div class="strip">{strip}</div>'
            f'<p class="total">{count}</p><p class="swipe">{esc(c["swipe"])}</p>{foot(tpl, 1, total_cards)}</section>')


def day_card(tpl: dict, i: int, day: date, events: list[dict], names: dict, n: int, total_cards: int) -> str:
    d, rules = tpl["day"], tpl["rules"]
    per_card, dense_from = int(rules.get("perCard", 4)), int(rules.get("denseFrom", 3))
    head = (f'<div class="head"><span class="date">{day.month}.{day.day}</span><span class="name">{DAY_NAMES[i]}</span>'
            + (f'<span class="count">{esc(fill(d["count"], n=len(events)))}</span>' if events else "") + "</div>")
    if not events:
        e = tpl["empty"]
        body = (f'<div class="empty"><p class="big">{esc(e["title"])}</p><p class="sub">{esc(e["sub"])}</p>'
                f'<p class="tip">{esc(e["tip"])}</p></div>')
    else:
        rows = []
        for event in events[:per_card]:
            begin, finish = times(event)
            meta = []
            if food(event, names):
                meta.append(f'<span class="pill">{esc(food(event, names))}</span>')
            if seoul(event):
                meta.append(f'<span class="pill away">{esc(d["away"])}</span>')
            if place(event):
                meta.append(f'<span class="where">📍 {esc(place(event))}</span>')
            if audience(event) and len(events) < per_card:
                meta.append(f'<span class="who">{esc(fill(d["audience"], text=audience(event)))}</span>')
            rows.append(f'<article class="ev"><div class="t">{esc(begin)}{f"<small>~ {esc(finish)}</small>" if finish else ""}</div>'
                        f'<div><h2>{esc(event.get("title") or "")}</h2><div class="meta">{"".join(meta)}</div></div></article>')
        body = '<div class="list">' + "".join(rows) + "</div>"
        if len(events) > per_card:
            body += f'<p class="more">{esc(fill(d["more"], n=len(events) - per_card))}</p>'
    dense = " dense" if len(events) >= dense_from else ""
    return (f'<section class="card{dense}"><div class="band"></div><p class="kicker">{esc(fill(d["kicker"], day=DAYS[i]))}</p>'
            f'{head}{body}{foot(tpl, n, total_cards)}</section>')


def style(tpl: dict) -> str:
    names = {"canvas": "canvas", "paper": "paper", "ink": "ink", "muted": "muted", "line": "line", "accent": "accent",
             "accentWash": "accent-wash", "accentText": "accent-text", "away": "away", "awayWash": "away-wash"}
    tokens = "".join(f"--{css}: {tpl['colors'][key]}; " for key, css in names.items())
    return f":root {{ {tokens}}}\n" + CARD_CSS.read_text(encoding="utf-8")


def build(feed: dict, monday: date, names: dict | None = None, tpl: dict | None = None) -> str:
    """The cards as one HTML document (a <section class="card"> each): the cover, then the shown days."""
    tpl = tpl or template()
    names = names if names is not None else {k: v["ko"] for k, v in labels()["freeFood"].items()}
    by_day = days(feed, monday, tpl["rules"])
    shown = shown_days(by_day, tpl["rules"])
    total = 1 + len(shown)
    cards = [cover(tpl, monday, by_day, total)]
    cards += [day_card(tpl, i, monday + timedelta(days=i), by_day[i], names, n + 2, total) for n, i in enumerate(shown)]
    return f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><style>{style(tpl)}</style></head><body>{"".join(cards)}</body></html>'


def render(document: str, folder: Path) -> list[Path]:
    from playwright.sync_api import sync_playwright
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("*.png"):
        old.unlink()                                   # a rerun may have fewer cards
    channel = os.environ.get("BABDODUK_BROWSER", "chrome")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=None if channel == "chromium" else channel, headless=True)
        page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1)
        page.set_content(document, wait_until="load")
        page.evaluate("document.fonts.ready")
        cards = page.locator(".card").all()
        paths = [folder / f"{n}.png" for n in range(1, len(cards) + 1)]
        for card, path in zip(cards, paths):
            card.screenshot(path=str(path))
        browser.close()
    return paths


def entry(feed: dict, monday: date, now: datetime, tpl: dict | None = None) -> dict:
    tpl = tpl or template()
    by_day = days(feed, monday, tpl["rules"])
    shown = shown_days(by_day, tpl["rules"])
    return {"week": monday.isoformat(), "renderedAt": now.isoformat(timespec="seconds"),
            "feedGeneratedAt": feed.get("generatedAt"), "counts": [len(d) for d in by_day],
            "total": sum(len(d) for d in by_day), "days": shown,
            "images": [f"data/cardnews/{monday.isoformat()}/{n}.png" for n in range(1, len(shown) + 2)]}


def write_index(out: Path, item: dict) -> dict:
    """The week first, replacing an earlier run of the same week; at most KEEP_WEEKS weeks."""
    path = out / "index.json"
    weeks = json.loads(path.read_text(encoding="utf-8")).get("weeks", []) if path.exists() else []
    weeks = [item] + [w for w in weeks if w.get("week") != item["week"]]
    weeks.sort(key=lambda w: w["week"], reverse=True)
    index = {"schemaVersion": 1, "weeks": weeks[:KEEP_WEEKS]}
    path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return index


def send(paths: list[Path], caption: str, token: str, chat_id: str, opener: Callable = urllib.request.urlopen) -> str:
    """The cards to the owner's Telegram: one album (sendMediaGroup, 2-10 photos; the caption on the
    first), or one photo when only the cover was drawn. Returns PUSH_SENT or a fixed failure code;
    the token is in the URL only, never in what is returned."""
    boundary = uuid.uuid4().hex
    parts, media = [], []
    for n, path in enumerate(paths):
        name = f"card{n + 1}"
        media.append({"type": "photo", "media": f"attach://{name}", **({"caption": caption[:1024]} if n == 0 else {})})
        parts.append((name, path.name, path.read_bytes()))
    if len(paths) == 1:
        method, fields = "sendPhoto", {"chat_id": str(chat_id), "caption": caption[:1024]}
        files = [("photo", parts[0][1], parts[0][2])]
    else:
        method, fields, files = "sendMediaGroup", {"chat_id": str(chat_id), "media": json.dumps(media, ensure_ascii=False)}, parts
    body = b""
    for key, value in fields.items():
        body += f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
    for key, filename, data in files:
        body += (f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"; filename="{filename}"\r\n'
                 f'Content-Type: image/png\r\n\r\n').encode() + data + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    request = urllib.request.Request(f"{TELEGRAM_API}/bot{token}/{method}", data=body, method="POST",
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with opener(request, timeout=60) as response:
            ok = json.loads(response.read().decode("utf-8")).get("ok") is True
    except urllib.error.HTTPError:
        return "PUSH_REJECTED"
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return "PUSH_TRANSPORT_FAILED"
    return "PUSH_SENT" if ok else "PUSH_REJECTED"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--week", type=date.fromisoformat, help="the Monday of the week (default: this or the coming week)")
    parser.add_argument("--feed", type=Path, default=FEED)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--send", action="store_true", help="send the cards to the owner's Telegram afterwards")
    parser.add_argument("--local", type=Path, default=ROOT / ".local", help="--send: the operations checkout's .local")
    args = parser.parse_args(argv)
    now = datetime.now(KST)
    monday = args.week or monday_of(now.date())
    if monday.weekday() != 0:
        raise SystemExit("--week must be a Monday")
    tpl = template()
    feed = json.loads(args.feed.read_text(encoding="utf-8"))
    paths = render(build(feed, monday, tpl=tpl), args.out / monday.isoformat())
    item = entry(feed, monday, now, tpl)
    write_index(args.out, item)
    result = {"week": item["week"], "counts": item["counts"], "days": item["days"], "images": [str(p) for p in paths]}
    if args.send:
        from ggongbab.instagram.telegram_review import credentials
        token, chat = credentials(args.local)
        if not (token and chat):
            raise SystemExit("TELEGRAM_NOT_CONFIGURED")
        caption = fill(tpl["telegram"]["caption"], range=week_range(monday), total=item["total"], page=PAGE)
        result["telegram"] = send(paths, caption, token, chat)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("telegram", "PUSH_SENT") == "PUSH_SENT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
