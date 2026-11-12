# 별 누른 꽁밥 30분 전 알림 (lab)

Owner 2026-11-12: a starred 꽁밥 should alert the phone 30 minutes before, without a file to download, for
people who add the site to their home screen ("오케이 너무 좋다 그러면"). The calendar subscription
(`docs/CALENDAR_FEED.md`) was step 1; this web push alert is step 2.

**Status:** lab only (`HOSTS` in `js/ggongbab-push.js`). Three things must be in place, in this order:

1. The owner applies `supabase/migrations/014_push_alerts.sql` in the Supabase SQL editor.
2. The owner runs `bash ~/Babdoduk-ops/scripts/push/setup.sh` once on the ops computer. It makes the push key
   pair (the private half goes to `~/.config/babdoduk/credentials/babdoduk_push-vapid`, mode 600, never
   printed; an existing key is kept) and starts the 2-minute timer `babdoduk-push.timer`.
3. The public half (printed by setup, also in `~/Babdoduk-ops/.local/push/vapid-public.txt`) goes into
   `VAPID_PUBLIC_KEY` in `js/ggongbab-push.js`. Until then the feature stays hidden.

Replacing the key pair silently stops every phone that already turned alerts on, so the key is kept.

## What a visitor does

- **iPhone:** add the site to the home screen (Safari share button → 홈 화면에 추가) and open it from there.
  Web push works only in that home-screen app (iOS 16.4 and later); in a Safari tab the saved list says so.
  The first star in the home-screen app asks **별 누른 꽁밥, 30분 전에 알려 드릴까요?**; yes shows the
  phone's own permission question.
- **Home page:** a star on the home calendar does the same (the question in the home-screen app, then
  the list kept current).
- **Android and computers:** the switch **별 누른 꽁밥 30분 전 알림** in 저장한 꽁밥 (`ggongbab.html`).
- **Signed in:** the card **30분 전 알림** on 마이 밥도둑 (`my.html`) turns it on or off for this device.

From then on every starred listing alerts about 30 minutes before it starts (the timer runs every 2
minutes, so 28 to 30 minutes). A tap opens the listing on the site.

## How it works

| Part | Where |
|---|---|
| Browser | `js/ggongbab-push.js` (`BabdodukPush`): asks permission inside the tap, installs `sw.js`, subscribes with the public key, and sends the push address, the starred ids, the language and the site with the anon function `push_device_save`. After any star change, and once a day at most when nothing changed, it sends the list again; turning off unsubscribes and calls `push_device_remove`. A browser the server refused is unsubscribed again, so "켜짐" is never shown without a working row. |
| Service worker | `sw.js` at the site root: shows the alert and opens the listing on our own site. No caching, no fetch handler. `vercel.json` serves it `no-cache`. |
| Database | `push_devices`: endpoint (Apple, Google, Mozilla or Windows push services only), the two browser keys, up to 300 listing ids, `ko`/`en`, one of our three sites. No account, name, email or address. Closed to browsers; the backend key reads, counts failures and deletes. At most 500 new devices a day, 50 000 in all. |
| Sender | `scripts/push/send.js` (Node, no packages; `scripts/push/webpush.js` is the RFC 8291 encryption and RFC 8292 VAPID signature). Every 2 minutes it reads the public feed (www.babdodukms.com, else lab); only when a listing starts within 30 minutes does it read the devices that starred it, then sends each one message once. The time and place always come from the newest feed, so a moved or withdrawn listing never alerts at the old time. A 404/410 forgets the device; ten refusals in a row too; a busy service is retried while it is still before the start. What went out is kept in `~/Babdoduk-ops/.local/push/sent.json` as hashes for two days. |

Check by hand on the ops computer: `node ~/Babdoduk-ops/scripts/push/send.js --dry-run` prints what would
be sent (device hashes only) and sends nothing. The log is `journalctl --user -u babdoduk-push`.

## Limits

- The home page calendar (`index.html`) asks and updates the alert list too (owner 2026-11-12, "첫 화면에서도
  바로 들어가게"); it loads the public config for this module only. It keeps the browser's guest list, so for
  someone signed in it leaves the alert list to 오늘의 꽁밥 and 마이 밥도둑, which hold the account's list.
- For someone signed in, each device keeps the list it last sent; a star made on another device counts
  once this device opens 오늘의 꽁밥 or 마이 밥도둑.
- The alert depends on the ops computer being on and online.
- iPhone delivers alerts only to the home-screen app and only if its notifications are allowed in Settings.

## Tests

`tests/test_push_alerts.py`: the migration statically and, with `pgserver` and `psycopg`, on a throwaway
PostgreSQL; the encryption against RFC 8291's worked example and decrypted the way a browser does; the VAPID
signature verified; the sender with a fake clock, network and files (due window, once only, moved listings,
gone and busy services, no database read when nothing is due, no secret printed); and the pages in Chrome
with a stand-in push service (the question, permission refused, server refused, Safari outside the
home-screen app, other hosts, the daily resend, 마이 밥도둑). A real phone receiving a real alert is checked
by hand.
