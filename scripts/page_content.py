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
from collections import Counter
from pathlib import Path
from urllib.parse import quote

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
    """A JavaScript string literal in the tables' own style: single quotes, an apostrophe as \\'.
    Backslashes, line breaks and `</script` or `<!--` (which would break the page's script) are escaped."""
    value = (value.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace("\r", "\\r")
             .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))
    value = re.sub(r"<(/script|!--)", r"<\\\1", value, flags=re.I)
    return f"'{value}'"


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


def event_entry(item: dict) -> list[str]:
    """The world cup's start screen right in the card of the activity that runs it (owner 2026-10-14:
    the news page shows the live event, not a teaser photo and a button). The same markup as
    worldcup.html's (worldcup_entry); js/worldcup.js, loaded by the page only while the activity is
    running, fills it and sends the start to worldcup.html. The link below stays for a past activity
    and when the script does not run."""
    if item.get("entry") != "worldcup":
        return []
    return ['  <div class="wc-embed" data-wc-embed>',
            '    <div class="wc-view wc-intro" id="wcIntro" hidden>',
            *["      " + row for row in worldcup_entry()],
            '    </div>',
            *["    " + row for row in worldcup_chip()],
            '    <p class="wc-sr" id="wcStatus" role="status" aria-live="polite"></p>',
            '  </div>']


def event_link(link: str) -> str:
    """The original post opens in a new tab; a page of this site where people take part (an
    activity like the menu world cup) opens in place."""
    if link.startswith("https://"):
        return (f'  <a class="event-link" href="{attr(link)}" target="_blank" rel="noopener noreferrer">'
                '<span data-event-cta>당시 게시물</span> <span aria-hidden="true">↗</span>'
                '<span class="event-sr" data-i18n="event.newTab">(새 창)</span></a>')
    return (f'  <a class="event-link" href="{attr(link)}" data-event-page>'
            '<span data-event-cta>페이지 보기</span> <span aria-hidden="true">→</span></a>')


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
            *event_entry(item),
            event_link(item["link"]),
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
    return {"events": rows, "notices": listed}


def event_strings(data: dict | None = None) -> dict[str, dict[str, str]]:
    """The translations of the rows and notices, by language."""
    data = load("events") if data is None else data
    tables: dict[str, dict[str, str]] = {}
    for lang in LANGS:
        table = tables[lang] = {}
        for key, item in activities(data):
            table[f"event.{key}.summary"] = item["title"][lang]
            if "place" in item:
                table[f"event.{key}.place"] = item["place"][lang]
            table[f"event.{key}.detail"] = "".join(detail_sheet(item["details"], lang))
        for key, item in notices(data):
            table[f"event.{key}.title"] = item["title"][lang]
            table[f"event.{key}.text"] = item["text"][lang]
    return tables


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
    return {"timeline": rows}


def history_strings(data: dict | None = None) -> dict[str, dict[str, str]]:
    """The translations of the timeline, by language."""
    data = load("history") if data is None else data
    tables: dict[str, dict[str, str]] = {}
    for lang in LANGS:
        table = tables[lang] = {}
        for key, item in milestones(data):
            table[f"history.{key}.photoAlt"] = item["picture"]["alt"][lang]
            table[f"history.{key}.year"] = milestone_date(item["date"], lang)
            table[f"history.{key}.label"] = item["title"][lang]
            table[f"history.{key}.desc"] = item["text"][lang]
        table["history.roadmap.label"] = data["roadmap"]["title"][lang]
        table["history.roadmap.desc"] = data["roadmap"]["text"][lang]
    return tables


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
            if item.get("entry") and (item["entry"] != "worldcup" or item.get("link") != "worldcup.html"):
                errors.append(f"events.json: {name} shows the entry {item['entry']!r}, which only worldcup.html has")
            if "previewFrom" in item and (not item.get("entry") or str(item["previewFrom"]) > str(item.get("start"))):
                errors.append(f"events.json: {name} has a previewFrom that is not on or before the start of an activity with an entry")
            link = str(item.get("link") or "")
            if not link.startswith("https://") and not (root / link).is_file():
                errors.append(f"events.json: {name} links {link}, which is not a page of this site")
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
    errors += worldcup_errors(root)
    return errors


