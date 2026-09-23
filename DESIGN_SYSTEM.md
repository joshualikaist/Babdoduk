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
| Food accent | `--color-accent: #d9472b` candidate, used for action and editorial emphasis | Home accent; shared CSS currently uses `#ff675d` |
| States | Semantic `info`, `success`, `warning`, `error`, `unknown`; never color-only or inferred from “food” | Existing loading/error/review states |
| Borders | One subdued separator role plus strong focus/control boundary | Current `--border`, `--border-strong` |
| Shadows | Small elevation only for overlap/floating controls; ordinary cards use surface and border | Existing `--shadow-*` |
| Scrollbar | Keep warm track, distinguishable thumb, hover and corner; preserve forced-color native behavior | `site.css` scrollbar contract |

These color values are starting proposals, not an instruction to replace all existing page values at once. Test text and control contrast in rendered states before promotion. Do not make source/confidence/eligibility status depend on hue alone.

Typography: retain Noto Sans KR with the current system fallback. Candidate scale is 12/14/16/20/28/36 px for meta, supporting text, body, lead, section and page title. Normal Korean body text should be approximately 1.6 line-height; compact headings 1.2–1.35. Avoid tiny uppercase English labels as the sole explanation of a control. Long Korean and unbroken English titles must wrap without expanding the page.

Spacing scale: 4, 8, 12, 16, 24, 32, 48, 64 px. Use 12 px controls, 16 px functional cards and up to 24 px for feature/photo treatment as radius candidates. Reserve pill shapes for short filters and badges. Define exceptions locally and explain why.

Container roles: reading around 720 px, interactive tool around 960 px, broad editorial/home around 1200 px. These are caps to validate against existing 1180/1240/760 px pages, not a blanket width replacement. Mobile uses one task-first column; tablet rearranges only when content fits; desktop columns may hold distinct desks while each magazine lane reads vertically. Keep `min-width: 0` and natural wrapping on grid/flex children.

## Component and interaction contracts

| Pattern | Required anatomy and behavior |
| --- | --- |
| Navigation | Clear primary destinations for checking and choosing; current page state; keyboard opening/closing and Escape; stable language control; experimental pages off normal navigation. Mobile hierarchy may use More for secondary links. |
| Buttons | Primary action once per decision region; secondary/text actions have distinguishable hover, focus, disabled and busy states. External navigation uses a link, not a button. |
| Editorial card | Category, meaningful title, source, edition/date when relevant, summary and original link. Generated fallback may need its own label. |
| Food opportunity card | Time/date, place, explicitly provided food, eligibility, registration requirement and approved action. “Unknown” is not a positive badge. |
| Menu card | Official meal date, restaurant/building, meal period, items, price/calories only when provided by source. Stale data is visibly labelled. |
| Recommendation card | Dish idea, plain-language reason, alternatives and feedback. Internal scoring is not a probability of fit or proof of sale. |
| Event card | NOW/COMING UP/PAST date band and separate confirmed/tentative/unknown/cancelled status. Partner marks require authored evidence. |
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

Existing scrollbar styling and vertical magazine trend flow are accepted baseline behavior. Keep `scripts/check_site_ui.py` and `scripts/check_ggongbab_ui.py` as regression gates; extend them for new behavior without weakening their current assertions.

## Current inconsistencies to migrate deliberately

`css/site.css` has shared tokens; `css/index.css` uses a distinct warm palette; `css/magazine.css` has its own paper and widths; `css/ggongbab.css` uses a dense feed style; `css/app.css` uses many `!important` overrides; HTML files also contain substantial local CSS and repeated navigation/footer markup. The same cafeteria data has a hub renderer and a separate magazine renderer with different freshness treatment. First define component roles, then adopt them per page with visual regression checks. Do not normalize a page simply because its number differs.
