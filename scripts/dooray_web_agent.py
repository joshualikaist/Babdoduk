# -*- coding: utf-8 -*-
"""Unattended Dooray mailbox agent: scan -> filter -> register as project task.

One manual SSO login plus one Enter to confirm the inbox, then no human input:

    python scripts/dooray_web_agent.py --setup        # opens https://kaist.gov-dooray.com/
    python scripts/dooray_web_agent.py --discover
    python scripts/dooray_web_agent.py --run --run-pipeline

The agent does no event analysis. It moves candidate mails into the collection
project; refresh_ggongbab.py does the rest (OpenAI -> Supabase -> latest.json).

Passwords are never read, stored or typed. When the SSO session expires the run
stops with AUTH_REQUIRED (10) and asks for one manual login.

Exit codes: 0 success · 10 auth required · 20 UI changed · 30 project not found
            · 40 pipeline failed
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ggongbab.config import KST, load_settings  # noqa: E402
from ggongbab.prefilter import classify  # noqa: E402
from ggongbab.web import browser as browser_mod  # noqa: E402
from ggongbab.web import exit_codes  # noqa: E402
from ggongbab.web.browser import DEFAULT_DOORAY_URL, browser_session, wait_for_login  # noqa: E402
from ggongbab.web.calibrate import calibrate  # noqa: E402
from ggongbab.web.exit_codes import (NAMES, SUCCESS, AgentError, AuthRequired,  # noqa: E402
                                     PipelineFailed, UiContractError)
from ggongbab.web.mail_reader import (NetworkObserver, list_mails, observe,  # noqa: E402
                                      open_body, write_discovery_report)
from ggongbab.web.page_select import (collect_targets, describe,  # noqa: E402
                                      mail_row_evidence, select_mail_page)
from ggongbab.web.state import AgentState  # noqa: E402
from ggongbab.web.task_writer import DEFAULT_PROJECT_NAME, MailPayload, TaskWriter  # noqa: E402
from ggongbab.web.ui_contract import load_contract  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
LOCAL_DIR = ROOT / ".local"
PROFILE_DIR = LOCAL_DIR / browser_mod.PROFILE_DIRNAME
STATE_FILE = LOCAL_DIR / "ggongbab-mail-state.json"
CONTRACT_FILE = LOCAL_DIR / "dooray-ui.json"
DISCOVERY_FILE = LOCAL_DIR / "dooray-discovery.json"


def stamp() -> str:
    return datetime.now(KST).strftime("[%H:%M]")


def log(message: str) -> None:
    print(message, flush=True)


# ---------------------------------------------------------------------------
def _report_findings(report: dict) -> None:
    evidence = report.get("evidence") or {}
    log("")
    log("evidence that this page is the mail list:")
    log(f"  A  mail-list JSON call observed : {'yes' if evidence.get('A_mailListCallObserved') else 'NO'}")
    log(f"  B  confirmed by you             : {'yes' if evidence.get('B_confirmedByUser') else 'no'}")
    log(f"  C  mail-row groups in the DOM   : {evidence.get('C_mailRowGroups', 0)}"
        f"  (repeated containers: {evidence.get('repeatedContainers', 0)})")
    recommended = report.get("recommendedListApi")
    if recommended:
        log("")
        log(f"recommended list_api: {recommended}")

    for label, key in (("mail-list candidates", "mailListCandidates"),
                       ("mail-detail candidates", "mailDetailCandidates")):
        rows = report.get(key) or []
        log("")
        log(f"{label}: {len(rows)}")
        for call in rows[:6]:
            log(f"  {call['method']:4} {call['status']}  {call['url']}")
            log(f"       why: {', '.join(call.get('why') or [])}")
    others = report.get("otherJsonCalls") or []
    if others:
        log("")
        log(f"other JSON calls: {len(others)} (see the report file)")
    read_keys = report.get("observedReadStateKeys") or []
    log("")
    log(f"read/unread keys actually present in the data: {read_keys or 'none observed'}")
    if not read_keys:
        log("  -> no read-state flag was seen, so no --preserve-unread option is offered.")


def _confirm(prompt: str) -> bool:
    """Wait for Enter. False when there is no one to ask.

    isatty() is not a reliable guard on Windows, where NUL is a character device
    and reports as a terminal, so the real check is that reading gives EOF.
    """
    try:
        input(prompt)
        return True
    except (EOFError, KeyboardInterrupt):
        return False


def cmd_setup(args) -> int:
    contract = load_contract(CONTRACT_FILE)
    start = args.url or DEFAULT_DOORAY_URL
    origin_host = urlparse(start).netloc
    log(f"Opening {start}")
    log("A browser window will open. Log in with KAIST SSO there.")
    log("Nothing is typed for you, and no password is read or stored.")
    with browser_session(PROFILE_DIR, contract, headless=False, start_url=start) as session:
        landing = wait_for_login(session, log=log)
        log("")
        log("로그인되었습니다.")
        log(f"  landing page: {landing.split('?')[0]}")
        log("")
        log("Dooray에서 [메일] -> [받은메일함] 으로 이동하세요.")
        log("받은메일함 목록이 보이면 이 터미널에서 Enter를 누르세요.")
        log("(이 Enter는 최초 설정에서 한 번뿐입니다. 이후 자동 실행에는 입력이 없습니다.)")

        # Attached to the CONTEXT, not to the launch page: Dooray may put the
        # mailbox in another tab, and a page listener would miss all of its calls.
        observer = NetworkObserver(session.context)
        observer.start()
        try:
            if not _confirm("\nEnter를 누르면 현재 받은메일함을 기록합니다... "):
                log("")
                log("[error] --setup needs an interactive terminal: it waits for you to")
                log("        reach 받은메일함 and press Enter. Run it from a normal")
                log("        Command Prompt or PowerShell window, not from a scheduled task.")
                return 1
            observer.on_mail_screen = True

            # Never trust the page we launched: look at every page and frame.
            targets = collect_targets(session.context, origin_host)
            log("")
            for line in describe(targets):
                log(line)
            target = select_mail_page(session.context, origin_host)
            if target is None:
                log("")
                log("[refused] none of the open pages looks like a mailbox.")
                log("          No page is under the /mail/ area and none shows mail-row-like")
                log("          repetition. mail_url was NOT saved.")
                log("          Re-run --setup and press Enter while 받은메일함 is on screen.")
                return exit_codes.UI_CHANGED
            if session.contract.looks_like_login(target.url):
                raise AuthRequired("the browser is back on a login screen",
                                   hint="run --setup again and finish the SSO login")

            log("")
            log(f"selected mail page:\n  {target.location}")
            log("")
            log("observing inbox...")
            observe(session, observer, seconds=6, target=target)
            log("reloading inbox...")
            observe(session, observer, seconds=8, reload=True, target=target)

            mail_url = target.frame.url or target.url
            row_evidence = mail_row_evidence(target.frame)
            report = write_discovery_report(observer, row_evidence, DISCOVERY_FILE,
                                            page_url=mail_url, confirmed_by_user=True)
        finally:
            observer.stop()

    evidence = report.get("evidence") or {}
    # B alone is never enough. Repetition alone is never enough either: a home page
    # has plenty of repeated elements. It takes a real mail-list call, or DOM rows
    # that carry dates and ids the way mail rows do.
    corroborated = bool(evidence.get("A_mailListCallObserved")) or bool(evidence.get("C_strong"))
    if not corroborated:
        log("")
        log("[refused] that page did not produce mail evidence.")
        log("          No mail-list JSON call, and its repeated containers do not look")
        log("          like mail rows (no per-row dates/ids). mail_url was NOT saved.")
        _report_findings(report)
        return exit_codes.UI_CHANGED

    contract.mail_url = mail_url      # overwrites an earlier wrong value
    contract.verified = False         # a human still confirms the endpoint shape
    contract.save(CONTRACT_FILE)
    log("")
    log(f"mail_url recorded:\n  {mail_url.split('?')[0]}")
    log(f"session stored in  {PROFILE_DIR}")
    _report_findings(report)
    log("")
    log(f"report: {DISCOVERY_FILE}")
    log("setup complete.")
    log("")
    if report.get("recommendedListApi"):
        log("Next: confirm the recommended list_api above really is the inbox, copy it")
        log(f"      into {CONTRACT_FILE} as \"list_api\", then set \"verified\": true.")
    else:
        log("Next: pick a list_api from the candidates above, put it in")
        log(f"      {CONTRACT_FILE}, then set \"verified\": true by hand.")
    return SUCCESS


def cmd_discover(args) -> int:
    contract = load_contract(CONTRACT_FILE)
    if not contract.mail_url:
        raise UiContractError("no mailbox URL recorded yet", hint="run --setup first")
    log(f"opening {contract.mail_url.split('?')[0]}")
    origin_host = urlparse(contract.mail_url).netloc
    with browser_session(PROFILE_DIR, contract, headless=False) as session:
        session.assert_authenticated()
        observer = NetworkObserver(session.context)
        observer.on_mail_screen = True
        observer.start()
        try:
            target = select_mail_page(session.context, origin_host)
            if target is None:
                for line in describe(collect_targets(session.context, origin_host)):
                    log(line)
                raise UiContractError(
                    "the recorded mail_url does not open a mailbox",
                    hint="run --setup again and press Enter while 받은메일함 is on screen")
            log(f"mail page: {target.location}")
            observe(session, observer, seconds=args.observe_seconds, target=target)
            # Reload so the inbox list request fires again while we are watching.
            observe(session, observer, seconds=max(6, args.observe_seconds // 2),
                    reload=True, target=target)
            row_evidence = mail_row_evidence(target.frame)
            report = write_discovery_report(observer, row_evidence, DISCOVERY_FILE,
                                            page_url=target.frame.url or target.url,
                                            confirmed_by_user=False)
        finally:
            observer.stop()

    evidence = report.get("evidence") or {}
    if not (evidence.get("A_mailListCallObserved") or evidence.get("C_strong")):
        _report_findings(report)
        raise UiContractError(
            "the recorded mail_url does not look like a mail list",
            hint="run --setup again and confirm while 받은메일함 is on screen")
    _report_findings(report)
    log("")
    log(f"report: {DISCOVERY_FILE}")
    log(f"Fill {CONTRACT_FILE.name} from the candidates above, then set \"verified\": true.")
    log("Until it is verified, --run exits 20 without touching anything.")
    return SUCCESS


# ---------------------------------------------------------------------------
def _window(args, state: AgentState) -> tuple[date, date]:
    today = datetime.now(KST).date()
    if args.since_last_run:
        return state.since_last_run(args.days), today
    start = args.date_from or (today - timedelta(days=args.days - 1))
    end = args.date_to or today
    return start, end


def cmd_run(args) -> int:
    settings = load_settings()
    state = AgentState.load(STATE_FILE)
    contract = load_contract(CONTRACT_FILE)
    contract.require_ready()

    start, end = _window(args, state)
    log(f"{stamp()}")
    log(f"window: {start.isoformat()} .. {end.isoformat()}")

    writer = TaskWriter(settings, project_name=args.project_name)
    writer.verify_project()          # fail closed before a browser even opens
    log(f"project: verified ({args.project_name})")

    scanned = already = candidates = registered = 0
    opened = unread_skipped = read_skipped = date_skipped = 0
    with browser_session(PROFILE_DIR, contract, headless=not args.headed) as session:
        session.assert_authenticated()
        log("session: ok")
        # The mailbox may live in another tab or a frame; never assume the launch page.
        target = select_mail_page(session.context, urlparse(contract.mail_url).netloc)
        if target is None and not contract.list_api:
            raise UiContractError("could not find the mailbox page",
                                  hint="run --calibrate again")
        headers = list_mails(session, limit=args.max_mails, target=target, since=start)
        log(f"loaded rows: {len(headers)}")
        for header in headers:
            if header.received and not (start <= header.received <= end):
                date_skipped += 1
                continue
            scanned += 1
            if state.seen(header.mail_id):
                already += 1
                continue
            # Read-state is decided from the row, BEFORE any body is opened, so a
            # --read-state read pass can never flip an unread mail to read.
            if args.read_state != "all" and header.unread is not None:
                if args.read_state == "read" and header.unread:
                    unread_skipped += 1
                    continue
                if args.read_state == "unread" and not header.unread:
                    read_skipped += 1
                    continue
            decision = classify(header.subject, header.preview)
            if not decision.candidate and args.open_body and not args.subject_only:
                # The preview is short; a mail that looks plausible from its
                # subject gets its body read before being dismissed.
                if decision.has_event_word or decision.has_meal_time:
                    open_body(session, header, target=target)
                    opened += 1
                    decision = classify(header.subject, header.text_for_filter)
            elif decision.candidate and args.open_body:
                open_body(session, header, target=target)
                opened += 1
            if not decision.candidate:
                state.record(header.mail_id, header.subject, header.received,
                             registered=False, outcome="filtered")
                continue
            candidates += 1
            payload = MailPayload(mail_id=header.mail_id, subject=header.subject,
                                  body=header.body or header.preview, received=header.received,
                                  preview_only=not header.body_opened)
            try:
                post_id = writer.create_task(payload, dry_run=args.dry_run)
            except AgentError:
                state.record(header.mail_id, header.subject, header.received,
                             registered=False, outcome="write-failed")
                state.save()
                raise
            if not args.dry_run:
                registered += 1
            state.record(header.mail_id, header.subject, header.received,
                         registered=bool(post_id), outcome="candidate")

    state.mark_run(end)
    state.prune()
    if not args.dry_run:
        state.save()

    log(f"date matched: {scanned}  (outside the window: {date_skipped})")
    log(f"already processed: {already}")
    log(f"new: {scanned - already}")
    if args.read_state != "all":
        log(f"skipped by --read-state {args.read_state}: "
            f"{unread_skipped} unread / {read_skipped} read")
    log(f"bodies opened: {opened}")
    log(f"candidates: {candidates}")
    log(f"registered: {registered}{' (dry run)' if args.dry_run else ''}")

    if args.run_pipeline and registered:
        return _run_pipeline()
    if args.run_pipeline:
        log("pipeline: skipped (nothing new registered)")
    return SUCCESS


def _run_pipeline() -> int:
    log("pipeline: running refresh_ggongbab.py --only dooray")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "refresh_ggongbab.py"), "--only", "dooray"],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace")
    for line in (result.stdout or "").splitlines():
        log(f"  {line}")
    if result.returncode != 0:
        for line in (result.stderr or "").splitlines()[-5:]:
            log(f"  {line}")
        raise PipelineFailed(f"refresh_ggongbab.py exited {result.returncode}")
    log("pipeline: success")
    return SUCCESS


def cmd_calibrate(args) -> int:
    """Open the saved inbox, watch it load, verify the endpoint, write the contract."""
    contract = load_contract(CONTRACT_FILE)
    if not contract.mail_url:
        raise UiContractError("no mailbox URL recorded yet", hint="run --setup first")
    origin_host = urlparse(contract.mail_url).netloc
    log(f"opening {contract.mail_url.split('?')[0]}")
    with browser_session(PROFILE_DIR, contract, headless=not args.headed) as session:
        session.assert_authenticated()
        observer = NetworkObserver(session.context)
        observer.on_mail_screen = True
        observer.start()
        try:
            target = select_mail_page(session.context, origin_host)
            if target is None:
                for line in describe(collect_targets(session.context, origin_host)):
                    log(line)
                raise UiContractError("the saved mail_url did not open a mailbox",
                                      hint="run --setup again while 받은메일함 is on screen")
            log(f"mail target: {target.location}"
                f"  ({'frame' if not target.is_main else 'top-level page'})")
            observe(session, observer, seconds=args.observe_seconds, target=target)
            log("reloading inbox...")
            observe(session, observer, seconds=max(6, args.observe_seconds // 2),
                    reload=True, target=target)

            row_evidence = mail_row_evidence(target.frame)
            report = write_discovery_report(observer, row_evidence, DISCOVERY_FILE,
                                            page_url=target.frame.url or target.url,
                                            confirmed_by_user=False)
            log("")
            log("calibrating...")
            summary = calibrate(target.page, observer, contract, log=log)
        finally:
            observer.stop()

    log("")
    if summary.get("strategy") != "api" or not contract.verified:
        log("[not verified] no endpoint passed the read-only smoke test.")
        log(f"               report: {DISCOVERY_FILE}")
        log("               DOM fallback needs a stable per-row id; the live inbox")
        log("               uses generated class names and a shared row attribute,")
        log("               so it cannot supply one. Re-run --calibrate after the UI settles.")
        _report_findings(report)
        return exit_codes.UI_CHANGED

    contract.save(CONTRACT_FILE)
    log(f"contract written: {CONTRACT_FILE}")
    log(f"  strategy      : JSON list endpoint (no DOM selectors needed)")
    log(f"  page param    : {contract.list_page_param or '(none)'}")
    log(f"  size param    : {contract.list_size_param or '(none)'}")
    log(f"  read-state key: {contract.read_state_key or '(none observed)'}")
    log(f"  verified      : {contract.verified}")
    log("")
    log("No task was created, no mail body was opened, nothing was written to the mailbox.")
    log("")
    log("Next (dry run, writes nothing):")
    log(r"  python scripts\dooray_web_agent.py --run --from 2026-09-01 --to 2026-09-19 ^")
    log("      --read-state read --dry-run")
    return SUCCESS


def cmd_selftest(args) -> int:
    settings = load_settings()
    writer = TaskWriter(settings, project_name=args.project_name)
    post_id = writer.selftest()
    log(f"write contract ok; created post {post_id}")
    log("Delete that task in Dooray when you are done.")
    return SUCCESS


# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--setup", action="store_true", help="open a browser once for the manual SSO login")
    mode.add_argument("--discover", action="store_true", help="record how the mail page loads")
    mode.add_argument("--run", action="store_true", help="unattended scan and register")
    mode.add_argument("--calibrate", action="store_true",
                      help="fill .local/dooray-ui.json from the live inbox (no hand editing)")
    mode.add_argument("--selftest", action="store_true", help="create one harmless task to verify write access")

    parser.add_argument("--url", help=f"Dooray address for --setup (default {DEFAULT_DOORAY_URL})")
    parser.add_argument("--observe-seconds", type=int, default=12,
                        help="how long --discover watches the inbox (default 12)")
    parser.add_argument("--from", dest="date_from", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
                        metavar="YYYY-MM-DD", help="earliest received date to scan")
    parser.add_argument("--to", dest="date_to", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
                        metavar="YYYY-MM-DD", help="latest received date to scan")
    parser.add_argument("--since-last-run", action="store_true", help="scan from the previous run (with a day of overlap)")
    parser.add_argument("--days", type=int, default=3, help="default window when no dates are given (default 3)")
    parser.add_argument("--max-mails", type=int, default=200, help="safety limit on rows read (default 200)")
    parser.add_argument("--read-state", choices=["all", "read", "unread"], default="all",
                        help="which mails to process; 'read' never opens an unread mail")
    parser.add_argument("--project-name", default=DEFAULT_PROJECT_NAME,
                        help="exact project name that must match, or nothing is written")
    parser.add_argument("--run-pipeline", action="store_true", help="run refresh_ggongbab.py --only dooray afterwards")
    parser.add_argument("--dry-run", action="store_true", help="scan and filter but create no task and keep state unchanged")
    parser.add_argument("--headed", action="store_true", help="show the browser during --run (debugging)")
    parser.add_argument("--subject-only", action="store_true",
                        help="never open a mail body, so no mail is marked read (tasks carry subject + preview only)")
    parser.add_argument("--no-open-body", dest="open_body", action="store_false",
                        help="alias of --subject-only")
    parser.set_defaults(open_body=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.subject_only:
        args.open_body = False
    try:
        if args.setup:
            return cmd_setup(args)
        if args.discover:
            return cmd_discover(args)
        if args.calibrate:
            return cmd_calibrate(args)
        if args.selftest:
            return cmd_selftest(args)
        return cmd_run(args)
    except AgentError as exc:
        name = NAMES.get(exc.code, "ERROR")
        log(f"[{name}] {exc}")
        if exc.hint:
            log(f"          {exc.hint}")
        return exc.code
    except KeyboardInterrupt:
        log("[interrupted]")
        return 1


if __name__ == "__main__":
    sys.exit(main())
