---
name: ui-review
description: Visual, responsive and accessibility review of Babdoduk pages (home hero and free-food calendar, food hub, magazine, events, and the lab-only food log) at 1920, 1440, 768, 390 and 360 px, locally and on the deployed babdoduk-lab candidate, using real screenshots plus state and failure checks.
---

# UI review

Review rendered pages, not only CSS or DOM numbers. Take the screenshots and look at them.

## Setup
- Serve the repository on loopback with `python scripts/check_ggongbab_ui.py --serve --port 8000`. Its safe server returns 404 for dot-paths except the preview JSON. Stop it when done.
- Capture each page at 1920×1080, 1440×900, 768×1024, 390×844 and 360×800 with Playwright:
  - use `channel="chrome"`, and `ignore_default_args=["--hide-scrollbars"]` to keep the Windows classic scrollbars;
  - capture Korean and English (set `localStorage 'babdoduk-lang'`);
  - wait for `document.fonts.ready` first.
- For pages that read data, repeat with failing data (route `**/data/**` to 503) and with stale or empty payloads.
- `python scripts/check_site_ui.py --screenshots` saves the offline gate's views to `.local/site-ui-shots/`. Fonts are blocked in that run by design.

## On babdoduk-lab (before any production release)
- Review the deployed lab commit, not only a local server: https://babdoduk-lab.vercel.app after its `Vercel – babdoduk-lab` status for that exact `lab` SHA succeeded. Record the SHA and the URLs checked; this is the `LAB_URL_TESTED` evidence for `/release-babdoduk`.
- For shared pages, compare lab with production (https://www.babdodukms.com, same path and query). Lab must show at least the production baseline; every difference must be an intentional lab-only experiment or the change under review. An unexplained regression on lab fails the review.
- Check Korean and English, at 1440, 390 and 360 at least, with no horizontal overflow and no JS errors.

## Every size
- No horizontal overflow of `html` or `body`, and the nav and footer stay inside the viewport.
- Keyboard focus is visible and in order, targets are about 44 px, Escape closes menus, and nothing is reachable only by hover.
- `prefers-reduced-motion: reduce` removes non-essential motion, and nothing moves on its own.
- Hierarchy: one `h1` and no skipped heading levels. Korean wraps with `keep-all`, and long English words still wrap.
- Images: decorative images have `alt=""`. Above-the-fold images are not lazy and carry `width`/`height`. No image is heavier than its display size needs.
- States: loading, empty, stale and error are each stated in words. A failure never removes the page's main task.
- English text does not overflow controls or cards.

## Home
- One editorial hero, with its primary and secondary actions in the first mobile screen:
  - primary: `오늘의 꽁밥 보기` → `ggongbab.html`;
  - secondary: `메뉴 뽑기` → `choose.html`.
- The campus map (`#homeMap`, `js/home-map.js`, `docs/CAMPUS_MAP.md`) replaced the photo collage: wider than 720px it sits beside the copy; at 720px and below only the `꽁밥 지도` button (`#homeMapOpen`, at least 44px) shows and opens it in a dialog. Its pins show only events of the day the calendar shows.
- The free-food calendar (`#homeCal`, `docs/HOME_CALENDAR.md`) replaced the old status strip; `#homeFreeStatus` is gone. The cafeteria line keeps the `#homeMenuStatus` states and the calendar the "마지막 변경 {time}" wording. Neither makes "latest", "real-time" or "live" claims.
- Below the hero only the calendar, the cafeteria line and the map (owner 2026-11-02): the former groups 01 오늘 먹기, 02 읽어보기 and 03 밥도둑 소식 are gone; the map, Instagram and history stay in the More menu, the magazine and news in the top bar.
- The wordmark keeps the original holographic gradient.
- Nothing is invented: no fabricated events, notices, menus, counts or restaurant inventory.

Report findings by size and state, split into must-fix (regressions, accessibility failures, dishonest states) and polish.
