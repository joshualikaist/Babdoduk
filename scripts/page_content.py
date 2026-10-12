"""The authored page content in data/content/, rendered for the pages that show it.

events.json holds the owner's notices and activities (event.html), history.json the timeline
(history.html). scripts/sync_site_chrome.py writes what these functions render into the pages'
marked blocks: the markup between `<!-- @content:<name> -->` and `<!-- @end content -->`, and the
translation entries between `// @content:<name>:<lang>` and `// @end content` in each language's
table. The pages keep working without JavaScript (the Korean text is in the markup) and an entry
is written in one place, in both languages.

Order is not authored: activities run by start then end date (the first is event.e0), notices
newest first, milestones oldest first with the roadmap last.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / "data" / "content"
LANGS = ("ko", "en")
# The four fixed detail labels (docs/EVENT_DETAIL_FIELDS.md), in the order they are shown.
DETAIL_LABELS = {
    "summary": {"ko": "이벤트 내용", "en": "Event summary"},
    "duration": {"ko": "진행 기간", "en": "Duration"},
    "prizes": {"ko": "이벤트 상품", "en": "Prizes"},
    "participation": {"ko": "참여 방법", "en": "How to participate"},
}
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
# The only markup a detail value may carry; everything else in the content is plain text.
INLINE_MARKUP = re.compile(r"</?strong>")


def load(name: str) -> dict:
    return json.loads((CONTENT / f"{name}.json").read_text(encoding="utf-8"))


def text(value: str) -> str:
    return html.escape(value, quote=False)


def attr(value: str) -> str:
    return html.escape(value, quote=True)


def js_str(value: str) -> str:
    """A JavaScript string literal in the tables' own style: single quotes unless the text has one."""
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def entry(key: str, value: str) -> str:
    return f"'{key}': {js_str(value)},"


def dotted(day: str) -> str:
    return day.replace("-", ".")


def date_range(start: str, end: str) -> str:
    """`2026.05.13 — 05.20`; the end keeps its year only when the year changes."""
    first = f'<time datetime="{start}">{dotted(start)}</time>'
    if end == start:
        return first
    shown = dotted(end)[5:] if end[:4] == start[:4] else dotted(end)
    return f'{first} — <time datetime="{end}">{shown}</time>'


def milestone_date(day: str, lang: str) -> str:
    year, month, date = (int(part) for part in day.split("-"))
    return f"{year}.{month}.{date}" if lang == "ko" else f"{MONTHS[month - 1]} {date}, {year}"


def activities(data: dict) -> list[tuple[str, dict]]:
    ordered = sorted(data["activities"], key=lambda item: (item["start"], item["end"]))
    return [(f"e{index}", item) for index, item in enumerate(ordered)]


def notices(data: dict) -> list[tuple[str, dict]]:
    ordered = sorted(data["notices"], key=lambda item: item["date"], reverse=True)
    return [(f"n{index}", item) for index, item in enumerate(ordered)]


def detail_sheet(details: dict, lang: str) -> list[str]:
    """The detail sheet as the fragments of one string: the fixed rows, or one note row."""
    rows = ['<div class="event-detail-sheet">']
    if "note" in details:
        rows.append('<div class="event-detail-row event-detail-row--solo"><div class="event-detail-value">'
                    f'{details["note"][lang]}</div></div>')
    for field, label in DETAIL_LABELS.items():
        if field in details:
            marker = ' data-detail="participation"' if field == "participation" else ""
            rows.append(f'<div class="event-detail-row"{marker}><div class="event-detail-label">{label[lang]}</div>'
                        f'<div class="event-detail-value">{details[field][lang]}</div></div>')
    return rows + ["</div>"]


def event_blocks(data: dict | None = None) -> dict[str, list[str]]:
    data = load("events") if data is None else data
    rows: list[str] = []
    for key, item in activities(data):
        place = ""
        if "place" in item:
            place = f' <span class="event-place" data-i18n="event.{key}.place">{text(item["place"]["ko"])}</span>'
        rows += [
            f'<li class="event-item" data-start="{item["start"]}" data-end="{item["end"]}" '
            f'data-confirmation="{item["confirmation"]}">',
            f'  <p class="event-date">{date_range(item["start"], item["end"])}{place}</p>',
            f'  <h3 class="event-name" data-i18n="event.{key}.summary">{text(item["title"]["ko"])}</h3>',
            '  <p class="event-state" data-event-state hidden></p>',
            f'  <a class="event-link" href="{attr(item["link"])}" target="_blank" rel="noopener noreferrer">'
            '<span data-event-cta>당시 게시물</span> <span aria-hidden="true">↗</span>'
            '<span class="event-sr" data-i18n="event.newTab">(새 창)</span></a>',
            '  <details class="event-more">',
            '    <summary data-i18n="event.more">자세히</summary>',
            '    <p class="event-note" data-event-note></p>',
            f'    <div class="event-detail" data-i18n-html="event.{key}.detail">'
            f'{"".join(detail_sheet(item["details"], "ko"))}</div>',
            '  </details>',
            '</li>',
        ]
    listed = [f'<li class="event-notice"><time datetime="{item["date"]}">{dotted(item["date"])}</time>'
              f'<strong data-i18n="event.{key}.title">{text(item["title"]["ko"])}</strong>'
              f'<p data-i18n="event.{key}.text">{text(item["text"]["ko"])}</p></li>'
              for key, item in notices(data)]
    blocks = {"events": rows, "notices": listed}
    for lang in LANGS:
        table: list[str] = []
        for key, item in activities(data):
            table.append(entry(f"event.{key}.summary", item["title"][lang]))
            if "place" in item:
                table.append(entry(f"event.{key}.place", item["place"][lang]))
            sheet = detail_sheet(item["details"], lang)
            table.append(f"'event.{key}.detail':")
            table += [f"  {js_str(part)} +" for part in sheet[:-1]] + [f"  {js_str(sheet[-1])},"]
        for key, item in notices(data):
            table += [entry(f"event.{key}.title", item["title"][lang]), entry(f"event.{key}.text", item["text"][lang])]
        blocks[f"events:{lang}"] = table
    return blocks


