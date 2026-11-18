# 내 꽁밥 캘린더 구독

Owner 2026-11-12: a starred 꽁밥 should reach the phone's calendar without a file or an add screen each
time ("사람들은 ics 파일 이런거 다운 못받아"). The owner chose the subscription first ("1번부터 가도 돼
허락!"); a home-screen push alert 30 minutes before is the second step (`docs/PUSH_ALERTS.md`).

**Status:** on lab and, since 2026-11-12 (owner), production. Migration `supabase/migrations/013_calendar_feed.sql` is applied (the owner ran it in the Supabase SQL editor); without it the card stays hidden and `/cal/…` answers 503.

## One connection, never a duplicate (owner 2026-11-19)

The owner saved two events to the iPhone calendar, starred a third a week later, tapped 연결 again, and the
first two showed twice ("동일한 행사가 두개 뜨는거지. 그거는 불필요한거잖아 ... 로직을 전면 수정해"; "gmail 같은것처럼
이거 설정할 수 있게"). An iPhone keeps every subscription it is given and every calendar file makes a new entry,
so the rule is now: **each listing is in the calendar once.**

- **The card is a setting.** On 마이 밥도둑 it says 연결됨 with the time the calendar last read the list, 연결 확인 중
  after a tap (until the calendar's first read; it turns into 연결됨 by itself when the visitor comes back), or
  한동안 확인이 없었어요 after three days without a read. The big button shows only when nothing is connected.
- **The newest connection wins.** `supabase/migrations/016_calendar_connect.sql` (REVIEW AND APPLY MANUALLY, after
  013) adds `my_calendar_link()`: the address to subscribe to now (a fresh `next_token`) plus `read_at` and
  `linked_at`. The first time a calendar reads the fresh address, `calendar_feed_events()` makes it the live one
  and the old address answers an empty list, so an older subscription (a second tap, another phone) goes empty
  instead of showing every event again. 다시 연결 is therefore always safe. `api/cal.js` is unchanged.
  Two subscriptions made from the very same address before either is read stay a narrow case: the card hides the
  button after a tap so it is not tapped again.
- **Before 016 is applied** the card falls back to 013's address (`my_calendar_feed()`), cannot know the state, and
  after a tap only says that one tap is enough.
- **Signed in on an iPhone**, a listing's 캘린더에 추가 offers no file or Google page, only "별을 누르면 연결한 아이폰
  캘린더에 들어가요" with a link to the card: a copy beside the subscription is exactly the duplicate.
- **Guests and other devices** still get one-listing files or Google Calendar's add page, but this browser remembers
  what it sent (`babdoduk-calendar-sent`: listing id → start, 300 at most): the star does not send a listing again,
  a button asks for a second tap ("이미 캘린더에 넣은 꽁밥이에요 · 한 번 더 누르면 또 넣어요"), and a listing whose
  time moved is sent again with "캘린더의 예전 일정은 지워 주세요" (a file can never change an entry already there).

Existing duplicates stay until the visitor deletes them; after 016, one 다시 연결 empties the older subscriptions,
which can then be removed in the Calendar app (캘린더 → 캘린더 목록 → the empty 밥도둑 내 꽁밥 → 구독 해지).

## What a visitor does

1. Signs in (the list must be on the server for the phone to fetch it).
2. On 마이 밥도둑 (`my.html`), taps **아이폰 캘린더에 연결** (`webcal://`), then 구독, once; the card then shows the
   connection instead of the button (above). The card shows on iPhone and
   iPad only (owner 2026-11-12): a laptop needs no calendar link, and Android's Google Calendar fetches a
   subscribed address only every few hours and cannot add one in its app, so Android gets the 30-minute
   push alert instead (`docs/PUSH_ALERTS.md`). The card says nothing about the private address.
3. From then on every star shows up in that calendar by itself, with an alert 30 minutes before; taking a
   star away takes it out at the next refresh. A star whose event day is over leaves the saved lists by
   itself but stays saved, so the calendar keeps the event (owner 2026-11-12).

Signed in, the star no longer opens a calendar add screen or file (the subscription takes it; on iPhone
Chrome a file download also cut off the account save). iPhone Chrome, Firefox and Edge get Google
Calendar's add page instead of an .ics download for guests.

## How it works

| Part | Where |
|---|---|
| Private address | `/cal/<token>.ics`, a 43-character random token per account (`my_calendar_feed()`, signed-in only). `my_calendar_feed(true)` replaces it and the old address stops; the card no longer offers this (owner 2026-11-12), so a leaked address is replaced on request. |
| Calendar file | `api/cal.js` (Vercel function, routed by `vercel.json`). It reads the token's list with the anon function `calendar_feed_events(token)` and the site's publishable key, then writes each entry with the site's own calendar code (`js/ggongbab-live.js` `icsText`, 30-minute alarm). Times and places come from the current published feed (`data/ggongbab/latest.json`, then the archive), else from the snapshot saved with the star. A deadline-only giveaway has no time and is left out. |
| Fixed origins | The feed is read from, and the entries link to, one of our own sites only: `www.babdodukms.com`, `babdodukms.com`, `babdoduk.vercel.app` or `babdoduk-lab.vercel.app`, whichever the request came to. Any other host (a preview address, or a forged `x-forwarded-host`) gets `https://www.babdodukms.com`, so a request can never make the function fetch from an address it names (security audit 2026-11-13). An empty list (or an unknown token) fetches no feed at all. |
| Privacy | The table `calendar_feeds` is closed to browsers. The file holds what the person saved (titles, times, places), never a name, email or account id. Anyone with the address can read that list; the address is long and random and appears only in the iPhone's calendar settings. Responses are `private, no-store` and `noindex`. |

## Limits

- The phone decides how often it fetches a subscribed calendar; the file only hints every 15 minutes
  (`REFRESH-INTERVAL`, `X-PUBLISHED-TTL`). A star made just before an event can arrive after its alert.
- Not offered on Android or computers (see above).
- Guests (not signed in) cannot subscribe: their stars live only in their browser.
- iPhone can be set to drop alerts from subscribed calendars; this needs checking on a real phone.

## Tests

`tests/test_calendar_feed.py`: the migrations (013 and 016) read statically and, with `pgserver` and `psycopg`,
applied to a throwaway PostgreSQL (tokens, other users, a new address, the newest connection winning, account
deletion); `api/cal.js` run under Node
with fetch replaced (including forged hosts and an empty list). `tests/test_my_babdoduk.py`: the card on iPhone only, its short text, its states (not connected, 확인 중,
연결됨, stale, before 016) and the card hidden while the function is missing. `tests/test_star_calendar.py`: a
listing is sent once, a button asks for a second tap, a moved listing is sent again with the note.
`tests/test_push_alerts.py`: signed in on an iPhone, a listing's calendar choice points to the connection.
