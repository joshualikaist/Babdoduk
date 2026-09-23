# Babdoduk product requirements

Status: lab design baseline, 2026-09-23. Product choices marked **Open** require the owner's decision before changing their data or meaning. This document describes intended user behavior; `ARCHITECTURE.md` records implementation and safety boundaries.

## Product definition and vision

Babdoduk helps people at KAIST check food opportunities, choose a meal, and explore food culture and campus experiences. A successful visit may end after a single cafeteria lookup. The service should make that short task easy while giving interested visitors a path into Babdoduk's editorial voice and activities.

The current product started as a personal food and social hub. The recurring campus task is now important enough to lead the navigation and home page. KAIST remains the primary context; dish ideas and editorial content need not be restricted to food sold on campus.

## Problem and principles

Visitors currently need to discover the food tools through navigation, and “오늘 뭐 먹지?” refers both to available food and to a dish recommendation embedded in the magazine. The two questions are different:

- **What is available?** A dated KAIST menu or a publishable free-food event. This is information, subject to source freshness and participation conditions.
- **What should I choose?** A dish idea from the local food catalog, with a reason and alternatives. This is a suggestion, not confirmation that a venue sells it today.

Principles: solve the meal task before decoration; distinguish facts, suggestions and unknowns; show one clear next action; keep editorial curiosity without turning every article into promotion; use playfulness only where it helps choosing; keep public data within approved publication boundaries.

## Target users and needs

These are hypotheses from the current features, not measured audience segments.

| User | Immediate question | Most useful task | Likely entry and next step |
| --- | --- | --- | --- |
| KAIST student near a meal | What is served now? | Check dated menu by restaurant and meal | Home or direct link → cafeteria menu |
| Student looking for free food | Is a relevant event upcoming? | Check time, place, eligibility and registration | Ggongbab → event's approved public action |
| Undecided eater | What dish should I pick? | Get a reasoned suggestion and alternatives | Home or picker link → choose or try again |
| Food-content visitor | What can I learn or watch? | Browse four magazine desks and source links | Search/SNS → magazine → original item |
| Interested participant | What is happening with Babdoduk? | Check confirmed event state and instructions | Home/SNS → events → participation details |
| Returning recorder | What did I eat or spend? | Review and edit local entries | Food log → record/history |

## Pillars and feature hierarchy

| Tier | Experience | Present implementation |
| --- | --- | --- |
| Core | **Check today's food**: KAIST cafeteria, publishable upcoming free food | `ggongbab.html`, `js/ggongbab.js`, `js/kaist-menu.js` |
| Core | **Choose a dish**: a quick, explainable suggestion | `js/food-engine.js`, `js/food-picker.js`, `js/eat-slot.js`, currently in `mukbang.html#what` |
| Secondary | Explore: magazine, curated restaurant map, history and social channels | `mukbang.html`, `history.html`, external links |
| Secondary | Participate: verified events and collaborations | `event.html` |
| Secondary, owner decision open | Food expense and meal log: personal, creator-authored or explicitly separated modes | `food.html`, `data/food-log.json`, browser localStorage |
| Experimental | Isolated layout, fixture and preview work | `lab.html`, `lab-ggongbab.html` |
| Operational | Collection, validation, publication, session recovery and monitoring | `scripts/`, `supabase/`, workflows; never a public navigation destination |

The slot animation is an optional presentation of a selected result, not an availability source or a separate product pillar.

## Primary journeys

1. **Check**: Home or direct visit → today's food → cafeteria or free food → date, location and conditions → approved next action or finish.
2. **Choose**: Home or direct visit → dish picker → minimal inputs → dish with plain-language reasons and alternatives → choose, retry or finish.
3. **Explore and participate**: An optional continuation from either journey to a related article, map or confirmed event. Do not require this continuation for task success.

The home page should show the service definition, primary check action, secondary choose action, a small freshness-aware summary when available, then confirmed activity and editorial content. Do not make unfinished social channels compete with the two primary actions.

## Page responsibilities and naming

