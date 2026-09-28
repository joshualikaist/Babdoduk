# -*- coding: utf-8 -*-
"""Option A trigger: debounced, main-only workflow_dispatch; fakes only, no network or credential store."""
from __future__ import annotations

import json
import urllib.error

import pytest

from ggongbab import dispatch

T0 = 1_790_570_000.0          # a fixed clock
TOKEN = "github_pat_" + "S" * 60


class FakeResponse:
    def __init__(self, status=204):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class Opener:
    def __init__(self, status=204, error=None):
        self.status, self.error, self.requests = status, error, []

    def __call__(self, request, timeout=None):
        self.requests.append({"url": request.full_url, "method": request.get_method(),
                              "body": json.loads(request.data.decode("utf-8")),
                              "auth": request.get_header("Authorization")})
        if self.error:
            raise self.error
        if self.status >= 400:
            raise urllib.error.HTTPError(request.full_url, self.status, "x", {}, None)
        return FakeResponse(self.status)


def call(tmp_path, opener, *, new=True, now=T0, token=TOKEN, source="radar"):
    return dispatch.request_refresh(tmp_path / "dispatch-state.json", new_candidates=new, source=source, now=now,
                                    token_provider=lambda: token, opener=opener)


def test_one_new_candidate_dispatches_the_cloud_refresh_on_main(tmp_path):
    opener = Opener()
    assert call(tmp_path, opener) == dispatch.DISPATCHED
    [req] = opener.requests
    assert req["method"] == "POST"
    assert req["url"] == "https://api.github.com/repos/joshualikaist/Babdoduk/actions/workflows/ggongbab-refresh.yml/dispatches"
    assert req["body"] == {"ref": "main", "inputs": {"mode": "full", "source": "radar"}}
    assert req["auth"] == f"Bearer {TOKEN}"


def test_the_token_never_reaches_state_or_result(tmp_path):
    code = call(tmp_path, Opener())
    assert TOKEN not in code
    assert TOKEN not in (tmp_path / "dispatch-state.json").read_text(encoding="utf-8")


def test_without_a_stored_token_nothing_is_sent(tmp_path):
    opener = Opener()
    assert call(tmp_path, opener, token=None) == dispatch.NOT_CONFIGURED
    assert opener.requests == []


def test_nothing_new_sends_nothing(tmp_path):
    opener = Opener()
    assert call(tmp_path, opener, new=False) == dispatch.NOTHING_NEW
    assert opener.requests == []


def test_a_second_candidate_inside_the_window_waits_and_the_next_cycle_sends_it(tmp_path):
    opener = Opener()
    assert call(tmp_path, opener, now=T0) == dispatch.DISPATCHED
    assert call(tmp_path, opener, now=T0 + 120) == dispatch.DEBOUNCED
    assert call(tmp_path, opener, new=False, now=T0 + 200) == dispatch.DEBOUNCED   # still pending
    assert call(tmp_path, opener, new=False, now=T0 + 301) == dispatch.DISPATCHED  # pending, window over
    assert call(tmp_path, opener, new=False, now=T0 + 700) == dispatch.NOTHING_NEW
    assert len(opener.requests) == 2


def test_daily_cap(tmp_path):
    opener = Opener()
    for i in range(dispatch.DAILY_CAP):
        assert call(tmp_path, opener, now=T0 + i * 301) == dispatch.DISPATCHED
    assert call(tmp_path, opener, now=T0 + dispatch.DAILY_CAP * 301) == dispatch.DAILY_LIMIT
    assert len(opener.requests) == dispatch.DAILY_CAP


@pytest.mark.parametrize("status,code", [(401, dispatch.AUTH_FAILED), (403, dispatch.AUTH_FAILED),
                                         (404, dispatch.REJECTED), (422, dispatch.REJECTED)])
def test_refusals_are_reported_and_stay_pending(tmp_path, status, code):
    opener = Opener(status=status)
    assert call(tmp_path, opener) == code
    state = dispatch.DispatchState.load(tmp_path / "dispatch-state.json")
    assert state.pending and state.last_result == code and state.count == 0


def test_a_network_failure_is_retried_on_the_next_cycle(tmp_path):
    assert call(tmp_path, Opener(error=urllib.error.URLError("down"))) == dispatch.TRANSPORT_FAILED
    assert call(tmp_path, Opener(), new=False, now=T0 + 60) == dispatch.DISPATCHED


def test_the_ref_is_not_a_parameter_and_unknown_sources_are_refused(tmp_path):
    import inspect

    assert "ref" not in inspect.signature(dispatch.request_refresh).parameters
    with pytest.raises(ValueError):
        call(tmp_path, Opener(), source="anything")


def test_the_mailbox_agent_refuses_two_writers():
    import dooray_web_agent as agent
    from ggongbab.web.exit_codes import UiContractError

    args = agent.build_parser().parse_args(["--run", "--dispatch-refresh", "--run-pipeline"])
    with pytest.raises(UiContractError):
        agent.cmd_run(args)
