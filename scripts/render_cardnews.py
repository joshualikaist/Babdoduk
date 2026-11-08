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
import base64
import html
import json
import os
import re
import shutil
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

LIVE_FEED = "https://babdoduk.vercel.app/data/ggongbab/latest.json"
MAX_FEED_AGE = timedelta(hours=36)   # the list is refreshed several times a day; older means a stale copy
OUT = ROOT / "data" / "cardnews"
TEMPLATE = ROOT / "inputs" / "cardnews" / "template.json"
CARD_CSS = ROOT / "inputs" / "cardnews" / "card.css"
PAGE = "https://babdoduk-lab.vercel.app/cardnews.html"
KST = timezone(timedelta(hours=9))
WIDTH, HEIGHT = 1080, 1350
DAYS = ("월", "화", "수", "목", "금")
DAY_NAMES = ("월요일", "화요일", "수요일", "목요일", "금요일")
KEEP_DAYS = 31        # a week's cards are kept a month (owner 2026-11-02), then deleted
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


def occurrences(event: dict) -> list[dict]:
    """When and where the event happens: each of its sessions when the list has them, else the event itself.
    A talk series held every day of the week (자연과학 토크 콘서트, 2026-11-02 to 11-06) is on every
    one of those days' cards, not only on the first (owner 2026-11-03). A session's own place wins: the
    2026 KPF 학술 세미나 was in E6 3438호 on Tuesday and E11 203호 on Wednesday, so the event itself has
    no single place and the 2026-11-08 cards showed none (owner 2026-11-08)."""
    sessions = [s for s in event.get("sessions") or [] if isinstance(s, dict) and s.get("startAt")]
    if not sessions:
        return [{"startAt": event.get("startAt") or "", "endAt": event.get("endAt") or ""}]
    out = []
    for session in sessions:
        item = {"startAt": session["startAt"], "endAt": session.get("endAt") or ""}
        where = session.get("location")
        if isinstance(where, dict) and any(str(where.get(k) or "").strip() for k in ("name", "building", "room")):
            item["location"] = where
        out.append(item)
    return out


def days(feed: dict, monday: date, rules: dict) -> list[list[dict]]:
    """The list's events by the Korean day they happen on, Monday to Friday, each day by start time.
    An entry is the event with that day's session times (and place, when the session has one)."""
    out = [[] for _ in range(5)]
    week = [(monday + timedelta(days=i)).isoformat() for i in range(5)]
    for event in feed.get("events") or []:
        if rules.get("skipTipOnly", True) and tip_only(event):
            continue
        for when in occurrences(event):
            day = kst_day(when["startAt"])
            if day in week:
                out[week.index(day)].append({**event, **when, "_event": event.get("id") or id(event)})
    for entries in out:
        entries.sort(key=lambda e: e.get("startAt") or "")
    return out


def distinct(by_day: list[list[dict]]) -> int:
    """How many events the week has: an event on several days counts once."""
    return len({e["_event"] for d in by_day for e in d})


def shown_days(by_day: list[list[dict]], rules: dict) -> list[int]:
    return [i for i in range(5) if by_day[i] or not rules.get("skipEmptyDays", True)]


def pages(by_day: list[list[dict]], rules: dict) -> list[tuple[int, list[dict], int, int]]:
    """The day cards as (weekday, its events on this card, part, parts). A day with more events than
    fit on one card goes on as many cards as it needs (owner 2026-11-03: no event is left off), unless
    the template turns splitBusyDays off; then the card says how many more."""
    per_card = int(rules.get("perCard", 4))
    out = []
    for i in shown_days(by_day, rules):
        events = by_day[i]
        chunks = ([events[k:k + per_card] for k in range(0, len(events), per_card)]
                  if rules.get("splitBusyDays", True) and len(events) > per_card else [events])
        out += [(i, chunk, n + 1, len(chunks)) for n, chunk in enumerate(chunks)]
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


def week_range(monday: date) -> str:
    friday = monday + timedelta(days=4)
    return f"{monday.month}월 {monday.day}일(월) – {friday.month}월 {friday.day}일(금)"


# Hand-drawn strokes in the accent color, as in the 'KAIST에서 오늘 뭐 먹지?' series (owner 2026-11-08).
SCRIBBLE = ('<svg class="scribble" viewBox="0 0 400 40" preserveAspectRatio="none" aria-hidden="true">'
            '<path d="M6 26 C 70 12, 130 34, 200 22 S 330 10, 394 20" /><path d="M40 34 C 120 26, 240 36, 360 28" /></svg>')
