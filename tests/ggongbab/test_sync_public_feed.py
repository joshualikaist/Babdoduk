"""scripts/sync_public_feed.py: the projection step the refresh workflow runs after it has published
the snapshot. Synthetic repositories only; never a live service."""
from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest

import sync_public_feed as step
from ggongbab.config import KST
from ggongbab.db.repository import MemoryRepository
from ggongbab.exporter import build_payload

NOW = datetime(2026, 10, 13, 9, tzinfo=KST)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("LIVE_NETWORK_FORBIDDEN")
    monkeypatch.setattr("urllib.request.urlopen", forbidden)
    monkeypatch.setattr("requests.sessions.Session.send", forbidden)


def event(number=1, **overrides):
    return {
        "id": str(UUID(int=number)), "title": "Campus lunch seminar", "summary": "Lunch provided",
        "event_start": (NOW + timedelta(days=number)).isoformat(), "event_end": None,
        "status": "published", "needs_review": False, "confidence": 0.9,
        "food_provided": "true", "food_type": "lunchbox", "location_name": "N1",
        "_sources": [{"type": "dooray", "name": "PRIVATE_NAME", "url": "https://kaist.dooray.com/task/PRIVATE"}],
        **overrides,
    }


class Repo(MemoryRepository):
    def __init__(self, rows):
        super().__init__()
        self.events = {row["id"]: deepcopy(row) for row in rows}

    def publishable_events(self):
        return deepcopy(list(self.events.values()))


def test_the_projection_holds_exactly_what_the_snapshot_publishes(settings, capsys):
    rows = [event(1), event(2, needs_review=True), event(3, food_provided="false"),
            event(4, event_start=(NOW - timedelta(days=3)).isoformat())]
    repo = Repo(rows)
    assert step.main(settings=settings, repo=repo, now=NOW) == 0
    snapshot = build_payload(rows, settings, NOW, food_only=True)
    assert set(repo.public_events) == {e["id"] for e in snapshot["events"]} == {rows[0]["id"]}
    assert repo.public_feed_generation() == 1
    out = capsys.readouterr().out
    assert out.strip() == "public feed synchronized events=1"
    assert "PRIVATE" not in str(repo.public_events) and "dooray.com" not in str(repo.public_events)


def test_an_ended_event_leaves_the_projection_on_the_next_run(settings):
    repo = Repo([event(1)])
    step.main(settings=settings, repo=repo, now=NOW)
    later = NOW + timedelta(days=5)
    assert step.main(settings=settings, repo=repo, now=later) == 0
    assert repo.public_events == {} and repo.public_feed_generation() == 2


def test_a_failed_replacement_is_a_red_exit_and_the_old_generation_stays(settings, capsys):
    class Broken(Repo):
        def replace_public_feed(self, generation, rows):
            raise RuntimeError("rpc refused: https://secret.example/x")
    repo = Broken([event(1)])
    assert step.main(settings=settings, repo=repo, now=NOW) == step.EXIT_SYNC
    out = capsys.readouterr().out
    assert "PUBLIC_FEED_SYNC_FAILED" in out and "secret.example" not in out
    assert repo.public_feed_generation() == 0


def test_without_backend_configuration_nothing_is_touched(capsys):
    assert step.main(settings=SimpleNamespace(has_supabase=False)) == step.EXIT_SUPABASE
    assert "missing" in capsys.readouterr().out
