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
- **Signed in on other devices**, a listing's 캘린더에 추가 gives the listing's file (or Google Calendar's add page); guests get no calendar (below). This browser remembers
  what it sent (`babdoduk-calendar-sent`: listing id → start, 300 at most): the star does not send a listing again,
  a button asks for a second tap ("이미 캘린더에 넣은 꽁밥이에요 · 한 번 더 누르면 또 넣어요"), and a listing whose
  time moved is sent again with "캘린더의 예전 일정은 지워 주세요" (a file can never change an entry already there).

Existing duplicates stay until the visitor deletes them; after 016, one 다시 연결 empties the older subscriptions,
which can then be removed in the Calendar app.

## A profile instead of a subscription link (owner 2026-11-19)

016 left one problem: "하나만 되도록 하는건 잘 된거 같아. 그래도 문제는 구독은 쌓여" — every 다시 연결 left an empty
calendar on the phone, and a website cannot delete a phone's subscription. So on iPhone and iPad the button now
installs a **configuration profile** (`/cal/<token>.mobileconfig`, routed by `vercel.json` to `api/cal.js?profile=1`)
holding Apple's calendar subscription payload (`com.apple.subscribedcalendar.account`, iPhone and iPad only) for
the account's address. Its top-level `PayloadIdentifier` is always `com.babdodukms.calendar`, and Apple's
reference says this identifier "is used to determine whether a new profile should replace an existing one or
should be added" (Configuration Profile Reference; Apple Platform Deployment, "Intro to device management
payloads": a matching identifier is an "update"). So:

- installing again **replaces** the installed profile: the phone always holds exactly one 밥도둑 calendar, named
  **밥도둑 꽁밥** (`SubCalAccountDescription`), never a second one;
- removing the profile (설정 → 일반 → VPN 및 기기 관리 → 밥도둑 캘린더 → 프로필 제거) removes the calendar;
- the profile only wraps the address: serving it reads nothing and counts as no calendar read. It carries a fresh
  address (016), so its first read retires the old one.

The visitor taps the button and 허용, then 설치 under 프로필이 다운로드됨 at the top of Settings (three steps on the
card). Only Safari hands a downloaded profile to Settings, but students use Chrome (owner 2026-11-19: "웬만한거 다
크롬으로 기본 설정 다 바꿔줘 학생들 사파리 안써"). The profile's address needs no sign-in, so in Chrome and in-app
browsers the button is `x-safari-https://<host>/cal/<token>.mobileconfig`: Safari opens for that one address and
the visitor comes back to Chrome, where the card turns into 연결됨. This handoff is undocumented but used by iPhone
apps (reported to work on iOS 15 and 17 on, not 16). If the page is still in front 2.5 s after the tap, Safari did
not open, and the card offers the file itself (파일로 받기): tapped once in the Files app, it reaches Settings the
same way. The profile is not signed, so Settings shows it as unverified.

**Old webcal subscriptions** (the ones made before this, named 밥도둑 내 꽁밥) are reported, since they cannot be
removed from here: `supabase/migrations/017_calendar_leftover.sql` (REVIEW AND APPLY MANUALLY, after 016) keeps the
address a new connection replaces (`calendar_feed_retired`, closed to browsers, gone with the account). A read of
a kept address answers one marker row (`babdoduk:retired`), which `api/cal.js` turns into a single all-day notice
in that calendar, "밥도둑 지난 구독 · 지워 주세요", with no alert (an older `api/cal.js` skips the row and answers an
empty calendar, as before). `my_calendar_link()` also returns `leftover_at`, the last read of an old address. The
card named such a calendar for a few hours (밥도둑 내 꽁밥, with a 지웠어요 button) until the owner removed it the same
day (2026-11-19, "이거 아무도 안했을거야 삭제해줘": hardly anyone subscribed the old way). The page now ignores
`leftover_at`; the notice inside the old calendar stays.

**How fast a star arrives.** A subscription is pulled: the iPhone decides when to read the address, usually about
hourly, and no website can make it read now; the card shows only "최종 동기화 시간 : …", the time of the last read. Pulling the Calendars list
down in the Calendar app reads it at once. The owner asked for a 동기화 button; since a website cannot make the
iPhone refresh, the nearest thing is **캘린더 열기** (`calshow://`, the Calendar app's own address, undocumented but
widely used) on the connected card and in a signed-in iPhone's 저장한 꽁밥, with the line "캘린더 누르고, 아래로
스크롤 해서 새로고침" (the owner's own wording, 2026-11-19, which also made the card's lines "별 누르면 캘린더에 저장!"
and "최종 동기화 시간 : …" and dropped the "새 별은 아이폰이 확인할 때 들어가요" line). The owner tried it on an iPhone from
Chrome on 2026-11-19 ("와 미친 이거 된다"): 캘린더 열기 opened the app and the swipe brought the new star in. Google Calendar is not an option (owner: "구글 캘린더 아무도 안써").

Not verifiable here: the install on a real iPhone (the handoff from Chrome, Safari's prompt, Settings' 설치, the
Files fallback) and the replacement on a second install; they need one check on a phone.

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
Chrome a file download also cut off the account save).

