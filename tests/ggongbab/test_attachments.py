# -*- coding: utf-8 -*-
"""Attachment download endpoint and deferred (cache-aware) fetching."""
from __future__ import annotations

import urllib.error
from typing import Optional

import pytest

from ggongbab.collectors.dooray import AttachmentError, DoorayClient, DoorayCollector
from ggongbab.db.repository import MemoryRepository
from ggongbab.models import RawAttachment, RawItem
from ggongbab.pipeline import Pipeline

from .conftest import FakeExtractor
from .test_pipeline_export import DOORAY_POST, FUTURE_TEXT, ListCollector, _item, future_extraction

PROJ, POST, FILE = "4424523215847914253", "4424564466674071765", "4424564466271580134"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 9000


# --- endpoint shape ----------------------------------------------------------
def test_download_path_uses_media_raw():
    """Verified live: only `?media=raw` returns the file; the bare path and /files/{id} are 404."""
    client = DoorayClient("https://api.gov-dooray.com", "token")
    path = client.file_path(PROJ, POST, FILE)
    assert path == f"/project/v1/projects/{PROJ}/posts/{POST}/files/{FILE}?media=raw"
    assert path.endswith("?media=raw")
    assert not path.startswith("/files/")


def test_body_file_ids_are_not_treated_as_endpoints():
    import inspect

    from ggongbab.collectors import dooray

    source = inspect.getsource(dooray.DoorayClient.download_post_file) + inspect.getsource(dooray.DoorayClient.file_path)
    assert 'f"/files/{file_id}"' not in source, "/files/{id} is a body reference, not a download endpoint"


# --- redirect handling -------------------------------------------------------
class FakeHTTPError(urllib.error.HTTPError):
    def __init__(self, code, location: Optional[str] = None):
        headers = {"Location": location} if location else {}
        super().__init__("https://api.gov-dooray.com/x", code, "redirect", headers, None)


class FakeResponse:
    def __init__(self, data: bytes, ctype: str, status: int = 200):
        self._data, self.status = data, status
        self.headers = {"Content-Type": ctype, "Content-Length": str(len(data))}

    def read(self, n=-1):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_redirect_to_file_host_keeps_auth(monkeypatch):
    responses = [FakeHTTPError(307, "https://file-api.gov-dooray.com/signed/abc"), FakeResponse(PNG, "image/png")]
    calls = []

    class FakeOpener:
        def open(self, req, timeout=None):
            calls.append((req.full_url, {k.lower(): v for k, v in req.headers.items()}))
            item = responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

    monkeypatch.setattr("urllib.request.build_opener", lambda *a, **kw: FakeOpener())
    client = DoorayClient("https://api.gov-dooray.com", "token")
    data, ctype = client.download_post_file(PROJ, POST, FILE, 6 * 1024 * 1024)
    assert data == PNG and ctype == "image/png"
    assert calls[0][0].endswith("?media=raw")
    assert "authorization" in calls[0][1]
    # file-api.gov-dooray.com is still a dooray host, so the token may travel.
    assert "authorization" in calls[1][1]


def test_redirect_to_external_host_drops_auth(monkeypatch):
    responses = [FakeHTTPError(307, "https://s3.amazonaws.com/signed/abc"), FakeResponse(PNG, "image/png")]
    calls = []

    class FakeOpener:
        def open(self, req, timeout=None):
            calls.append((req.full_url, {k.lower(): v for k, v in req.headers.items()}))
            item = responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

    monkeypatch.setattr("urllib.request.build_opener", lambda *a, **kw: FakeOpener())
    client = DoorayClient("https://api.gov-dooray.com", "token")
    client.download_post_file(PROJ, POST, FILE, 6 * 1024 * 1024)
    assert "authorization" not in calls[1][1], "never send the token to a non-dooray host"