def worldcup_entry(data: dict | None = None) -> list[str]:
    """The world cup's start screen, the one markup of worldcup.html and of the event card that runs
    it (owner 2026-10-14: "초입이 재미있어야"). js/worldcup.js fills the floating photos, the headline's
    round, the tiles and the preview. Inside <div class="wc-view wc-intro" id="wcIntro" hidden>."""
    size = (load("worldcup") if data is None else data).get("size", 32)
    return [
        '<div class="wc-floaters" id="wcFloaters" aria-hidden="true"></div>',
        '<div class="wc-intro-card">',
        f'  <h3 class="wc-intro-title" id="wcIntroTitle">오늘의 <span class="wc-hl">{size}강</span>, 뭐가 나올까?</h3>',
        '  <p class="wc-intro-tone" data-i18n="wc.intro.tone">시험기간으로 지친 당신! 메뉴나 골라~</p>',
        '  <p class="wc-ended" data-wc-show="ended" hidden><span aria-hidden="true">🏁</span> '
        '<span data-i18n="wc.ended">이벤트 종료 · 그래도 계속 즐길 수 있어요</span></p>',
        # The tiles and the preview are one mystery box before the launch (owner 2026-10-14: blurred, nothing
        # revealed): js/worldcup.js makes the body inert and hidden from assistive tech while the gate says
        # `soon`, css/worldcup-entry.css blurs it, and the lock over it (data-wc-show) says when it opens.
        '  <div class="wc-mystery" id="wcMystery">',
        '    <div class="wc-mystery-body" id="wcMysteryBody">',
        '      <p class="wc-sr" id="wcCatsLabel" data-i18n="wc.catLabel">카테고리</p>',
        '      <div class="wc-tiles" id="wcCats" role="group" aria-labelledby="wcCatsLabel"></div>',
        '      <div class="wc-preview" id="wcPreview" hidden>',
        '        <p class="wc-preview-label"><span class="wc-preview-emoji" aria-hidden="true">👀</span> '
        '<span data-i18n="wc.preview">이 중에서 나와요!</span></p>',
        '        <ul class="wc-preview-photos" id="wcPreviewPhotos"></ul>',
        '      </div>',
        '    </div>',
        '    <p class="wc-mystery-lock" id="wcMysteryLock" data-wc-show="soon" hidden>'
        '<span class="wc-sr" data-wc-fmt="wc.mystery.sr">카테고리는 곧 공개돼요</span>'
        '<span class="wc-mystery-badge" aria-hidden="true"><span>🔒</span> <span data-wc-fmt="wc.mystery.badge">곧 공개</span></span></p>',
        '  </div>',
        '  <div class="wc-intro-actions">',
        # Before the launch (js/worldcup-gate.js): the start button gives way to this locked pill.
        '    <p class="wc-locked" id="wcLocked" data-wc-show="soon" hidden><span class="wc-locked-pill">'
        '<span aria-hidden="true">🔒</span> <span data-wc-fmt="wc.locked">곧 오픈</span></span> '
        '<span class="wc-locked-count" data-wc-countdown></span></p>',
        '    <button type="button" class="wc-btn wc-btn--big" id="wcStart"><span class="wc-btn-emoji" aria-hidden="true">🎰</span>'
        f'<span id="wcStartLabel">{size}강 시작</span></button>',
        '    <button type="button" class="wc-btn wc-btn--big wc-btn--resume" id="wcResume" hidden><span class="wc-btn-emoji" '
        'aria-hidden="true">▶</span><span id="wcResumeLabel"></span></button>',
        '    <button type="button" class="wc-link" id="wcNew" hidden><span data-i18n="wc.newStart">새로 시작</span></button>',
        '  </div>',
        '</div>',
    ]


def worldcup_chip() -> list[str]:
    """The one photo-credit chip (owner 2026-10-14): every photo is a cropped, resized Wikimedia Commons
    file, credited by name where it is shown large (the match, the winner)."""
    return ['<p class="wc-chip"><span aria-hidden="true">📷</span> <span data-i18n="wc.photoChip">'
            '사진 위키미디어 공용(잘라서 줄임)</span></p>']