| Page | Primary job | Next connection | Exclude |
| --- | --- | --- | --- |
| `index.html` | Orient and start the two core tasks | Today's food, picker, then editorial/events | Equal-weight directory of all features |
| `ggongbab.html` | Answer what is available through free-food and cafeteria tabs | Approved registration or the dish picker | Treat catalog suggestions as live inventory |
| `mukbang.html` | Publish four editorial desks: tips, trends, health, habits | Original story and selective food connection | Permanently own the only entry to the picker |
| `food.html` | Record/review food and expenses once ownership is decided | Optional return from choosing | Unlabelled mixture of personal and creator records |
| `event.html` | Show now, coming up and past activity with verified status | Confirmed participation instructions | Past dates described as upcoming |
| `history.html` | Explain Babdoduk's story and provenance | Relevant content and activities | Duplicate the live food dashboard |
| `lab.html`, `lab-ggongbab.html` | Isolated experiments and tests | Development documentation | Public core navigation or private preview exposure |

Suggested navigation labels are **오늘의 한 끼** for the availability hub and **메뉴 고르기** for the recommendation tool. “오늘 뭐 먹지?” may remain as supporting copy. Existing URLs should continue to resolve during a later navigation change. A separate picker destination is a proposed future phase, not a current route.

## Functional requirements

- Free-food publication requires explicit `food.provided == "true"`, approved/published state, `needs_review == false`, confidence and date/horizon checks. The UI must hide ended events, preserve ascending date order, filters, Radar and featured next event. Initial period is **전체 예정**; a previously saved filter takes precedence. Unknown food is not a negative or a positive assertion.
- Cafeteria menus must carry their actual date/source. A stale payload must not be presented as today's confirmed menu. Restaurant, meal, favourites and retry behavior should be consistent wherever the menu appears.
- Dish recommendations must identify the result as a catalog suggestion, show an intelligible reason and alternatives, preserve local feedback, and never claim live availability, validated health/allergen safety or a measured probability. A “choose” action does not prove the user ate the dish.
- Magazine stories retain their category, source, edition date and original link. Authored fallback and collected items need an honest presentation. Each category remains a vertical reading flow.
- Events must be classified as NOW / COMING UP / PAST by dates and separately report whether occurrence was confirmed, tentative, cancelled or unknown. Past dates do not prove an event happened. Collaborations appear only when supported by authored facts. Existing four detail fields and index/date contract remain until an approved replacement.
- The food log must explain whether an entry is personal, creator-authored or both before changing storage or merging behavior. Existing local entries must remain readable through any later redesign.

## UX, responsive, accessibility and content

The mobile first screen must expose the primary task and a second clear path to choosing. Controls must be usable with keyboard and touch, announce state changes meaningfully, retain visible focus, support text enlargement and Korean/English titles, and respect reduced motion. Test desktop, tablet, 390 px and 360 px mobile layouts, including Windows classic scrollbars and long words.

Use a distinct state for loading, no results, outdated data, failed refresh, and unavailable service. Show a date or last-known status where recency affects the user's decision. Source and confirmation status are content, not decorative badges. Don't invent events, collaborators, restaurant inventory, news, legal pages or user activity to fill an empty state.

## Success measures and open evidence

Before assigning targets, establish a privacy-reviewed baseline. Candidate measures: task completion for finding a dated menu or eligible event; time to first relevant result; picker completion and alternative selection; stale-information misunderstanding in user tests; return visits to the two core tools. Views of an article, button presses and “이거 먹을래” are not evidence of a consumed meal. Do not install analytics as an incidental UI change.

Open owner decisions: positioning of the creator brand relative to the campus utility; final navigation labels and picker URL; ownership/mode of the food log; verified outcomes of old events; bilingual parity; publication status of legal links; permitted measurement and privacy policy; later production promotion scope.

## Out of scope and future possibilities

This product definition does not authorize credential or MFA automation, Portal detail GET, new Supabase tables, migrations, account profiles, push notifications, a framework migration or a new backend. After the core journeys work, investigate optional editorial links and local-only personalization using measured user need and explicit privacy decisions.
