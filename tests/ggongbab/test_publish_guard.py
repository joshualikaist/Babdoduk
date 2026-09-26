# -*- coding: utf-8 -*-
"""The generated-data publisher commits a ggongbab feed only when its content changed.

Every export stamps a new generatedAt. Without the guard, each 30-minute run would
commit and push to lab and main (two deployments each) even when no event changed.
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

import publish_generated

FEED_PATH = "data/ggongbab/latest.json"
MESSAGE = "ggongbab: event feed refresh"
EVENT_A = {"id": "evt-a", "title": "Lunch seminar", "start": "2026-09-29T12:00:00+09:00", "food": "lunch box"}
EVENT_B = {"id": "evt-b", "title": "Evening talk", "start": "2026-09-30T18:00:00+09:00", "food": "pizza"}
FEED = {"generatedAt": "2026-09-25T10:00:00+09:00", "timezone": "Asia/Seoul", "count": 2,
        "events": [EVENT_A, EVENT_B]}
MANUAL = '{"events": []}\n'


def _dump(payload) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _feed(**changes) -> dict:
    payload = copy.deepcopy(FEED)
    payload.update(changes)
    return payload


def _meaningful(old: dict, new: dict, path: str = FEED_PATH) -> list[str]:
    return publish_generated.meaningful_changes([path], lambda p: _dump(old), lambda p: _dump(new))


# ---------------------------------------------------------------------------
# The comparison
# ---------------------------------------------------------------------------
def test_only_generated_at_differs_is_not_a_change():
    assert _meaningful(FEED, _feed(generatedAt="2026-09-25T10:30:00+09:00")) == []


def test_comparison_is_semantic_not_textual():
    old = _dump(FEED)
    new = json.dumps(dict(reversed(list(_feed(generatedAt="2026-09-25T11:00:00+09:00").items()))))
    assert publish_generated.meaningful_changes([FEED_PATH], lambda p: old, lambda p: new) == []


def test_a_changed_event_is_a_change():
    changed = dict(EVENT_B, start="2026-09-30T19:00:00+09:00")
    assert _meaningful(FEED, _feed(generatedAt="later", events=[EVENT_A, changed])) == [FEED_PATH]


def test_a_removed_event_is_a_change():
    assert _meaningful(FEED, _feed(generatedAt="later", count=1, events=[EVENT_A])) == [FEED_PATH]


def test_an_added_event_is_a_change():
    extra = dict(EVENT_A, id="evt-c", start="2026-10-01T12:00:00+09:00")
    assert _meaningful(FEED, _feed(generatedAt="later", count=3, events=[EVENT_A, EVENT_B, extra])) == [FEED_PATH]


def test_new_missing_or_unreadable_files_always_count():
    fp = [FEED_PATH]
    assert publish_generated.meaningful_changes(fp, lambda p: None, lambda p: _dump(FEED)) == fp
    assert publish_generated.meaningful_changes(fp, lambda p: _dump(FEED), lambda p: None) == fp
    assert publish_generated.meaningful_changes(fp, lambda p: _dump(FEED), lambda p: "{not json") == fp


def test_other_generated_paths_keep_committing_on_any_change():
    """Only the ggongbab feed and its archive are guarded; magazine and menu publishing are unchanged."""
    for path in ("data/magazine/latest.json", "data/kaist-menu/latest.json"):
        assert _meaningful(FEED, _feed(generatedAt="later"), path) == [path]
    assert set(publish_generated.VOLATILE_KEYS) == {FEED_PATH, ARCHIVE_PATH}
    assert publish_generated.VOLATILE_KEYS[FEED_PATH] == {"generatedAt"}
    assert publish_generated.VOLATILE_KEYS[ARCHIVE_PATH] == {"generatedAt"}


# ---------------------------------------------------------------------------
# Past listings (archive/index.json) follow the same rule
# ---------------------------------------------------------------------------
ARCHIVE_PATH = "data/ggongbab/archive/index.json"
ARCHIVE = {"generatedAt": "2026-09-25T10:00:00+09:00", "timezone": "Asia/Seoul", "windowDays": 30,
           "count": 1, "events": [dict(EVENT_A, id="evt-past", start="2026-09-20T12:00:00+09:00")]}


def _archive(**changes) -> dict:
    payload = copy.deepcopy(ARCHIVE)
    payload.update(changes)
    return payload


def test_an_archive_that_differs_only_in_generated_at_is_not_a_change():
    assert _meaningful(ARCHIVE, _archive(generatedAt="2026-09-25T10:30:00+09:00"), ARCHIVE_PATH) == []


def test_an_archived_or_aged_out_listing_is_a_change():
    added = _archive(generatedAt="later", count=2, events=ARCHIVE["events"] + [dict(EVENT_B, id="evt-old")])
    assert _meaningful(ARCHIVE, added, ARCHIVE_PATH) == [ARCHIVE_PATH]
    assert _meaningful(ARCHIVE, _archive(generatedAt="later", count=0, events=[]), ARCHIVE_PATH) == [ARCHIVE_PATH]


def test_the_first_archive_file_always_counts():
    ap = [ARCHIVE_PATH]
    assert publish_generated.meaningful_changes(ap, lambda p: None, lambda p: _dump(ARCHIVE)) == ap


# ---------------------------------------------------------------------------
# What may be published
# ---------------------------------------------------------------------------
def test_manual_json_is_never_copied_or_deleted(tmp_path):
    src, dest = tmp_path / "src", tmp_path / "dest"
    (src / "data/ggongbab/.staging").mkdir(parents=True)
    (src / "data/ggongbab/latest.json").write_text(_dump(FEED), encoding="utf-8")
    (src / "data/ggongbab/manual.json").write_text('{"events": ["from the runner"]}\n', encoding="utf-8")
    (src / "data/ggongbab/.staging/latest.json").write_text("{}", encoding="utf-8")
    (dest / "data/ggongbab").mkdir(parents=True)
    (dest / "data/ggongbab/manual.json").write_text(MANUAL, encoding="utf-8")
    (dest / "data/ggongbab/stale.json").write_text("{}", encoding="utf-8")

    publish_generated.copy_allowed(src, dest, ["data/ggongbab"])

    assert (dest / "data/ggongbab/manual.json").read_text(encoding="utf-8") == MANUAL
    assert (dest / FEED_PATH).read_text(encoding="utf-8") == _dump(FEED)
    assert not (dest / "data/ggongbab/stale.json").exists()
    assert not (dest / "data/ggongbab/.staging").exists()


@pytest.mark.parametrize("path", ["data", "js", "data/ggongbab/../../js", "supabase", ".github/workflows"])
def test_paths_outside_the_generated_allowlist_are_refused(monkeypatch, path):
    monkeypatch.setattr(sys, "argv", ["publish_generated.py", "--paths", path, "--message", MESSAGE])
    with pytest.raises(SystemExit, match="refusing path"):
        publish_generated.main()


# ---------------------------------------------------------------------------
# End to end against a local origin: does anything get committed and pushed?
# ---------------------------------------------------------------------------
def _git(cwd, *args) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True, encoding="utf-8").stdout.strip()


@pytest.fixture
def origin(tmp_path, monkeypatch):
    """A bare origin with lab and main, and a clone standing in for the Actions checkout."""
    config = tmp_path / "gitconfig"
    config.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    bare, seed, checkout = tmp_path / "origin.git", tmp_path / "seed", tmp_path / "checkout"
    _git(tmp_path, "init", "-q", "--bare", str(bare))
    _git(tmp_path, "clone", "-q", str(bare), str(seed))
    (seed / "data/ggongbab").mkdir(parents=True)
    (seed / FEED_PATH).write_text(_dump(FEED), encoding="utf-8")
    (seed / "data/ggongbab/manual.json").write_text(MANUAL, encoding="utf-8")
    (seed / "app.js").write_text("// feature code\n", encoding="utf-8")
    _git(seed, "checkout", "-q", "-b", "main")
    _git(seed, "add", "-A")
    _git(seed, "-c", "user.name=seed", "-c", "user.email=seed@example.invalid", "commit", "-q", "-m", "seed")
    _git(seed, "push", "-q", "origin", "main", "main:lab")
    _git(tmp_path, "clone", "-q", str(bare), str(checkout))
    monkeypatch.setattr(publish_generated, "ROOT", checkout)
    return bare


def _artifact(tmp_path, payload) -> Path:
    artifact = tmp_path / "artifact"
    (artifact / "data/ggongbab").mkdir(parents=True, exist_ok=True)
    (artifact / FEED_PATH).write_text(_dump(payload), encoding="utf-8")
    (artifact / "data/ggongbab/manual.json").write_text('{"events": ["runner copy"]}\n', encoding="utf-8")
    return artifact


@pytest.mark.parametrize("branch", ["lab", "main"])
def test_generated_at_only_run_neither_commits_nor_pushes(origin, tmp_path, capsys, branch):
    before = _git(origin, "rev-parse", branch)
    artifact = _artifact(tmp_path, _feed(generatedAt="2026-09-25T10:30:00+09:00"))

    publish_generated.update_branch(branch, artifact, ["data/ggongbab"], MESSAGE)

    assert _git(origin, "rev-parse", branch) == before
    assert f"{branch}: no meaningful feed change" in capsys.readouterr().out


@pytest.mark.parametrize("branch", ["lab", "main"])
def test_real_change_commits_only_the_feed(origin, tmp_path, capsys, branch):
    before = _git(origin, "rev-parse", branch)
    artifact = _artifact(tmp_path, _feed(generatedAt="later", count=1, events=[EVENT_A]))

    publish_generated.update_branch(branch, artifact, ["data/ggongbab"], MESSAGE)

    after = _git(origin, "rev-parse", branch)
    assert after != before and _git(origin, "rev-parse", f"{after}^") == before
    assert _git(origin, "log", "-1", "--format=%an|%s", after) == f"babdoduk-content-bot|{MESSAGE}"
    assert _git(origin, "diff", "--name-only", before, after).splitlines() == [FEED_PATH]
    assert _git(origin, "show", f"{after}:data/ggongbab/manual.json") + "\n" == MANUAL
    assert f"{branch}: pushed generated data" in capsys.readouterr().out


def _artifact_with_archive(tmp_path, feed, archive) -> Path:
    artifact = _artifact(tmp_path, feed)
    (artifact / ARCHIVE_PATH).parent.mkdir(parents=True, exist_ok=True)
    (artifact / ARCHIVE_PATH).write_text(_dump(archive), encoding="utf-8")
    return artifact


@pytest.mark.parametrize("branch", ["lab", "main"])
def test_archive_publishes_once_then_generated_at_only_runs_stay_quiet(origin, tmp_path, capsys, branch):
    before = _git(origin, "rev-parse", branch)
    publish_generated.update_branch(branch, _artifact_with_archive(tmp_path / "1", FEED, ARCHIVE), ["data/ggongbab"], MESSAGE)
    first = _git(origin, "rev-parse", branch)
    assert first != before
    assert _git(origin, "diff", "--name-only", before, first).splitlines() == [ARCHIVE_PATH]

    quiet = _artifact_with_archive(tmp_path / "2", _feed(generatedAt="later"), _archive(generatedAt="later"))
    publish_generated.update_branch(branch, quiet, ["data/ggongbab"], MESSAGE)
    assert _git(origin, "rev-parse", branch) == first
    assert f"{branch}: no meaningful feed change" in capsys.readouterr().out

    aged_out = _artifact_with_archive(tmp_path / "3", _feed(generatedAt="later"), _archive(generatedAt="later", count=0, events=[]))
    publish_generated.update_branch(branch, aged_out, ["data/ggongbab"], MESSAGE)
    last = _git(origin, "rev-parse", branch)
    assert last != first
    assert sorted(_git(origin, "diff", "--name-only", first, last).splitlines()) == sorted([ARCHIVE_PATH, FEED_PATH])
