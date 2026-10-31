# Easy Login assist (owner decision 2026-10-29)

**Lab-only / not promoted to production in the current main baseline.** Status: **implemented
(`scripts/ggongbab/easy_login.py`, synthetic tests `tests/ggongbab/test_easy_login.py`) and enabled
on the operations PC. A manual run passed live on 2026-10-29 (the owner approved, the Portal logged
in). On 2026-10-31 at 17:51 the watchdog's own attempt sent a code that went unanswered, and the tab
stayed on an SSO page the automatic attempt does not start from; the owner's request (below) was
added for that case and has not run live yet.**

## Why

When the KAIST SSO session ends, the Portal worker and the Dooray Radar wait for a person. Until
now that meant connecting to the operations PC by remote desktop just to press two buttons. KAIST
SSO **Easy Login** needs no password: the page remembers the ID, and the approval is a biometric
push on the owner's phone that asks for the two-digit number shown on the login page. The owner
decided (2026-10-29) that the operations PC may start that login and send the number to the
owner's Telegram, so that a login is one tap on the phone. The approval itself stays human.

## The flow it may run

Only in the Babdoduk Ops Chrome (loopback CDP 9224), only while a login latch is set (the Portal
LIST or the Dooray Radar reports that it needs a login), and only these steps:

1. On `portal.kaist.ac.kr/common/login/login.do`, click **로그인 (Login)**.
2. On `sso.kaist.ac.kr/auth/kaist/user/login/view`, with the **Easy Login** tab selected and the ID
   field **already filled by Remember ID**, click **Login**.
3. On `sso.kaist.ac.kr/auth/twofactor/mfa/login2Factor`, read the two-digit **Verification Code**
   and the remaining time.
4. Send one Telegram message to the configured owner chat: the code, the time limit and what to do
   ("휴대폰 KAIST 인증 앱 알림에서 67을 선택하세요"). Nothing else from the page.
5. Wait for the SSO page to close, then let the existing resume path (`ops_policy.may_resume`) take
   over. Dooray follows the same steps on its own SSO page.

## What it must never do

* Type into any field, store or read a password, choose **ID/PW Login**, or use the browser's
  password manager. An empty ID field stops the assist.
* Open any address except the Portal's login page (`PORTAL_LOGIN_URL`,
  `https://portal.kaist.ac.kr/common/login/login.do`). It opens that page only on the owner's request
  (below).
* Approve, extend or answer the MFA push, read an OTP, or replay a cookie, token or session.
* Log, store, screenshot or put the code anywhere but the one Telegram message. The log keeps only
  fixed reason codes (for example `EASY_LOGIN_CODE_SENT`, `EASY_LOGIN_STOPPED_UNEXPECTED_PAGE`).
* Continue past an unexpected page, a CAPTCHA, an error message, a changed button or a URL outside
  `portal.kaist.ac.kr` and `sso.kaist.ac.kr`: it stops and leaves the login to a person.
* Run without a configured Telegram push (then nobody would see the code).

## Limits

* At most one attempt per 30 minutes and four per day; a code that expires unanswered counts.
* After two unanswered attempts in a row it stops until a person logs in by hand, so the phone never
  turns into a stream of approval requests that someone answers by habit.
* An approval request that arrives **without** a matching Telegram message is not ours: reject it.
* The owner's own requests (below) skip these limits: the owner is there and asked. They have their own
  limits instead: at most one a minute (a double tap counts once) and ten a day. A request also restarts
  the 30 minutes before the next automatic attempt. It does not lift the pause after two unanswered
  codes; only a successful login does that.

## How it runs

* The watchdog (`resident_ops.Watchdog.start_easy_login`) looks at a login wait at most every 5
  minutes: the Portal worker at a login latch (after its one quick retry has had 150 s), or the
  Radar reporting `DOORAY_AUTH_REQUIRED`. If the limits allow, it launches one attempt as its own
  process (`ggongbab_workers.py easy-login`, lock `.local/easy-login.lock`), so it never waits on a
  page itself.
* A Portal tab on the Portal's own login page (`/common/login/login.do`) is itself a login wait
  when the worker is not running and has not scanned for 3 minutes: the watchdog latches
  `PORTAL_LIST_AUTH_REQUIRED` instead of restarting the worker, and skips the quick retry. After the
  Portal's dawn outage on 2026-10-29 the LIST answered a logged-out session with a 5xx, which the
  worker can only report as a transport failure, so no login latch and no attempt came.