SPARK = ('<svg class="spark" viewBox="0 0 80 80" aria-hidden="true"><path d="M40 6 L40 26" /><path d="M66 18 L52 32" />'
         '<path d="M74 46 L54 44" /></svg>')
ARROW = ('<svg class="arrow" viewBox="0 0 120 50" aria-hidden="true"><path d="M6 30 C 36 10, 70 44, 108 22" />'
         '<path d="M90 12 L110 21 L96 38" /></svg>')
LINK = ('<svg class="link-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M10 14a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1" />'
        '<path d="M14 10a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1" /></svg>')


def avatar_css(tpl: dict) -> str:
    """The Instagram account's profile picture, inlined once in the style (the cards are drawn from a
    string, so a file path would not load)."""
    path = ROOT / (tpl.get("brand") or {}).get("avatar", "")
    if not (tpl.get("brand") or {}).get("avatar") or not path.is_file():
        return ""
    kind = "png" if path.suffix.lower() == ".png" else "jpeg"
    return f'.brand .avatar {{ background-image: url("data:image/{kind};base64,{base64.b64encode(path.read_bytes()).decode()}") }}\n'


def avatar(tpl: dict) -> str:
    return '<span class="avatar"></span>' if avatar_css(tpl) else ""


def chrome(tpl: dict, tag: str = "") -> str:
    """Decoration and the brand row every card shares: the two pink circles and the profile header."""
    brand = (tpl.get("brand") or {}).get("name") or tpl["cover"]["kicker"]
    return (f'<div class="blob b1"></div><div class="blob b2"></div>'
            f'<header class="brand">{avatar(tpl)}<span>{esc(brand)}</span>{tag}</header>')


def window(tpl: dict, inner: str, extra: str = "") -> str:
    """The main information sits in a rounded white browser window."""
    where = (tpl.get("brand") or {}).get("window") or tpl["footer"]["site"]
    return (f'<div class="window{extra}"><div class="bar"><i></i><i></i><i></i><span class="url">{esc(where)}</span></div>'
            f'<div class="pane">{inner}</div></div>')


def foot(tpl: dict, n: int, total: int) -> str:
    f = tpl["footer"]
    dots = "".join(f'<i class="{"on" if k == n else ""}"></i>' for k in range(1, total + 1))
    return (f'<div class="foot"><small>{esc(f["note"])}</small><div class="row"><span class="link">{LINK}<b>{esc(f["site"])}</b></span>'
            f'<span class="dots" aria-hidden="true">{dots}</span><div class="page">{n} / {total}</div></div></div>')


def cover(tpl: dict, monday: date, by_day: list[list[dict]], total_cards: int) -> str:
    c = tpl["cover"]
    strip = "".join(
        f'<div class="day{"" if by_day[i] else " zero"}"><div class="w">{DAYS[i]}</div>'
        f'<div class="d">{(monday + timedelta(days=i)).month}.{(monday + timedelta(days=i)).day}</div>'
        f'<div class="n">{len(by_day[i]) or "–"}</div></div>' for i in range(5))
    total = distinct(by_day)
    count = esc(fill(c["total"], n=total)).replace(f"{total}개", f"<em>{total}개</em>", 1)
    return (f'<section class="card cover">{chrome(tpl)}<p class="kicker">{esc(c["kicker"])}</p>'
            f'<h1>{esc(c["headline"])}<br /><span class="mark">{esc(c["headlineMark"])}{SCRIBBLE}</span>{SPARK}</h1>'
            f'<p class="range">{week_range(monday)}</p>'
            + window(tpl, f'<div class="strip">{strip}</div>')
            + f'<p class="total">{count}</p><p class="swipe">{esc(c["swipe"])}{ARROW}</p>{foot(tpl, 1, total_cards)}</section>')


