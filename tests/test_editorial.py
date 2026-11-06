"""Synthetic publication and browser checks: no GitHub write, Vercel deploy or live account."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess

import pytest
from publish_editorial import digest, plan, validate_queue
from check_site_ui import ROOT, launch, new_context
from playwright.sync_api import sync_playwright
import publish_editorial as publisher

NOW = datetime(2026, 11, 6, 3, 0, tzinfo=timezone.utc)


def notice(id="synthetic-001", at="2026-11-06T12:00:00+09:00", status="scheduled"):
    return {"id": id, "kind": "notice", "status": status, "publishAt": at,
            "content": {"date": "2026-11-06", "title": {"ko": "검사", "en": "Test"}, "text": {"ko": "내용", "en": "Text"}}}


def test_due_boundary_kst_drafts_future_and_idempotence():
    queue = {"schemaVersion": 1, "items": [notice(), notice("future-001", "2026-11-06T12:01:00+09:00"), notice("draft-001", status="draft")]}
    validate_queue(queue)
    before = {"schemaVersion": 1, "notices": [], "activities": []}
    events, receipts, due = plan(queue, {"schemaVersion": 1, "items": []}, before, NOW)
    assert due == ["synthetic-001"] and events["notices"] == [notice()["content"]]
    assert before["notices"] == []
    assert plan(queue, receipts, events, NOW) == (events, receipts, [])
    changed = copy.deepcopy(queue); changed["items"][0]["content"]["text"]["en"] = "Changed"
    with pytest.raises(ValueError, match="published entry was changed"):
        plan(changed, receipts, events, NOW)


def test_cancelled_schedule_does_not_publish():
    queue = {"schemaVersion": 1, "items": [notice(status="draft", at=None)]}
    validate_queue(queue)
    events = {"schemaVersion": 1, "notices": [], "activities": []}
    assert plan(queue, {"schemaVersion": 1, "items": []}, events, NOW)[2] == []


def test_python_and_server_digests_agree_for_korean_and_markup():
    value = notice(); value["content"]["text"]["ko"] = "한글 <strong>강조</strong> & \"따옴표\""
    actual = subprocess.check_output(["node", "-e", "let s='';process.stdin.on('data',x=>s+=x);process.stdin.on('end',()=>process.stdout.write(require('./lib/editorial.cjs').digest(JSON.parse(s))));"],
                                     input=json.dumps(value, ensure_ascii=False), text=True, cwd=ROOT)
    assert actual == digest(value)


def test_server_security_contracts():
    subprocess.run(["node", "--test", "tests/editorial.test.cjs"], cwd=ROOT, check=True)


def test_real_git_publication_is_allowlisted_atomic_and_rejects_a_cancel_race(tmp_path, monkeypatch):
    """Exercise actual refs/worktrees in a disposable local bare repository; no network."""
    remote, repo = tmp_path / "remote.git", tmp_path / "repo"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "clone", str(remote), str(repo)], check=True, capture_output=True)
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()
    git("config", "user.name", "Synthetic"); git("config", "user.email", "synthetic@example.invalid")
    git("checkout", "-b", "main")
    (repo / "scripts").mkdir(); (repo / "lib").mkdir(); (repo / "inputs/editorial").mkdir(parents=True); (repo / "data/content").mkdir(parents=True)
    shutil.copy(ROOT / "lib/editorial.cjs", repo / "lib/editorial.cjs")
    # This fixture only exercises Git publication boundaries; production rendering/validation
    # and the browser are covered separately by the required repository gates.
    (repo / "scripts/validate_content.py").write_text("pass\n")
    (repo / "scripts/sync_site_chrome.py").write_text("from pathlib import Path\nPath('event.html').write_text(Path('data/content/events.json').read_text())\n")
    (repo / "data/content/events.json").write_text(json.dumps({"schemaVersion": 1, "notices": [], "activities": []}))
    (repo / "inputs/editorial/schedule.json").write_text(json.dumps({"schemaVersion": 1, "items": []}))
    (repo / "event.html").write_text("initial event page")
    git("add", "--", "scripts", "lib", "inputs", "data", "event.html"); git("commit", "-m", "Synthetic baseline"); git("push", "origin", "main")
    git("checkout", "-b", "lab")
    (repo / "lab-only.txt").write_text("must never reach main")
    key = "synthetic-queue-key-with-at-least-32-characters"; monkeypatch.setenv("EDITORIAL_QUEUE_KEY", key)
    encrypted = subprocess.check_output(["node", "-e", "let s='';process.stdin.on('data',x=>s+=x);process.stdin.on('end',()=>process.stdout.write(JSON.stringify(require('./lib/editorial.cjs').encodeQueue(JSON.parse(s),process.env.EDITORIAL_QUEUE_KEY))));"],
                                        input=json.dumps({"schemaVersion": 1, "items": [notice()]}), text=True, cwd=repo)
    (repo / "inputs/editorial/schedule.json").write_text(encrypted)
    git("add", "--", "lab-only.txt", "inputs/editorial/schedule.json"); git("commit", "-m", "Synthetic schedule"); git("push", "origin", "lab")
    monkeypatch.setattr(publisher, "ROOT", repo)
    original_git = publisher.git
    monkeypatch.setattr(publisher, "git", lambda *args, cwd=None: original_git(*args, cwd=cwd or repo))
    original_validate = publisher.validate_queue
    monkeypatch.setattr(publisher, "validate_queue", lambda data: original_validate(data, root=repo))
    state = tmp_path / "state.json"
    prepared = publisher.prepare(NOW, state)
    assert prepared["count"] == 1
    changed = set(git("diff", "--name-only", prepared["base_main"], prepared["main_sha"]).splitlines())
    assert changed == {publisher.EVENTS, publisher.RECEIPTS, "event.html"}
    assert "lab-only.txt" not in git("ls-tree", "--name-only", prepared["main_sha"])
    before_main = git("rev-parse", "origin/main")
    # The owner changes the queue while checks are running. Both remote refs must stay safe.
    (repo / "inputs/editorial/schedule.json").write_text(json.dumps({"schemaVersion": 1, "items": []}))
    git("add", "--", "inputs/editorial/schedule.json"); git("commit", "-m", "Cancel synthetic schedule"); git("push", "origin", "lab")
    with pytest.raises(ValueError, match="Remote moved"):
        publisher.finish(state)
    assert git("rev-parse", "origin/main") == before_main
    # Re-approve, rebuild and publish both refs in a single ordinary atomic push.
    (repo / "inputs/editorial/schedule.json").write_text(encrypted)
    git("add", "--", "inputs/editorial/schedule.json"); git("commit", "-m", "Reschedule synthetic post"); git("push", "origin", "lab")
    ready = publisher.prepare(NOW, state); publisher.finish(state)
    assert git("rev-parse", "origin/main") == ready["main_sha"]
    assert git("rev-parse", "origin/lab") == ready["lab_sha"]
    git("merge-base", "--is-ancestor", "origin/main", "origin/lab")
    assert publisher.prepare(NOW, state) == {"due": "false"}


def test_editor_preserves_input_on_conflict_and_previews_both_languages():
    with sync_playwright() as pw:
        browser = launch(pw); context = new_context(browser)
        writes = []
        def api(route):
            action = route.request.url.split("action=")[-1]
            if action == "session": result = {"configured": True, "authenticated": True, "login": "synthetic", "csrf": "synthetic"}
            elif route.request.method == "POST":
                writes.append(route.request.post_data_json)
                route.fulfill(status=409, json={"error": "Changed"}); return
            else: result = {"queue": {"schemaVersion": 1, "items": []}, "sha": "synthetic", "receipts": {"items": []}}
            route.fulfill(json=result)
        context.route("**/api/editorial?*", api)
        page = context.new_page(); page.goto("https://site-ui.invalid/lab.html", wait_until="networkidle")
        page.locator("#editorWorkspace").wait_for(state="visible")
        for lang, text in (("ko", "한글 제목"), ("en", "English title")):
            page.locator(f"#title-{lang}").fill(text); page.locator(f"#text-{lang}").fill("<script>never executable</script>")
        assert "한글 제목" in page.locator("#editorPreview").inner_text()
        page.locator("#langToggle").click()
        assert "English title" in page.locator("#editorPreview").inner_text()
        assert page.locator("#editorPreview script").count() == 0
        page.locator("#editorSave").click()
        page.wait_for_function("document.querySelector('#editorStatus').hasAttribute('data-error')")
        assert len(writes) == 1 and writes[0]["sha"] == "synthetic"
        assert page.locator("#title-en").input_value() == "English title"
        assert not page.locator("#editorSave").is_disabled()
        context.close(); browser.close()


@pytest.mark.parametrize("width", [360, 390, 768, 1440, 1920])
def test_editor_preview_responsive_and_cannot_fake_a_server_save(width):
    with sync_playwright() as pw:
        browser = launch(pw); context = new_context(browser)
        context.route("**/api/editorial?*", lambda route: route.fulfill(json={"configured": False, "authenticated": False}))
        page = context.new_page(); page.set_viewport_size({"width": width, "height": 900})
        page.goto("https://site-ui.invalid/lab.html", wait_until="networkidle")
        page.locator("#editorTry").click()
        assert page.locator("#editorSave").is_disabled() and page.locator("#editorSchedule").is_disabled()
        for lang in ("ko", "en"):
            page.locator(f"#title-{lang}").fill("아주 긴 제목 " * 10)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.locator("#editorKind").select_option("activity")
        assert page.locator("#summary-ko").is_visible() and not page.locator("#text-ko").is_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        context.close(); browser.close()
