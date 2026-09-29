# Babdoduk design system

Status: proposed shared rules for lab. This describes target behavior; current CSS still has page-specific styles. Migrate incrementally after a representative page proves the rule. `PRD.md` determines which experience leads.

## Identity and repeated devices

Babdoduk is a warm, food-centered editorial product with a useful KAIST campus tool inside it. It should feel human and confident, with playful moments at decisions and quiet clarity around dates and eligibility. Avoid a generic SaaS dashboard, universal frosted glass, gratuitous gradient and decoration that obscures the meal task.

Five repeated devices make the product recognizable beyond its logo:

1. A short, substantial Korean headline with small editorial numbering where numbering helps reading order.
2. A consistent campus food stamp: KST date, meal, building/place and availability or registration state, only when supported by source data.
3. Food imagery with a deliberate crop and visible provenance. Atmospheric photography must not imply a photographed item is the actual menu/event food.
4. One plain, human annotation about the next decision, distinct from factual source metadata.
5. Playful motion or language only in the optional picker moment; information lookup, errors and accessibility remain calm.

## Foundations

| Role | Proposed token/rule | Current reference |
| --- | --- | --- |
| Canvas | `--color-canvas: #f7f4ee` candidate; page overrides require a named reason | `site.css` default `#f7f7f5`, home `#f5f1e8`, magazine `#f7f4ee` |
| Paper surface | `--color-surface: #fffdf8` candidate, with a muted surface token for grouped controls | Current `--surface` and magazine paper |
| Ink | `--color-ink: #1e1d1a` candidate; muted ink remains distinct and contrast-tested | Current `--text`, magazine ink |
| Food accent | `--color-accent: #b43d27` for shared navigation and readable links; home still has editorial `#d9472b` | Older shared `--accent: #ff675d` remains during migration |
| States | Semantic `info`, `success`, `warning`, `error`, `unknown`; never color-only or inferred from “food” | Existing loading/error/review states |
| Borders | One subdued separator role plus strong focus/control boundary | Current `--border`, `--border-strong` |
| Shadows | Small elevation only for overlap/floating controls; ordinary cards use surface and border | Existing `--shadow-*` |
| Scrollbar | Keep warm track, distinguishable thumb, hover and corner; preserve forced-color native behavior | `site.css` scrollbar contract |

The Babdoduk wordmark and the scroll-progress bar keep their original holographic gradient as the brand mark (owner decision, 2026-09-24); reduced motion stops their animation. The navigation and footer otherwise use the semantic tokens in `css/site.css`, which is their only stylesheet owner: page `<style>` blocks must not copy `.site-nav*`, `.nav-mega*`, `.site-footer*` or `.footer-apple*` rules (`tests/test_site_ui.py` enforces this). Navigation and footer markup has one source, `shared/nav.html` and `shared/footer.html`: `python scripts/sync_site_chrome.py` writes the static copy (usable without JavaScript) into every page, and `--check`, also run by the `ui-guardian` workflow, fails on drift. The footer has no surface of its own: on every page it sits on the page canvas below the shared rule, with nothing below it, so it never reads as a slab on one page and not another. The footer is positioned above the fixed `body::before` canvas and links only to real routes; policy/legal links stay absent until those documents exist. Shared `.btn` variants use tokens with visible focus and a disabled state. Other page surfaces and the legacy `--accent` still differ. Treat further adoption as a scoped page change. Test text and control contrast in rendered states before promotion. Do not make source/confidence/eligibility status depend on hue alone.

Typography: retain Noto Sans KR with the current system fallback. Candidate scale is 12/14/16/20/28/36 px for meta, supporting text, body, lead, section and page title. Normal Korean body text should be approximately 1.6 line-height; compact headings 1.2–1.35. Avoid tiny uppercase English labels as the sole explanation of a control. Long Korean and unbroken English titles must wrap without expanding the page.

Spacing scale: 4, 8, 12, 16, 24, 32, 48, 64 px. Use 12 px controls, 16 px functional cards and up to 24 px for feature/photo treatment as radius candidates. Reserve pill shapes for short filters and badges. Define exceptions locally and explain why.

Container roles: reading around 720 px, interactive tool around 960 px, broad editorial/home around 1200 px. These are caps to validate against existing 1180/1240/760 px pages, not a blanket width replacement. Mobile uses one task-first column; tablet rearranges only when content fits; desktop columns may hold distinct desks while each magazine lane reads vertically. Keep `min-width: 0` and natural wrapping on grid/flex children.

## Copy

Less text. Babdoduk speaks through titles, dates, images, short metadata and actions, not paragraphs of UI explanation.

- If the title already explains the section, there is no description line. If the UI already explains the action, there is no sentence for it.
- Keep a sentence only when the reader needs it to understand, decide, trust or act: freshness (마지막 발행), provenance (소개 문구는 밥도둑 메모), safety (판매 여부·가격·알레르기는 가게에서 확인), storage (이 브라우저에만 저장) and honest states (진행 여부 미확인).
- Budgets: section title one line; metadata one short line; call to action two to five words; empty state one short sentence; status a short noun phrase. Long-form writing belongs in magazine content, not in navigation or utility UI.
- Prefer labels (공지, 예정, 지난 활동, 당시 게시물) over assistant-like sentences (알려 드려요, 모아 두었어요, 확인해 보세요, 골라 드려요).
- Fuller context may sit behind a disclosure (자세히). Accessible names, screen-reader text, heading structure, focus and truth/status semantics are never cut to save words.