# The launch gate's texts (js/worldcup-gate.js): the locked pill, the countdown, the dates. The home
# page's promo carries these besides its own `home.wc` family.
WORLDCUP_GATE_KEYS = ("wc.locked", "wc.dateShort", "wc.months", "wc.countdown.d", "wc.countdown.long",
                      "wc.countdown.hours", "wc.countdown.minutes")
# The translation keys the start screen uses (the event page carries these, not the whole `wc` family).
WORLDCUP_ENTRY_KEYS = ("wc.intro.title", "wc.intro.tone", "wc.catLabel", "wc.preview", "wc.start", "wc.resume",
                       "wc.newStart", "wc.round.n", "wc.round.semi", "wc.round.final", "wc.catCount", "wc.catLanded",
                       "wc.cat.all", "wc.cat.korean", "wc.cat.chinese", "wc.cat.japanese", "wc.cat.western",
                       "wc.cat.world", "wc.cat.snack", "wc.cat.dessert", "wc.cat.random", "wc.cat.randomSub",
                       "wc.photoChip", "wc.ended", "wc.state.soon", "wc.mystery.badge", "wc.mystery.sr", *WORLDCUP_GATE_KEYS)
# Every dish photo is images/worldcup/<id>.jpg; the event page's slim data lists no paths.
WORLDCUP_PHOTO_PATH = "images/worldcup/{id}.jpg"


def worldcup_blocks(data: dict | None = None) -> dict[str, list[str]]:
    """The world cup's dishes as a script block in worldcup.html: data/content/ is never deployed
    (.vercelignore), so the page carries them instead of fetching them."""
    data = load("worldcup") if data is None else data
    payload = json.dumps({"size": data.get("size", len(data["dishes"])), "basis": data["basis"],
                          "dishes": data["dishes"], "categories": data.get("categories") or {},
                          "photos": data.get("photos") or {}},
                         ensure_ascii=False)
    return {"worldcup": [
        "<script>",
        "  // Written by scripts/sync_site_chrome.py from data/content/worldcup.json; edit that, not this.",
        "  window.BABDODUK_WORLDCUP = " + payload.replace("<", "\\u003c") + ";",
        "</script>",
    ], "worldcup-font": [
        "<!-- Jua (OFL) for the world cup's display lettering only (titles, category tiles, buttons, the",
        "     splash and the start gacha): just the letters of WORLDCUP_JUA_KEYS in scripts/page_content.py. -->",
        f'<link href="{worldcup_font_url()}" rel="stylesheet" />',
    ], "worldcup-entry": worldcup_entry(data), "worldcup-chip": worldcup_chip()}


def worldcup_font_block() -> dict[str, list[str]]:
    """The display font alone, for the event page's start screen."""
    return {"worldcup-font": worldcup_blocks()["worldcup-font"]}


def home_font_block() -> dict[str, list[str]]:
    """The display font for the home page's world cup promo: just the letters of HOME_JUA_KEYS."""
    return {"worldcup-font": [
        "<!-- Jua (OFL) for the world cup promo's lettering only: just the letters of HOME_JUA_KEYS in",
        "     scripts/page_content.py. -->",
        f'<link href="{worldcup_font_url(HOME_JUA_KEYS)}" rel="stylesheet" />',
    ]}


def worldcup_gate(data: dict | None = None) -> dict:
    """The world cup's launch window, read from the activity of data/content/events.json that shows its
    start screen: the first and last day (KST, both included) and, for lab only, `previewFrom`."""
    data = load("events") if data is None else data
    item = next(item for item in data["activities"] if item.get("entry") == "worldcup")
    gate = {"start": item["start"], "end": item["end"]}
    if "previewFrom" in item:
        gate["previewFrom"] = item["previewFrom"]
    return gate


def worldcup_gate_blocks(data: dict | None = None) -> dict[str, list[str]]:
    """js/worldcup-gate.js: the launch window as a script block (data/content/ is never deployed)."""
    return {"worldcup-gate": ["window.BABDODUK_WC_WINDOW = " + json.dumps(worldcup_gate(data)) + ";"]}


def catalog_names(root: Path = ROOT) -> dict[str, list[str]]:
    """[Korean, English] name of every catalog dish."""
    names = {}
    catalog = json.loads((root / "data" / "foods" / "catalog.json").read_text(encoding="utf-8"))
    for pack in catalog.get("packs") or []:
        for item in json.loads((root / pack["src"]).read_text(encoding="utf-8")).get("items") or []:
            names[item["id"]] = [item.get("nameKo") or "", item.get("nameEn") or ""]
    return names


