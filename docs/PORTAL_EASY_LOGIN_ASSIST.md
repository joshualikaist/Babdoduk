# Easy Login assist (owner decision 2026-10-29)

**Lab-only / not promoted to production in the current main baseline.** Status: **rule approved,
not implemented.** Until the implementation lands with its tests, a login is still started by hand.

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

## Tests required before it is enabled

Synthetic page fixtures only (no live SSO in tests): the three pages in order; an empty ID field;
the ID/PW tab selected; an unknown page; a CAPTCHA or error text; an expired code; the rate limits;
no Telegram configured; the code absent from every log line and state file. Then one live acceptance
run with the owner present.
