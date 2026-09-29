# Magazine discovery and publication

The magazine (`mukbang.html`) publishes **source-backed stories only**. There is no Babdoduk Desk
fallback and no generated filler: every story has a real source, a real URL, the source's own
title and a short excerpt of text that was actually retrieved from that source. When sources are
down or thin, the edition is smaller, and a lane may be empty.

## Status: implemented / lab-only / planned

| Part | Status |
|---|---|
| Source registry, candidate store, dedup, quality filter, lane classification, ranking, selection | **Implemented** (`scripts/discovery/`) |
| RSS/Atom adapter (8 feeds) | **Implemented, active** |
| YouTube channel feeds (4 channels) | **Implemented, DEGRADED on GitHub-hosted runners**: YouTube answers HTTP 404 there every day (observed since 2026-09-22); the same feeds work from the operator PC. Classified as an access-path problem, not a missing API key. |
| YouTube query search (Data API or local yt-dlp) | **Implemented, disabled** (not configured; no key requested) |
| Web search (Exa) and page reading (Jina Reader, public pages only) | **Implemented, disabled** (needs `EXA_API_KEY`, not configured) |
| Naver Blog via `site:blog.naver.com` web search | **Implemented through the web adapter, disabled** |
| Instagram (OpenCLI, dedicated local profile) | **Planned**; the adapter reports `NOT_CONFIGURED` and contributes nothing |
| Agent Reach | **Not integrated.** It is a capability/routing reference: the adapters above follow its routes (feedparser-style RSS, yt-dlp, Jina Reader, Exa) as Babdoduk-owned code. Nothing imports or installs it. |

## Pipeline

```
scripts/discovery/sources.json   (the one registry)
      -> adapters (rss, youtube, web, instagram)
      -> research/magazine/candidates.jsonl   (candidate store)
      -> normalize -> dedup -> quality filter -> lane -> rank
      -> editorial selection
      -> data/magazine/YYYY-MM-DD.json, latest.json, index.json   (public output)
```

`python scripts/refresh_magazine.py` runs it; `content-refresh` calls it daily at 10:00 KST.
- `--discover-only` updates the store without building an edition.
- `--sanitize-only` cleans stored editions without the network.
- `--skip-type youtube_channel` builds on a machine that can reach what GitHub's runners cannot, with
  the same result the cloud gets. The skipped sources are recorded as `DEGRADED / SKIPPED_CLOUD_PARITY`.

## Public vs internal

| Public: `data/magazine/` (served) | Internal: `research/magazine/` (not served) |
|---|---|
| Daily edition, `latest.json`, `index.json` | `candidates.jsonl`: every discovered candidate with provenance |
| Per story: title, short summary, source, URL, medium, publishedAt, discoveredAt, image and its origin, sourceId, candidateId | Scores, rejection reasons, dedup relations (`duplicateOf`, `seenVia`), discovery method and query, excerpts, selection history |
| No scores, no rejection reasons, no queries | `source-health.json`, `health.json` (report), `runs.jsonl` (run and query log) |

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
  queries, note, knownIssue.
- **Trust tiers:**
  - A: authoritative or original publisher.
  - B: established creator, food publication or official brand.
  - C: discovery or community source. It is never published as factual advice on its own; it needs
    at least 200 characters of retrieved text.
- **Runtime health** (`research/magazine/source-health.json`): lastAttemptAt, lastSuccessAt,
  lastFailureAt, failureCount, lastFailureCode, lastItemCount, newestItemAt, status.

| Status | Meaning |
|---|---|
| ACTIVE | answers and has published within 120 days |
| STALE | answers, but its newest item is older than 120 days |
| DEGRADED | the last attempt failed or was skipped for a known access problem |
| DISABLED | `enabled: false` (for example an adapter without its credential) |

## Candidate rules

**Dedup.** Deterministic; the earliest discovery (by a persistent `discoveredSeq`) stays the
original.
- **Same candidate:** a candidate's id is its canonical URL, so the same URL reached through two
  routes is one candidate, with both routes kept in `seenVia`.
- **Duplicate:** a later candidate points at the original with `duplicateOf` when any of these match:
  - the source item id (for example the YouTube video id);
  - the content hash (title plus text);
  - a similar title, **and** either the same site or a matching excerpt. Title similarity alone is
    never enough.

**Quality filter.** Each rejection records a fixed reason:
- `BAD_URL`, `NO_TITLE`;
- `NO_SOURCE_TEXT`: less than 60 characters of retrieved text (20 for a video);
- `AD_OR_SPONSORED`, `BLOCKED_TOPIC`, `OFF_TOPIC_RESTAURANT_TRAVEL`;
- `NOT_FOOD` (Tier C only), `WEAK_TIER_C`;
- `TOO_OLD`: more than 365 days.

**Freshness.**
- The trend lane (요즘) takes only items published in the last 30 days.
- Older items may appear in the evergreen lanes (tips, health, habit) up to 365 days, dated on the card.
- A story runs in **one** edition only (`selectedFor`), so a stale source is not recycled day after day.

**Ranking.**

```
score = 0.35 × source trust + 0.25 × freshness + 0.20 × lane relevance + 0.20 × quality
```

- Freshness is exp(−age/21 days).
- Quality is text length plus a validated image.

**Selection.**
- Each lane takes at most 8 stories, and at most 2 from one source; **8 is a maximum, not a quota**.
- The featured story is the best qualifying story with a validated image of its own. Only when none
  has one does the page show a quiet text-only hero.

## Truth and image rules

- **Summary:** at most 120 characters, cut from the source's own text. Links, addresses and hashtags
  are removed. If less than 20 characters remain, the card shows title and source only. Nothing is
  written by Babdoduk: no generated claims about taste, health, trends or ingredients.
- **Image:** allowed sources, in order of preference:
  1. RSS/Atom media of the same item;
  2. an image in the same feed entry's HTML;
  3. the official YouTube thumbnail of the same video;
  4. the og:image declared by the same article's own page.

  It is shown only after the URL answered with an image. There are no stock, search, generated or
  other-article images.
- **Stored editions:** every run also sanitizes them. Desk items, link-less items and idea desks are
  removed; generated summaries of items built before provenance existed are dropped.
- **Validation:** `validate_content.py` rejects any desk, sourceless or link-less story in any edition,
  and accepts sparse lanes.

## Health report

`research/magazine/health.json` is written on every run:
- per adapter: its status, code, item count and last success;
- the counts of candidates, new, duplicates, rejected and selected;
- `fabricated: 0`;
- warnings for failing, stale and degraded sources.

A broken source means fewer stories and a warning, never filler.

## Evaluation

`python -m discovery.evaluate` (from `scripts/`) runs synthetic sources through the real pipeline.
It covers:
- a recipe, a YouTube video, a duplicate URL, a duplicate title;
- a missing image, a valid image, a bad URL, an ad, an off-topic item;
- a sparse lane and a fetch failure.

It reports precision, duplicates suppressed, URL and image provenance completeness, and the
fabricated count; the release bar is 0 fabricated. `tests/test_magazine_discovery.py` asserts it,
along with the audit rules above.
