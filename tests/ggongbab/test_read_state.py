from contextlib import contextmanager
from types import SimpleNamespace

import pytest

import dooray_web_agent as agent
from ggongbab.web.calibrate import detect_read_key
from ggongbab.web.mail_reader import MailHeader, _from_json_rows, _apply_read_state
from ggongbab.web.read_state import inspect_read_schema, crosscheck_dom
from ggongbab.web.ui_contract import UiContract


def rows(values):
    return [{"id": str(i), "subject": "private subject", "createdAt": "2026-09-19",
             "annotations": {"read": value}} for i, value in enumerate(values)]


@pytest.mark.parametrize("state", ["read", "unread"])
def test_missing_contract_read_state_exits20_before_any_side_effect(monkeypatch, state):
    monkeypatch.setattr(agent, "load_contract", lambda _: UiContract(verified=True, list_api="https://x/mails"))
    beats = []
    monkeypatch.setattr(agent, "emit_heartbeat", lambda code, *, published: beats.append((code, published)))
    def forbidden(*a, **kw):
        pytest.fail("must stop before browser, body, or writer")
    for name in ("open_session", "TaskWriter", "open_body"):
        monkeypatch.setattr(agent, name, forbidden)
    monkeypatch.setattr("sys.argv", ["agent", "--run", "--read-state", state])
    assert agent.main() == 20
    assert beats == [(20, False)]


def setup_run(monkeypatch, headers, key=""):
    c = UiContract(verified=True, list_api="https://x/mails", read_state_key=key)
    monkeypatch.setattr(agent, "load_contract", lambda _: c)
    monkeypatch.setattr(agent, "load_settings", lambda: None)
    monkeypatch.setattr(agent.AgentState, "load", lambda path: agent.AgentState(path=path))
    monkeypatch.setattr(agent, "select_mail_page", lambda *_: None)
    monkeypatch.setattr(agent, "list_mails", lambda *a, **kw: headers)
    monkeypatch.setattr(agent, "classify", lambda *_: SimpleNamespace(candidate=True))
    writes = []
    class Writer:
        def __init__(self, *a, **kw): pass
        def verify_project(self): pass
        def create_task(self, payload, dry_run):
            assert dry_run
            writes.append("dry-run")
    monkeypatch.setattr(agent, "TaskWriter", Writer)
    @contextmanager
    def session(*a, **kw):
        yield SimpleNamespace(context=None, assert_authenticated=lambda: None)
    monkeypatch.setattr(agent, "open_session", session)
    monkeypatch.setattr(agent, "open_body", lambda *a, **kw: pytest.fail("body opened"))
    return writes


def test_subject_only_dry_run_without_read_field_is_allowed(monkeypatch):
    writes = setup_run(monkeypatch, [MailHeader(mail_id="1", subject="private")])
    monkeypatch.setattr("sys.argv", ["agent", "--run", "--subject-only", "--dry-run"])
    assert agent.main() == 0
    assert writes == ["dry-run"]


def test_runtime_missing_state_rejects_entire_batch_before_body_or_write(monkeypatch):
    writes = setup_run(monkeypatch, [MailHeader(mail_id="1", subject="private", unread=False),
                                    MailHeader(mail_id="2", subject="private", unread=None)], "annotations.read")
    monkeypatch.setattr("sys.argv", ["agent", "--run", "--read-state", "read", "--dry-run"])
    assert agent.main() == 20
    assert writes == []


@pytest.mark.parametrize("values,expected", [([True, False], [False, True]),
    (["true", "false"], [False, True]), (["Y", "N"], [False, True]),
    (["read", "unread"], [False, True]), ([None, "maybe"], [None, None])])
def test_nested_path_strict_extraction(values, expected):
    assert [h.unread for h in _from_json_rows(rows(values), "annotations.read")] == expected


def test_nested_field_validated_and_contract_roundtrips(tmp_path):
    key = detect_read_key(rows([True, False] * 3))
    assert key == "annotations.read"
    c = UiContract(read_state_key=key)
    path = tmp_path / "contract.json"
    c.save(path)
    assert UiContract.load(path).read_state_key == key


