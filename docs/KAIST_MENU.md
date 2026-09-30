# KAIST cafeteria: this week's menus

The 학식 tab of `ggongbab.html` shows the official KAIST cafeteria menus for the whole current
week, one date at a time. Home (`index.html`) and the magazine's `#what` section (`mukbang.html`) show only today's summary.

## Week

A week runs Monday to Sunday in KST (`Asia/Seoul`), whatever the server's or the viewer's timezone.
* **Collector:** `refresh_kaist_menu.kst_today()` converts an aware clock to KST, and `week_of(day)`
  starts at `day - weekday()`.
* **Browser:** `BabdodukKaistMenu.weekDates(todayKst)` does the same calendar arithmetic in UTC, so
  month and year boundaries and leap days are exact.

## Data

| File | Meaning |
|---|---|
| `data/kaist-menu/YYYY-MM-DD.json` | The validated menu of that date. Written only when at least one restaurant has a menu for it. |
| `data/kaist-menu/latest.json` | **Today's** snapshot, byte-identical to today's dated file. Home, the magazine's `#what` section and the hub's today view read it. It never becomes the week. |
| `data/kaist-menu/week.json` | A small index of the current week. It holds no menus. |

`week.json`:

```json
{
  "weekStart": "2026-09-28",
  "weekEnd": "2026-10-04",
  "generatedAt": "2026-09-30T06:00:04+09:00",
  "timezone": "Asia/Seoul",
  "days": [
    {"date": "2026-09-28", "available": true, "restaurantCount": 8, "status": "AVAILABLE", "fetchedAt": "2026-09-28T06:00:02+09:00"},
    {"date": "2026-10-04", "available": false, "restaurantCount": 0, "status": "NOT_PUBLISHED_YET", "fetchedAt": null}
  ]
}
```

(Only two of the seven `days` are shown.)

A dated file keeps the earlier schema (`date`, `dateLabel`, `fetchedAt`, `source`, `restaurants`)
and adds:
* `status` (`AVAILABLE`);
* `coverage`: `{requested, fetched, failed, carried}`. These are restaurant codes and counts only,
  never error text.

### Day states

| State | Meaning | Dated file |
|---|---|---|
| `AVAILABLE` | This run got a menu for the date. | written |
| `NOT_PUBLISHED_YET` | Every restaurant answered with the official menu table, and every table was empty. | none |
| `FETCH_FAILED` | No usable answer, and nothing was saved before. | none |
| `STALE_SAVED_DATA` | This run could not confirm the date (a failure, a changed page, or an empty answer where a menu was saved before), so the saved file stays. | kept unchanged |

## Collection

`python scripts/refresh_kaist_menu.py` runs in `content-refresh` (`magazine-daily.yml`) at
06:00, 10:30 and 16:30 KST, as before. It is never polled.

**Which days a run fetches:**
* The first run of a week, or `--full-week`, fetches all seven days (baseline).
* Every other run fetches only today and the rest of the week. Completed past days are not
  fetched again.

**Requests:** one per restaurant and date, 8 restaurants.

| Day of the week | Requests per run |
|---|---|
| Monday (baseline) | 56 |
| Tuesday | 48 |
| Wednesday | 40 |
| Thursday | 32 |
| Friday | 24 |
| Saturday | 16 |
| Sunday | 8 |

On average that is about 32 requests per run and about 96 per day (the old today-only collector
made 8 per run).

**Pacing and failure limits:**
* There is a 0.25 s pause between requests.
* Each request has a 25 s timeout.
* A run stops asking after 8 consecutive failures (one date's worth) or after 8 minutes. The
  remaining dates keep their saved files.
* In the worst case (the site is down), a run makes 8 requests and ends in about 200 s.

**Failure safety:**
* A page without the menu table is an upstream change (`MenuParseError`), never "no meals". An
  unpublished date still renders the table, with three empty cells; this was verified live on
  2026-09-28.
* A known-good daily file is never replaced by an empty, failed or partial answer.
* If some restaurants fail on a date that already has a saved file, their saved entries are
  carried over and listed in `coverage.carried`.
* If today has no usable menu, `latest.json` keeps the previous day's file and the script exits 2.
  The workflow treats exit 2 as "keep previous files".
* Writes are atomic (temporary file, then rename).
* Workflow logs print exception class names only.

**Publication:** `publish_generated.py` mirrors `data/kaist-menu/` from the main-branch run onto
lab and main.

## Page

* **Loading:** the hub loads `latest.json` for today. `week.json` and other dates are requested
  only when someone picks another date, or when `latest.json` still names an earlier day (just
  after midnight): then `week.json` and today's `YYYY-MM-DD.json` are read and, when today's file
  exists, used instead (`loadTodayMenu`, the same rule for home and the magazine summary).
  * `week.json` comes first, so a date the index marks `NOT_PUBLISHED_YET` is not requested at all.
  * Then comes `YYYY-MM-DD.json`. A loaded date is kept in memory for the page session.
  * A missing or older `week.json` is ignored.
* **Selection:**
  * The selected date is page state and every load starts at today KST.
  * The meal (아침/점심/저녁) keeps its saved behavior and stays the same when the date changes.
  * Favorites are the same on every date.
* **Freshness:** `isDataForSelectedDate(data, date)` decides whether a payload is right for the
  selected date; `isToday(date)` is a separate question. Only today's view can be stale: when
  `latest.json` still holds an earlier day and today's dated file is absent, the saved-menu notice
  appears. A future date is
  never called stale.
* **States:**

  | State | Message |
  |---|---|
  | No menu for the date (404, or `NOT_PUBLISHED_YET`) | 아직 올라온 메뉴가 없어요 / No menu has been posted yet |
  | Request failed, or a `FETCH_FAILED` date | 메뉴를 불러오지 못했어요 / Couldn’t load the menu, with a retry button |

* **Top metric:** the page's top metric (오늘 꽁밥 N개 · 학식 N곳) always describes today. Browsing
  other dates does not change it.
* **Date strip:** seven buttons in a 7-column grid that fits 360 px, so the selected date is always
  visible without internal scrolling.
  * Selected uses the filled ink style of the hub tabs, with `aria-pressed`.
  * Today carries a small 오늘/Today word, with `aria-current="date"`.
  * Left/Right/Home/End move focus between dates.
* No deep link: `ggongbab.html#menu` opens the tab as before.

## Tests

* `tests/test_kaist_menu_week.py`, with fake pages and no KAIST calls:
  * week arithmetic, including month, year and leap-day boundaries;
  * KST versus host timezone;
  * filenames and `week.json`;
  * `latest.json` staying today's;
  * unpublished days;
  * partial failure;
  * empty-answer and parser-change preservation;
  * the failure breaker and the time budget;
  * exit code 2;
  * validator cases.
* `scripts/check_ggongbab_ui.py`, `weekly_cafeteria`:
  * date strip, today versus selected, month boundary;
  * meal kept across dates, cards and counts per date;
  * favorites, page cache, no-menu and failure states;
  * no stale label on future dates, unchanged top metric;
  * escaping, keyboard;
  * KO/EN at 360/390/1440, no page overflow;
  * a browser in another timezone;
  * a missing `week.json`.
* `scripts/validate_content.py` checks:
  * every dated file's date against its filename;
  * that `latest.json` matches its dated file;
  * that `week.json` is exactly Monday–Sunday of `weekStart`, generated during that week, with
    unique days, non-negative counts and availability consistent with the dated files.
