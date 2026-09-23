---
name: ui-review
description: Visual, responsive and accessibility review of Babdoduk pages (home hero and banner shelf, food hub, magazine, events, food log) at 1920, 1440, 768, 390 and 360 px, using real screenshots plus state and failure checks.
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
  - primary: `오늘의 한 끼 보기` → `ggongbab.html`;
  - secondary: `메뉴 고르기` → `mukbang.html#what`.
- The collage is labelled as atmosphere, not today's menu.
- The today strip keeps the `#homeMenuStatus` and `#homeFreeStatus` states and the "마지막 발행 {time}" wording. It makes no "latest", "real-time" or "live" claims.
- Banner shelf:
  - order: today and pick (wider, level 2), then magazine, event and map (level 3);
  - native swipe and wheel scrolling, with a visible peek of the next card;
  - desktop buttons that use `aria-disabled` at the ends;
  - no autoplay, and the map link opens with `rel="noopener"`.
- Nothing is invented: no fabricated events, menus, counts or restaurant inventory.

Report findings by size and state, split into must-fix (regressions, accessibility failures, dishonest states) and polish.
