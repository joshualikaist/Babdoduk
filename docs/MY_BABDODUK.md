# 마이 밥도둑 (밥도둑 2.0 Phase 2)

Phase 2 of the 밥도둑 2.0 requirements (Q1, Q6, Q7, Q13, Q18, Q19). The owner approved starting it on 2026-11-08 ("2,3 단계도 승인해줄게").

This phase adds:

- optional sign-in with Google and Kakao;
- the 마이 밥도둑 page, `my.html`;
- the saved free-food list on the server;
- the merge of what a guest saved in the browser;
- clearing saved data and leaving.

Phase 1 (save, share, calendar) is described in [GGONGBAB_LIVE.md](GGONGBAB_LIVE.md); the overall plan is in [BABDODUK_2_PLAN.md](BABDODUK_2_PLAN.md).

**Status:** on babdoduk-lab since 2026-11-10, and on production (www.babdodukms.com) since 2026-11-11 (owner: "로그인은 푸시 및 배포가 안된거임? 이거까지 했어야지"). The owner turned on Google and Kakao under Supabase Authentication and applied migration 011, then `enabled` in `js/babdoduk-auth-config.js` became `true`.

With the switch off, `my.html` shows "로그인은 준비 중이에요", and no page loads the login client.

`my.html` is served on every host, and every page's top bar has a person icon beside Instagram that opens it (`js/site.js`); since 2026-11-12 (owner) 마이 밥도둑 also heads the 더보기 group, which is the second group of the phone menu panel (`shared/nav.html`). The sign-in buttons are raised, with each provider's mark. The configuration's `hosts` list names www.babdodukms.com, babdodukms.com, babdoduk.vercel.app and babdoduk-lab.vercel.app. Lab still shows the 먹킷리스트 counts; production's `js/my.js` hides them (`SHOW_PLACES = false` on `main`) because 밥약 메이커 is lab-only.

## What visitors see

| Situation | Behavior |
|---|---|
| Not signed in | `my.html` explains what signing in adds and shows **카카오로 계속하기** and **Google로 계속하기**. Every feature works without signing in. The site never opens a login popup on its own when someone visits. |
| Inside the KakaoTalk browser | Google blocks login inside embedded browsers, so the Google button is replaced by a **기본 브라우저로 열기** link (`kakaotalk://web/openExternal`). Kakao login works there as usual. |
| Login failed (`?error=` on return) | An alert says "로그인하지 못했어요". |
| Right after signing in | Items this browser saved that the account does not have are merged in **automatically**: see "Guest merge" below for the full rules. |
| Signed in | The page shows: <ul><li>"{name}님, 반가워요";</li><li>**저장한 꽁밥**, with upcoming, being checked, removed from the list and past items, and a link to each upcoming event;</li><li>**먹킷리스트** counts (Phase 3 data);</li><li>**내 정보**: display name, login methods, linking the other login method, logging out;</li><li>**데이터 지우기·탈퇴**.</li></ul> |
| Logging out | Logs out on this device only (`scope: local`). The list this browser saved separately stays as it is. |
| On the Today's Free Food page (`ggongbab.html`) | If someone is signed in on this browser, ☆ saves to the account and the saved box says "계정에 저장돼요 · 다른 기기에서도 보여요" with a link to 마이 밥도둑. If the server refuses a save, the screen reverts and says "저장하지 못했어요". If the account cannot be loaded, the page shows the browser's list and says so. **Visitors who have not signed in never load the login client**: it loads only when this browser holds a login token (`sb-<ref>-auth-token`). |
| Clearing data | **저장한 데이터 지우기**, then confirm, deletes the saved events, restaurants, memos and lists stored on the account. The account stays. An optional checkbox also clears this browser's list. |
| Leaving | **탈퇴하기**: <ul><li>If the last login was more than 10 minutes ago, the person must log in again with the same provider. They return to `my.html?next=leave`, and the marker is removed from the address.</li><li>They then tick **모두 지워지는 것을 확인했어요** and confirm.</li><li>The account and every row are deleted, and the page shows "탈퇴했어요".</li><li>It tells them: "결제·주문 정보를 받지 않아 법으로 따로 보관하는 개인정보는 없어요."</li></ul> |

