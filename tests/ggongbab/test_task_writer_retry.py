# -*- coding: utf-8 -*-
"""The task writer retries a GET that failed on the network, and never a write (2026-10-28).
Fakes only: urlopen is replaced, nothing leaves the machine."""
from __future__ import annotations

import io
import json
import urllib.error

import pytest

from ggongbab.web import task_writer as tw
from ggongbab.web.exit_codes import AgentError

KEY = "ab" * 32


class Answer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def ok(payload):
    return Answer(json.dumps({"header": {"isSuccessful": True}, **payload}).encode("utf-8"))


class Net:
    """Plays a script of answers per call: an exception instance is raised, anything else returned."""

    def __init__(self, *script):
        self.script, self.calls = list(script), []

    def __call__(self, request, timeout=None, context=None):
        self.calls.append((request.get_method(), request.full_url))
        step = self.script.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step


@pytest.fixture
def writer(settings, monkeypatch):
    settings.dooray_token = "SYNTHETIC"
    settings.dooray_project_id = "1"
    pauses = []
    w = tw.TaskWriter(settings, sleep=pauses.append)
    w.pauses = pauses
    return w


def test_a_get_that_times_out_is_tried_again_and_then_succeeds(writer, monkeypatch):
    net = Net(TimeoutError(), urllib.error.URLError("reset"), ok({"result": {"id": "7"}}))
    monkeypatch.setattr(tw.urllib.request, "urlopen", net)
    assert writer._request("GET", "/project/v1/projects/1/posts/7")["result"]["id"] == "7"
    assert len(net.calls) == 3 and writer.pauses == list(tw.GET_RETRY_PAUSES)


def test_a_get_that_keeps_failing_stops_after_three_attempts(writer, monkeypatch):
    net = Net(TimeoutError(), TimeoutError(), TimeoutError())
    monkeypatch.setattr(tw.urllib.request, "urlopen", net)
    with pytest.raises(AgentError, match="TimeoutError"):
        writer._request("GET", "/project/v1/projects/1/posts/7")
    assert len(net.calls) == 3


def test_a_write_is_never_repeated(writer, monkeypatch):
    """A POST that timed out may have created the task: create_task looks for it instead of posting twice."""
    net = Net(TimeoutError(), ok({}))
    monkeypatch.setattr(tw.urllib.request, "urlopen", net)
    with pytest.raises(AgentError, match="TimeoutError"):
        writer._request("POST", "/project/v1/projects/1/posts", {"subject": "x"})
    assert len(net.calls) == 1 and writer.pauses == []


def test_an_http_error_answer_is_not_retried(writer, monkeypatch):
    error = urllib.error.HTTPError("https://x", 404, "not found", {}, io.BytesIO(b'{"header":{}}'))
    net = Net(error, ok({}))
    monkeypatch.setattr(tw.urllib.request, "urlopen", net)
    with pytest.raises(AgentError, match="HTTP 404"):
        writer._request("GET", "/project/v1/projects/1/posts/9")
    assert len(net.calls) == 1 and writer.pauses == []


def test_the_duplicate_index_survives_one_slow_post(writer, monkeypatch):
    """The case of 10-28: one of the per-post reads timed out and the whole scan failed."""
    listing = ok({"result": [{"id": "1", "subject": "a"}, {"id": "2", "subject": "b"}]})
    net = Net(listing, ok({"result": {"id": "1", "body": {"content": "no marker"}}}),
              TimeoutError(), ok({"result": {"id": "2", "body": {"content": f"mail_key={KEY}"}}}))
    monkeypatch.setattr(tw.urllib.request, "urlopen", net)
    writer.settings.dooray_page_size = 100
    writer.settings.dooray_max_pages = 1
    assert writer._mail_task_index() == {f"mail_key={KEY}": "2"}
    assert writer.pauses == [tw.GET_RETRY_PAUSES[0]]
