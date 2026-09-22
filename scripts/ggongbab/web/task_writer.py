# -*- coding: utf-8 -*-
"""Create the collection-project task for a candidate mail.

Deliberately uses the Dooray Project REST API rather than clicking the web UI's
"업무 등록" button:

  * the target is addressed by project id, so registering into the wrong project
    is structurally impossible rather than merely unlikely;
  * it does not depend on any DOM that can change under us;
  * the API is already verified and used by the ingest collector.

Fail closed: the project is re-verified by id AND exact name before every run.
If verification fails, nothing is written.
"""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from ..config import Settings
from ..ingest_marker import render_portal_marker
from .exit_codes import ProjectNotFound

UA = "BabdodukGgongbabAgent/1.0 (+https://github.com/joshualikaist/Babdoduk)"
DEFAULT_PROJECT_NAME = "밥도둑-꽁밥-행사-수집함"
TASK_MARKER = "ggongbab-agent"


@dataclass
class MailPayload:
    """What the agent knows about a mail. No addresses are carried here."""

    mail_id: str
    subject: str
    body: str
    received: Optional[date] = None
    preview_only: bool = False


@dataclass
class PortalPayload:
    """Portal notice queued into the same collection project. No raw portal ids."""

    external_key: str
    title: str
    body: str
    source_created_at: str = ""
    private_source: bool = True


class TaskWriter:
    def __init__(self, settings: Settings, project_name: str = DEFAULT_PROJECT_NAME, timeout: int = 25):
        self.settings = settings
        self.project_name = project_name
        self.timeout = timeout
        self._ctx = ssl.create_default_context()
        self._verified = False

    # -- transport -----------------------------------------------------
    def _request(self, method: str, path: str, body: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        url = self.settings.dooray_base.rstrip("/") + path
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"dooray-api {self.settings.dooray_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": UA,
        })
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=self._ctx) as res:
                raw = res.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise ProjectNotFound(f"{method} {path}: HTTP {exc.code} {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProjectNotFound(f"{method} {path}: {exc.__class__.__name__}") from exc
        payload = json.loads(raw.decode("utf-8")) if raw else {}
        header = payload.get("header") or {}
        if header and header.get("isSuccessful") is False:
            raise ProjectNotFound(f"{method} {path}: {header.get('resultMessage', 'not successful')}")
        return payload

    # -- fail-closed verification --------------------------------------
    def verify_project(self) -> dict[str, Any]:
        """Confirm the configured id really is the collection project, by exact name."""
        if not self.settings.has_dooray:
            raise ProjectNotFound("DOORAY_API_TOKEN / DOORAY_PROJECT_ID missing",
                                  hint="fill them in .env before running the agent")
        result = self._request("GET", f"/project/v1/projects/{self.settings.dooray_project_id}").get("result") or {}
        code = str(result.get("code") or "")
        if code != self.project_name:
            raise ProjectNotFound(
                f"project {self.settings.dooray_project_id} is named {code!r}, expected {self.project_name!r}",
                hint="refusing to register tasks into a project that does not match exactly")
        if str(result.get("state") or "active") != "active":
            raise ProjectNotFound(f"project state is {result.get('state')!r}, not active")
        self._verified = True
        return result

    # -- writes --------------------------------------------------------
    def build_task(self, mail: MailPayload) -> dict[str, Any]:
        """Task body mirrors what an auto-classified mail task looks like.

        The original-message header block is what parsers/dooray_mail.py reads, so
        the ingest pipeline treats an agent-created task exactly like a classified one.
        Sender and recipient lines are deliberately omitted: the pipeline does not
        need them and the sanitizer would strip them anyway.
        """
        received = mail.received.isoformat() if mail.received else ""
        note = " (preview only; mail body was not opened)" if mail.preview_only else ""
        content = (
            f"-----Original Message-----\n"
            f"Sent: {received}\n"
            f"Subject: {mail.subject}\n\n"
            f"{mail.body}\n\n"
            f"[{TASK_MARKER}] collected from the Dooray mailbox{note}"
        )
        return {
            "subject": mail.subject or "(제목 없음)",
            "body": {"mimeType": "text/x-markdown", "content": content},
        }

    def build_portal_task(self, notice: PortalPayload) -> dict[str, Any]:
        marker = render_portal_marker(
            external_key=notice.external_key,
            source_created_at=notice.source_created_at,
            private_source=notice.private_source,
        )
        content = (
            f"{marker}\n\n"
            f"Original Notice\n"
            f"Subject: {notice.title}\n\n"
            f"{notice.body}\n"
        )
        return {
            "subject": notice.title or "(제목 없음)",
            "body": {"mimeType": "text/x-markdown", "content": content},
        }

    def create_task(self, mail: MailPayload, dry_run: bool = False) -> Optional[str]:
        """Returns the new post id, or None on a dry run."""
        if not self._verified:
            raise ProjectNotFound("verify_project() must succeed before any write")
        if not mail.mail_id:
            raise ProjectNotFound("mail has no stable id; refusing to register it")
        if dry_run:
            return None
        payload = self._request("POST", f"/project/v1/projects/{self.settings.dooray_project_id}/posts",
                                self.build_task(mail))
        result = payload.get("result") or {}
        post_id = str(result.get("id") or "")
        if not post_id:
            raise ProjectNotFound("task creation returned no post id")
        return post_id

    def create_portal_task(self, notice: PortalPayload, dry_run: bool = False) -> Optional[str]:
        if not self._verified:
            raise ProjectNotFound("verify_project() must succeed before any write")
        if not notice.external_key:
            raise ProjectNotFound("portal notice has no stable external key; refusing to register it")
        if dry_run:
            return None
        payload = self._request("POST", f"/project/v1/projects/{self.settings.dooray_project_id}/posts",
                                self.build_portal_task(notice))
        result = payload.get("result") or {}
        post_id = str(result.get("id") or "")
        if not post_id:
            raise ProjectNotFound("task creation returned no post id")
        return post_id

    def selftest(self) -> str:
        """Create one harmless task to confirm the write contract, then report its id.

        The subject carries no event or food wording, so the ingest prefilter and
        the model both treat it as a non-event. Delete it in Dooray afterwards.
        """
        self.verify_project()
        probe = MailPayload(
            mail_id=f"{TASK_MARKER}-selftest",
            subject=f"[{TASK_MARKER}] write contract self-test",
            body="Automated write check. Safe to delete.",
        )
        return self.create_task(probe) or ""