* The attempt reads the page list, starts from an open SSO login page or the portal login page
  (never from an open verification page, which is a login already in progress), and attaches to
  that one tab. A page probe returns fixed facts only; the owner's ID is compared inside the page.
  Each click must reach the next page within 20 s; an unanswered page (for example an `alert()`
  dialog) stops it.
* After the code is sent, the attempt ends. The owner approves on the phone; the SSO page closes
  and the watchdog's existing resume path (`may_resume`) restarts the worker.
* State `.local/easy-login-state.json`: attempt times, the time of the last code, the unanswered
  count. Log `.local/ops-easy-login.log`: fixed codes only (`EASY_LOGIN_*`).
* A verification page that expired without an answer stays in the tab, and on 2026-10-31 the tab
  then showed `sso.kaist.ac.kr/auth/user/login/view`. The automatic attempt starts from neither page,
  so it logs `EASY_LOGIN_NO_LOGIN_PAGE` until a person acts. That person is the owner's request
  (below), from the 🔑 button that every code message and every login alert carries.

## On the owner's request (owner decision 2026-10-31)

The owner cannot always approve at once. The owner asked: "내가 로그인 다시 할게. 아니면 로그인이라고 말하거나,
로그인 버튼이 있으면 누를게. 그러면 다시 너가 승인 요청하도록까지 창 만들어줘". So when the owner is ready:

1. They tap **🔑 로그인 요청** under a login alert (`notify.LocalTelegramNotifier`, while Easy Login is
   enabled), or **🔁 새 승인 번호 받기** under a code message. Or they send a message that is only the request:
   "로그인", "다시 로그인", "로그인 해줘", "로그인 다시 할게" or "/login" (`easy_login.is_request`). A question
   such as "로그인 됐어?" is not a request: it goes to the ops agent (`docs/OPS_AGENT.md`), which may start a
   request only when the owner's message asks for a login.
2. The Instagram radar, which reads the bot, starts `ggongbab_workers.py easy-login --requested` at once in
   its own process (`launch_request`) and says so. The owner tells it apart from the code message.
3. The attempt picks the page to start from (`request_target`), from the host and path of each tab:
   * an open SSO page while the Portal has no tab of its own (the Dooray tab is open), whether an
     expired verification page, `/auth/user/login/view` or an older login page. It goes back to the
     Portal's login page (`Page.navigate`, that one URL) and starts afresh;
   * the Portal's login page as it is, or another Portal page while the watchdog holds a login latch
     (sent to the login page first);
   * Dooray's own SSO login page (the Portal tab is open, the Dooray tab is not), as it is;
   * no Portal tab at all while the Portal waits for a login: a background tab is opened at the login page.

   Any other set of tabs is `EASY_LOGIN_STOPPED_TABS_UNCLEAR` and nothing is touched. With no SSO page,
   no Portal login page and no login wait, it is `EASY_LOGIN_NOT_NEEDED`.
4. From there it runs the same steps as above (two clicks, the code to Telegram, every stop rule). A code
   that is still waiting is replaced by the new one.
5. A request that ends without a code tells the owner why in fixed words (`easy_login.OUTCOME`), with
   🔑 다시 요청 when pressing again could help. An automatic attempt still reports nothing.

The watchdog does not count the Portal's login page appearing after an SSO page as a finished login
(`Watchdog.may_resume`), so the request's first step never resumes the worker early.

## Enable or disable (owner, on the operations PC)

```
# on (the ID is the one Remember ID shows; it is compared, never typed):
printf '{"enabled": true, "expected_id": "<KAIST ID>"}\n' > ~/Babdoduk-ops/.local/easy-login.json
# one attempt by hand, for example the live acceptance run (it sends a real approval request):
~/Babdoduk-ops/scripts/linux/ops.sh run easy-login
# the owner's request, as the 🔑 button runs it (reopens the login page; reports its outcome):
~/Babdoduk-ops/scripts/linux/ops.sh login
# off:
rm ~/Babdoduk-ops/.local/easy-login.json
```

Telegram must be configured first (`ops.sh alert --status`).

## Tests required before it is enabled

Synthetic page fixtures only (no live SSO in tests): the three pages in order; an empty ID field;
the ID/PW tab selected; an unknown page; a CAPTCHA or error text; an expired code; the rate limits;
no Telegram configured; the code absent from every log line and state file. All of these are in
`tests/ggongbab/test_easy_login.py`. Still open: one live acceptance run with the owner present
(the verification page's markup was never seen by the code; the digit reading is the part most
likely to need a fix).