@pytest.mark.parametrize("base,host,trusted", [
    # The live deployment is the government tenant; its file host is a sibling label.
    ("https://api.gov-dooray.com", "api.gov-dooray.com", True),
    ("https://api.gov-dooray.com", "file-api.gov-dooray.com", True),
    ("https://api.gov-dooray.com", "evil-dooray.com.attacker.net", False),
    ("https://api.gov-dooray.com", "s3.amazonaws.com", False),
    ("https://api.gov-dooray.com", "notgov-dooray.com", False),
    ("https://api.dooray.com", "file-api.dooray.com", True),
    ("https://api.dooray.com", "api.gov-dooray.com", False),
])
def test_redirect_trust_anchor(base, host, trusted):
    assert DoorayClient(base, "t")._trusted(host) is trusted


def test_evil_lookalike_host_drops_auth(monkeypatch):
    responses = [FakeHTTPError(307, "https://evil-dooray.com.attacker.net/x"), FakeResponse(PNG, "image/png")]
    calls = []

    class FakeOpener:
        def open(self, req, timeout=None):
            calls.append((req.full_url, {k.lower(): v for k, v in req.headers.items()}))
            item = responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

    monkeypatch.setattr("urllib.request.build_opener", lambda *a, **kw: FakeOpener())
    DoorayClient("https://api.gov-dooray.com", "token").download_post_file(PROJ, POST, FILE, 6 * 1024 * 1024)
    assert "authorization" not in calls[1][1]


def test_attachment_error_reports_status_and_stage(monkeypatch):
    responses = [FakeHTTPError(404)]

    class FakeOpener:
        def open(self, req, timeout=None):
            raise responses.pop(0)

    monkeypatch.setattr("urllib.request.build_opener", lambda *a, **kw: FakeOpener())
    client = DoorayClient("https://api.gov-dooray.com", "secret-token")
    with pytest.raises(AttachmentError) as excinfo:
        client.download_post_file(PROJ, POST, FILE, 6 * 1024 * 1024)
    message = str(excinfo.value)
    assert "http=404" in message and "stage=request" in message and "redirected=no" in message
    assert "secret-token" not in message


def test_attachment_error_after_redirect_says_so(monkeypatch):
    responses = [FakeHTTPError(307, "https://file-api.gov-dooray.com/signed/abc"), FakeHTTPError(403)]

    class FakeOpener:
        def open(self, req, timeout=None):
            item = responses.pop(0)
            raise item

    monkeypatch.setattr("urllib.request.build_opener", lambda *a, **kw: FakeOpener())
    with pytest.raises(AttachmentError) as excinfo:
        DoorayClient("https://api.gov-dooray.com", "t").download_post_file(PROJ, POST, FILE, 6 * 1024 * 1024)
    assert "redirected=yes" in str(excinfo.value) and "http=403" in str(excinfo.value)
    assert "signed/abc" not in str(excinfo.value), "never leak the signed URL"


# --- deferred fetching -------------------------------------------------------
class CountingCollector(ListCollector):
    """Attaches a loader and counts how often the pipeline asks for bytes."""

    def __init__(self, items):
        super().__init__(items)
        self.downloads = 0
        for item in items:
            item.attachment_loader = self._make(item)

    def _make(self, item):
        def load():
            self.downloads += 1
            for att in item.attachments:
                att.data = PNG
                att.mime_type = "image/png"
                att.parse_status = "downloaded"
                att.compute_sha()
        return load


def with_attachment(**kw):
    item = _item(**kw)
    item.attachments = [RawAttachment(external_file_id=FILE, filename="poster.png", size=len(PNG))]
    return item


def test_attachment_downloaded_once_and_not_on_cached_run(settings):
    repo = MemoryRepository()
    extractor = FakeExtractor(future_extraction)

    first = CountingCollector([with_attachment()])
    stats = Pipeline(settings, repo, extractor, [first]).run()
    assert stats.ai_calls == 1 and first.downloads == 1
    assert extractor.calls[0][2] == 1, "poster should reach the model"
    assert repo.attachments[(list(repo.raw_items)[0], FILE)]["parse_status"] in ("downloaded", "used")

    second = CountingCollector([with_attachment()])
    stats2 = Pipeline(settings, repo, extractor, [second]).run()
    assert stats2.ai_calls == 0 and stats2.ai_skipped == 1
    assert second.downloads == 0, "cached item must not re-download attachments"
    assert len(extractor.calls) == 1


