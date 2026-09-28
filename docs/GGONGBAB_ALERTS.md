# Operator alerts: local and cloud push

Collector failures must reach the operator even when the Windows PC that runs the workers is off.
There are two senders. They share one message format and one provider (Telegram preferred;
authenticated ntfy as the alternative).

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
* Critical: at once, then a reminder every 6 hours while it lasts.
* Warning: only after it has lasted 10 minutes, so a scan that is briefly late (for example after
  sleep) stays quiet.
* Recovery: pushed only for something that was pushed.
* A failed push waits 5 minutes before retrying.
* State: `.local/alert-push-state.json`.

**Cloud:** there is no state between runs, so a problem is repeated on every scheduled run until it
is fixed. When the PC is deliberately off for days, set the repository variable
`GGONGBAB_WATCH_PAUSED_UNTIL=YYYY-MM-DD`.

The watch always exits 0, so a monitoring problem never fails the refresh job. GitHub's own
failed-run e-mail still covers a job that fails before the watch step.

## Credentials

| Where | Token | Chat id / topic |
|---|---|---|
| This PC | Windows Credential Manager, target `babdoduk/alert-telegram` (ntfy: `babdoduk/alert-ntfy`) | `.local/alert-push.json` (not a secret) |
| GitHub | environment secret `TELEGRAM_BOT_TOKEN` in `ggongbab-production` (main only) | environment secret `TELEGRAM_CHAT_ID` |

A token is never stored in the repository, `.env`, logs, Supabase, browser storage or state JSON.

## Activation (owner approval required; nothing below has been run)

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

   * `--store-telegram-token` prompts without echo.
   * `--find-telegram-chat` prints your chat id.
   * `--test` sends one test message.
4. On GitHub, add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` as secrets of the
   `ggongbab-production` environment. Then dispatch `ggongbab-refresh` once in `check` mode and
   confirm the log line `cloud watch: all watched collectors healthy` or `PUSH_SENT`.

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
