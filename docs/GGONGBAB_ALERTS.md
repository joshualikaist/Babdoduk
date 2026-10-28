# Operator alerts: local and cloud push

Collector failures must reach the operator even when the Windows PC that runs the workers is off.
There are two senders. They share one message format and one provider (Telegram preferred;
authenticated ntfy as the alternative). On the operations PC itself a Windows toast also shows
each alert (owner decision 2026-10-12): no account, token or network, see "Windows toast" below.

| Sender | Where it runs | Reacts within | Sees |
|---|---|---|---|
| Local watchdog (`resident_ops.emit_alerts` → `notify.push_local`) | this PC, every 15 s | seconds to 10 min | Portal, Radar, dispatch, flash candidates (`.local` files) |
| Cloud watch (`scripts/watch_ggongbab_collectors.py`, last step of `ggongbab-refresh`) | GitHub, on the refresh schedule | the next scheduled run (GitHub runs it a few times a day) | heartbeat rows in Supabase, the refresh run's own result |

The cloud watch is the "eventually" alarm. If the PC is off, crashed or asleep, the collectors'
heartbeats stop and the next cloud run reports them as stale. It also reports a failed refresh.

## Message

A message has only the fixed alert fields:
* component;
* severity;
* reason code;
* last-success age;
* time;
* recommended action.

Example:

```
[Babdoduk ops] cloud monitor · 09-29 07:12 KST
CRITICAL · Portal LIST · SCAN_STALE · last success 3 h 5 min ago
  → run start_ggongbab_workers.cmd after checking the status
```

A mail subject, preview, identifier, URL or token can never be part of it. Reasons outside the
fixed list become `NO_SUCCESS_RECORDED`.

## When it pushes

**Local:**
* Critical: after it has lasted 5 minutes (since 2026-10-29, the same wait as the toast, so a scan
  that is only late right after a wake, a login or a restart never reaches the phone), then a
  reminder every 6 hours while it lasts.
* Warning: only after it has lasted 10 minutes, so a scan that is briefly late (for example after
  sleep) stays quiet.
* Recovery: pushed only for something that was pushed.
* A failed push waits 5 minutes before retrying.
* State: `.local/alert-push-state.json`.
* Wording (since 2026-10-29, `notify.LocalTelegramNotifier`): the toast's fixed Korean title and
  lines (`notify.format_toast`, with the Linux actions on Linux) plus the time. For a login it says
  to connect to this PC by remote desktop and log in in the Ops Chrome; the watchdog opens that
  Chrome if it is missing. The cloud monitor keeps the English fixed-field message above.

**Windows toast (this PC):** the watchdog passes `notify.local_toast` to the same push, with its own
state file (`.local/alert-toast-state.json`). PowerShell shows it through the Windows toast API under
PowerShell's app id, hidden and without taking focus. The wording is fixed Korean text per
component, reason and action (`notify.format_toast`): never a subject, title, id or URL. A
critical alert must last 5 minutes before it shows, so a scan that is only late right after the
PC wakes, a login or a restart stays quiet; warnings wait 10 minutes as above. It is on by default
on Windows and Linux; `{"enabled": false}` in `.local/alert-toast.json` turns it off.

**Linux desktop notification (`notify.NotifySendNotifier`):** the same text and policy, sent through
the freedesktop `Notify` call (`gdbus`; plain `notify-send` is the fallback). It uses ONE slot: the id
of the last toast is kept in `.local/alert-toast-id.json` and every new toast replaces it, so the
recovery message ("다시 정상입니다", transient, it leaves nothing in the list) takes the place of an
old "조치가 필요합니다" instead of standing beside it. Only a critical alert that a person must act on
(login, contract, browser, configuration) is sticky; anything else expires after 20 seconds. Each
toast ends with the time it was evaluated ("(14:08 기준)").

**What counts as "no success" (corrected 2026-10-18 after three false alarms):**
* The age of the last success is judged from the later of that success and the current start of
  the running worker. A worker that was just started or resumed (for example after a login) has had
  no time yet to prove itself, and its previous success may be hours old. The age shown to the
  operator is still the true age of the last success.
* A Portal worker that is running and whose latest code is a network error (a transport error, a
  timeout, a failed heartbeat write) retries by itself and nothing can be done about it: it stays a
  warning, `NETWORK_UNSTABLE` ("네트워크 불안정"), until 30 minutes without a success, then
  becomes the critical `SCAN_STALE`. A real login expiry (`AUTH_EXPIRED`) is never softened.

**Cloud:** there is no state between runs, so a problem is repeated on every scheduled run until it
is fixed. When the PC is deliberately off for days, set the repository variable
`GGONGBAB_WATCH_PAUSED_UNTIL=YYYY-MM-DD`.

