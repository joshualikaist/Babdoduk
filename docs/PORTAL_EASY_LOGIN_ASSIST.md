# Easy Login assist (owner decision 2026-10-29)

**Lab-only / not promoted to production in the current main baseline.** Status: **implemented
(`scripts/ggongbab/easy_login.py`, synthetic tests `tests/ggongbab/test_easy_login.py`); off until
the owner enables it on the operations PC, and not yet proven on a live login.**

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

## How it runs

* The watchdog (`resident_ops.Watchdog.start_easy_login`) looks at a login wait at most every 5
  minutes: the Portal worker at a login latch (after its one quick retry has had 150 s), or the
  Radar reporting `DOORAY_AUTH_REQUIRED`. If the limits allow, it launches one attempt as its own
  process (`ggongbab_workers.py easy-login`, lock `.local/easy-login.lock`), so it never waits on a
  page itself.
* The attempt reads the page list, starts from an open SSO login page or the portal login page
  (never from an open verification page, which is a login already in progress), and attaches to
  that one tab. A page probe returns fixed facts only; the owner's ID is compared inside the page.
  Each click must reach the next page within 20 s; an unanswered page (for example an `alert()`
  dialog) stops it.
* After the code is sent, the attempt ends. The owner approves on the phone; the SSO page closes
  and the watchdog's existing resume path (`may_resume`) restarts the worker.
* State `.local/easy-login-state.json`: attempt times, the time of the last code, the unanswered
  count. Log `.local/ops-easy-login.log`: fixed codes only (`EASY_LOGIN_*`).
* Known gap: a verification page that expired without an answer stays open in the tab. The assist
  never touches an open verification page, so after that a person starts the next login (the
  ordinary "로그인 만료" alert keeps reminding).

## Enable or disable (owner, on the operations PC)

```
# on (the ID is the one Remember ID shows; it is compared, never typed):
printf '{"enabled": true, "expected_id": "<KAIST ID>"}\n' > ~/Babdoduk-ops/.local/easy-login.json
# one attempt by hand, for example the live acceptance run (it sends a real approval request):
~/Babdoduk-ops/scripts/linux/ops.sh run easy-login
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
