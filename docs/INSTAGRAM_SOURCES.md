# Following department Instagram accounts (research, 2026-10-18)

> **2026-10-29:** the owner set up the official route (Meta app, Business Discovery). The radar that uses it is `docs/INSTAGRAM_RADAR.md`; anonymous scraping was tried once the same day (instaloader 4.16 and the embed page) and is blocked (HTTP 429 / error page).

## Account check, 2026-10-29 (Business Discovery, one GET each)

36 handles found on department sites, linktr.ee pages and search results were checked through the
radar's own token. **Readable (professional accounts)**, now in `inputs/instagram/accounts.json` (24):
shoutoutto.ee, in.cs.tagram, kaistua_grit, kaist_cbe, idkaist_student, thurithuri_mathuri, kaist_chem,
bbe_kaist, kaist_gsa, kisakaist, kaist.ina, sparcs.kaist, kaist_me, kaist_ae, kaist_cee, kaist_bcs, kaist_id,
kaistbio_official, kaist_engineering, kaist_dhcss, kaist_stp, kaist_isss, kaist_library, official_kaist.
Readable but left out: kaistbiz (Seoul campus), startupkaist (4 posts), kaistua_partnership (last post
2026-03), kaist_studyabroad (last post 2024-05).
**Not readable (personal accounts, error 110):** kaist.mse (신소재 학생회), kaist_aerospace (항공 학생회),
kaist_gsis, kaist_future, kaistua_glow and kaistua_kind (past councils), kaist._.welfare, gdsc.kaist,
vlab.kaist. They can be read once their owners switch to a professional account (free).
**No Instagram handle found:** the student councils of 기계공학과, 물리학과, 생명과학과, 기술경영학부,
산업및시스템공학과, 원자력및양자공학과, 반도체시스템공학과, 융합인재학부, the 새내기학생회, 동아리연합회
and 생활관자치회 (Facebook pages or e-mail only).

Why: some events are announced only on a department's or a student council's Instagram account, or only to
one department. The pipeline reads Dooray mail; it cannot see those. This note records what was found, with
the dates it was checked, so the owner can decide. **Nothing here has been built or run against Instagram.**

All GitHub numbers were read from the GitHub API on 2026-10-18. "Verified" means read from a primary page that
day; the rest is marked.

## Options

