# Ggongbab discovery: radar, evidence, evaluation (lab)

The measure is not "did the model understand the mail eventually" but **"did a student know
about the free food while it was still useful"**, without trading away privacy, truthfulness,
source provenance, account security or deterministic validation. MISS-001 (2026-09-28, a coffee
truck handing out coffee "until sold out", mailed after it started) is the incident that
defined this document. Its forensics are in the MISS registry below.

## Two systems, two cadences

| | Free Food Radar | Magazine discovery |
|---|---|---|
| Purpose | find free food fast | find interesting food content and trends |
| Sources | Dooray mail, Portal, KAIST notices, department/student-council notices, official accounts | RSS, YouTube, Naver Blog, Instagram, general web |
| Latency that matters | minutes | hours |
| Evidence bar | explicit provision wording, deterministic validation, review when unsure | editorial; softer sources are fine |
| Output | `data/ggongbab/latest.json` (public) | `data/magazine/` |

They never share a cadence or a queue. A two-day cadence is acceptable only for slow editorial
research, never for the radar.

## Stages and what each may decide

```
source (mailbox LIST / Portal LIST / notice / feed)
  -> radar or discovery agent      decides only: worth examining? (+ urgency)
  -> candidate (private)           Dooray collection task or private queue
  -> sanitizer                     strips addresses, phones, ids, headers, timing lines
  -> GPT-5.6 Luna                  structured extraction only; never the search engine
  -> deterministic validator       checks every field against rule facts from the same text
  -> publish (explicit food, no review, confidence) or needs_review
```

No LLM has publish authority. The radar only answers "worth examining?"; it cannot publish.
`urgency` ("high" for flash hand-outs or same-day events) orders scans and alerts and never
relaxes evidence or publication rules.

## Source matrix

| Source | Authentication | Target cadence | Trust | Output | Collector | Failure mode | State (2026-09-28) |
|---|---|---|---|---|---|---|---|
| Dooray mailbox (radar) | local SSO session, dedicated Chrome on 127.0.0.1:9222 | 2–5 min | A | private collection task | `dooray_web_agent.py` | SSO expiry, UI contract change, PC off | recovered and calibrated; no scheduled scanner yet (Phase 2) |
| Dooray collection project | cloud API token (GitHub secret) | on trigger + 30-min schedule | A | Supabase -> feed | cloud `refresh_ggongbab.py` | GitHub schedule delay | the schedule runs ~6×/day (see `GGONGBAB_TRIGGER.md`) |
| Portal recent LIST | local SSO session, dedicated Chrome on 127.0.0.1:9223 | 60 s | A (title = Stage A signal only) | private pending ledger | Portal worker | session expiry, transport | healthy again since 2026-09-28 13:57 |
| KAIST public boards | none | 10–30 min | A | feed | cloud collector | markup change | rides the cloud schedule |
| Department / student-council pages | none | 10–30 min | A/B | candidate | not built | markup change | Phase 4 |
| Curated Instagram accounts | dedicated local account and profile | 30–60 min | B | private review only | local sidecar | login challenge, rate limit, ban | Phase 4 POC |
| General web / Naver Blog via search | search API | 1–3 h | C | private review only | local sidecar | third-party ranking, SSRF | Phase 4 POC |
| Food RSS, Naver Blog RSS | none | 30–60 min | B/C | magazine | local sidecar | feed change | Phase 4 POC |
| YouTube | none | 6–24 h | C | magazine only | local sidecar | yt-dlp breakage | Phase 4 POC |
| Manual (`data/ggongbab/manual.json`) | owner | on demand | A | feed | cloud collector | — | 0 items |

**Trust tiers.** A: KAIST official notices, Portal, institutional mail, official department pages.
B: official department/student-council/club accounts, a company's own campus-event account.
C: blogs, general social posts, community posts, general web. A Tier C item never creates a public
listing by itself: it looks for corroboration (preferably Tier A) and otherwise stays `needs_review`.

## First come, supply and time windows

* `선착순` is registration only with sign-up wording (`선착순 신청/모집/접수/마감`). With a hand-out
  verb (`커피 선착순 제공`, `선착순 배부`) or `소진 시 종료/까지`, it is a **supply limit**:
  `RuleFacts.supply_limited`, `supply_limit_text`, `end_condition = "until_sold_out"`. These are internal
  fields, not in the public schema, until their public value is proven.
* A supply limit is never eligibility. `방문자 전원` is not a restriction. `선착순 50명` keeps its
  meaning as a capacity.
* When Luna reads a supply limit as sign-up, the validator corrects it to `unknown` without a
  review. Any other unsupported `true` still goes to review.
* An event without an end time stays listed on the page for 3 h after it starts, the same window the
  feed keeps it (`GGONGBAB_EXPIRED_GRACE_HOURS`). Before 2026-09-28 the page hid it at its start time,
  so MISS-001 could never have been shown even with zero pipeline latency.

## Miss registry

`tests/fixtures/ggongbab/misses/MISS-NNN-<slug>.json`. Every confirmed miss becomes a fixture, and
`tests/ggongbab/test_miss_registry.py` replays each one through the prefilter, rules, validator
(including known model misreadings), exporter and the real page selection code.

A fixture holds a sanitized source text, the source class, why it was missed, and what each stage
must conclude. It never holds sender or recipient addresses, Dooray/Portal ids, private links,
cookies, internal task ids or personal information; the test fails if it looks like it does.

