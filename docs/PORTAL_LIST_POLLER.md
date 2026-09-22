# Portal LIST-only local poller

This mode reuses a human-authenticated Portal session. It does not automate
credentials, SSO/MFA, authentication endpoints, notice details, or view counts.
No live Portal compatibility claim is made by the synthetic tests.

## Run and recover

Install `requirements-ggongbab.txt`. Use the existing dedicated resident Chrome
on Windows, loopback port 9223 and `.local/portal-browser-profile`.

```powershell
# Human SSO/MFA only, if prompted:
python scripts/portal_web_agent.py --setup --cdp

# One bounded local LIST scan, no remote heartbeat:
python scripts/portal_web_agent.py --poll-list --cdp --once --local-only

# Long-running polling, with Supabase operational heartbeat:
python scripts/portal_web_agent.py --poll-list --cdp --interval 60
```

The first successful scan establishes a baseline from at most two LIST pages;
it does not announce historical notices. Later scans inspect at least two pages
(unless the list ends), extending up to `--max-pages` (default 20, range 2–100)
until an already observed/older anchor page or the list end. A full page of new
rows extends the scan. An incomplete/failed scan never advances the checkpoint.

30 seconds is also supported. One-page frequency alone is 1,440–2,880 requests
per day; this implementation normally overlaps two pages, plus initial session
verification and bounded catch-up requests. Monitor server limits before choosing
30 seconds. 429 Retry-After and exponential backoff take priority over cadence.
No promise is made about Portal session lifetime or uninterrupted detection.

Authentication/redirect failure exits 10; schema failure exits 20. The poller
does not automatically open/reload Chrome or retry authentication. Complete
manual setup if prompted, then explicitly restart the same poll command. The
restart acquires a fresh in-memory session without resetting the detection state.
Transport failures during polling back off; `--once` exits 1 instead. An initial
session-verification transport failure exits 1 and requires a later restart.
Ctrl+C closes the HTTP
session. Chrome is left running. A process lock prevents overlapping pollers.

## Session boundary

The provider first verifies the TCP listener's owning Chrome process, dedicated
profile argument, and loopback debugging flags. It attaches without navigation,
selects exactly one Portal browser context and obtains only cookies applicable to
the pinned LIST URL. Only an unambiguous, secure Portal JSESSIONID is copied into
the local HTTP client. Missing/unsupported scopes fail closed; extra SSO cookies,
browser storage and headers are never copied as fallback.

The exact LIST JSON/schema response is positive evidence of usable access. A
cookie's presence alone is not authentication evidence. If JSESSIONID alone is
insufficient in the current tenant, stop and review the minimum requirements;
do not add credentials, identity parameters or authentication replay.

Requests are pinned to GET `https://portal.kaist.ac.kr/wz/api/board/recents` and
the existing LIST_QUERY; only pageIndex varies, pstNo remains empty. The final
prepared request is checked again before network transmission. Redirects are
never followed, TLS verification is enabled and ambient proxies/.netrc are not
used. Response size and pagination are bounded, with 5s connect/15s read-inactivity
timeouts and an elapsed-time check between response chunks. These are not a
hard wall-clock deadline against a continuously trickling server.

The HTTP session is memory-only. It is not put into env vars, CLI arguments,
Redis, files, Supabase, logs, heartbeat or generated JSON. Normal Python memory
cannot promise secure erasure; do not enable HTTP debug logging or upload crash
dumps. The existing browser profile remains sensitive local account storage.
OS process attestation currently supports Windows only; other platforms stop.

## Detection and privacy

Only exact `publicYn == "Y"` rows are candidates. Missing/invalid fields stop
the scan. pstNo identifies a notice; regDt is interpreted explicitly in KST.
Equal timestamps, nonmonotonic IDs and page overlap do not collapse distinct
notices. Duplicate IDs with conflicting metadata during a scan cause a retry.

The title-only prefilter produces Stage A signals, not confirmed food events.
No detail body, Dooray task, AI extraction, public feed or push is produced.
publicYn is not permission to republish private Portal content on the internet.

`.local/portal-list-state.json` contains only pseudonymous identifier hashes,
metadata fingerprints, timestamps and boolean flags. Its `pending` map is a
durable metadata-only Stage A detection outbox committed atomically with the
checkpoint; it contains no titles, bodies, raw IDs, addresses or cookies. It is
separate from the existing body-based PortalQueue. A downstream consumer/public
publication flow is not enabled. Pending records remain until a future consumer
acknowledges them or an observed notice is no longer public/a candidate.

The recent overlap window is bounded, not a historical reconciliation service.
Backdated insertions outside it, old edits, and notices disappearing between
polls may be missed. Body-only edits/cancellations cannot be detected from the
LIST. Absence from a page is never interpreted as cancellation. Corrupt state
stops rather than silently treating all notices as new. The ledger retains a
rolling recent window; pending detections are not silently expired.

## Heartbeat

Use existing migration 003 and its RPC; no schema migration is required.
The agent_id is `portal-list-poller`, separate from `dooray-resident`.
last_scan_at records an attempted scan, last_success_at a validated committed
scan (including an empty result), and last_publish_at is never advanced by this
mode. Existing RPC semantics preserve prior success/publish times on errors.

Remote heartbeat is required by default; missing configuration fails before
session handoff. `--local-only` explicitly disables it. A heartbeat write failure
stops the poller with a fixed, value-free local message. No remote operations are
performed merely by importing modules or running the synthetic tests.

An external monitor should alert immediately on auth_required/ui_changed/error,
and on missing heartbeat or stale successful scans after roughly three polling
intervals plus timeout allowance. An always-on remote alert delivery service is
not installed by this change. Authentication failure stops the process and leaves
its error heartbeat for that monitor; a living process is not implied afterward.

## Verification

Synthetic tests replace HTTP, browser ownership/attachment, clock and heartbeat.
They must never use a real account, database, browser cookie or push endpoint.

```powershell
python -m pytest tests/ggongbab -q
python scripts/validate_content.py
python scripts/check_ggongbab_ui.py
```

After those tests, separately authorized live acceptance may make LIST requests
only. Do not run the legacy detail calibration as a prerequisite for this mode.
Known-schema detail guards remain in place; the new poller has no detail API.
