# Magazine discovery and publication

The magazine (`mukbang.html`) publishes **source-backed stories only**. There is no Babdoduk Desk
fallback and no generated filler: every story has a real source, a real URL, the source's own
title and a short excerpt of text that was actually retrieved from that source. When sources are
down or thin, the edition is smaller, and a lane may be empty. An empty lane is explained in
`research/magazine/health.json` (`lanes`), never silent.

## Routes: implemented, where they run

| Route | Lane(s) | Runs | Status |
|---|---|---|---|
| Recipe RSS/Atom (7 blogs) | tips, health | cloud | active |
| Korean food-industry and health news RSS (식품음료신문, 식품저널, 식품외식경제, 대한급식신문, 연합뉴스 산업·건강, 코메디닷컴, 뉴시스 건강, 동아일보 건강, 서울신문 라이프) | trend, habit, health (evidence rules apply) | cloud | active; Korean hosts time out now and then from GitHub runners (recorded as FETCH_FAILED) |
| Web search, Exa hosted MCP (`https://mcp.exa.ai/mcp`, **no key**), with page text from `web_fetch_exa` and Jina Reader | trend (10 queries), habit (10 queries) | cloud | active, **with a free daily quota** (below) |
| Naver Blog through the same web search (`site:blog.naver.com`) | trend | cloud | active, Tier C |
| YouTube search, yt-dlp metadata only | trend (10 queries) | **local only** (sidecar) | active on the operator PC |
| YouTube channels (4): Atom feed, else yt-dlp channel listing | tips, health, trend | **local only** (sidecar) | active on the operator PC |
| Exa REST search with `EXA_API_KEY` | - | optional | not configured, not needed |
| YouTube Data API with `YOUTUBE_API_KEY` | - | optional | not configured, not requested |
| Instagram (OpenCLI) | trend | local only | **OWNER_CHECKPOINT**, disabled |

Evidence for the split (probe workflow runs 36525458559 and 36525712270 on a GitHub-hosted runner,
2026-09-29, read-only, no secrets):
- YouTube channel Atom feeds: HTTP 404 on the runner. Since 2026-09-29 they also answer 404 (and
  sometimes 500) from the operator PC, so the sidecar falls back to a yt-dlp channel listing.
- yt-dlp search on the runner returns title, channel, URL, views and thumbnails but **no upload
  date** (flat search), and per-video metadata stops at YouTube's "confirm you're not a bot"
  check. No cookies are used to get around it, so YouTube stays local.
