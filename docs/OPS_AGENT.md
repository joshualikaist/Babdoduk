# Ops agent: the owner's Telegram messages, answered on the operations PC

Lab-only, on the operations PC. Owner, 2026-10-31: "너가 받아서 확인한 다음에 진짜 모르겠는거만 지금처럼
나한테 물어보면 되지", using the Instagram radar's classifier model ("우리 기존에 쓰던 분류기 모델도 그거로
하면 되는거 아니야?"). Code: `scripts/ggongbab/ops_agent.py`; tests: `tests/ggongbab/test_ops_agent.py`.

## What happens to a message

1. The owner writes or sends a photo to the ops bot. The Instagram radar keeps it in
   `.local/telegram-inbox.jsonl` (`telegram_review.keep_note`, `docs/INSTAGRAM_RADAR.md`) and answers
   "📝 받았습니다. 상태를 확인하고 몇 분 안에 답할게요." while the agent is on.
2. The systemd path unit `babdoduk-ops-agent.path` sees the inbox change and starts the one-shot
   `babdoduk-ops-agent.service` (`ggongbab_workers.py ops-agent`). There is no resident process.
3. The run builds a summary of the operations state, the same one each time:
   - the three services (`systemctl --user is-active`) and whether each is switched on (its control file);
   - the ops checkout's commit and whether the unread latch is set;
   - the state files under `.local/` (listed in `STATE_FILES`; never `easy-login.json`, which holds the
     Portal ID, or `alert-push.json`), with epoch seconds written as local time;
   - the last 60 lines of each worker log. These logs hold reason codes only, as `SafeLog` writes them.

   Token-like strings are masked (`telegram_review.SECRETISH`).
4. It asks the radar's primary model (`OPENAI_MODEL_PRIMARY`, `gpt-6-luna`; never swapped here). The
   request carries the system prompt, the message, at most three photos from the inbox folder, the last
   three exchanges and the summary. The prompt includes every alert action of `alerts.ACTIONS` with the
   instruction the owner gets (`notify.LINUX_TOAST_ACTION`). The model returns structured output: a
   Korean `reply`, at most three `actions` and `for_next_session`. It has no tools: it reads only what it
   is sent and changes nothing.
5. The program sends the reply ("🤖 자동 점검"), carries out the actions it allows (below) and appends
   the exchange to `.local/ops-agent/history.jsonl` (the latest 200).

The run handles the owner's button taps first, then new messages, and repeats while more arrive. A
second run waits on `.local/ops-agent/run.lock`.

## What it may do

| Action | Done by the program | Limit |
| --- | --- | --- |
| `restart` (portal-worker, dooray-radar, ig-radar) | `systemctl --user reset-failed` and `restart --no-block` | Only a worker whose control file is switched on (the owner's stop is respected); once an hour per worker |
| `recheck` (1-3 days) | `ops.sh radar-stop`, `ggongbab_workers.py radar-recheck --days N`, `ops.sh radar-start` | Once every six hours. A radar the owner left off is only rechecked, never started. A radar still finishing its scan is left running and the recheck is put off |
| `allow_unread` | Nothing at first: a Telegram question with ✅ 풀기 / ❌ 그대로 두기 | Only ✅ runs `radar-allow-unread`, then rereads the days the latch skipped (1-3). A question expires after a day |
| `login` | After the reply: `ggongbab_workers.py easy-login --requested`, which reopens the KAIST login page and sends a new approval code (`docs/PORTAL_EASY_LOGIN_ASSIST.md`) | Only when the owner's message mentions a login (로그인 or login) and Easy Login is enabled; the request's own limits apply. A message that is only "로그인" never reaches the agent: the bot starts the request itself |

Everything else is refused, because the model's answer can only name these four. That includes approving
a login, a code or site fix, a deployment, a database change and a Meta setting. The reply says what the owner can
do. Developer work goes in `for_next_session`; the next Claude session reads it with
`ops.sh agent-status` or `.local/ops-agent/history.jsonl`.

The ✅/❌ taps reach the agent through the radar, because one bot has one `getUpdates` reader. The radar
writes them to `.local/ops-agent/answers.jsonl` (`record_answer`), which the path unit also watches.

## Limits and failures

- At most 30 model calls in any 24 hours. After that, messages are only kept, and the owner is told once
  that day.
- If the model call fails, the owner gets one "자동 점검이 실패했습니다" message. The message is not retried
  and stays in the inbox for the next Claude session.
- Log codes go to `.local/ops-agent.log`: `OPS_AGENT_ANSWERED`, `OPS_AGENT_FAILED`, `OPS_AGENT_LIMIT`,
  `OPS_AGENT_RESTART`, `OPS_AGENT_RECHECK`, `OPS_AGENT_UNREAD_ALLOWED` and `OPS_AGENT_TELEGRAM_FAILED`.
- Data leaves the PC only to OpenAI, through the same API key the Instagram radar's judge uses: each
  message, its photo and the masked summary. Telegram receives the replies, which are masked as well.
- A message that arrives in the instant between a run's last check and its exit waits for the next
  message or tap.

## Commands (`scripts/linux/ops.sh`)

| Command | Effect |
| --- | --- |
| `agent-install` | Writes both units, switches the agent on (messages already kept are not answered) and enables the path unit |
| `agent-off` / `agent-on` | Pauses or resumes answering. While it is off, messages are only kept, as before |
| `agent-status` | Shows the trigger, the calls in the last 24 hours, waiting questions and the latest exchanges with what was left for Claude |
| `agent-remove` | Switches the agent off and removes both units; the history is kept |
