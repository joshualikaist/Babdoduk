# Home free-food calendar

Owner decisions, 2026-10-01: the home answers one question first, "what free food is on today
or soon?". The Phase 1 layout (variant A) and the Phase 2 visual spec are approved; this is the lab
prototype. It replaces the old dated status strip and the shelf's TODAY tile.

## What it shows

One surface (`section#homeCal`), right below the hero copy:

* **Answer line** (today's status only):
  `오늘 2개 · 12:00부터` · `오늘은 없어요 · 다음 10월 7일 (수)` ·
  `오늘 일정은 끝났어요 · 다음 …` · `오늘 일정은 끝났어요` · `예정된 꽁밥이 없어요`.
* **Month grid**: seven columns, Monday first (월 … 일), like the cafeteria week and the hub's
  "이번 주". 4–6 rows; other-month days are muted.
* **Selected day**: that date's events, one row each (title / time · place / food · 사전 신청).
  A row opens inline (one at a time) for the full time and place, eligibility, the sign-up deadline,
  the sign-up link and a public original post. There is no modal.
* **다가오는 꽁밥**: up to four upcoming events on dates after the selected day (or after today when a
  past day is selected). Hidden when there are none, never an empty heading.
* **Footer**: `전체 일정 →` (the hub, `ggongbab.html#free`) and `마지막 발행 {time}`.

On phones the order is copy, calendar, cafeteria line, collage. On wide screens the collage stays
beside the copy on the paper band and the calendar splits into the day (left) and the month (right,
336 px).

## Data and rules

* **Sources**: the same static files as the hub, `data/ggongbab/latest.json` and
  `data/ggongbab/archive/index.json` (a 404 means nothing has been archived yet). No database and no
  Realtime client. Nothing else enters the grid: no cafeteria menus, stories, Babdoduk events or
  campus news.
* **Eligibility and time**: `js/ggongbab-select.js` (`isPublic`, `isUpcoming`, `eventEnd`), so the
  explicit-food rule and the 3-hour open-ended window are the hub's. A row is upcoming while it has
  not ended, and past afterwards. Rows are keyed by `id` and the live copy wins over an archived one.
* **KST**: dates are computed from `toKst`/`ymd` and whole-day arithmetic in UTC, so the browser's
  time zone never changes "today".
* **Retained window**: the archive's `windowDays` (30) before today. Older days are inert (not
  focusable, no marker) and the month arrows stop there. Forward browsing reaches two months past
  today's month, or further if a published event is later.
* **Default selection**: today when it has an event that has not ended; otherwise the next date that
  has one (the answer line still speaks about today); otherwise today. The grid always opens on
  today's month. `오늘` (shown only on another month) returns there with the same rule. Coming back to
  the tab after midnight (KST) starts again from the new today; there are no timers.
* **Markers**: an upcoming event is a filled accent dot, a past one a hollow muted ring; at most two
  per day, never a count, title or icon. The marker slot is always reserved.
* **Links**: a sign-up link while the event is open (not ended, deadline not passed); an original
  post only for public web sources (`kaist_public`, `manual`). Mail and other internal sources are
  named in plain text (`출처 · KAIST 메일`). Mail-system hosts are never linked.
* **Loading and errors**: the grid renders at once; dots appear when data arrives. If the live
  snapshot fails the module says `꽁밥 일정을 불러오지 못했어요` and links to the hub; it never shows an
  empty-day message for data it could not read. If only the archive fails, past days say
  `지난 기록을 불러오지 못했어요` instead of `기록 없음`.

## Look

A pocket calendar on the warm home canvas: one `--color-surface` panel with a hairline border and
`--radius-lg`, no shadow, no inner cards, no cell borders. Today is an accent ring with an accent
numeral, the selected date an ink disc (`--color-ink`), today and selected together an accent disc.
The only colour is `--color-accent`. Type is the site's Noto Sans KR at 500/700/800 (no 900).
Motion is limited to 140 ms colour changes and is removed under `prefers-reduced-motion`.

## Accessibility

APG date-grid pattern: `table role="grid"` labelled by the month; focusable `gridcell`s with a
roving tabindex, `aria-selected`, `aria-current="date"` and a full-date label that includes the event
count. Arrow keys move by day and week, Home/End to the week's ends, PageUp/PageDown by month,
Enter/Space select. A polite live region announces the selected day. Event rows are buttons with
`aria-expanded`/`aria-controls`. Presence is never colour alone (shape and label), forced-colors
keeps today, the selection and the markers, and phone cells are 44 px or wider at 390 px.

## FIRST_COME_PUBLIC_CONTRACT_PENDING

The pipeline records a first-come supply limit internally (`supply_limited`, `supply_limit_text`,
`end_condition` in `scripts/ggongbab/models.py`; `rule_parser.supply_limit`), but the public event
schema (`GG_EVENT_SCHEMA` in `scripts/validate_content.py`) does not export it. The calendar therefore
shows no `선착순` marker and never derives one from titles, summaries or food text.

The owner has agreed that the public contract may later expose the verified fields. That is a
separate, protected change: the exporter, `GG_EVENT_SCHEMA`, the privacy tests and the feed docs.
Once exported, the row's metadata line shows `선착순`, or `선착순 100명` only when the count is in the
data; a structured count would let English say "First 100" without parsing Korean text.

## Tests

`tests/test_home_calendar.py` (month math, KST, states, markers, default selection, disclosure,
errors, keyboard, strings and layout) and the home checks in `scripts/check_site_ui.py`
(`home_summary`, `home_hero_shelf`, `structure_and_failures`).
