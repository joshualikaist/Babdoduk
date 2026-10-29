# Following department Instagram accounts (research, 2026-10-18)

> **2026-10-29:** the owner set up the official route (Meta app, Business Discovery). The radar that uses it is `docs/INSTAGRAM_RADAR.md`; anonymous scraping was tried once the same day (instaloader 4.16 and the embed page) and is blocked (HTTP 429 / error page).

## Account check, 2026-10-29 (Business Discovery, one GET each)

Owner decision 2026-10-29: **undergraduate accounts only**, never a graduate one; an address is never
guessed (NOT_FOUND is recorded instead); a past council account is kept apart from the current one. 38
handles found on department and council sites, linktr.ee pages and search results were checked through
the radar's own token (profile, followers, last post, posts in 30 days, every image and carousel child of
the last 10 posts, food words in those 10 captions). Every readable account returned all its image URLs.
The owner approved the list below the same day; it is `inputs/instagram/accounts.json`. Priority sets the
interval: A 3 h, B 4 h, C 6 h (about 190 calls a day).

### Undergraduate departments (22, plus 반도체시스템공학과)

| Department | Account | Type | Last post | API | Priority |
| --- | --- | --- | --- | --- | --- |
| 물리학과 | kaist_physics | department ("카이스트 물리학과"; council or not unknown) | 10-12 | readable, food 5/10 | A |
| 수리과학과 | thurithuri_mathuri | student-run (likely) | 10-13 | readable, 6/10 | A |
| 화학과 | kaist_chem | student council | 09-28 | readable, 7/10 | A |
| 생명과학과 | kaistbio_official | department (council: Facebook only) | 10-08 | readable, 4/10 | B |
| 뇌인지과학과 | kaist_bcs (council NOT_FOUND) | department | 10-26 | readable, 0/10 | C |
| 기계공학과 | i_love_mesc / kaist_me | student council ("카이스트 기계공학과 학생회", given by the owner) / department | 10-27 / 07-22 | readable, 6/10 / 2/10 | A / C |
| 항공우주공학과 | kaist_aerospace / kaist_ae | undergraduate council / department | - / 10-29 | **personal (110)** / readable, 0/10 | - / B |
| 전기및전자공학부 | shoutoutto.ee | student council | 10-05 | readable, 6/10 | A |
| 전산학부 | in.cs.tagram | student council | 09-29 | readable, 5/10 | A |
| 건설및환경공학과 | kaist_cee (council NOT_FOUND) | department | 10-26 | readable, 0/10 | C |
| 바이오및뇌공학과 | bbe_kaist | department (council or not unknown) | 10-18 | readable, 7/10 | A |
| 산업디자인학과 | idkaist_student / kaist_id | student council / department | 10-07 / 10-26 | readable, 5/10 / 1/10 | A / C |
| 산업및시스템공학과 | isyse_kaist | student-run (likely; "아이조아") | 10-09 | readable, 9/10 | A |
| 생명화학공학과 | kaist_cbe | student council | 10-13 | readable, 3/10 | A |
| 신소재공학과 | kaist.mse | student council (department site footer) | ~13 posts | **personal (110)** | - |
| 원자력및양자공학과 | kaist_nqe | department ("NQe Official") | 06-19 | readable, 4/10 | C |
| AI컴퓨팅학과 | NOT_FOUND | | | | |
| AI시스템학과 | NOT_FOUND | | | | |
| AX학과 | NOT_FOUND | | | | |
| AI미래학과 | NOT_FOUND | | | | |
| 기술경영학부 | kaist_btm | department | **2025-11-04 (dormant)** | readable | held |
| 융합인재학부 | ts_kaist | department ("KAIST 융합인재학부") | 10-09 | readable, 2/10 | B |
| 반도체시스템공학과 | NOT_FOUND | | | | |

AI대학 (approved 2025-12-11, undergraduate courses since spring 2026; org chart
https://www.kaist.ac.kr/kr/html/kaist/0106.html): the college and its four department sites carry no SNS
link. 반도체시스템공학과 is `sse.kaist.ac.kr`; `semicon.kaist.ac.kr` is the graduate 반도체공학대학원 and
is excluded. No web page names kaist_physics, isyse_kaist, kaist_nqe, kaist_btm, ts_kaist or
kaist_freshman: their affiliation rests on the profile name returned by the API.

### Student councils and campus bodies

| Body | Account | Type | Last post | API | Priority |
| --- | --- | --- | --- | --- | --- |
| 제37대 학부 총학생회 GRIT (term from 2026-01-01) | kaistua_grit | undergraduate council | 10-28 | readable, 4/10 | A |
| 새내기학생회 | kaist_freshman | student body | 10-05 | readable, 4/10 | A |
| 행사준비위원회 상상효과 | imgeffect.kaist | student body | 10-27 | readable, 7/10 | A |
| 학생복지위원회 | kaist._.welfare | student body | - | **personal (110)** | - |
| 학생문화공간위원회 | scspace_kaist | student body | - | **personal (110)** | - |
| 환경자치단체 G-inK | green_in_kaist | student body | 10-28 | readable, 5/10 | B |
| SPARCS | sparcs.kaist | student group | 10-23 | readable, 0/10 | C |
| 교육방송국 VOK | vok_kaist | student group | 10-01 | readable, 1/10 | C |
| 응원단 ELKA | kaist_elka | student group | 10-08 | readable, 1/10 | C |
| 카이누리 | kainuri_official | student ambassadors | 10-08 | readable, 0/10 | C |
| KAIST | official_kaist | university | 10-28 | readable, 1/10 | C |
| 동아리연합회, 생활관자치회 | NOT_FOUND | | | | |

Also followed (readable): kisakaist (국제학생회, B), kaist_engineering (공과대학, C), kaist_isss (C),
kaist_library (C), kaist.ina (인도네시아 학생회, C).

### Not followed

* **Graduate (excluded by rule):** kaist_gsa (대학원 총학생회), kaist_dhcss, kaist_stp, kaistbiz (Seoul
  campus business school), kaist_gsis, kaist_future.
* **Past councils:** kaistua_glow (35th) and kaistua_kind (34th), personal (110); kaistua_partnership
  (last post 2026-03).
* **Personal (110), not readable:** kaist_aerospace, kaist.mse, kaist._.welfare, scspace_kaist,
  gdsc.kaist, vlab.kaist. Readable once the owner of the account switches it to a professional account
  (free); then add it to the file.
* **Readable but left out:** kaist_btm (dormant since 2025-11), startupkaist (4 posts), kaist_studyabroad
  (last post 2024-05).
* **Not checked:** the 92 club handles of the club directory and AE clubs (icarus_kaist, kaist_thrust,
  cfdkaist, kaisthealthae), kaisttimes.

When the owner finds a missing account (a NOT_FOUND council, an AI대학 department), check it with one
Business Discovery GET, add it here and to the file.

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