| Option | Source | Fetches | Login | Status on 2026-10-18 |
| --- | --- | --- | --- | --- |
| **Instagram Graph API, Business Discovery** (official) | Meta developer docs | recent media of *other* professional accounts. Media fields (media reference, read 2026-10-18): `caption` (not for album children), `media_type`, `media_url` (omitted for media flagged for copyrighted audio), `permalink` (not for album children), `timestamp` (UTC), and the `children` edge of a carousel (its response is not described on that page) | Facebook-login token; the calling account and the target must both be Business/Creator | Documented (page read 2026-10-18). Personal accounts are excluded; age-gated accounts are not returned; rate limits and App Review need are **not stated on that page** (unverified). `caption` exists only for the Facebook-login flavor of the API. |
| **instaloader** `instaloader/instaloader` | GitHub, MIT, Python, 13.6k stars | per its README (read 2026-10-18): public and private profiles, hashtags, stories, feeds, saved media; captions, comments, geotags; `--fast-update` and `--latest-stamps` fetch only newer media | needed for private profiles; the README says nothing about rate limits (see the issues in the next column) | Maintained: v4.15.4 on 2026-10-12 ("fix profile resolution and logged-in post fetching"). **Anonymous 429 errors are still open** (#2726, Aug 7 2026: first request to `web_profile_info` returns 429 on three networks; #2750, Oct 10 2026). HTTP/2 fix PR #2730 is open, #2676 was closed unmerged. |
| **instagrapi** `subzeroid/instagrapi` | GitHub, Python, 7.0k stars, pushed 2026-10-17 | private mobile API: media, stories, users | login required | Active. GitHub could not classify its license (`NOASSERTION`): read the LICENSE file before any use. Login-based, so account challenge/ban risk (not measured here). |
| **RSSHub** `DIYgod/RSSHub` | GitHub, AGPL-3.0, TypeScript, 46.6k stars, pushed 2026-10-18 | `/instagram/user/:id` as an RSS feed | an Instagram account in its config (a user report on RSSHub 2026.04.04 got an authentication error without one) | Active project; the Instagram route depends on a logged-in account. |
| **RSS-Bridge** `RSS-Bridge/rss-bridge` | GitHub, Unlicense, PHP, 9.3k stars | feeds, including an Instagram bridge | unknown | Project active; the Instagram bridge's current state was **not verified**. |
| instagram-private-api `dilame/instagram-private-api` | GitHub, MIT, TypeScript, 6.5k stars | private API | login | **Stale**: last push 2024-08-09. |
| Others by stars | `postaddictme/instagram-php-scraper` (3.4k, last push 2025-05), `huaying/instagram-crawler` (1.4k, 2024-05), `drawrowfly/instagram-scraper` (0.9k, 2023-03) | | | Stale or low-activity. Not recommended. |
| `sokomishalov/skraper` | GitHub, Apache-2.0, Kotlin, 353 stars, pushed 2026-10-12 | multi-site scraper | unknown | Small; its Instagram provider was not checked. |

## Honest risk

* Instagram's terms prohibit automated collection; tools that log in risk the account (checkpoint, ban) and the IP
  (429). Anonymous access is rate-limited and currently unreliable (see instaloader #2726).
* The repository's rules (`AGENTS.md`) block credential and OTP/MFA automation for the Portal and Dooray. Using an
  Instagram login would be a **new owner decision**.
* Poster images are other people's work: store captions and links, show the original link, no reuse beyond the
  site's own listing. This is not legal advice.

## Recommendation

1. **Check which department accounts are Business/Creator accounts** (a category label shows under the name on the
   profile). For those, use the official Business Discovery route: no password given to any scraper, terms-compliant.
   The owner needs a Business/Creator Instagram account linked to a Facebook Page, a Meta developer app and a
   long-lived token (refreshed before it expires). App Review need: verify in the permission docs first.
2. Personal-type accounts cannot be read officially. Options: ask the account owners to switch to a Creator account
   (free), ask them to share posters by e-mail, or accept instaloader with a *dedicated throwaway account*, a session
   file, one check every few hours per account, a human solving any checkpoint. Treat this as unreliable until the
   429 issues are resolved.
3. Do not start with RSSHub or instagrapi: both need a logged-in account and add moving parts.

## How it would fit the pipeline (not started)

* Input (authored): `inputs/ggongbab/instagram-sources.json` with `{handle, unit, audience, enabled}` per account.
* A collector (`scripts/ggongbab/collectors/instagram.py`) returns one `RawItem` per new post (dedup by shortcode):
  caption as text, poster images as attachments, `source_url` = the post link. The existing AI parser then reads
  caption and poster exactly as it reads a mail; `sessions` and `audience` (see `docs/GGONGBAB_PAGE.md`) come with it.
  The account's unit (`기계공학과`) is the strongest audience signal there is: it can be passed to the model as the
  poster's source.
* Failure modes map to fixed codes and the existing alerts (private account, deleted post, rate limit, login
  challenge). Tests use recorded fixtures only: no live call in the suite.
* Protected under `AGENTS.md`: a new collector, secrets for the token, the workflow schedule and the public
  `sources[].type` enum (a schema change). Each needs the owner's explicit authorization.

## Open decisions for the owner

1. Official API only (Business/Creator accounts), or also a throwaway-account scraper for the rest?
2. Which accounts (the list of profile URLs), and how often to check (suggested: every 3-6 hours).
3. Who creates the Meta app and token, and where the token lives (never in the repository).