def day_card(tpl: dict, i: int, day: date, events: list[dict], names: dict, n: int, total_cards: int,
             day_total: int | None = None, part: int = 1, parts: int = 1) -> str:
    d, rules = tpl["day"], tpl["rules"]
    per_card, dense_from = int(rules.get("perCard", 4)), int(rules.get("denseFrom", 3))
    day_total = len(events) if day_total is None else day_total
    head = (f'<div class="head"><span class="date">{day.month}.{day.day}</span><span class="name">{DAY_NAMES[i]}{SCRIBBLE}</span>'
            + (f'<span class="count">{esc(fill(d["count"], n=day_total))}</span>' if events else "") + "</div>")
    kicker = fill(d["kicker"], day=DAYS[i]) + (f" · {part}/{parts}" if parts > 1 else "")
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
    if events and d.get("hint"):
        body += f'<p class="hint">{esc(d["hint"])}{ARROW}</p>'
    dense = " dense" if len(events) >= dense_from else ""
    return (f'<section class="card{dense}">{chrome(tpl)}<p class="kicker">{esc(kicker)}</p>'
            f'{head}{window(tpl, body)}{foot(tpl, n, total_cards)}</section>')


def style(tpl: dict) -> str:
    names = {"canvas": "canvas", "canvasEnd": "canvas-end", "paper": "paper", "ink": "ink", "muted": "muted", "line": "line",
             "accent": "accent", "accentWash": "accent-wash", "accentText": "accent-text", "highlight": "highlight",
             "blob": "blob", "away": "away", "awayWash": "away-wash"}
    tokens = "".join(f"--{css}: {tpl['colors'][key]}; " for key, css in names.items() if key in tpl["colors"])
    return f":root {{ {tokens}}}\n" + CARD_CSS.read_text(encoding="utf-8") + avatar_css(tpl)


def build(feed: dict, monday: date, names: dict | None = None, tpl: dict | None = None) -> str:
    """The cards as one HTML document (a <section class="card"> each): the cover, then the shown days."""
    tpl = tpl or template()
    names = names if names is not None else {k: v["ko"] for k, v in labels()["freeFood"].items()}
    by_day = days(feed, monday, tpl["rules"])
    shown = pages(by_day, tpl["rules"])
    total = 1 + len(shown)
    cards = [cover(tpl, monday, by_day, total)]
    cards += [day_card(tpl, i, monday + timedelta(days=i), chunk, names, n + 2, total, len(by_day[i]), part, parts)
              for n, (i, chunk, part, parts) in enumerate(shown)]
    return f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><style>{style(tpl)}</style></head><body>{"".join(cards)}</body></html>'


CLIPPED = """(card) => [...card.querySelectorAll('.ev h2, .ev .t')].some((el) => {
    const box = el.getBoundingClientRect(), pane = el.closest('.window').getBoundingClientRect();
    return box.bottom > pane.bottom - 4 || box.right > pane.right + 1;
})"""


def render(document: str, folder: Path, clipped: list[int] | None = None) -> list[Path]:
    """Draws each card to a PNG. A card whose event title or time runs past its window (a title too long
    for the layout) is added to `clipped` by its number, so the check before sending can name it."""
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
        for number, (card, path) in enumerate(zip(cards, paths), start=1):
            card.screenshot(path=str(path))
            if clipped is not None and card.evaluate(CLIPPED):
                clipped.append(number)
        browser.close()
    return paths


def entry(feed: dict, monday: date, now: datetime, tpl: dict | None = None) -> dict:
    tpl = tpl or template()
    by_day = days(feed, monday, tpl["rules"])
    shown = [i for i, *_ in pages(by_day, tpl["rules"])]     # one entry per day card: a busy day repeats
    return {"week": monday.isoformat(), "renderedAt": now.isoformat(timespec="seconds"),
            "feedGeneratedAt": feed.get("generatedAt"), "counts": [len(d) for d in by_day],
            "total": distinct(by_day), "days": shown,
            "images": [f"data/cardnews/{monday.isoformat()}/{n}.png" for n in range(1, len(shown) + 2)]}


def write_index(out: Path, item: dict) -> dict:
    """The week first, replacing an earlier run of the same week. Weeks that started more than
    KEEP_DAYS before the newest one leave the index, and their folders of cards are deleted."""
    path = out / "index.json"
    weeks = json.loads(path.read_text(encoding="utf-8")).get("weeks", []) if path.exists() else []
    weeks = [item] + [w for w in weeks if w.get("week") != item["week"]]
    weeks.sort(key=lambda w: w["week"], reverse=True)
    oldest = (date.fromisoformat(weeks[0]["week"]) - timedelta(days=KEEP_DAYS)).isoformat()
    kept = [w for w in weeks if w["week"] > oldest]
    index = {"schemaVersion": 1, "weeks": kept}
    path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    names = {w["week"] for w in kept}
    for folder in out.iterdir():
        if folder.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", folder.name) and folder.name not in names:
            shutil.rmtree(folder)
    return index