Policies:

- KAIST verification is not required (Q18).
- Signing in does not make anyone eligible for an event: eligibility is set per event, and the page says so.
- The profile is private.
- The site does not ask for an email address, and does not show one if a provider sends it.

## Rules

* **Guest merge (Q13).**
  - The page reads the browser's `babdoduk-ggongbab-saved` v1 and the Phase 3 `babdoduk-places-saved` v1.
  - Only ids the account does not have are added (`merge_saved_events` and `merge_saved_places`).
  - For an id the account already has, the account's `seen`, status and memo are kept, and only the earlier `saved_at` is kept.
  - When memos differ, the account memo is kept and the page reports "메모가 서로 다른 식당 n곳".
  - Nothing is deleted or overwritten.
  - The page remembers exactly which ids it added, and **되돌리기** removes only those.
  - The browser's own copy is never rewritten.
  - The time each user's data was merged on this browser is recorded in `babdoduk-account-merged` `{v:1, users:{<uid>: iso}}`, at most 10 users. On later logins only items saved after that time are merged. This stops an item deleted on another device from coming back from an old browser copy.
* **Shared computers.** Logging out leaves the browser's guest list alone, and the account list is never written into the browser. A guest's list on a shared PC can therefore join the account. The page tells the person right away and offers 되돌리기 ("내 것이 아니면 되돌릴 수 있어요").
* **Two providers.** Supabase links accounts automatically only when both providers give the same verified email. Kakao may provide no email, in which case the two logins become separate accounts. The page explains this and offers **{p} 로그인도 연결** (`linkIdentity`). That requires Supabase's Manual Linking setting; when it is off, the page says "지금은 로그인 방법을 연결할 수 없어요". Inside KakaoTalk's in-app browser Google refuses the sign-in, and the default browser opens without this session, so the page shows no Google link button there: it says "Google 연결은 카카오톡 안에서 막혀 있어요. 기본 브라우저에서 카카오로 로그인한 뒤 연결해 주세요." with **기본 브라우저로 열기** (`kakaotalk://web/openExternal`). Linking Kakao stays a button inside the app.
* **Display name.** On the first login, the name the provider gives (`full_name`, `name` or `nickname`) is stored as a private `profiles.display_name`, which the person can change or clear. It is never shown anywhere public.

## Data (supabase/migrations/011_accounts.sql)

| Table | Contents |
|---|---|
| `profiles` | `user_id` (→ `auth.users`, cascade), `display_name` (1–40 characters or null) |
| `saved_events` | `(user_id, event_id)` primary key, `saved_at`, `seen` jsonb (2 KB or less). Same id rule as Phase 1. At most 300. |
| `saved_places` | `(user_id, place_id)`, `status` want/been/again, `memo` (500 characters or less, private), `saved_at`, `updated_at`. At most 1,000. |
| `place_lists`, `place_list_items` | The person's own restaurant lists (at most 20, 200 restaurants each). `is_public` must match whether `share_slug` is set. |

* **RLS denies everything by default.**
  - All five tables grant rights only to `authenticated`, and only on rows where `user_id = auth.uid()`; for list items, the owner of the list.
  - `anon` cannot read anything.
  - Triggers stop a row's `user_id` from changing to someone else's.
* **The only public read is `public_place_list(slug)`.** It returns only the title and restaurant ids of a list whose owner made it public. It never returns the owner, a name, a memo or a status.
  - `set_place_list_sharing(list, true|false)` issues a new 22-character slug each time sharing is turned on, and clears it when sharing is turned off, so an old link stops working.
* **Deleting.**
  - `delete_my_saved_data()` deletes only your own rows.
  - `delete_my_account()` (security definer) works only when `last_sign_in_at` is within the last 10 minutes. It then deletes the `auth.users` row, which cascades to every table above and to Supabase's identities and sessions.
