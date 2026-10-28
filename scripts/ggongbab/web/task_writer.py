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

A mail's poster images (since 2026-10-14) are uploaded as files of its task, where the cloud
collector already downloads task files for the AI (collectors/dooray.py).
"""
from __future__ import annotations

import hashlib
import json
import time
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional

from ..config import KST, Settings
from ..ingest_marker import render_portal_marker, render_timing
from .exit_codes import ProjectNotFound

UA = "BabdodukGgongbabAgent/1.0 (+https://github.com/joshualikaist/Babdoduk)"
DEFAULT_PROJECT_NAME = "밥도둑-꽁밥-행사-수집함"
TASK_MARKER = "ggongbab-agent"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Redirects are followed by hand, so the auth header never follows a hop off Dooray."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def mail_identity(mail_id: str) -> str:
    """One-way identity for a mailbox row. The raw mail id is not recoverable."""
    return hashlib.sha256(f"dooray-mail:{mail_id}".encode("utf-8")).hexdigest()


@dataclass
class MailPayload:
    """What the agent knows about a mail. No addresses are carried here."""

    mail_id: str
    subject: str
    body: str
    received: Optional[date] = None
    preview_only: bool = False
    # Private latency metadata (to the minute / second). Never public, never sent to the AI.
    received_at: Optional[datetime] = None
    discovered_at: Optional[datetime] = None
    # Poster images (mime, bytes), already shrunk by the Radar; uploaded as task files.
    images: list = field(default_factory=list)


@dataclass
class PortalPayload:
    """Portal notice queued into the same collection project. No raw portal ids."""

    external_key: str
    title: str
    body: str
    source_created_at: str = ""
    private_source: bool = True


# A GET that fails on the network (timeout, reset, DNS) is tried again after these pauses; a write
# (POST/PUT) never is, and an HTTP error answer never is. 2026-10-28: the duplicate-task index reads
# ~130 posts one by one; on this PC's network one of them timed out on every attempt, so every Radar
# scan failed with DOORAY_WRITE_FAILED although each post answered in about a second on its own.
GET_RETRY_PAUSES = (2.0, 5.0)


class TaskWriter:
    def __init__(self, settings: Settings, project_name: str = DEFAULT_PROJECT_NAME, timeout: int = 25,
                 sleep=time.sleep):
        self._sleep = sleep
        self.settings = settings
        self.project_name = project_name
        self.timeout = timeout
        self._ctx = ssl.create_default_context()
        self._verified = False
        self._mail_index: Optional[dict[str, str]] = None
        self.uploads = {"uploaded": 0, "failed": 0}
        labels = urllib.parse.urlparse(settings.dooray_base).netloc.split(":")[0].split(".")
        self._trusted_domain = ".".join(labels[-2:]).lower() if len(labels) >= 2 else ""

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
        pauses = GET_RETRY_PAUSES if method == "GET" else ()
        for attempt in range(len(pauses) + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout, context=self._ctx) as res:
                    raw = res.read()
                break
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:300]
                raise ProjectNotFound(f"{method} {path}: HTTP {exc.code} {detail}") from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempt < len(pauses):
                    self._sleep(pauses[attempt])
                    continue
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
        if mail.received_at is not None:
            received = mail.received_at.astimezone(KST).strftime("%Y-%m-%d %H:%M") + " (GMT+09:00)"
        else:
            received = mail.received.isoformat() if mail.received else ""
        note = " (preview only; mail body was not opened)" if mail.preview_only else ""
        timing = render_timing(discovered_at=mail.discovered_at)
        content = (
            f"-----Original Message-----\n"
            f"Sent: {received}\n"
            f"Subject: {mail.subject}\n\n"
            f"{mail.body}\n\n"
            f"[{TASK_MARKER}] collected from the Dooray mailbox{note}\n"
            f"mail_key={mail_identity(mail.mail_id)}"
        ) + (f"\n{timing}" if timing else "")
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
        # A previous attempt may have created the task and then lost the response.
        # Reuse that post instead of appending a second one.
        existing = self.find_existing_mail_task(mail.mail_id)
        if existing:
            if mail.images and not self._post_files(existing):
                self.attach_images(existing, mail.images)
            return existing
        payload = self._request("POST", f"/project/v1/projects/{self.settings.dooray_project_id}/posts",
                                self.build_task(mail))
        result = payload.get("result") or {}
        post_id = str(result.get("id") or "")
        if not post_id:
            raise ProjectNotFound("task creation returned no post id")
        if self._mail_index is not None:
            self._mail_index[f"mail_key={mail_identity(mail.mail_id)}"] = post_id
        if mail.images:
            self.attach_images(post_id, mail.images)
        return post_id

    def attach_images(self, post_id: str, images: list) -> int:
        """Upload poster images to the task. A failed upload never fails the task: its text is
        already there, and the count shows up in the Radar's runtime counts."""
        done = 0
        for index, (mime, data) in enumerate(images, start=1):
            ext = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif", "image/webp": "webp"}.get(mime, "bin")
            try:
                self.upload_file(post_id, f"poster-{index}.{ext}", mime, data)
                done += 1
                self.uploads["uploaded"] += 1
            except ProjectNotFound:
                self.uploads["failed"] += 1
        return done

    def _post_files(self, post_id: str) -> list:
        try:
            payload = self._request("GET", f"/project/v1/projects/{self.settings.dooray_project_id}/posts/{post_id}/files")
        except ProjectNotFound:
            return []
        files = payload.get("result")
        return files if isinstance(files, list) else []

    def upload_file(self, post_id: str, filename: str, mime: str, data: bytes) -> str:
        """POST a task file (multipart). Dooray answers the API host with a 307 to its file host;
        the auth header is re-sent only while the hop stays on the configured Dooray domain."""
        boundary = "----babdoduk" + hashlib.sha256(data).hexdigest()[:24]
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
                f"Content-Type: {mime}\r\n\r\n").encode("utf-8") + data + f"\r\n--{boundary}--\r\n".encode("ascii")
        url = (self.settings.dooray_base.rstrip("/")
               + f"/project/v1/projects/{self.settings.dooray_project_id}/posts/{post_id}/files")
        opener = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=self._ctx))
        for _ in range(4):
            host = urllib.parse.urlparse(url).netloc.split(":")[0].lower()
            headers = {"Accept": "application/json", "User-Agent": UA,
                       "Content-Type": f"multipart/form-data; boundary={boundary}"}
            if self._trusted_domain and (host == self._trusted_domain or host.endswith("." + self._trusted_domain)):
                headers["Authorization"] = f"dooray-api {self.settings.dooray_token}"
            req = urllib.request.Request(url, data=body, method="POST", headers=headers)
            try:
                with opener.open(req, timeout=max(self.timeout, 60)) as res:
                    raw = res.read()
            except urllib.error.HTTPError as exc:
                location = exc.headers.get("Location")
                if exc.code in (307, 308) and location:
                    url = urllib.parse.urljoin(url, location)
                    continue
                raise ProjectNotFound(f"file upload: HTTP {exc.code}") from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                raise ProjectNotFound(f"file upload: {exc.__class__.__name__}") from exc
            payload = json.loads(raw.decode("utf-8")) if raw else {}
            header = payload.get("header") or {}
            if header and header.get("isSuccessful") is False:
                raise ProjectNotFound(f"file upload: {header.get('resultMessage', 'not successful')}")
            return str((payload.get("result") or {}).get("id") or "")
        raise ProjectNotFound("file upload: too many redirects")

    def find_existing_mail_task(self, mail_id: str) -> Optional[str]:
        """Return a collection-project post that already carries this mail hash."""
        if not mail_id:
            return None
        token = f"mail_key={mail_identity(mail_id)}"
        return self._mail_task_index().get(token)

    def _mail_task_index(self) -> dict[str, str]:
        if self._mail_index is not None:
            return self._mail_index
        found: dict[str, str] = {}
        project = self.settings.dooray_project_id
        size = max(1, self.settings.dooray_page_size)
        for page in range(max(1, self.settings.dooray_max_pages)):
            payload = self._request(
                "GET", f"/project/v1/projects/{project}/posts?page={page}&size={size}")
            posts = self._post_list(payload)
            if not posts:
                break
            for post in posts:
                post_id = str(post.get("id") or "")
                if not post_id:
                    continue
                blob = json.dumps(post, ensure_ascii=False)
                if "mail_key=" not in blob:
                    detail = self._request("GET", f"/project/v1/projects/{project}/posts/{post_id}")
                    blob = json.dumps(detail, ensure_ascii=False)
                for part in blob.split("mail_key=")[1:]:
                    key = part[:64]
                    if len(key) == 64 and all(ch in "0123456789abcdef" for ch in key):
                        found[f"mail_key={key}"] = post_id
            if len(posts) < size:
                break
        self._mail_index = found
        return found

    @staticmethod
    def _post_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
        posts = payload.get("result")
        if posts is None:
            raise ProjectNotFound("task lookup returned no result")
        if isinstance(posts, dict):
            posts = posts.get("contents") or posts.get("data") or []
        if not isinstance(posts, list):
            raise ProjectNotFound("task lookup returned an unexpected shape")
        return [post for post in posts if isinstance(post, dict)]

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
