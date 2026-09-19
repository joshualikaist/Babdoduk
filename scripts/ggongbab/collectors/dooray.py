# -*- coding: utf-8 -*-
"""Dooray project-task collector.

Dooray automatic mail classification already creates a task in the project
"밥도둑-꽁밥-행사-수집함" for every candidate mail. This collector only reads
those tasks through the verified endpoints:

    GET /common/v1/members/me
    GET /project/v1/projects/{PROJECT_ID}/posts?size=100
    GET /project/v1/projects/{PROJECT_ID}/posts/{POST_ID}

Attachments are optional enrichment. Any download failure is swallowed and
recorded on the attachment; it never fails the collector.
"""
from __future__ import annotations

import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Optional

from ..config import KST, Settings
from ..models import RawAttachment, RawItem
from ..parsers.dooray_mail import parse_original_message
from ..parsers.html_text import html_to_text, inline_file_ids
from .base import Collector, CollectorError

UA = "BabdodukGgongbab/1.0 (+https://github.com/joshualikaist/Babdoduk)"
IMAGE_EXT = re.compile(r"\.(png|jpe?g|gif|webp)$", re.I)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


class AttachmentError(Exception):
    """Attachment download failure. Carries enough detail to debug without leaking the signed URL."""

    def __init__(self, stage: str, status: Optional[int] = None, redirected: bool = False, detail: str = ""):
        self.stage = stage
        self.status = status
        self.redirected = redirected
        self.detail = detail
        parts = [f"stage={stage}"]
        if status is not None:
            parts.append(f"http={status}")
        parts.append(f"redirected={'yes' if redirected else 'no'}")
        if detail:
            parts.append(detail)
        super().__init__(" ".join(parts))


