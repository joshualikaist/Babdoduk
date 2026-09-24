# -*- coding: utf-8 -*-
"""The ggongbab-refresh workflow: it parses, and only the publishing modes can publish.

GitHub rejected the whole file for months because one plain `run:` value held
"ggongbab: event feed refresh" (": " starts a YAML mapping). These tests read the
workflow as text, so they need no YAML library; GitHub stays the final parser.
"""
from __future__ import annotations

import re
from pathlib import Path

import publish_generated
import refresh_ggongbab

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
WORKFLOW = WORKFLOWS / "ggongbab-refresh.yml"

MODES = {"check", "dry-run", "review-report", "export-only", "full"}
PUBLISHING = {"export-only", "full"}
ORIGINAL_DEFECT = ('        run: python scripts/publish_generated.py --paths data/ggongbab'
                   ' --message "ggongbab: event feed refresh"')


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _steps(text: str) -> dict[str, str]:
    """Each step's block, keyed by its name (or `uses`), in file order."""
    starts = [m.start() for m in re.finditer(r"(?m)^\s*- (?:name|uses):", text)]
    blocks = [text[a:b] for a, b in zip(starts, starts[1:] + [len(text)])]
    return {re.match(r"\s*- (?:name|uses):\s*(.+)", b).group(1).strip(): b for b in blocks}


def _if(block: str) -> str:
    return re.search(r"(?m)^\s*if:\s*(.+)$", block).group(1)


def _plain_run_with_mapping_colon(line: str) -> bool:
    """A single-line, unquoted `run:` value that YAML would read as a nested mapping."""
    m = re.match(r"\s*(?:- )?run:[ \t]+(\S.*)$", line)
    if not m or m.group(1)[0] in "|>'\"":
        return False
    value = m.group(1).split(" #")[0].rstrip()
    return ": " in value or value.endswith(":")


def test_the_check_catches_the_original_defect():
    assert _plain_run_with_mapping_colon(ORIGINAL_DEFECT)
    assert not _plain_run_with_mapping_colon("        run: pip install -r requirements-ggongbab.txt")
    assert not _plain_run_with_mapping_colon("        run: |")


def test_no_workflow_has_a_plain_run_value_with_a_mapping_colon():
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            assert not _plain_run_with_mapping_colon(line), f"{path.name}:{n}: use a block scalar (run: |)"


def test_dispatch_offers_every_mode_and_defaults_to_the_harmless_one():
    text = _text()
    options = re.search(r"(?m)^\s*options:\s*\n((?:\s*- .+\n)+)", text).group(1)
    assert {line.strip()[2:].strip() for line in options.splitlines()} == MODES
    assert re.search(r"(?m)^\s*default:\s*check\s*$", text)
    source = Path(refresh_ggongbab.__file__).read_text(encoding="utf-8")
    for flag in ("--check", "--dry-run", "--review-report", "--export-only"):
        assert f'"{flag}"' in source, flag


def test_schedule_stays_off_until_the_manual_checks_pass():
    """Recovery: manual dispatch only. Re-enabling the cron is a separate commit."""
    code = "\n".join(line for line in _text().splitlines() if not line.lstrip().startswith("#"))
    assert "schedule:" not in code and "cron:" not in code


def test_each_mode_runs_its_own_runner_command():
    refresh = _steps(_text())["Refresh ggongbab"]
    for mode, flag in {"check": "--check", "dry-run": "--dry-run",
                       "review-report": "--review-report", "export-only": "--export-only"}.items():
        branch = re.search(rf"(?ms)^\s*{re.escape(mode)}\)(.*?);;", refresh).group(1)
        assert f"refresh_ggongbab.py {flag}" in branch, mode
    full = re.search(r"(?ms)^\s*full\)(.*?);;", refresh).group(1)
    assert full.strip().endswith("python scripts/refresh_ggongbab.py")
    unknown = re.search(r"(?ms)^\s*\*\)(.*?);;", refresh).group(1)
    assert "python" not in unknown