def worldcup_entry_data_blocks(data: dict | None = None) -> dict[str, list[str]]:
    """What the start screen needs on the event page, without the catalog's 1.3 MB and the photo
    credits: the game size, each dish's Korean and English name and category, and where the photos are. Written into
    js/worldcup-entry-data.js, which the page loads only while the world cup runs."""
    data = load("worldcup") if data is None else data
    names = catalog_names()
    categories = data.get("categories") or {}
    payload = json.dumps({"size": data.get("size", len(data["dishes"])), "photoPath": WORLDCUP_PHOTO_PATH,
                          "dishes": {dish: [*names[dish], categories[dish]] for dish in data["dishes"]}},
                         ensure_ascii=False, separators=(",", ":"))
    return {"worldcup": ["window.BABDODUK_WORLDCUP = " + payload.replace("<", "\\u003c") + ";"]}


# The world cup's display lettering is Jua (owner 2026-10-14: a playful entry). Google Fonts sends
# only the letters asked for (`text=`), so the link carries every letter these labels use, in both
# languages. Dish names are never set in Jua (dynamic text would mix fonts letter by letter).
WORLDCUP_JUA_KEYS = ("wc.locked", "wc.ended", "wc.months", "wc.dateShort", "wc.title", "wc.intro.title", "wc.start", "wc.resume", "wc.newStart", "wc.preview",
                     "wc.cat.all", "wc.cat.korean", "wc.cat.chinese", "wc.cat.japanese", "wc.cat.western",
                     "wc.cat.world", "wc.cat.snack", "wc.cat.dessert", "wc.cat.random", "wc.catGame",
                     "wc.round.n", "wc.round.semi", "wc.round.final", "wc.gacha.drawing", "wc.gacha.ask",
                     "wc.gacha.skip", "wc.splash.quarter", "wc.splash.semi", "wc.splash.final", "wc.vs")


# The home page's promo sets only its title, its state line and its button in Jua (months are the
# English month names of the date it shows).
HOME_JUA_KEYS = ("home.wc.title", "home.wc.soon", "home.wc.live", "home.wc.cta.soon", "home.wc.cta.live",
                 "wc.months", "wc.dateShort")


def worldcup_font_letters(keys: tuple[str, ...] | None = None) -> str:
    letters = set("0123456789 !")
    for lang in LANGS:
        strings = json.loads((ROOT / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))
        for key in WORLDCUP_JUA_KEYS if keys is None else keys:
            letters |= set(re.sub(r"\{\w+\}", "", strings[key]))
    return "".join(sorted(letters))


def worldcup_font_url(keys: tuple[str, ...] | None = None) -> str:
    return "https://fonts.googleapis.com/css2?family=Jua&display=swap&text=" + quote(worldcup_font_letters(keys), safe="")


# The world cup's categories (owner, 2026-10-14): each dish of the pool is in exactly one, taken from
# the catalog's `cuisineGroup`. "all" is the whole pool and is not stored. js/worldcup.js lists the
# same keys in the order of the chips.
WORLDCUP_CATEGORIES = ("korean", "chinese", "japanese", "western", "world", "snack", "dessert")
WORLDCUP_CATEGORY_BY_GROUP = {
    "korean": "korean", "chinese": "chinese", "japanese": "japanese",
    "western": "western", "italian": "western", "american": "western", "french": "western", "mexican": "western",
    "southeast-asian": "world", "indian": "world", "middle-eastern": "world", "fusion": "world",
    "snack": "snack", "dessert": "dessert",
}


def worldcup_category(item: dict) -> str | None:
    """The world cup category of one catalog dish, or None when its cuisineGroup is not mapped."""
    return WORLDCUP_CATEGORY_BY_GROUP.get(item.get("cuisineGroup") or "")