def test_changed_content_downloads_again(settings):
    repo = MemoryRepository()
    extractor = FakeExtractor(future_extraction)
    Pipeline(settings, repo, extractor, [CountingCollector([with_attachment()])]).run()
    changed = CountingCollector([with_attachment(text=FUTURE_TEXT + "\n장소 변경 안내")])
    stats = Pipeline(settings, repo, extractor, [changed]).run()
    assert stats.ai_calls == 1 and changed.downloads == 1


def test_collector_defers_download(settings):
    """collect() itself must not touch the network for files."""
    settings.dooray_token = "x"
    downloaded = []

    class Client:
        def list_posts(self, project_id, page=0, size=100):
            return [DOORAY_POST] if page == 0 else []

        def get_post(self, project_id, post_id):
            return DOORAY_POST

        def list_post_files(self, project_id, post_id):
            return []

        def download_post_file(self, project_id, post_id, file_id, max_bytes):
            downloaded.append(file_id)
            return PNG, "image/png"

    collector = DoorayCollector(settings, client=Client())
    items = collector.collect()
    assert len(items) == 1 and items[0].attachments
    assert downloaded == [], "collect() must not download"
    items[0].load_attachments()
    assert downloaded == [items[0].attachments[0].external_file_id]
    items[0].load_attachments()
    assert len(downloaded) == 1, "load_attachments is idempotent"


def test_attachment_failure_does_not_stop_pipeline(settings):
    settings.dooray_token = "x"

    class Client:
        def list_post_files(self, project_id, post_id):
            return []

        def download_post_file(self, project_id, post_id, file_id, max_bytes):
            raise AttachmentError("request", status=404, redirected=False)

    item = with_attachment()
    collector = DoorayCollector(settings, client=Client())
    item.attachment_loader = lambda: collector.download_attachments(POST, item)

    repo = MemoryRepository()
    stats = Pipeline(settings, repo, FakeExtractor(future_extraction), [ListCollector([item])]).run()
    assert stats.events_created == 1, "a failed poster must not lose the event"
    assert item.attachments[0].parse_status == "failed"
    assert repo.attachments[(list(repo.raw_items)[0], FILE)]["parse_status"] == "failed"


def test_prompt_version_change_invalidates_cache(settings):
    """A reworded prompt must re-parse stored items instead of reusing old extractions."""
    from ggongbab.config import PROMPT_VERSION

    repo = MemoryRepository()
    extractor = FakeExtractor(future_extraction)
    Pipeline(settings, repo, extractor, [ListCollector([_item()])]).run()
    raw_id = list(repo.raw_items)[0]
    content_hash = repo.raw_items[raw_id]["content_hash"]
    assert repo.cached_parse(raw_id, content_hash, PROMPT_VERSION) is not None
    assert repo.cached_parse(raw_id, content_hash, "ggongbab-extract-v0") is None


def test_reparse_of_single_source_event_applies_corrections(settings):
    """The live run stored eligibility='참석자'; a re-parse must be able to clear it."""
    repo = MemoryRepository()

    def with_eligibility(text):
        return future_extraction(text).model_copy(update={"eligibility": "참석자"})

    Pipeline(settings, repo, FakeExtractor(with_eligibility), [ListCollector([_item()])]).run()
    event = next(iter(repo.events.values()))
    assert event["eligibility"] is None, "validator should already drop attendee-words"

    # Force a stale value as the old validator would have stored it, then re-parse.
    event["eligibility"] = "참석자"
    repo.ai_runs.clear()
    stats = Pipeline(settings, repo, FakeExtractor(future_extraction), [ListCollector([_item()])]).run()
    assert stats.events_updated == 1
    assert next(iter(repo.events.values()))["eligibility"] is None