The watch always exits 0, so a monitoring problem never fails the refresh job. GitHub's own
failed-run e-mail still covers a job that fails before the watch step.

## Credentials

| Where | Token | Chat id / topic |
|---|---|---|
| This PC (Windows) | Windows Credential Manager, target `babdoduk/alert-telegram` (ntfy: `babdoduk/alert-ntfy`) | `.local/alert-push.json` (not a secret) |
| This PC (Linux) | `~/.config/babdoduk/credentials/babdoduk_alert-telegram`, outside every checkout: directory 0700, file 0600; a file others can read is refused (`ops_credentials.py`) | `.local/alert-push.json` (not a secret) |
| GitHub | environment secret `TELEGRAM_BOT_TOKEN` in `ggongbab-production` (main only) | environment secret `TELEGRAM_CHAT_ID` |

A token is never stored in the repository, `.env`, logs, Supabase, browser storage or state JSON.

## Activation (owner approval required; nothing below has been run)

Status for the campus-news task: **PARTIALLY CONFIGURED**, not ACTIVE. Code and
synthetic tests do not establish a stored credential, a successful real message,
or owner phone delivery. Do not create a bot or send a test during this lab task.
The current operations checkout may predate this CLI: install the reviewed alert
code there at the owner checkpoint before using the commands below.

1. In Telegram, open @BotFather, then `/newbot`. Name it, for example, "Babdoduk Ops"; the bot
   username must end in `bot`. Keep the token private.
2. Open the new bot, press **Start**, and send it any message.
3. On this PC, from the operations checkout:

   ```
   python scripts\alert_push.py --store-telegram-token
   python scripts\alert_push.py --find-telegram-chat
   python scripts\alert_push.py --use-telegram --chat-id <id>
   python scripts\alert_push.py --test
   ```

   On the Linux operations PC the same commands are `scripts/linux/ops.sh alert --store-telegram-token`,
   `alert --find-telegram-chat`, `alert --use-telegram --chat-id <id>` and `alert --test`
   (`alert --status` shows what is configured, never the token). The running watchdog reads the
   configuration on each evaluation, so no restart is needed.

   * `--store-telegram-token` prompts without echo.
   * `--find-telegram-chat` prints your chat id.
   * `--test` sends exactly the safe connection message below. It does not assert
     that Portal/Radar are healthy and contains no source content.
4. On GitHub, add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` as secrets of the
   `ggongbab-production` environment. Then dispatch `ggongbab-refresh` once in `check` mode and
   confirm the log line `cloud watch: all watched collectors healthy` or `PUSH_SENT`.

The owner checkpoint sequence is: open @BotFather and `/newbot`; create the
Babdoduk operations bot; send `/start` to that bot; store its token via the
non-echoing prompt; obtain the chat ID only in the owner's local terminal (do
not paste it in chat/logs); configure local delivery; add cloud copies **only**
as `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` environment secrets in
`ggongbab-production`; send one connection test and confirm phone receipt.

```
✅ Babdoduk monitoring connected

component: operations
status: healthy
```

Then test a local warning and its recovery with synthetic `Alert` rows and a
separate `.local/telegram-acceptance/` PushPolicy state, using the configured
notifier. Preserve the live collectors, heartbeat and alert state. The existing
`test_a_brief_warning_never_reaches_the_phone_but_a_lasting_one_does` and recovery
tests show the warning/debounce/healthy sequence; real phone receipt must be
recorded independently. Finally temporarily rename only `.local/alert-push.json`
to `.local/alert-push.disabled.json` to disable local sending, run the approved
main `ggongbab-refresh` check at the checkpoint, and verify cloud phone delivery
for an actual stale heartbeat (or a separately approved synthetic cloud test).
Restore the local configuration afterward. Do not falsify or delete production
heartbeats to manufacture an alert. Each delivery remains unverified until the
owner confirms receipt; no mailbox/Portal title, private URL or ID is permitted.

**Rollback:**
1. Run `python scripts\alert_push.py --remove`.
2. Delete the two environment secrets.
3. Revoke the bot in @BotFather (`/revoke` or `/deletebot`).

**ntfy instead:**
* Use an access token and a reserved topic.
* Locally, store the token under `babdoduk/alert-ntfy` and write
  `{"provider": "ntfy", "server": ..., "topic": ...}` to `.local/alert-push.json`.
* In the cloud, use the secrets `NTFY_TOKEN`, `NTFY_TOPIC` and optionally `NTFY_SERVER`.

## Tests

* `tests/ggongbab/test_notify.py`:
  * the fixed fields;
  * token-free results;
  * failure codes;
  * debounce, reminder, recovery and backoff;
  * the cloud watch with the PC off;
  * a failed refresh, pause and no configuration.
* `tests/ggongbab/test_refresh_workflow.py`: the watch step's position, and that secrets are passed
  only as env.