class DoorayClient:
    """Thin urllib client. Token only ever goes into the Authorization header."""

    def __init__(self, base: str, token: str, timeout: int = 25):
        self.base = base.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._ctx = ssl.create_default_context()
        # Trust anchor for redirects, derived from the configured base rather than
        # hard-coded: api.gov-dooray.com -> gov-dooray.com, so file-api.gov-dooray.com
        # is trusted while evil-dooray.com.attacker.net is not.
        labels = urllib.parse.urlparse(self.base).netloc.split(":")[0].split(".")
        self._trusted_domain = ".".join(labels[-2:]) if len(labels) >= 2 else ""

    def _trusted(self, host: str) -> bool:
        host = (host or "").split(":")[0].lower()
        domain = self._trusted_domain.lower()
        return bool(domain) and (host == domain or host.endswith("." + domain))

    # -- low level --------------------------------------------------------
    def _headers(self, accept: str = "application/json") -> dict[str, str]:
        return {
            "Authorization": f"dooray-api {self.token}",
            "Accept": accept,
            "User-Agent": UA,
        }

    def get_json(self, path: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        url = self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=self._ctx) as res:
                payload = json.loads(res.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise CollectorError(f"dooray {path}: HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise CollectorError(f"dooray {path}: {exc.__class__.__name__}") from exc
        header = payload.get("header") or {}
        if header and header.get("isSuccessful") is False:
            raise CollectorError(f"dooray {path}: {header.get('resultMessage', 'not successful')}")
        return payload

    def download(self, url_or_path: str, max_bytes: int, max_hops: int = 4) -> tuple[bytes, str]:
        """Download a file, following up to `max_hops` redirects manually.

        Verified behaviour (2026-09-19, live project): the raw-media endpoint answers
        307 with a Location on `file-api.gov-dooray.com`. The auth header is re-sent
        only while the hop stays on a `*.dooray.com` host; a signed URL on any other
        host is fetched without it.
        """
        url = url_or_path if url_or_path.startswith("http") else self.base + url_or_path
        opener = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=self._ctx))
        redirected = False
        for _ in range(max_hops + 1):
            host = urllib.parse.urlparse(url).netloc
            stage = "redirect" if redirected else "request"
            headers = {"User-Agent": UA, "Accept": "*/*"}
            if self._trusted(host):
                headers["Authorization"] = f"dooray-api {self.token}"
            req = urllib.request.Request(url, headers=headers)
            try:
                res = opener.open(req, timeout=self.timeout)
            except urllib.error.HTTPError as exc:
                location = exc.headers.get("Location")
                if exc.code in (301, 302, 303, 307, 308) and location:
                    url = urllib.parse.urljoin(url, location)
                    redirected = True
                    continue
                raise AttachmentError(stage, status=exc.code, redirected=redirected) from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                raise AttachmentError(stage, redirected=redirected, detail=exc.__class__.__name__) from exc
            with res:
                length = res.headers.get("Content-Length")
                if length and length.isdigit() and int(length) > max_bytes:
                    raise AttachmentError("size", status=res.status, redirected=redirected,
                                          detail=f"{length} bytes > limit")
                data = res.read(max_bytes + 1)
                if len(data) > max_bytes:
                    raise AttachmentError("size", status=res.status, redirected=redirected, detail="over limit")
                if not data:
                    raise AttachmentError("empty", status=res.status, redirected=redirected)
                return data, res.headers.get("Content-Type", "") or ""
        raise AttachmentError("redirect", redirected=True, detail=f"more than {max_hops} hops")

    # -- verified endpoints ---------------------------------------------
    def me(self) -> dict[str, Any]:
        return self.get_json("/common/v1/members/me").get("result") or {}

    def list_posts(self, project_id: str, page: int = 0, size: int = 100) -> list[dict[str, Any]]:
        payload = self.get_json(f"/project/v1/projects/{project_id}/posts", {"page": page, "size": size})
        result = payload.get("result")
        return result if isinstance(result, list) else []

    def get_post(self, project_id: str, post_id: str) -> dict[str, Any]:
        return self.get_json(f"/project/v1/projects/{project_id}/posts/{post_id}").get("result") or {}

    def list_post_files(self, project_id: str, post_id: str) -> list[dict[str, Any]]:
        """May legitimately be empty for inline attachments; callers must also read the body."""
        try:
            payload = self.get_json(f"/project/v1/projects/{project_id}/posts/{post_id}/files")
        except CollectorError:
            return []
        result = payload.get("result")
        return result if isinstance(result, list) else []

    def file_path(self, project_id: str, post_id: str, file_id: str) -> str:
        """The only download path confirmed against the live API.

        Verified 2026-09-19 against the collection project:
          * `…/posts/{post}/files/{file}?media=raw` -> 307 -> file host -> 200 image/png
          * `…/posts/{post}/files/{file}` (no media param) -> 404 {"resultMessage":"null"}
          * `/files/{file}` (the path used by inline <img> in the body) -> 404
        The body's `/files/{id}` reference is therefore only a source of file *ids*,
        never a download endpoint.
        """
        return f"/project/v1/projects/{project_id}/posts/{post_id}/files/{file_id}?media=raw"

    def download_post_file(self, project_id: str, post_id: str, file_id: str, max_bytes: int) -> tuple[bytes, str]:
        return self.download(self.file_path(project_id, post_id, file_id), max_bytes)


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    return dt.astimezone(KST)


