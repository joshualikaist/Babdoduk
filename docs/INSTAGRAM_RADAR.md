# Instagram 꽁밥 radar (owner request 2026-10-29)

**Lab-only / not promoted to production in the current main baseline.** It runs on the operations PC
from the lab checkout, like the Dooray Radar. Status: **token in place since 2026-10-29; `ig-check` and one live
dry run passed (below); the resident service and the Telegram question are not live yet.**

## What it does

KAIST student council and department accounts announce free food on Instagram, often only there or
only for their own department. The radar reads their **public posts through the official Meta Graph
API (Business Discovery)**, decides which posts are a 꽁밥, asks the owner when unsure, and hands the
confirmed ones to the existing pipeline.

```
Business Discovery (GET, every 1-6 h per account)
  -> new posts + images downloaded at once (.local/ig-media, content-addressed)
  -> free keyword prefilter -> gpt-6-luna -> (unsure) gpt-6.1-terra -> (still unsure) owner on Telegram
  -> confirmed: one Dooray collection task per event (Korean/English twins merged)
  -> the cloud pipeline extracts, validates, dedups and publishes it like any mail
```

Handing over through a Dooray task (the mail radar's path) keeps one extraction, validation and
publication path and needs no database migration. The radar's own records live in
`.local/ig-radar.sqlite3`: `ig_accounts`, `ig_posts`, `ig_post_images`, `analysis_runs`,
`food_event_candidates`, `human_reviews`, `api_usage_log`.

## Meta setup (done by the owner, 2026-10-29)

* Facebook Page **밥도둑 Babdoduk** (`1424442224076460`), Instagram professional account
  **@babdodukms** (IG user `17841440065235713`), business portfolio `971866082067099`.
* App **Babdoduk Food Radar** (`1377291371146412`), **Development mode** (do not change), with only the
  read permissions `instagram_basic`, `instagram_manage_insights`, `pages_read_engagement`,
  `pages_show_list`. The app also lists `instagram_manage_comments`; the radar never uses it and the
  owner may remove it in the dashboard.
* Verified by hand with Graph API v26.0: Business Discovery works for `shoutoutto.ee`, `in.cs.tagram`,
  `kaistua_grit`; `me/accounts` is empty (portfolio-owned page), so the IG user id is configured, not
  looked up; `account_type` is not a field there.

## Owner steps (the radar never does these)

1. **Server token.** Recommended: business.facebook.com -> System users -> a system user with the app,
   the page and @babdodukms assigned -> generate a token with the four permissions above (no expiry).
   Alternative: a 60-day long-lived user token (`fb_exchange_token`, needs the app secret); the radar
   warns on Telegram 7 days before it expires.
2. **`.env` of the operations checkout** (`~/Babdoduk-ops/.env`, mode 600), typed by the owner:
   ```
   META_GRAPH_VERSION=v26.0
   META_IG_USER_ID=17841440065235713
   META_ACCESS_TOKEN=...          # the server token
   META_APP_SECRET=...            # optional: adds appsecret_proof
   OPENAI_MODEL_PRIMARY=gpt-6-luna
   OPENAI_MODEL_REVIEW=gpt-6.1-terra
   ```
   The OpenAI key and the Telegram bot are the existing ones (`OPENAI_API_KEY`; the ops alert bot in
   `ops.sh alert`). `TELEGRAM_BOT_TOKEN` / `TELEGRAM_ALLOWED_CHAT_ID` override the bot if set.
3. **OpenAI monthly limit** in the OpenAI dashboard (suggested $10).
4. Then, on the operations PC:
   ```
   scripts/linux/ops.sh ig-check            # config, scopes, expiry, models, accounts, Telegram
   scripts/linux/ops.sh ig-once --dry-run   # one cycle: collects and analyzes, sends and writes nothing
   scripts/linux/ops.sh ig-install          # the systemd --user unit (once)
   scripts/linux/ops.sh ig-start            # resident; ig-status / ig-stop
   ```

## Accounts

`inputs/instagram/accounts.json` (authored, never deployed): username, display name, interval in
minutes, active. The radar syncs it into `ig_accounts` at start and keeps per-account state there
(last success, last media id, status `ok` / `unsupported` / `error`). An account that is not a
professional account, or does not exist, becomes `unsupported` with one Telegram notice and is not
retried; fix or remove it in the file.

## Limits

* Business Discovery is rate-limited per caller (@babdodukms) by Business Use Case limits that grow
  with the account's reach, so they start small.
* Every answer's `X-App-Usage` and `X-Business-Use-Case-Usage` go to `api_usage_log`. Above 80 % every
  interval doubles (Telegram notice); below 50 % it returns. A rate-limit error (codes 4, 17, 32, 613,
  800xx or HTTP 429) stops the round and backs off 15 min, doubling up to 6 h.
* Accounts are read one after another with a pause. Posts before `collect_since` in
  `inputs/instagram/accounts.json` (a KST date; owner decision 2026-10-29: 2026-10-26, that week's
  Monday) are never collected or analyzed; a first check takes at most 30 posts. Later runs stop at
  the first known post (10 per call); a known or older post is skipped, not a stop, within a page,
  because a pinned post can sit above newer ones. 32 undergraduate accounts at 3, 4 or 6 h by
  priority (owner-approved 2026-10-29; graduate accounts never, `docs/INSTAGRAM_SOURCES.md`) make
  about 190 calls a day.

## Analysis

* Prefilter (free): no food word in the caption and at most one image -> not a candidate, no model call.
* `gpt-6-luna` with the caption, the post time and up to 6 images, Structured Outputs (the fields of
  `analyze.Judgement`). Confidence >= 0.8 decides.
* Otherwise `gpt-6.1-terra` on the same input: >= 0.75 decides (its verdict wins over luna's).
* A confirmation without a start or end time goes to the owner (`analyze.undated`): whether it is still
  ahead cannot be read. The prompt also rules out prize draws and vouchers, recaps of events that
  already took place, and events only for graduate students. On the first live run (2026-10-29) a
  coffee-voucher draw and a past graduate orientation recap, both undated, were confirmed and handed over.
* The bridge rereads each candidate just before writing its task, so a status changed meanwhile (an
  answer, a correction) is respected.
* Otherwise the owner: a Telegram message with the poster, the summary, both verdicts and the
  permalink, and ✅ / ❌ / ✏️ (✏️ asks for "필드: 값" lines in a reply). Nothing is handed over before
  the answer. More than 5 questions a day wait for a digest at 09:00 or 18:00 KST. The owner's latest
  verdicts are few-shot examples in later prompts.
* Events that are over (`analyze.is_past`: the end, or the start plus 3 h, before now; without a
  readable time, a post older than 14 days) become `expired`: never asked about, never handed over.
  A first run backfills months of posts; on 2026-10-29 all 31 confirmed posts were past events.
* Merging: posts of one account within 48 h with the same start time are one event when they are in
  two languages or either is `mixed` (a Korean and an English post name place and food differently),
  unless their head counts differ; in one language the place and food must match too. The first confirmed post creates the task with every permalink.
* Models are configuration. Each day the radar checks that both exist and accept an image; if not it
  stops and says so on Telegram (it never swaps a model). Every call's tokens and estimated cost are
  recorded; a month above $5 is announced. Estimated cost: about $1 a month.

## Rules

* Official Graph API only: no scraping, no unofficial API, no login automation. GET only; no posting,
  comments, messages or ads; `instagram_manage_comments` is never used.
* No Meta app, mode, permission or account change by the radar or an agent.
* The token goes in an `Authorization` header (never a URL); with an app secret every call carries
  `appsecret_proof`. Tokens, secrets and keys are never printed, logged, stored in the database or
  committed. Logs hold fixed codes (`IG_*`); signed CDN URLs are masked if ever logged.
* Posts and images are kept on the operations PC for analysis and attribution; the site shows the
  extracted summary and the original link.

## Acceptance (docs requirement -> status)

1. `ig-check` confirms the four scopes: **live, 2026-10-29**: token valid, never expires, all four
   scopes and no other.
2. Three accounts collected, images saved, no duplicates on a rerun: **live dry run 2026-10-29**: 90
   posts (30 per account), 1 image download failed, 2 prefiltered, 57 rejected, 31 confirmed (23
   events), $0.10. Rerun without duplicates: synthetic test.
3. Golden posts (`Dd-1fg2j4Nf` confirmed with correct fields, `Dd-1k-tD9Iw` merged into it,
   `DeG1R4Njz4m` not a candidate): **live, 2026-10-29**, confidence 0.99 each; start 10-06 17:30,
   GOPIZZA set, the paid-fee EE eligibility.
4. An unsure post asks on Telegram and the button changes the state: **live, 2026-10-29** (first
   run of the service, 32 accounts, 21 posts since 10-26, 2 questions answered by the owner).
5. Usage headers recorded, backoff unit-tested: done.
6. No secret in logs or commits: tested on every file the radar writes.

Open: the published event's source label is the mail source (the task path), not "Instagram"; a
source label of its own is a pipeline change for a later task.