@pytest.mark.parametrize("case", ["ambiguous", "missing", "wrong_type", "too_few", "array", "unrelated"])
def test_invalid_nested_candidates_rejected(case):
    data = rows([True] * 6)
    if case == "ambiguous":
        for row in data: row["read"] = True
    elif case == "missing": data[0]["annotations"] = {}
    elif case == "wrong_type": data[0]["annotations"]["read"] = {"value": True}
    elif case == "too_few": data = data[:1]
    elif case == "array":
        for row in data: row["annotations"] = [row["annotations"]]
    else:
        for row in data: row["annotations"] = {"flagged": True}
    assert detect_read_key(data) == ""


def test_schema_diagnostics_never_contain_values_or_dynamic_keys():
    data = rows([True] * 5)
    for row in data:
        row["users"] = [{"private@example.com": {"token": "secret-token", "name": "Secret Name"}}]
    schema, candidates, key = inspect_read_schema(data)
    text = repr((schema, candidates))
    for secret in ("private@example.com", "secret-token", "Secret Name", "private subject"):
        assert secret not in text
    assert schema["annotations.read"] == ["bool"]
    assert key == "annotations.read"


def test_read_state_alignment_ignores_unparseable_rows():
    data = [{"annotations": {"read": True}}] + rows([False])
    headers = _from_json_rows(data)
    _apply_read_state(data, headers, "annotations.read")
    assert len(headers) == 1 and headers[0].unread is True


@pytest.mark.parametrize("key", ["", "mailSummary.flags.read"])
def test_calibration_instructions_follow_available_read_field(key):
    lines = []
    agent.log_calibration_next(UiContract(read_state_key=key), cdp=True, log=lines.append)
    text = "\n".join(lines)
    assert ("--read-state read" in text) == bool(key)
    assert ("--subject-only" in text) == (not key)
    assert "--dry-run" in text and "--cdp" in text


def test_dom_crosscheck_counts_only_and_requires_unique_ids():
    data = rows([True] * 6)
    frame = SimpleNamespace(evaluate=lambda _: [{"id": str(i), "unread": False} for i in range(6)])
    assert crosscheck_dom(frame, data, "annotations.read") == {"matched": 6, "agreement": 6, "verified": True}
    frame.evaluate = lambda _: [{"id": "0", "unread": False}, {"id": "0", "unread": False}]
    assert crosscheck_dom(frame, data, "annotations.read")["matched"] == 0


def test_nested_unread_boolean_keeps_its_polarity():
    data = [{"id": "1", "subject": "private", "annotations": {"isUnread": False}}]
    assert _from_json_rows(data, "annotations.isUnread")[0].unread is False


def test_dom_disagreement_rejects_api_read_field(monkeypatch):
    from ggongbab.web import calibrate as calibration
    data = rows([True] * 6)
    monkeypatch.setattr(calibration, "fetch_rows", lambda *a: (data, _from_json_rows(data)))
    frame = SimpleNamespace(evaluate=lambda _: [{"id": str(i), "unread": True} for i in range(6)])
    result = calibration.smoke_test(None, "https://x/mails", dom_frame=frame)
    assert result.ok and result.read_key == ""
    assert result.dom_check == {"matched": 6, "agreement": 0, "verified": False}


def test_calibration_persists_nested_path_from_validated_rows(monkeypatch):
    from ggongbab.web import calibrate as calibration
    data = rows([True, False] * 3)
    monkeypatch.setattr(calibration, "fetch_rows", lambda *a: (data, _from_json_rows(data)))
    observer = SimpleNamespace(calls={"list": {"rawUrl": "https://x/mails",
        "shape": {"kind": "rows", "rowCount": 6, "rowKeys": ["id", "subject", "createdAt"]}}})
    c = UiContract()
    calibration.calibrate(None, observer, c, log=lambda *_: None)
    assert c.verified and c.read_state_key == "annotations.read"