def send(paths: list[Path], caption: str, token: str, chat_id: str, opener: Callable = urllib.request.urlopen) -> str:
    """The cards to the owner's Telegram: albums of at most ten (Telegram's limit; a busy week can have
    more cards), the caption on the very first card. Returns PUSH_SENT or the first failure's code."""
    for start in range(0, len(paths), 10):
        result = send_album(paths[start:start + 10], caption if start == 0 else "", token, chat_id, opener)
        if result != "PUSH_SENT":
            return result
    return "PUSH_SENT"


def send_album(paths: list[Path], caption: str, token: str, chat_id: str, opener: Callable) -> str:
    """One album (sendMediaGroup, 2-10 photos; the caption on the first), or one photo. Returns PUSH_SENT
    or a fixed failure code; the token is in the URL only, never in what is returned."""
    boundary = uuid.uuid4().hex
    parts, media = [], []
    for n, path in enumerate(paths):
        name = f"card{n + 1}"
        media.append({"type": "photo", "media": f"attach://{name}", **({"caption": caption[:1024]} if n == 0 and caption else {})})
        parts.append((name, path.name, path.read_bytes()))
    if len(paths) == 1:
        method, fields = "sendPhoto", {"chat_id": str(chat_id), **({"caption": caption[:1024]} if caption else {})}
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


def check(feed: dict, monday: date, document: str, rules: dict) -> dict:
    """The self-check before sending (owner 2026-11-03), plain code and no model: every event the list
    has on a weekday of this week must be on that day's card, read back from the drawn cards. An event
    spanning several days without sessions in the list is named too: it is only on its first day."""
    week = [(monday + timedelta(days=i)).isoformat() for i in range(5)]
    on_card: dict[int, list[str]] = {i: [] for i in range(5)}
    for section in re.findall(r'<section class="card[^"]*">.*?</section>', document, re.S):
        kicker = re.search(r'<p class="kicker">([^<]*)</p>', section)
        day = next((i for i in range(5) if kicker and f"· {DAYS[i]}" in kicker.group(1)), None)
        if day is not None:
            on_card[day] += [html.unescape(t) for t in re.findall(r"<h2>(.*?)</h2>", section, re.S)]
    missing, first_day_only, expected = [], [], set()
    for event in feed.get("events") or []:
        if rules.get("skipTipOnly", True) and tip_only(event):
            continue
        title = event.get("title") or ""
        sessions = [s.get("startAt") for s in event.get("sessions") or [] if isinstance(s, dict) and s.get("startAt")]
        for day in sorted({kst_day(start) for start in (sessions or [event.get("startAt") or ""])} & set(week)):
            expected.add(event.get("id") or title)
            if title not in on_card[week.index(day)]:
                missing.append(f"{day[5:]} {title}")
        start, end = kst_day(event.get("startAt") or ""), kst_day(event.get("endAt") or "")
        if not sessions and start and end and end > start and start <= week[-1] and end >= week[0]:
            first_day_only.append(f"{start[5:]}~{end[5:]} {title}")
    return {"events": len(expected), "missing": missing, "firstDayOnly": first_day_only}


def held(monday: date, client) -> list[str]:
    """Events of this week that the 꽁밥 store holds for review although food is confirmed: they are
    on neither the site nor the cards. Read only, from the operations PC's private store; the titles go
    to the owner's Telegram and never into the public index."""
    begin = datetime.combine(monday, datetime.min.time(), KST)
    rows = client.select_all("events", {
        "select": "id,title,event_start,review_reason", "status": "eq.review", "needs_review": "eq.true",
        "food_provided": "eq.true", "and": f"(event_start.gte.{begin.isoformat()},event_start.lt.{(begin + timedelta(days=5)).isoformat()})",
        "order": "event_start.asc,id.asc"})
    return [f"{kst_day(r.get('event_start') or '')[5:]} {r.get('title') or ''} ({(r.get('review_reason') or '').split('; ')[0][:60]})"
            for r in rows]