Page heads use an index number and a one-line title (`.page-head`, `.page-title`, `.page-num` in `css/site.css`): 02 밥도둑 매거진 (with the picker section “오늘 뭐 먹지?” at `#what`), 03 밥도둑 소식, matching the home groups 01 오늘 먹기, 02 읽어보기, 03 밥도둑 소식. Section titles use `.page-section-title` (a title followed by a thin rule). Archive and history lists are flat (rules, numbers, dates); only current content keeps an emphasized surface.

Magazine states (2026-09-29): a story card needs a real source link; there is no desk or filler card. An empty lane shows one quiet sentence (`.mg-lane-empty`). A featured story without its own image uses the text-only hero (`.mg-hero--text`); the BABDODUK wordmark is never shown as a stand-in picture, and with no featured story the hero is hidden.

## Component and interaction contracts

| Pattern | Required anatomy and behavior |
| --- | --- |
| Navigation | Clear primary destinations for checking and choosing; current page state; keyboard opening/closing and Escape; stable language control; experimental pages off normal navigation. Mobile hierarchy may use More for secondary links. |
| Buttons | Primary action once per decision region; secondary/text actions have distinguishable hover, focus, disabled and busy states. External navigation uses a link, not a button. |
| Editorial card | Category, meaningful title, source, edition/date when relevant, summary and original link. Generated fallback may need its own label. |
| Food opportunity card | Time/date, place, explicitly provided food, eligibility, registration requirement and approved action. “Unknown” is not a positive badge. |
| Menu card | Official meal date, restaurant/building, meal period, items, price/calories only when provided by source. Stale data is visibly labelled. |
| Recommendation card | Dish idea, plain-language reason, alternatives and feedback. Internal scoring is not a probability of fit or proof of sale. |
| Event row | Number, date, title, one short state and the post link; the full announcement and state explanation sit behind 자세히. The date band (now, coming up, past) is separate from the confirmed, tentative, unknown or cancelled status. Partner marks require authored evidence. |
| Badges | Distinct meaning for source, date, eligibility, editorial opinion and warning; text conveys state even without color. |
| Filters | Preserve the selected value, expose `aria-pressed`, support keyboard/touch and a useful empty result. |
| Tabs | Matched tablist/tab/tabpanel relationships, selected state and keyboard focus order. Do not substitute a styled button row without equivalent semantics. |
| Forms | Persistent labels, helpful format hints, field-level errors, confirmation of storage and easy correction. Explain whether entries stay in this browser. |
| Modal | Labelled dialog, focus moves in and returns, Escape closes, background is inert while open, no important action hidden behind motion. |
| Empty/loading/error | Separate no data, no filter match, stale, loading and request failure; show retry when useful and retain last known good data according to the feature contract. |

Use source-safe text insertion for external/generated strings. HTML fragments in the authored event translation map are a different trust class and must not be copied as a rendering pattern for live data.

## Media, iconography and motion

Food images should show the dish clearly and have purposeful alternative text. Decorative imagery should have empty alt; source and rights must be reviewed before adding third-party media. Icons share scale and stroke; emoji may add personality but cannot carry the only meaning of a tab, badge or state.

Feedback transitions may use roughly 120–200 ms as a starting point. The slot may be more expressive but must retain a reduced-motion path and a readable final result without waiting for animation. Respect `prefers-reduced-motion`; never convey data freshness or a registration deadline only through animation.

## Responsive and accessibility acceptance

Check 360×800 and 390×844 mobile, 768×1024 tablet, 1440×900 and 1920×1080 desktop, including Windows classic scrollbars. Body and footer must not gain unintended horizontal overflow. Long Korean/English titles, 200% text enlargement, keyboard-only travel, visible focus, language switching and high contrast need manual and automated checks. Touch targets should generally be about 44×44 px or larger where feasible. Validate contrast, labels, control status and focus with real rendered pages; a color token table alone is insufficient.

Existing scrollbar styling and vertical magazine trend flow are accepted baseline behavior. Keep `scripts/check_site_ui.py` and `scripts/check_ggongbab_ui.py` as regression gates; extend them for new behavior without weakening their current assertions. `check_site_ui.py` also audits every page in Korean and English for one `main` and `h1`, named controls, 24 px minimum control size, unique ids and `noopener` on new-tab links, and checks the unavailable-data states of home, hub and magazine. Its site guardian compares the shared chrome across the seven public pages (navigation structure and destinations, the current-page marker, footer links, computed footer styles, nothing below the footer, overflow, console errors and broken resources) in Korean and English at 1440, 390 and 360 px, and its visual check compares the nav, footer and footer context with the owner-approved images in `tests/visual/chrome/<platform>` (`docs/VISUAL_BASELINES.md`). CI (`ui-guardian`) runs both on every frontend change in a pinned Linux container against its own approved set.

## Current inconsistencies to migrate deliberately

`css/site.css` has shared tokens; `css/index.css` uses a distinct warm palette; `css/magazine.css` has its own paper and widths; `css/ggongbab.css` uses a dense feed style; `css/app.css` uses many `!important` overrides; HTML files also contain substantial local CSS and repeated translation and menu scripts; navigation and footer markup is generated from `shared/`. The same cafeteria data has a hub renderer and a separate summary renderer on the menu picker page, with the same freshness rule. First define component roles, then adopt them per page with visual regression checks. Do not normalize a page simply because its number differs.
