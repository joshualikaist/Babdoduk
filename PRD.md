# Babdoduk product requirements

Status: Phase 10B production-scoped candidate, 2026-09-24. Owner decisions below are locked for this release; preparation is not deployment.

## Product and journeys

Babdoduk helps KAIST visitors check available food, choose a dish, and explore food culture and campus activities. A quick cafeteria lookup is a successful visit; editorial discovery is optional.

Two distinct questions lead the experience:
- 오늘의 한 끼: dated official cafeteria menus and publishable upcoming free-food events.
- 메뉴 고르기: a catalog suggestion with reasons and alternatives, not proof of current restaurant inventory.

Home introduces those two actions, a freshness-labelled static summary, then magazine and activities. The picker remains integrated at mukbang.html#what; no new standalone page is planned for this release.

| Route | Responsibility |
| --- | --- |
| index.html | Start checking or choosing; name snapshot publication time |
| ggongbab.html | Free-food/cafeteria tabs, eligibility, dates and approved actions |
| mukbang.html | Four vertical editorial categories, sources/editions and integrated picker |
| food.html | Combined published/browser expense view with explicit provenance |
| event.html | Date bands separately from verified occurrence status |
| history.html | Authored Babdoduk history |
| lab.html, lab-ggongbab.html | Existing publicly reachable experimental routes, not private storage |

## Required behavior

- Free food: backend publication policy stays unchanged. The frontend repeats explicit food=true, no needs_review/needsReview and not-ended checks. Sort by ascending date. Initial filter is 전체 예정; saved filters win. Keep today/tomorrow/week/all, Radar and the next-event featured card.
- Cafeteria: retain actual KST date, source, restaurant/meal controls and favourites. Stale data cannot be called today's confirmed menu.
- Picker: explain a suggestion without pretending a score is probability, food availability or health/allergen assurance. Choosing records preference, not a consumed meal. Explicit eaten feedback remains separate.
- Magazine: four categories stack articles vertically at every breakpoint. Identify sources, original links and past editions; fallback copy must not invent fetched-source metadata.
- Events: dates determine NOW/COMING UP/PAST, not held/cancelled/successful/completed. All relevant historical May results stay 진행 여부 미확인. Preserve the four detail fields and original instructions as historical announcements.
- Food log: keep persisted data and current merge semantics intact. data/food-log.json is labelled 밥도둑 공개 기록; browser entries are labelled 이 브라우저 기록. A browser row takes precedence on the same date; combined summaries count that selected row once. Rendering provenance is not written into storage. No migration, deletion, rewriting or split of existing localStorage. True separate accounting modes are future work.
- Shared UI: two primary destinations plus secondary More, real footer destinations, no dead legal links, visible keyboard focus, announced errors, Korean/English labels and reduced motion.

## Release scope and non-goals

Promote only approved Phase 0–9 UI/product behavior, prerequisite e0f1c1c, production-scoped docs, UI regression tests, fixture correction and small approved wording changes.

Do not promote Realtime/public-feed backend, migrations, new Portal collectors, Dooray operations, Windows resident workers, generated data or workflows. Existing production backend code remains untouched; this is not an operational upgrade.

Do not remove, hide, relocate or redesign lab.html/calendar.ics: both already exist on main. Only shared navigation/footer prerequisites and the associated existing language-function syntax repair are included for lab.html. Public exposure is a later Privacy / Public Surface Audit.

No Privacy Policy or Terms are created. Do not add analytics, login, push or data collection as an incidental UI change. The factual inventory in ARCHITECTURE.md is not a legal determination.

Do not fix ggongbab-refresh.yml (reported broken) or scripts/refresh_magazine.py (known malformed summaries). Operational recovery and Magazine Content Quality are separate tasks.

## Acceptance and remaining evidence

Preserve local data, all existing synthetic safety tests and public eligibility rules. Test 360/390 mobile, 768 tablet, 1440/1920 desktop, classic Windows scrollbars, long Korean/English text, navigation and failure states.

Do not assign invented success metrics. Future privacy-reviewed user research may measure lookup completion, picker usefulness and stale-data misunderstanding. Page views or preference clicks do not prove meals eaten.

Production approval still needs explicit owner authorization and deployment-specific preflight. Browser automation does not establish data freshness, screen-reader usability or live external-service health.