def tips_not_listed(feed: dict, monday: date, client) -> list[str]:
    """Reader tips the owner confirmed (✅, status accepted) for a weekday of this week that the list
    does not have yet (owner 2026-11-03: a confirmed tip belongs in the 꽁밥 schedule). The list takes
    them in on its next refresh; until then they are named here. Read only, titles to Telegram only."""
    rows = client.select_all("ggongbab_tips", {
        "select": "id,title,event_date", "status": "eq.accepted",
        "and": f"(event_date.gte.{monday.isoformat()},event_date.lte.{(monday + timedelta(days=4)).isoformat()})",
        "order": "event_date.asc,id.asc"})
    listed = {e.get("title") for e in feed.get("events") or []}
    tip_ids = {str(s.get("id")) for e in feed.get("events") or [] for s in e.get("sources") or []
               if isinstance(s, dict) and s.get("type") == "tip" and s.get("id")}
    return [f"{(r.get('event_date') or '')[5:]} {r.get('title') or ''}" for r in rows
            if r.get("title") not in listed and str(r.get("id")) not in tip_ids]


def report(found: dict, waiting: list[str] | None, tips: list[str] | None = None) -> str:
    """The text that follows the cards on Telegram."""
    lines = [f"🔎 카드뉴스 점검 · 목록의 이번 주 꽁밥 {found['events']}개"]
    lines.append("✅ 모두 카드에 있어요" if not found["missing"] else f"❗ 카드에 빠진 행사 {len(found['missing'])}개")
    lines += [f"  · {m}" for m in found["missing"]]
    if found["firstDayOnly"]:
        lines.append(f"ℹ️ 여러 날이지만 회차가 없어 첫날에만 실은 행사 {len(found['firstDayOnly'])}개")
        lines += [f"  · {m}" for m in found["firstDayOnly"]]
    if waiting is None:
        lines.append("⚠️ 검토 대기 목록은 읽지 못했어요")
    elif waiting:
        lines.append(f"⏸ 음식은 확인됐지만 검토 대기라 사이트·카드에 없는 행사 {len(waiting)}개")
        lines += [f"  · {w}" for w in waiting]
    else:
        lines.append("✅ 검토 대기 중인 꽁밥 없음")
    if tips:
        lines.append(f"📮 확인한 제보인데 아직 목록에 없는 행사 {len(tips)}개 (다음 목록 갱신 때 들어가요)")
        lines += [f"  · {t}" for t in tips]
    return "\n".join(lines)[:4000]


