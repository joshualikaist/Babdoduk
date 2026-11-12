# 내 꽁밥 캘린더 구독 (lab)

Owner 2026-11-12: a starred 꽁밥 should reach the phone's calendar without a file or an add screen each
time ("사람들은 ics 파일 이런거 다운 못받아"). The owner chose the subscription first ("1번부터 가도 돼
허락!"); a home-screen push alert 30 minutes before is the second step (`docs/PUSH_ALERTS.md`).

**Status:** lab only. Needs migration `supabase/migrations/013_calendar_feed.sql`, which the owner applies
in the Supabase SQL editor. Until it is applied, the card stays hidden and `/cal/…` answers 503.

## What a visitor does

1. Signs in (the list must be on the server for the phone to fetch it).
2. On 마이 밥도둑 (`my.html`), taps **아이폰 캘린더에 연결** (iPhone, iPad, Mac: `webcal://`), then 구독.
   Elsewhere the button is **구글 캘린더에 연결** (Google Calendar's add-by-address page).
3. From then on every star shows up in that calendar by itself, with an alert 30 minutes before; taking a
   star away takes it out at the next refresh. A star whose event day is over leaves the saved lists by
   itself but stays saved, so the calendar keeps the event (owner 2026-11-12).

Signed in, the star no longer opens a calendar add screen or file (the subscription takes it; on iPhone
Chrome a file download also cut off the account save). iPhone Chrome, Firefox and Edge get Google
Calendar's add page instead of an .ics download for guests.

## How it works

| Part | Where |
|---|---|
| Private address | `/cal/<token>.ics`, a 43-character random token per account (`my_calendar_feed()`, signed-in only). **새 주소 만들기** replaces it and the old address stops. |
| Calendar file | `api/cal.js` (Vercel function, routed by `vercel.json`). It reads the token's list with the anon function `calendar_feed_events(token)` and the site's publishable key, then writes each entry with the site's own calendar code (`js/ggongbab-live.js` `icsText`, 30-minute alarm). Times and places come from the current published feed (`data/ggongbab/latest.json`, then the archive), else from the snapshot saved with the star. A deadline-only giveaway has no time and is left out. |
| Privacy | The table `calendar_feeds` is closed to browsers. The file holds what the person saved (titles, times, places), never a name, email or account id. Anyone with the address can read that list, so the card says so and offers a new address. Responses are `private, no-store` and `noindex`. |

## Limits

- The phone decides how often it fetches a subscribed calendar; the file only hints every 15 minutes
  (`REFRESH-INTERVAL`, `X-PUBLISHED-TTL`). A star made just before an event can arrive after its alert.
- Google Calendar fetches subscribed addresses only every few hours; the card says so.
- Guests (not signed in) cannot subscribe: their stars live only in their browser.
- iPhone can be set to drop alerts from subscribed calendars; this needs checking on a real phone.

## Tests

`tests/test_calendar_feed.py`: the migration read statically and, with `pgserver` and `psycopg`, applied to
a throwaway PostgreSQL (tokens, other users, a new address, account deletion); `api/cal.js` run under Node
with fetch replaced. `tests/test_my_babdoduk.py`: the card on iPhone and elsewhere, the new address, and the
card hidden while the function is missing.