class DoorayCollector(Collector):
    source_type = "dooray"
    name = "Dooray"

    def __init__(self, settings: Settings, client: Optional[DoorayClient] = None,
                 fetch_attachments: bool = True):
        self.settings = settings
        self.client = client or DoorayClient(settings.dooray_base, settings.dooray_token)
        self.fetch_attachments = fetch_attachments

    def enabled(self) -> bool:
        return self.settings.has_dooray

    # ------------------------------------------------------------------
    def collect(self) -> list[RawItem]:
        if not self.enabled():
            return []
        project_id = self.settings.dooray_project_id
        items: list[RawItem] = []
        for page in range(self.settings.dooray_max_pages):
            posts = self.client.list_posts(project_id, page=page, size=self.settings.dooray_page_size)
            if not posts:
                break
            for summary in posts:
                post_id = str(summary.get("id") or "")
                if not post_id:
                    continue
                try:
                    detail = self.client.get_post(project_id, post_id)
                except CollectorError as exc:
                    print(f"[warn] dooray post {post_id}: {exc}")
                    continue
                item = self.normalize_post(detail or summary)
                if item is None:
                    continue
                if self.fetch_attachments and item.attachments:
                    # Deferred: the pipeline calls load_attachments() only when it is
                    # actually going to parse the item, so cached posts cost no traffic.
                    item.attachment_loader = _loader(self, post_id, item)
                items.append(item)
            if len(posts) < self.settings.dooray_page_size:
                break
        return items

    # ------------------------------------------------------------------
    def normalize_post(self, post: dict[str, Any]) -> Optional[RawItem]:
        post_id = str(post.get("id") or "")
        if not post_id:
            return None
        body = post.get("body") or {}
        mime = (body.get("mimeType") or "").lower()
        content = body.get("content") or ""
        raw_html = content if "html" in mime else ""
        text = html_to_text(content) if "html" in mime else content
        original = parse_original_message(text)
        subject = original.subject or post.get("subject") or ""
        subject = re.sub(r"^\s*(?:\[?(?:FW|FWD|RE|전달|회신)\]?\s*[:：]\s*)+", "", subject, flags=re.I).strip()
        created = _parse_ts(post.get("createdAt"))
        updated = _parse_ts(post.get("updatedAt"))
        sent = original.sent_at or created

        attachments: list[RawAttachment] = []
        seen: set[str] = set()
        for f in post.get("files") or []:
            fid = str(f.get("id") or "")
            if not fid or fid in seen:
                continue
            seen.add(fid)
            attachments.append(RawAttachment(external_file_id=fid, filename=f.get("name") or "",
                                             size=int(f.get("size") or 0)))
        for fid in inline_file_ids(content):
            if fid not in seen:
                seen.add(fid)
                attachments.append(RawAttachment(external_file_id=fid, inline=True))

        return RawItem(
            source_type="dooray",
            external_id=post_id,
            subject=subject,
            sender_name=original.sender_name,
            sender_email=original.sender_email,
            raw_text=original.body if original.found else text,
            raw_html=raw_html,
            source_url="",
            source_created_at=sent,
            source_updated_at=updated,
            metadata={
                "dooray_post_number": post.get("number"),
                "dooray_created_at": post.get("createdAt"),
                "dooray_updated_at": post.get("updatedAt"),
                "original_header_found": original.found,
                "to_count": len(original.to),
                "cc_count": len(original.cc),
                "task_subject": post.get("subject") or "",
            },
            attachments=attachments,
        )

    def download_attachments(self, post_id: str, item: RawItem) -> None:
        """Fetch attachment bytes. Any failure is recorded on the attachment only."""
        project_id = self.settings.dooray_project_id
        listed = {str(f.get("id")): f for f in self.client.list_post_files(project_id, post_id)}
        for att in item.attachments:
            meta = listed.get(att.external_file_id)
            if meta:
                att.filename = att.filename or meta.get("name") or ""
                att.size = att.size or int(meta.get("size") or 0)
            if att.size and att.size > self.settings.ai_max_image_bytes:
                att.parse_status = "skipped"
                continue
            try:
                data, ctype = self.client.download_post_file(project_id, post_id, att.external_file_id,
                                                             self.settings.ai_max_image_bytes)
            except AttachmentError as exc:
                att.parse_status = "failed"
                att.mime_type = att.mime_type or ""
                print(f"[warn] dooray attachment {att.external_file_id[:8]}…: {exc}")
                continue
            except Exception as exc:  # noqa: BLE001 - optional enrichment, never fatal
                att.parse_status = "failed"
                print(f"[warn] dooray attachment {att.external_file_id[:8]}…: stage=unknown {exc.__class__.__name__}")
                continue
            att.data = data
            att.size = att.size or len(data)
            att.mime_type = _guess_mime(ctype, att.filename, data)
            att.compute_sha()
            att.parse_status = "downloaded" if att.mime_type.startswith("image/") else "skipped"


def _loader(collector: "DoorayCollector", post_id: str, item: RawItem):
    return lambda: collector.download_attachments(post_id, item)


def _guess_mime(content_type: str, filename: str, data: bytes) -> str:
    ctype = (content_type or "").split(";")[0].strip().lower()
    if ctype.startswith("image/"):
        return ctype
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:5] == b"%PDF-":
        return "application/pdf"
    match = IMAGE_EXT.search(filename or "")
    if match:
        ext = match.group(1).lower()
        return "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
    return ctype or "application/octet-stream"