def worldcup_errors(root: Path = ROOT) -> list[str]:
    """data/content/worldcup.json: a pool of catalog dishes, each with a photo and exactly one category,
    at least as large as a game (`size`, a power of two); every category holds at least a game of dishes."""
    path = root / "data" / "content" / "worldcup.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    dishes = data.get("dishes") or []
    errors = []
    photos = data.get("photos") or {}
    for dish in dishes:
        photo = photos.get(dish)
        if not photo:
            errors.append(f"worldcup.json: {dish} has no photo")
        elif not (root / str(photo.get("image") or "")).is_file():
            errors.append(f"worldcup.json: {dish} shows {photo.get('image')}, which does not exist")
        elif photo.get("image") != WORLDCUP_PHOTO_PATH.format(id=dish):
            errors.append(f"worldcup.json: {dish} shows {photo.get('image')}, not {WORLDCUP_PHOTO_PATH.format(id=dish)}")
    errors += [f"worldcup.json: a photo for {dish}, which is not in the bracket" for dish in photos if dish not in dishes]
    size = data.get("size", len(dishes))
    if size < 4 or size & (size - 1) or len(dishes) < size:
        errors.append(f"worldcup.json: a game of {size} from {len(dishes)} dishes is not a bracket")
    if len(set(dishes)) != len(dishes):
        errors.append("worldcup.json: a dish is listed twice")
    categories = data.get("categories") or {}
    errors += [f"worldcup.json: {dish} has no category" for dish in dishes if dish not in categories]
    errors += [f"worldcup.json: a category for {dish}, which is not in the bracket" for dish in categories if dish not in dishes]
    errors += [f"worldcup.json: {dish} is in the category {key!r}, which does not exist"
               for dish, key in categories.items() if key not in WORLDCUP_CATEGORIES]
    for key in WORLDCUP_CATEGORIES:
        have = sum(1 for dish in dishes if categories.get(dish) == key)
        if have < size:
            errors.append(f"worldcup.json: the category {key!r} has {have} dishes, fewer than a game of {size}")
    catalog_path = root / "data" / "foods" / "catalog.json"
    if catalog_path.exists():
        names = {}
        groups = {}
        for pack in json.loads(catalog_path.read_text(encoding="utf-8")).get("packs") or []:
            pack_path = root / str(pack.get("src") or "")
            if pack_path.is_file():
                items = json.loads(pack_path.read_text(encoding="utf-8")).get("items") or []
                names |= {item.get("id"): item.get("nameKo") or "" for item in items}
                groups |= {item.get("id"): worldcup_category(item) for item in items}
        # The category follows the catalog (cuisineGroup), so a dish cannot drift into another one.
        errors += [f"worldcup.json: {dish} is in the category {categories[dish]!r}, but the catalog says {groups[dish]!r}"
                   for dish in dishes if dish in categories and dish in groups and categories[dish] != groups[dish]]
        errors += [f"worldcup.json: {dish} is not a catalog dish" for dish in dishes if dish not in names]
        families = Counter(same_dish(dish, names[dish]) for dish in dishes if dish in names)
        errors += [f"worldcup.json: {count} dishes are {family}; at most {SAME_DISH_LIMIT} of the same dish"
                   for family, count in families.items() if count > SAME_DISH_LIMIT]
    return errors


# The owner's variety rule (2026-10-13): at most five variants of the same dish in the pool. A dish
# whose Korean name contains one of these words is that dish (the longest match wins: 볶음밥, not 밥).
SAME_DISH_LIMIT = 5
SAME_DISH = ("김밥", "치킨", "떡볶이", "라볶이", "라면", "피자", "버거", "초밥", "스시", "우동", "만두", "볶음밥", "국밥",
             "파스타", "샐러드", "케이크", "샌드위치", "카레", "커리", "냉면", "쌀국수", "짬뽕", "짜장", "탕수육", "돈까스",
             "카츠", "와플", "토스트", "마라", "컵밥", "덮밥", "비빔밥", "정식", "세트", "도시락", "찌개", "전골", "국수",
             "꼬치", "롤", "빙수", "타코", "부리또", "케밥", "스테이크", "리조또", "그라탕", "튀김", "덴뿌라", "말이",
             "볶음면", "소바", "라멘")


def same_dish(dish: str, name_ko: str) -> str:
    """The family a pool dish counts against: a SAME_DISH word in its Korean name, else the dish itself."""
    name = name_ko.replace(" ", "")
    hits = [word for word in SAME_DISH if word in name]
    return max(hits, key=len) if hits else dish
