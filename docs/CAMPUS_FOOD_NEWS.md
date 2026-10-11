# Campus food news

Owner decision, 2026-09-30: the KAIST food hub keeps its navigation and two tabs.
The free-food tab shows actual free opportunities, **먹거리 소식 / Campus food
news**, then past free listings. Home keeps its cafeteria/free-food summary.

## Content and storage

`free_food` remains the existing validated `events` array with its publication,
explicit food, review, confidence and time gates. Legacy events imply that type;
their public schema is unchanged. `campus_food_news` uses a separate generated
`data/ggongbab/news.json` with `items`, never `events`. Openings, closures and
significant food-service/menu/operating-hour changes need no giveaway.

Optional `hasFreeOffer`: true requires explicit free provision evidence; false
requires explicit negative evidence; omission means unknown. A title's silence
does not mean false. News with a giveaway can coexist with a separately validated
free event, but news itself never affects count, Radar, next-free or archive.

## Discovery is not publication

`portal_list_warrants_detail` retains its legacy name, not detail authorization.
Existing event/food signals OR food-service plus change signals create Stage A
candidates. Brand names alone do not publish. Recent unchanged rows newly
qualifying can enter pending without resetting the baseline/state.

The resident LIST poller still writes only hashed metadata. It does not fetch
bodies, create empty-body tasks or publish news. Portal's detail/view-count
boundary stays unchanged. Source evidence requires a separate authorized review.

The review file stays on the operator PC (`.local/ggongbab/food-news-review.json`), never in
git: this repository is public and its records carry source excerpts, some from the KAIST Portal.
`python scripts/export_food_news.py --review` validates it and writes only the public items to
`inputs/ggongbab/food-news.json`; that file is committed, and the refresh publishes it as
`data/ggongbab/news.json` after checking every item again on its own (allowlisted keys, clean
text, a generic source, the id its own facts derive). Data plan phase 2, 2026-10-12.
Each review record has `reviewed: true`, `sourceType` (`portal` or `kaist_public`),
`title`, ISO `noticeDate`, `dateVerified: true`, sanitized `evidence`, and
`campusEvidence`. Title and campus evidence must occur in the excerpt; optional
`summary`/`location` must be exact excerpts too. Never commit raw mail, whole
private notices, IDs, URLs, contacts or credentials. LIST signals alone remain
pending. No guessed facts and no source-detail requests are implied by review.

`food_news.extract_reviewed_news` validates source, campus scope, service-change
classification, factual support, verified date and privacy. Unreviewed sources
fail closed. `python scripts/export_food_news.py` generates the snapshot from the public
items; normal refresh export also uses this path. Dry-run writes nothing. Bad input keeps the
last good news snapshot and prevents publication. This first path requires source
review, not automatic candidate publication. No DB migration is introduced.

The public allowlist is `id` (from public title/date, never a Portal identifier),
`contentType`, `noticeDate`, `title`, optional `summary`/`location`/`hasFreeOffer`,
and generic `sources`. No source URLs or review evidence are exported. Dates are
notice dates, not inferred opening dates. The window is 30 days. Empty verified
input produces zero items, with no placeholder stories.

## UI and tests

Lightweight rows show date, title, optional place/fact and generic source
(`KAIST 포탈` for Portal). Independent loading/empty/error states leave free
events intact. Lab fixtures stay separate; local preview does not fetch news.
Tests cover generic recall and research-lab negatives, candidate reconsideration,
review gates, unsupported facts, private fields/URLs, duplicate IDs, unknown vs
false, generatedAt-only publication, count/archive isolation and coexistence.
The hub gate checks 390 KO, 1440 KO and 390 EN, news failure and cafeteria switching.
Visual baselines require later owner approval. Synthetic examples never establish
live No Brand Burger/BBQ facts; recovery evidence is reported separately.