**Signed in only (owner 2026-11-24):** "로그인을 하지 않으면 그런 기능을 아예 주지 말고, 로그인 시에만 그 기능이
첨부되도록". A guest gets no 캘린더에 추가 button (on 오늘의 꽁밥 or the home calendar), no calendar question after a
star, and no calendar line in 저장한 꽁밥; sharing and saving are unchanged. Signed in, an iPhone or iPad points to the
connection above and other devices get Google Calendar's add page and the listing's file. This replaces the guest
paths of 2026-11-11 to 2026-11-23 (the star's calendar question and its `babdoduk-star-calendar` answer, and iPhone
Chrome's handoff of the listing's file or page to Safari, which on a real iPhone opened Safari with no add screen,
owner 2026-11-23 "사파리만 열림"). The single-listing file `/cal/e/<id>.ics` that handoff used is gone with it; an old
`?cal=1` address just opens the listing.

**A withdrawn listing leaves the stars (owner 2026-11-24):** "빠진거는 알아서 별표에서도 빠져야지". A saved listing
that is in neither the published list nor the archive and is not over loses its star by itself when 오늘의 꽁밥 or
마이 밥도둑 next opens (the "목록에서 빠짐" row is gone), so it also leaves this calendar; `api/cal.js` leaves such a
star out at once, without waiting for that. Only when both lists were really read: a failed read never removes
anything (the row then says 확인 중, and the calendar keeps the saved copy). Push alerts already read only the
newest published list.

## How it works

| Part | Where |
|---|---|
| Private address | `/cal/<token>.ics`, a 43-character random token per account (`my_calendar_feed()`, signed-in only). `my_calendar_feed(true)` replaces it and the old address stops; the card no longer offers this (owner 2026-11-12), so a leaked address is replaced on request. |
| Calendar file | `api/cal.js` (Vercel function, routed by `vercel.json`). It reads the token's list with the anon function `calendar_feed_events(token)` and the site's publishable key, then writes each entry with the site's own calendar code (`js/ggongbab-live.js` `icsText`, 30-minute alarm). Times and places come from the current published feed (`data/ggongbab/latest.json`, then the archive), else from the snapshot saved with the star. A deadline-only giveaway has no time and is left out, and so is a star whose listing was withdrawn before it was over (both lists read, above). |
| Fixed origins | The feed is read from, and the entries link to, one of our own sites only: `www.babdodukms.com`, `babdodukms.com`, `babdoduk.vercel.app` or `babdoduk-lab.vercel.app`, whichever the request came to. Any other host (a preview address, or a forged `x-forwarded-host`) gets `https://www.babdodukms.com`, so a request can never make the function fetch from an address it names (security audit 2026-11-13). An empty list (or an unknown token) fetches no feed at all. |
| Privacy | The table `calendar_feeds` is closed to browsers. The file holds what the person saved (titles, times, places), never a name, email or account id. Anyone with the address can read that list; the address is long and random and appears only in the iPhone's calendar settings. Responses are `private, no-store` and `noindex`. |

## Limits

- The phone decides how often it fetches a subscribed calendar; the file only hints every 15 minutes
  (`REFRESH-INTERVAL`, `X-PUBLISHED-TTL`). A star made just before an event can arrive after its alert.
- Not offered on Android or computers (see above).
- Guests (not signed in) get no calendar at all: their stars live only in their browser.
- iPhone can be set to drop alerts from subscribed calendars; this needs checking on a real phone.

## Tests

`tests/test_calendar_feed.py`: the profile (a real property list, one fixed identifier, our own sites only), the
old-address notice, and the migrations (013, 016 and 017) read statically and, with `pgserver` and `psycopg`,
applied to a throwaway PostgreSQL (tokens, other users, a new address, the newest connection winning, account
deletion, an old address marked and reported); `api/cal.js` run under Node
with fetch replaced (including forged hosts and an empty list), and its entries with a fixed clock (a withdrawn star
left out once both lists are read, kept when either fails). `tests/test_star_calendar.py`: a guest gets no calendar
button, question or handoff on 오늘의 꽁밥 and the home calendar (iPhone Safari and Chrome, Android, KakaoTalk, PC, even
with an old answer stored), and signed in the home calendar offers it. `tests/test_my_babdoduk.py`: the card on iPhone only, its short text, its states (not connected, 확인 중,
연결됨, stale, before 016) and the card hidden while the function is missing. `tests/test_star_calendar.py`: signed in
on a phone, a listing is sent once, a button asks for a second tap, a moved listing is sent again with the note.
`tests/test_push_alerts.py`: signed in on an iPhone, a listing's calendar choice points to the connection.
