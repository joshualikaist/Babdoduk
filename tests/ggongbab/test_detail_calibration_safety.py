"""Synthetic request spies: calibration must never open unread/unknown mail."""
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from ggongbab.web.calibrate import calibrate, discover_detail_api
from ggongbab.web.ui_contract import UiContract


READ_KEY = "annotations.read"
LIST_URL = "https://mail.invalid/mails?page=0"
DETAIL_API = "https://mail.invalid/PRIVATE-TENANT/mails/{id}?render=PRIVATE-RENDER"
BODY = "PRIVATE-BODY " * 10
MISSING = object()


def synthetic_mailbox(states):
    rows = [{"id": f"PRIVATE-ID-{i}", "subject": f"PRIVATE-SUBJECT-{i}",
             "createdAt": "2026-09-19", "annotations": {} if state is MISSING else {"read": state}}
            for i, state in enumerate(states)]
    observer = SimpleNamespace(calls={
        "list": {"rawUrl": LIST_URL, "shape": {"kind": "rows", "rowCount": len(rows),
                                                  "rowKeys": list(rows[0])}},
        **{row["id"]: {"rawUrl": DETAIL_API.format(id=row["id"]),
                       "shape": {"kind": "object"}} for row in rows},
    })

    def respond(url, timeout):
        assert timeout == 30_000
        if url == LIST_URL:
            payload = {"contents": rows}
        else:
            assert url in [DETAIL_API.format(id=row["id"]) for row in rows]
            payload = {"result": {"body": BODY}}
        return SimpleNamespace(status=200, json=lambda: payload)

    page = SimpleNamespace(request=SimpleNamespace(get=Mock(side_effect=respond)))
    return rows, observer, page


def assert_private_values_absent(lines, rows):
    output = "\n".join(lines)
    for secret in (BODY, "PRIVATE-TENANT", "PRIVATE-RENDER", "PRIVATE-UNKNOWN",
                   *(row["id"] for row in rows), *(row["subject"] for row in rows)):
        assert secret not in output


@pytest.mark.parametrize("key,states", [
    ("", [True, True]),
    (READ_KEY, [False, False]),
    (READ_KEY, [None, "PRIVATE-UNKNOWN", MISSING, 1, {}]),
    (READ_KEY, [True, False]),
    (READ_KEY, [True, None]),
])
def test_detail_calibration_skips_before_any_request(key, states):
    rows, observer, page = synthetic_mailbox(states)
    lines = []
    assert discover_detail_api(page, rows, observer, log=lines.append,
                               read_state_key=key) == ("", "")
    page.request.get.assert_not_called()
    assert lines == ["detail calibration skipped: no verified read-state field" if not key else
                     "detail calibration skipped: fewer than two explicitly read mails"]
    assert_private_values_absent(lines, rows)


@pytest.mark.parametrize("key,states", [
    (READ_KEY, [False, None, True, "PRIVATE-UNKNOWN", True, True]),
    ("annotations.isUnread", [True, None, False, "PRIVATE-UNKNOWN", False, False]),
])
def test_detail_calibration_requests_only_first_two_explicitly_read_rows(key, states):
    rows, observer, page = synthetic_mailbox(states)
    if key != READ_KEY:
        for row in rows:
            row["annotations"] = {"isUnread": row["annotations"]["read"]}
    lines = []
    assert discover_detail_api(page, rows, observer, log=lines.append,
                               read_state_key=key) == (DETAIL_API, "result.body")
    assert page.request.get.call_args_list == [
        call(DETAIL_API.format(id=rows[i]["id"]), timeout=30_000) for i in (2, 4)
    ]
    assert_private_values_absent(lines, rows)


@pytest.mark.parametrize("states,expected_key,read_indices", [
    ([MISSING] * 5, "", []),
    ([False] * 5, READ_KEY, []),
    ([None] * 5, "", []),
    ([True, False, False, False, False], READ_KEY, []),
    ([False, True, False, True, False], READ_KEY, [1, 3]),
])
def test_list_calibration_passes_but_only_verified_read_rows_enable_detail(
        states, expected_key, read_indices):
    rows, observer, page = synthetic_mailbox(states)
    contract = UiContract(verified=True, read_state_key="stale.read",
                          detail_api="https://old.invalid/{id}", detail_body_path="stale.body")
    lines = []
    summary = calibrate(page, observer, contract, log=lines.append)
    assert summary["smoke"].ok and contract.verified
    assert contract.list_api == LIST_URL
    assert contract.read_state_key == expected_key
    assert page.request.get.call_args_list == [call(LIST_URL, timeout=30_000)] * 2 + [
        call(DETAIL_API.format(id=rows[i]["id"]), timeout=30_000) for i in read_indices
    ]
    assert contract.detail_api == (DETAIL_API if read_indices else "")
    assert contract.detail_body_path == ("result.body" if read_indices else "")
    assert (summary["detailApi"] is not None) == bool(read_indices)
    assert_private_values_absent(lines, rows)