* **No secrets in the browser.** Only the URL and publishable key in `js/ggongbab-public-config.js` are used. No service key appears in any file.

## Code

* `js/babdoduk-auth-config.js`: on/off switch and allowed hosts (`enabled: true` since 2026-11-10; lab hosts only).
* `js/babdoduk-account.js` (`window.BabdodukAccount`): login and logout, provider linking, guest merge and undo, the account store (same interface as Phase 1's `createStore`: change on screen first, undo if the server refuses), profile, clearing and leaving.
  - It loads the same pinned Supabase SDK as the tip board (version and SRI).
  - Options: `flowType: 'pkce'`, `persistSession`, `detectSessionInUrl`.
* `js/my.js` and `css/my.css`, page `my.html`, strings `my.*` in `i18n/` (Korean and English).
* `js/ggongbab.js`: the account store when signed in, and the saved-box note.

## Tests

* `tests/test_accounts_db.py`:
  - Static checks on the SQL.
  - Where `pgserver` and `psycopg` are installed, migration 011 is applied twice to a disposable local PostgreSQL 16 with a small stand-in for Supabase's `auth` and its roles. The tests then act as `anon`, user A and user B:
    - anonymous access is blocked;
    - other users' rows can't be read, written or have their owner changed;
    - merge rules;
    - memo conflicts;
    - shared lists (title and ids only, slug gone after unsharing);
    - limits;
    - clearing data;
    - leaving (blocked for an old login; full cascade for a recent one, other users unaffected).
  - Proof that the tests catch real breakage: changing the policy to `using (true)` or the time limit to 10 days made 3 tests fail.
  - The default development environment and CI do not have `pgserver`, so the DB tests skip there.
* `tests/test_my_babdoduk.py`: browser tests with a fake Supabase client that follows the same own-rows rule.
  - Covers:
    - off by default, and never on production;
    - no client for visitors who have not signed in;
    - the two login redirects and the KakaoTalk in-app browser;
    - login failure;
    - automatic merge, merging once, undo;
    - list states;
    - saving to the account from the free-food page, and undo when the server refuses;
    - fallback when the account can't be loaded;
    - display name;
    - logout;
    - clearing data;
    - leaving (re-login and checkbox);
    - English;
    - 360–1440 px wide.
* **NOT TESTED:**
  - real Google and Kakao logins;
  - Supabase's real redirect, PKCE and token refresh;
  - real Supabase identity linking;
  - real phones (iPhone Safari, Android Chrome, KakaoTalk in-app browser).

  These are checked by hand on babdoduk-lab after the owner finishes the setup.

## Before turning it on (owner)

1. Google Cloud: OAuth consent screen (email, profile and openid scopes) and a web client. The redirect URI is `https://myjglfynhnptlclawlcc.supabase.co/auth/v1/callback`.
2. Kakao Developers:
   - Turn on Kakao Login and set the same redirect URI.
   - Consent items: nickname and profile picture; email is optional.
   - Create a Client Secret.
   - Add `https://www.babdodukms.com` under Platform → Web.
3. Supabase Authentication:
   - Enter the keys under Providers for Google and Kakao. For Kakao, turn on the option that allows users without an email.
   - URL Configuration: Site URL `https://www.babdodukms.com`; Redirect URLs `https://babdoduk-lab.vercel.app/**`, `https://www.babdodukms.com/**` and `http://localhost:8000/**`.
   - Turn on Manual Linking (needed for **{p} 로그인도 연결**; it is off by default).
4. Apply `011_accounts.sql` in the SQL editor.
5. Change `enabled: true` in `js/babdoduk-auth-config.js` (lab commit), then test with a real phone on babdoduk-lab.

Secrets (Client Secret, REST API key) go only in the Supabase dashboard. They never go in the repository or in a chat.

## Not done yet (needs approval)

* **Production release:** needs owner approval of what was checked on lab, plus an update to the AGENTS.md rule that only `tip.html` loads the public config on main.
* **Sharing restaurant lists:** the DB functions exist. The screen will come with Phase 3's restaurant pages.
* **Anonymous statistics:** not decided.