| ID | Date | Source | What was missed | Root cause |
|---|---|---|---|---|
| MISS-001 | 2026-09-28 | Dooray mail | coffee truck, free coffee until sold out | no mailbox scanner since 2026-09-22; GitHub schedule gaps of hours; page hid open-ended events at start; `선착순` read as registration |

## Gold dataset and evaluation

`tests/fixtures/ggongbab/gold/*.jsonl` holds synthetic or sanitized samples:
* positives: meal, lunchbox, sandwich, pizza, snack, refreshments, coffee, drinks, meal coupons,
  gift cards, a free food truck, a coffee truck;
* supply and registration pairs;
* hard negatives: `12시 설명회`, `커피 산업 세미나`, `카페 할인 행사`, `점심시간 세미나`, `커피챗`,
  `식사 미제공`, `참석자 대상`;
* eligibility cases;
* ambiguous cases.

The miss registry is included automatically. The set grows toward 500–1000 samples; real mail
enters only after sanitization and owner review.

```
python scripts/eval_ggongbab.py                  # deterministic stages, offline
python scripts/eval_ggongbab.py --ai luna --budget 40
python scripts/eval_ggongbab.py --ai model:<name> --budget 20   # offline comparison only
```

The deterministic report covers:
* prefilter recall and precision against the expected-candidate labels;
* rule food-evidence recall, precision and false positives;
* food type, registration, supply, end condition, date and time accuracy.

The AI report covers:
* is_event, food provided, food type, registration, eligibility, date and time accuracy;
* free-food recall, false publications and review rate;
* tokens and estimated cost.

The AI stage uses the production sanitizer, prompt and validator, needs an explicit `--budget`,
and sends nothing without it. `tests/ggongbab/test_gold_eval.py` holds the deterministic stages to
100% on the seed set.

**Model policy.** Luna stays the extraction layer unless the gold set shows it misses the targets:
* explicit free-food recall of at least 99%;
* no false publication on hard negatives;
* field accuracy thresholds met.

A stronger model is compared offline on the failure categories. Being evaluated does not make it
the production fallback.

## Latency metrics

| Timestamp | Where it is recorded (private) |
|---|---|
| source_received_at | mail list row `createdAt`, written to the task as `Sent: YYYY-MM-DD HH:MM` -> `raw_items.metadata.mail_received_at` |
| discovered_at | radar scan time, task line `babdoduk_timing: discovered_at=…` -> `raw_items.metadata.discovered_at` (the line is removed before the sanitizer) |
| candidate_created_at | Dooray task `createdAt` -> `raw_items.metadata.dooray_created_at` |
| ingested_at | `raw_items` first write / `ingest_runs.started_at` |
| ai / validated_at | `ai_parse_runs.created_at` |
| stored_at | `events.first_seen_at` |
| published_at | the bot commit of `data/ggongbab/latest.json` and the Vercel status |

The intervals are:
* `T_detect = discovered − received`
* `T_ingest = ingested − discovered`
* `T_ai = validated − ai_started`
* `T_publish = published − validated`
* `T_total = published − received`

Target: P95 `T_total` < 10 min for same-day and flash events. The baseline measured on 2026-09-28:
* the wait for the next scheduled cloud run averaged 133 min, P95 300 min;
* a run itself takes about 3 min, plus 20–25 s for Vercel.

The trigger in `GGONGBAB_TRIGGER.md` is what closes that gap. None of these times is public.

## Unread mail

In the scheduled mode (`--read-state read`) an unread row is skipped before it is even classified.
Body access requires a verified read-state field and an already-read row (`web/calibrate.py`).
The radar may analyse list-level information only (subject, preview, received time, read flag,
id) of unread mail. Even that is allowed only after it has been shown, with a fresh unread test
mail, that listing never changes the read state. Unread bodies are never opened automatically.
What reaches Luna is the sanitized minimum.

## Browser and session boundary

* Each authenticated platform has its own dedicated browser profile under `.local/`; the owner's
  everyday Chrome profile is never used.
* Debug ports are loopback only (9222 Dooray, 9223 Portal), never 0.0.0.0, LAN or a tunnel.
* Cookies, session tokens, SSO material, addresses, private URLs and mail ids never go to Git,
  Actions artifacts, Supabase public tables, public JSON or logs.
* SSO/MFA is human work. A login challenge, CAPTCHA or rate limit stops a collector; it is never
  bypassed.

## Agent Reach (evaluated 2026-09-28, not installed)

`Panniantong/Agent-Reach` at `a19a171fa980a0785849596492e0af4db800c82f` (still upstream HEAD, MIT, v1.5.0)
is an installer, doctor and router rather than a data API: agents call the upstream tools directly.
* YouTube: yt-dlp.
* Web: Jina Reader, which sees every URL sent to it, so public URLs only.
* Search: Exa through the global npm tool `mcporter`.
* RSS: feedparser.
* Instagram: OpenCLI, a separate npm package plus a Chrome extension and a loopback daemon on
  127.0.0.1:19825 driving a logged-in Chrome.
* Naver Blog: no channel.

**Plan (Phase 4, local sidecar, no publication):**
* Babdoduk adapters in `scripts/discovery/` call pinned tools directly.
* Agent Reach, pinned to that commit in an isolated environment, is only an optional local doctor.
* Its `cookies` extra is never installed: it reads browser cookie stores.
* OpenCLI gets its own audit, a version pin and an unpacked extension from a reviewed commit (Web
  Store extensions update themselves).
* It runs only in a dedicated Chrome profile and account.
* Discovered URLs are http/https only; loopback, private-network, metadata and non-web schemes are
  rejected before any server-side fetch.