def send_text(text: str, token: str, chat_id: str, opener: Callable = urllib.request.urlopen) -> str:
    request = urllib.request.Request(f"{TELEGRAM_API}/bot{token}/sendMessage", method="POST",
                                     data=json.dumps({"chat_id": str(chat_id), "text": text}).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
    try:
        with opener(request, timeout=30) as response:
            ok = json.loads(response.read().decode("utf-8")).get("ok") is True
    except urllib.error.HTTPError:
        return "PUSH_REJECTED"
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return "PUSH_TRANSPORT_FAILED"
    return "PUSH_SENT" if ok else "PUSH_REJECTED"


def store_checks(feed: dict, monday: date) -> tuple[list[str] | None, list[str] | None]:
    """held() and tips_not_listed() through the operations PC's Supabase settings; None for a part
    whose settings are missing or whose read fails (the check says so; it never stops the cards)."""
    try:
        from ggongbab.config import Settings
        from ggongbab.db.supabase_client import SupabaseClient
        settings = Settings()
        if not (settings.supabase_url and settings.supabase_secret_key):
            return None, None
        client = SupabaseClient(settings.supabase_url, settings.supabase_secret_key)
    except Exception:
        return None, None
    out = []
    for part in (lambda: held(monday, client), lambda: tips_not_listed(feed, monday, client)):
        try:
            out.append(part())
        except Exception:
            out.append(None)
    return out[0], out[1]


def load_feed(source: str, opener: Callable = urllib.request.urlopen) -> dict:
    """The list from the live site (the default) or a file. A checkout's own copy can be days old: the
    2026-11-02 cards were drawn from a 2026-10-31 copy."""
    if source.startswith("https://"):
        with opener(urllib.request.Request(source, headers={"Cache-Control": "no-cache"}), timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    return json.loads(Path(source).read_text(encoding="utf-8"))


def stale(feed: dict, now: datetime) -> bool:
    try:
        made = datetime.fromisoformat(feed.get("generatedAt") or "")
    except (TypeError, ValueError):
        return True
    return now - made > MAX_FEED_AGE


def send_drawn(args, monday: date, tpl: dict) -> int:
    """The weekly schedule (owner 2026-11-08): the cards are drawn from the list as it is at 17:30 and sent
    at 18:00. This sends what the 17:30 run drew, with its check text; nothing is redrawn."""
    path = args.out / "index.json"
    index = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    item = next((w for w in index.get("weeks", []) if w.get("week") == monday.isoformat()), None)
    folder = args.out / monday.isoformat()
    paths = [folder / f"{n}.png" for n in range(1, len(item["images"]) + 1)] if item else []
    if not paths or not all(p.is_file() for p in paths):
        raise SystemExit(f"NOT_DRAWN: no cards for {monday.isoformat()} in {args.out}")
    from ggongbab.instagram.telegram_review import credentials
    token, chat = credentials(args.local)
    if not (token and chat):
        raise SystemExit("TELEGRAM_NOT_CONFIGURED")
    caption = fill(tpl["telegram"]["caption"], range=week_range(monday), total=item["total"], page=PAGE)
    result = {"week": item["week"], "renderedAt": item.get("renderedAt"), "feedGeneratedAt": item.get("feedGeneratedAt"),
              "images": [str(p) for p in paths], "telegram": send(paths, caption, token, chat)}
    if result["telegram"] == "PUSH_SENT" and args.report and args.report.is_file():
        result["telegram"] = send_text(args.report.read_text(encoding="utf-8"), token, chat)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["telegram"] == "PUSH_SENT" else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--week", type=date.fromisoformat, help="the Monday of the week (default: this or the coming week)")
    parser.add_argument("--feed", default=LIVE_FEED, help="the published list: its URL (default) or a file")
    parser.add_argument("--allow-stale", action="store_true", help="draw from a list older than 36 hours")
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--send", action="store_true", help="send the cards to the owner's Telegram afterwards")
    parser.add_argument("--local", type=Path, default=ROOT / ".local", help="--send: the operations checkout's .local")
    parser.add_argument("--report", type=Path, help="also write the check's text here (private: it can name held events)")
    parser.add_argument("--send-drawn", action="store_true",
                        help="send the week's cards already drawn in --out, with the check text of --report, without redrawing")
    args = parser.parse_args(argv)
    now = datetime.now(KST)
    monday = args.week or monday_of(now.date())
    if monday.weekday() != 0:
        raise SystemExit("--week must be a Monday")
    tpl = template()
    if args.send_drawn:
        return send_drawn(args, monday, tpl)
    feed = load_feed(str(args.feed))
    if stale(feed, now) and not args.allow_stale:
        raise SystemExit(f"FEED_STALE: the list was made at {feed.get('generatedAt')}")
    document = build(feed, monday, tpl=tpl)
    found = check(feed, monday, document, tpl["rules"])
    clipped: list[int] = []
    paths = render(document, args.out / monday.isoformat(), clipped)
    item = entry(feed, monday, now, tpl)
    write_index(args.out, item)
    result = {"week": item["week"], "counts": item["counts"], "days": item["days"], "images": [str(p) for p in paths],
              "check": {"events": found["events"], "missing": len(found["missing"]), "firstDayOnly": len(found["firstDayOnly"])}}
    waiting, tips = store_checks(feed, monday)
    result["check"]["held"] = None if waiting is None else len(waiting)
    result["check"]["tipsNotListed"] = None if tips is None else len(tips)
    result["check"]["clipped"] = clipped
    text = report(found, waiting, tips) + "".join(f"\n⚠️ {n}번 카드의 글이 창 밖으로 넘쳐요" for n in clipped)
    print(text, file=sys.stderr)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
    if args.send:
        from ggongbab.instagram.telegram_review import credentials
        token, chat = credentials(args.local)
        if not (token and chat):
            raise SystemExit("TELEGRAM_NOT_CONFIGURED")
        caption = fill(tpl["telegram"]["caption"], range=week_range(monday), total=item["total"], page=PAGE)
        result["telegram"] = send(paths, caption, token, chat)
        if result["telegram"] == "PUSH_SENT":
            result["telegram"] = send_text(text, token, chat)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("telegram", "PUSH_SENT") == "PUSH_SENT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