def test_only_export_only_and_full_can_set_publish():
    refresh = _steps(_text())["Refresh ggongbab"]
    assert refresh.count("publish=1") == 1
    guard = re.search(r'if \[ "\$MODE" != "export-only" \] && \[ "\$MODE" != "full" \]; then(.*?)fi',
                      refresh, re.S)
    assert guard, "diagnostic modes must leave before publish=1"
    assert "publish=0" in guard.group(1) and "exit" in guard.group(1)
    assert guard.start() < refresh.index("publish=1")


def test_validator_and_publisher_run_only_in_publishing_modes():
    steps = _steps(_text())
    for name in ("Validate generated JSON", "Publish generated data to lab and main"):
        cond = _if(steps[name])
        assert "steps.refresh.outputs.publish == '1'" in cond, name
        assert set(re.findall(r"env\.MODE == '([^']+)'", cond)) == PUBLISHING, name
    assert [name for name, block in steps.items() if "publish_generated.py" in block] == [
        "Publish generated data to lab and main"]


def test_publisher_is_limited_to_ggongbab_data():
    block = _steps(_text())["Publish generated data to lab and main"]
    command = re.search(r"python scripts/publish_generated\.py (.+)", block).group(1)
    paths = re.search(r"--paths((?:\s+[^-\s]\S*)+)", command).group(1).split()
    assert paths == ["data/ggongbab"] and command.count("--paths") == 1
    assert '--message "ggongbab: event feed refresh"' in command
    assert "data/ggongbab" in publish_generated.ALLOWED
    assert "manual.json" in publish_generated.SKIP_NAMES


def test_preflight_requires_what_each_mode_uses_and_sees_no_secret_value():
    steps = _steps(_text())
    names = list(steps)
    assert names.index("Check required configuration") < names.index("Refresh ggongbab")
    block = steps["Check required configuration"]
    need = {}
    for modes, groups in re.findall(r'(?m)^\s*([\w|-]+)\)\s*need="([^"]*)"', block):
        for mode in modes.split("|"):
            need[mode] = set(groups.split())
    everything = {"DOORAY", "SUPABASE", "OPENAI"}
    assert need == {"check": everything, "full": everything, "dry-run": {"DOORAY"},
                    "review-report": {"SUPABASE"}, "export-only": {"SUPABASE"}}
    expressions = re.findall(r"\$\{\{(.*?)\}\}", block)
    assert expressions
    for expr in expressions:
        assert re.fullmatch(r"\s*secrets\.\w+ != ''(\s*\|\|\s*secrets\.\w+ != '')*\s*", expr), expr


def test_review_report_log_keeps_the_count_and_drops_titles(capsys):
    """Actions logs of this repository are public; queued titles and reasons are not."""
    refresh = _steps(_text())["Refresh ggongbab"]
    branch = re.search(r"(?ms)^\s*review-report\)(.*?);;", refresh).group(1)
    assert re.search(r"refresh_ggongbab\.py --review-report\s*>", branch), "stdout must not reach the log"
    pattern = re.search(r"grep -E '([^']+)'", branch).group(1)

    class Repo:
        def __init__(self, rows):
            self.rows = rows

        def review_events(self):
            return self.rows

    row = {"status": "review", "event_start": "2026-09-26T15:00:00+09:00", "title": "PRIVATE TITLE",
           "id": "row-1", "confidence": 0.6, "food_provided": "unknown",
           "_sources": [{"type": "dooray"}], "review_reason": "PRIVATE REASON"}
    for rows, expected in (([row, row], "2 event(s) need review"), ([], "review queue empty")):
        refresh_ggongbab.review_report(Repo(rows))
        shown = [line for line in capsys.readouterr().out.splitlines() if re.search(pattern, line)]
        assert shown == [expected]


def test_content_jobs_share_one_serial_concurrency_group():
    for path in (WORKFLOW, WORKFLOWS / "magazine-daily.yml"):
        text = path.read_text(encoding="utf-8")
        assert re.search(r"(?m)^concurrency:\s*\n\s+group:\s*babdoduk-content-refresh\s*\n"
                         r"\s+cancel-in-progress:\s*false\s*$", text), path.name