def picture(key: str, item: dict) -> list[str]:
    shown = item["picture"]
    if "image" in shown:
        return [
            '<figure class="timeline-item-media">',
            '  <img',
            '    class="timeline-item-img"',
            f'    src="{attr(shown["image"])}"',
            f'    width="{shown["width"]}"',
            f'    height="{shown["height"]}"',
            '    loading="lazy"',
            '    decoding="async"',
            f'    alt="{attr(shown["alt"]["ko"])}"',
            f'    data-i18n-alt="history.{key}.photoAlt"',
            '  />',
            '</figure>',
        ]
    return [
        f'<figure class="timeline-item-media" role="img" aria-label="{attr(shown["alt"]["ko"])}" '
        f'data-i18n-aria-key="history.{key}.photoAlt">',
        f'  <span class="timeline-mark" aria-hidden="true">{text(shown["mark"])}</span>',
        '</figure>',
    ]


def timeline_item(cell: list[str], year: str, key: str, title: str, body: str, cell_attrs: str = "") -> list[str]:
    return [
        '<li class="timeline-item">',
        '  <div class="timeline-item-grid">',
        f'    <div class="timeline-item-photo-cell"{cell_attrs}>',
        *[f"      {line}" for line in cell],
        '    </div>',
        '    <div class="timeline-item-rail">',
        '      <span class="timeline-marker" aria-hidden="true"></span>',
        '    </div>',
        '    <div class="timeline-item-body">',
        f'      {year}',
        '      <hr class="timeline-rule" />',
        f'      <h2 class="timeline-label" data-i18n="history.{key}.label">{text(title)}</h2>',
        f'      <p class="timeline-desc" data-i18n="history.{key}.desc">{text(body)}</p>',
        '    </div>',
        '  </div>',
        '</li>',
    ]


def milestones(data: dict) -> list[tuple[str, dict]]:
    ordered = sorted(data["milestones"], key=lambda item: item["date"])
    return [(f"t{index}", item) for index, item in enumerate(ordered, 1)]


def history_blocks(data: dict | None = None) -> dict[str, list[str]]:
    data = load("history") if data is None else data
    rows: list[str] = []
    for key, item in milestones(data):
        year = (f'<time class="timeline-year" datetime="{item["date"]}" data-i18n="history.{key}.year">'
                f'{milestone_date(item["date"], "ko")}</time>')
        rows += timeline_item(picture(key, item), year, key, item["title"]["ko"], item["text"]["ko"])
    roadmap = data["roadmap"]
    rows += timeline_item(['<div class="timeline-item-media timeline-item-media--next">'
                           '<span class="timeline-next-mark">NEXT</span></div>'],
                          '<span class="timeline-year">—</span>', "roadmap", roadmap["title"]["ko"],
                          roadmap["text"]["ko"], ' aria-hidden="true"')
    blocks = {"timeline": rows}
    for lang in LANGS:
        table: list[str] = []
        for key, item in milestones(data):
            table += [entry(f"history.{key}.photoAlt", item["picture"]["alt"][lang]),
                      entry(f"history.{key}.year", milestone_date(item["date"], lang)),
                      entry(f"history.{key}.label", item["title"][lang]),
                      entry(f"history.{key}.desc", item["text"][lang])]
        table += [entry("history.roadmap.label", roadmap["title"][lang]),
                  entry("history.roadmap.desc", roadmap["text"][lang])]
        blocks[f"timeline:{lang}"] = table
    return blocks


def content_errors(root: Path = ROOT) -> list[str]:
    """What the contracts cannot say: an activity ends on or after its start, a detail carries no
    markup but <strong>, no two milestones share a date and a milestone's image exists."""
    errors = []
    events_path = root / "data" / "content" / "events.json"
    if events_path.exists():
        for item in json.loads(events_path.read_text(encoding="utf-8")).get("activities") or []:
            name = (item.get("title") or {}).get("ko")
            if str(item.get("end")) < str(item.get("start")):
                errors.append(f"events.json: {name} ends before it starts")
            for field, pair in (item.get("details") or {}).items():
                for lang, value in (pair or {}).items():
                    bare = INLINE_MARKUP.sub("", str(value))
                    if "<" in bare or ">" in bare:
                        errors.append(f"events.json: {name} {field}.{lang} has markup other than <strong>")
                    elif str(value).count("<strong>") != str(value).count("</strong>"):
                        errors.append(f"events.json: {name} {field}.{lang} leaves a <strong> open")
    history_path = root / "data" / "content" / "history.json"
    if history_path.exists():
        items = json.loads(history_path.read_text(encoding="utf-8")).get("milestones") or []
        dates = [item.get("date") for item in items]
        if len(set(dates)) != len(dates):
            errors.append("history.json: two milestones share a date")
        for item in items:
            image = (item.get("picture") or {}).get("image")
            if image and not (root / image).is_file():
                errors.append(f"history.json: {item.get('date')} shows {image}, which does not exist")
    return errors