- Exa hosted MCP (initialize, tools/list, `web_search_exa`) and Jina Reader answer from the runner.
- **The keyless Exa server has a daily quota per client address.** After about 250 calls in one
  afternoon (five full runs while the lane rules were tuned, 2026-09-29) it answered HTTP 429 with
  `retry-after` ≈ 17.8 hours, `x-ratelimit-reset` at 00:00 UTC (09:00 KST) and a message to create an
  API key. One daily run needs about 30 calls (searches, then page reads batched 10 URLs per call),
  but GitHub-hosted runners share addresses with other users, so the quota can be gone before our run.
  The adapter stops at the first 429 and the other search sources of that run are recorded as
  `RATE_LIMITED_SKIPPED` (DEGRADED); nothing is retried from another address. Setting `EXA_API_KEY`
  (Exa's own key, REST route, already implemented) removes the dependency on the shared quota; that
  is an owner decision. The habit lane therefore also has keyless news feeds, so it does not rest on
  one quota.
- The Korean RSS feeds answer from the runner; single feeds occasionally fail to resolve or connect.

## Agent Reach

`Panniantong/Agent-Reach` at `a19a171fa980a0785849596492e0af4db800c82f` (v1.5.0, MIT) was installed
only in an isolated virtual environment with an isolated home directory, and its doctor was run
there (RSS and Jina Reader available; YouTube needs yt-dlp; web search needs mcporter + Exa MCP;
Instagram needs OpenCLI with a logged-in desktop Chrome). Nothing from it is imported, vendored or
installed in the repository. Babdoduk implements the same routes in its own code:
- RSS: `adapters/rss.py` (stdlib parser, same fields as feedparser for our feeds);
- web search: `adapters/exa_mcp.py`, a small MCP client for the same hosted Exa server Agent Reach
  configures through mcporter, with **no API key**;
- web reading: `web_fetch_exa`, then Jina Reader (`r.jina.ai`) for public URLs only;
- YouTube: yt-dlp (pinned 2026.8.19), metadata only.

## Pipeline

```
scripts/discovery/sources.json   (the one registry)
      -> adapters (rss, web/Exa MCP, inbox for local-only sources, instagram stub)
      -> research/magazine/candidates.jsonl   (candidate store)
      -> normalize (+ evidence) -> dedup -> quality filter -> corroboration -> lane rules -> rank
      -> editorial selection (hero rule)
      -> data/magazine/YYYY-MM-DD.json, latest.json, index.json   (public output)

operator PC:  scripts/magazine_local_discovery.py -> research/magazine/inbox/<sourceId>.json
```

`python scripts/refresh_magazine.py` runs the pipeline; `content-refresh` calls it daily at 10:00 KST.
- `--discover-only` updates the store without building an edition.
- `--select-only` re-judges every stored candidate under the current rules and rebuilds today's
  edition, without the network. Nothing is fetched, searched or deleted, so a rule change or a
  rate-limited route never loses a discovered candidate. A search failure also leaves the store intact
  (tested).
- `--sanitize-only` cleans stored editions without the network.

### Local discovery sidecar (discovery, never publication)

`python scripts/magazine_local_discovery.py` runs the registry's `localOnly` sources on the
operator PC (yt-dlp from `BABDODUK_YTDLP_BIN` or PATH, `--skip-download --no-cache-dir`, no
cookies, no account) and writes each source's findings to `research/magazine/inbox/<sourceId>.json`.
It writes nothing else: not the candidate store, not source health, not `data/magazine`, not git.
The normal pipeline reads the inbox as that source's adapter result, so every local candidate goes
through the same rules, and only the normal publisher produces the public edition. An inbox older
than 3 days is reported as `LOCAL_INBOX_STALE` (DEGRADED); a missing one as `LOCAL_INBOX_MISSING`.

**Automation gap (`YOUTUBE_AUTOMATION_PENDING`, recorded in `health.json`).** Nothing yet runs the sidecar on a schedule or delivers the inbox to the
repository: today's inbox came from one controlled local run (2026-09-29) committed with the lab
change. A
durable path needs an owner decision (a scheduled task on the operator PC plus a way to hand the
inbox to the publisher, which touches the paused publisher credential / operations work). Until
then YouTube candidates reach the magazine only when an operator runs the sidecar and commits the
inbox; every other route is cloud-safe.

## Lanes are rules (owner decision, 2026-09-29)

| Lane | A candidate qualifies when | Typical sources |
|---|---|---|
| 요즘 먹방 유행 (trend) | published ≤ 30 days ago, dated, food-related, retrieved text, **and** at least one `trendEvidence` kind | news, web search, Naver, YouTube, food-industry press |
| 식습관 (habit) | dated, from a Tier A/B source, not a recipe or video, two habit topic words plus a behavior/evidence sentence (survey, share, study, increase); news ≤ 90 days, research ≤ 2 years | news, surveys, research, food-industry reports |
| 건강한 한 끼 (health) | Tier A/B source, the source's own health category or two health signals | recipe blogs, health news |
| 요리 비법 (tips) | a recipe, cooking post or video, with the source's tips category or two how-to signals | recipe blogs, cooking channels |

A candidate that qualifies for no lane is rejected (`NO_QUALIFYING_LANE`), with the reason per lane in
`laneDecisions`. A story about how people eat that also qualifies as a trend goes to habit; otherwise
the query's own lane wins when the candidate qualifies for it.

### Editorial precision (owner decision, 2026-09-29): classify the item, not the publisher

Fewer good stories beat more weak ones; there is no quota. `scripts/discovery/editorial.py`:

| Heading | A reader must be able to say | Fixed reasons when not |
|---|---|---|
| 요즘 먹방 유행 | "there is evidence this is happening now" | `PRODUCT_ANNOUNCEMENT_ONLY`: a launch, or a round-up of launches ([신상품], [오늘의 새상품], "… 외", TOP n), needs measured demand for it (sales, engagement, stockouts or queues); `RECIPE_WITHOUT_TREND_EVIDENCE`: a popular recipe is a recipe; `NO_TREND_EVIDENCE` |
| 요리 비법 | "this teaches me something" | `NOT_INSTRUCTIONAL`: ASMR, mukbang, montages, compilations and link round-ups without instructions in the retrieved text |
| 건강한 한 끼 | "the source supports a health or nutrition angle" | `NO_HEALTH_BASIS`: the title and text must frame food and health (never inferred from ingredients); a launch is `PRODUCT_ANNOUNCEMENT_ONLY` |
| 식습관 | "this is about how people eat" | `CELEBRITY_DIET_GOSSIP`, `PRODUCT_ANNOUNCEMENT_ONLY` (company promotion), `NO_BEHAVIOR_EVIDENCE` (a measured sentence must be about people, not a product's specification) |

Evidence is re-judged from the stored facts on every run and every offline rebuild:
- Company PR language ("…라고 밝혔다", "트렌드에 맞춰", "인기 상품", "소비자 니즈") is never evidence, and "인기", "신상" and "신제품" never count on their own.
- Ambiguous words ("급증", "트렌드") count only when the sentence is about demand ("오메가6를 급증시켜" and "환자가 급증" do not).
- Sales data means a demand figure that rose or set a record. A share ("매출의 70%"), a specification ("당도 68% 낮춰") or a recall ("기준치의 5배 검출") is not sales data.
- A creator's hashtags are labels, not claims, and a sold-out sentence about goods (굿즈) is not about food.
- Engagement means at least 100,000 views within 30 days, on a video that is itself about what is popular.
- Corroboration requires two distinctive shared words, one of them a real name (Latin words match whole). It never rescues a launch, and one release relayed by two outlets on the same day is one voice.

Also rejected for every lane: `OPINION_COLUMN`, `SHOPPING_OR_TRAVEL_GUIDE`, `NOTICE_OR_EVENT` (board notices, events, campaigns, lectures, awards), `PROMOTION` (contests, marketing round-ups, 1+1 deal lists), `AD_OR_SPONSORED` (paid placement, purchase links), `BUSINESS_NEWS` (earnings, supply deals, exports, market columns).

**trendEvidence** (found in the source's retrieved text or platform metadata, never the title alone):

| Kind | Meaning |
|---|---|
| `explicit_source_claim` | the text itself says it is popular, new, sold out or trending (유행, 화제, 급증, 품절, 트렌드, 인기, 신상, viral, trend …) |
| `corroborated` | another recent source on a different host covers the same thing (two distinctive words shared both ways) |
| `engagement` | platform metadata: at least 50,000 views within 30 days of upload |
| `sales_data` | the text reports sales or adoption figures (매출·판매·주문 with a number, %, 1위 …) |

A recipe is not a trend: for recipe content a weak claim ("인기", "popular") does not count. A
research paper older than 30 days is never a trend, whatever words it uses; it may be a habit
story, shown with its date. `trendEvidenceDetail` keeps the verbatim sentence or metadata behind
each kind, internally.

**Audience relevance** (`audienceRelevance`): Korea, convenience stores, students and young adults,
single-person households, quick meals, budget. It ranks what a KAIST student is likely to care about
higher without removing international material.

**Ranking.**

```
score = 0.25 × source trust + 0.20 × freshness + 0.15 × lane relevance + 0.15 × quality
      + 0.25 × audience relevance (+ up to 0.10 trend evidence in the trend lane)
```

Freshness is exp(−age/21 days); quality is text length plus a validated image.

**Selection.** Each lane takes at most 6 stories and at most 2 from one source (publisher); **6 is a
ceiling, never a number to fill**. Stories that corroborate one another take one slot. In tips and
health an evergreen story older than 90 days runs only when fewer than 3 fresh ones qualify. A story
runs in one edition only (`selectedFor`).

**Hero.** The edition records `featured.heroKind`:
- `trend`: a qualified trend story with independent evidence (measured demand, strong engagement,
  independent reporting of stockouts or popularity, or corroboration by an independent source, never the
  seller's own words; two kinds preferred), a validated image of its own, a Tier A/B source and
  audience relevance ≥ 0.5, published within 7 days preferred (30 at most). The page labels it
  **지금 뜨는 먹거리** and lists the evidence kinds.
- `pick`: otherwise the best recent story with its own validated image, labelled **오늘의 추천 글**,
  never wording that implies a trend. Category, medium, source and date show what kind of story it is.

## Trust tiers and search results

Search results take their tier from the result's host (`scripts/discovery/hosts.py`), never from the
route: A for government, public-health and research publishers; B for established news and food
publications; C for blogs, video search results and unknown hosts. Shopping and listing pages are
rejected (`COMMERCE_PAGE`). A Tier C source (for example a Naver blog) is discovery: it can show new
products and what people are trying, but it is never health advice, never habit evidence and never
the hero. It needs at least 200 characters of retrieved text.

## Public vs internal

| Public: `data/magazine/` (served) | Internal: `research/magazine/` (not served) |
|---|---|
| Daily edition, `latest.json`, `index.json`; `rules: "lanes-v1"` | `candidates.jsonl`: every candidate with provenance |
| Per story: title, short summary, source, URL, medium (blog, news, research, youtube), publishedAt, discoveredAt, image and its origin, sourceId, candidateId; trend stories also `trendEvidence` (kinds) | discoveryMethod, discoveryQuery, discoveryLane, seenQueries, trendEvidence and detail, sourceTrust, audienceRelevance, laneDecisions, scores, duplicateOf, selectedFor, rejectionReason |
| Featured: `heroKind` (`trend` or `pick`) | `inbox/` (local sidecar output), `source-health.json`, `health.json` (with per-lane counts and reasons), `runs.jsonl` |

`research/` is listed in `.vercelignore`, so the website never serves it.

**Persistence.** GitHub Actions runs are stateless. After a magazine run, the content bot commits
`research/magazine/` to lab and main through `scripts/publish_generated.py`, the same path as
`data/magazine/`, so the next run starts from it. The store is bounded: 90 days since last seen, at
most 4,000 candidates.

**Caveat until promotion to main:** main's daily run mirrors `data/magazine/` onto lab with main's
older builder. The research store is new, so main's publisher does not touch it.

## Registry and source status

`scripts/discovery/sources.json` is the only list of sources, versioned with the code.
- **Fields:** id, name, type, url or channelId, enabled, trustTier, categories, discoveryMethod,
  kind (recipe, news, research, video, mixed), lane (the lane a search asks for), localOnly,
  requireFood, queries (with `{year}` and `{month}` filled in at run time), objective, note,
  knownIssue.
- **Runtime health** (`research/magazine/source-health.json`): lastAttemptAt, lastSuccessAt,
  lastFailureAt, failureCount, lastFailureCode, lastItemCount, newestItemAt, status.

| Status | Meaning |
|---|---|
| ACTIVE | answers and has published within 120 days |
| STALE | answers, but its newest item is older than 120 days |
| DEGRADED | the last attempt failed, or a local inbox is missing or stale |
| DISABLED | `enabled: false` |

## Candidate rules

**Dedup.** Deterministic; the earliest discovery (by a persistent `discoveredSeq`) stays the
original. A candidate's id is its canonical URL, so the same URL reached through two routes is one
candidate, with both routes in `seenVia` and every query in `seenQueries`. A later candidate points at
the original with `duplicateOf` when the source item id, the content hash (title plus text), or a
similar title **with** the same site or a matching excerpt match. Title similarity alone is never
enough.

**Quality filter.** Each rejection records a fixed reason: `BAD_URL`, `NO_TITLE`, `NO_SOURCE_TEXT`
(less than 60 characters of retrieved text; 20 for a video; 120 for research), `COMMERCE_PAGE`,
`AD_OR_SPONSORED`, `PROMOTION`, `BLOCKED_TOPIC`, `OFF_TOPIC_RESTAURANT_TRAVEL`, `NOT_FOOD` (Tier C
and broad news feeds), `WEAK_TIER_C`, `TOO_OLD` (more than 365 days; research 2 years),
`NO_QUALIFYING_LANE`.

## Truth and image rules

- **Summary:** at most 120 characters, cut from the source's own text (for a web page its first
  real paragraph, without bylines, captions or links). If less than 20 characters remain, the card
  shows title and source only. Nothing is written by Babdoduk.
- **Date:** every card shows the source's publication date. For web pages it comes from search or
  page metadata, else the page's own printed date near its top (`publishedAtSource`).
- **Image:** in order of preference, RSS/Atom media of the same item, an image in the same feed
  entry's HTML, the official YouTube thumbnail of the same video, the og:image of the same page. It is
  shown only after the URL answered with an image.
- **Stored editions:** every run sanitizes them. Desk items, link-less items and idea desks are
  removed; generated summaries of items built before provenance existed are dropped; a trend item
  without evidence and the old builder's keyword-routed habit items (editions without
  `rules: "lanes-v1"`) are removed.
- **Validation:** `validate_content.py` rejects any desk, sourceless or link-less story, a trend story
  without evidence, older than 30 days or undated, an undated habit story, and a trend hero without
  evidence. Sparse and empty lanes are valid.

## Health report

`research/magazine/health.json` is written on every run: per adapter its status, code, item count
and last success; the counts of candidates, new, duplicates, rejected and selected; per lane the
qualifying count, how many candidates were discovered for it and why the others did not qualify;
`fabricated: 0`; warnings for failing, stale and degraded sources.

## Tests and evaluation

`python -m discovery.evaluate` (from `scripts/`) runs synthetic sources through the real pipeline.
`tests/test_magazine_discovery.py` covers provenance, dedup, quality, images and stored editions;
`tests/test_magazine_lanes.py` covers the lane rules, trend evidence, audience ranking, the hero
rule, the keyless MCP client, the local sidecar and the empty-lane case. No test uses the network.
