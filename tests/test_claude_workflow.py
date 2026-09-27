"""Project Claude Code workflow: guard decisions, settings, CLAUDE.md, skills, status line.

Only the hook's decision logic is exercised. No dangerous command is ever run.
"""
import importlib.util
import json
import re
import shutil
import subprocess
import sys

import pytest

from check_site_ui import ROOT

GUARD_PATH = ROOT / ".claude/hooks/git_guard.py"
spec = importlib.util.spec_from_file_location("git_guard", GUARD_PATH)
git_guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(git_guard)

ALLOWED = [
    "git status",
    "git diff --stat HEAD~1",
    "git log --oneline -5",
    "git add -- index.html css/index.css",
    'git commit -m "docs: never run git push --force or git reset --hard"',
    "git commit -F - <<'EOF'\nfix: explain why\n\ngit push --force and git reset --hard stay forbidden\nEOF",
    "git commit -m @'\ngit push --force is blocked\n'@",
    "git push",
    "git push origin release/product-refresh-2026-09",
    "git push -u origin agent/claude/home",
    "git push origin HEAD:main",
    "git merge --no-ff origin/release/product-refresh-2026-09 -m \"Merge release/product-refresh-2026-09\"",
    "git worktree add --detach ../Babdoduk-wt/prod-integration origin/main",
    "git worktree remove ../Babdoduk-wt/prod-integration",
    "git checkout -b agent/claude/home origin/lab",
    "git checkout main",
    "git restore --staged .",
    "git restore index.html",
    "git reset --soft HEAD~1",
    "git clean -n",
    "git stash list",
    "git branch -d merged-branch",
    "git revert -m 1 abc1234",
    'echo "git reset --hard"',
    "python -m pytest tests -q",
    "vercel ls",
    "cd ../repo && git fetch origin --prune",
]

DENIED = [
    "git push --force origin main",
    "git push -f",
    "git push origin main --force",
    "git push -uf origin main",
    "git push --force-with-lease",
    "git push --force-with-lease=main:abc123 origin main",
    "git push origin +main",
    "git push origin :old-branch",
    "git push --delete origin old-branch",
    "git push --mirror",
    "git reset --hard HEAD~1",
    "git -C ../other reset --hard origin/main",
    "GIT_TRACE=1 git reset --hard",
    "git clean -fd",
    "git clean -df",
    "git clean -xdf",
    "git clean --force",
    "git checkout -- .",
    "git checkout .",
    "git checkout -f main",
    "git restore .",
    "git restore --staged --worktree .",
    "git stash drop",
    "git stash clear",
    "git branch -D old-branch",
    "git worktree remove --force ../Babdoduk-wt/other",
    "vercel --prod",
    "vercel deploy --prod",
    "npx vercel --prod",
    "vercel promote https://example.vercel.app",
    "cd repo && git push -f origin main",
    "git status; git reset --hard",
    "bash -c 'git reset --hard'",
    'powershell -Command "git push --force origin main"',
    "C:/Program\\ Files/Git/cmd/git.exe push --force",
]


@pytest.mark.parametrize("command", ALLOWED)
def test_guard_allows_normal_work(command):
    assert git_guard.evaluate(command) is None


@pytest.mark.parametrize("command", DENIED)
def test_guard_denies_destructive_commands(command):
    reason = git_guard.evaluate(command)
    assert reason and len(reason) > 20


def run_hook(payload):
    result = subprocess.run([sys.executable, str(GUARD_PATH)], input=json.dumps(payload),
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_hook_emits_a_pretooluse_deny_decision_end_to_end():
    out = json.loads(run_hook({"tool_name": "Bash", "tool_input": {"command": "git push --force origin main"}}))
    decision = out["hookSpecificOutput"]
    assert decision["hookEventName"] == "PreToolUse" and decision["permissionDecision"] == "deny"
    assert "git_guard" in decision["permissionDecisionReason"]
    assert run_hook({"tool_name": "Bash", "tool_input": {"command": "git status"}}) == ""
    assert run_hook({"tool_name": "PowerShell", "tool_input": {"command": "git clean -fd"}})
    assert run_hook({"tool_name": "Read", "tool_input": {"file_path": "git reset --hard"}}) == ""


def test_settings_are_valid_and_conservative():
    settings = json.loads((ROOT / ".claude/settings.json").read_text(encoding="utf-8"))
    assert settings["$schema"] == "https://json.schemastore.org/claude-code-settings.json"
    assert settings["outputStyle"] == "Proactive"
    permissions = settings["permissions"]
    assert permissions["defaultMode"] == "acceptEdits"
    text = json.dumps(settings)
    assert "bypassPermissions" not in text and "Bash(*)" not in permissions["allow"]
    assert not [rule for rule in permissions["allow"] if re.search(r"push|reset|clean|restore|checkout|vercel|rm ", rule)]
    assert {"Bash(git push --force:*)", "Bash(git reset --hard:*)", "Bash(vercel --prod:*)"} <= set(permissions["deny"])
    hook = settings["hooks"]["PreToolUse"][0]
    assert "Bash" in hook["matcher"].split("|") and hook["hooks"][0]["type"] == "command"
    assert ".claude/hooks/git_guard.py" in hook["hooks"][0]["command"]
    assert settings["statusLine"]["type"] == "command" and "statusline.ps1" in settings["statusLine"]["command"]
    assert not re.search(r"[A-Za-z]:\\\\Users|/Users/|joshu", text), "no machine-specific paths"


def test_claude_md_imports_only_agents_md():
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    imports = re.findall(r"(?m)^\s*@(\S+)", text)
    assert imports == ["AGENTS.md"] and text.startswith("@AGENTS.md")
    body = [line for line in text.splitlines()[1:] if line.strip()]
    assert 5 <= len(body) <= 30
    for doc in ("PRD.md", "DESIGN_SYSTEM.md", "ARCHITECTURE.md", "README.md"):
        assert f"@{doc}" not in text


def frontmatter(path):
    text = path.read_text(encoding="utf-8")
    match = re.match(r"---\n(.*?)\n---\n(.+)", text, re.S)
    assert match, path
    try:
        import yaml
        meta = yaml.safe_load(match.group(1))
    except ImportError:
        meta = dict(line.split(": ", 1) for line in match.group(1).splitlines())
    return meta, match.group(2)


def test_five_project_skills_have_valid_frontmatter():
    names = sorted(p.parent.name for p in (ROOT / ".claude/skills").glob("*/SKILL.md"))
    assert names == ["handoff", "release-babdoduk", "session-start", "ui-review", "verify-babdoduk"]
    for name in names:
        meta, body = frontmatter(ROOT / ".claude/skills" / name / "SKILL.md")
        assert meta["name"] == name and re.fullmatch(r"[a-z0-9-]{1,64}", name)
        assert 40 <= len(meta["description"]) <= 400, name  # always in context: keep it short
        assert len(body) > 400, name
    release, _ = frontmatter(ROOT / ".claude/skills/release-babdoduk/SKILL.md")
    assert release.get("disable-model-invocation") in (True, "true")
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "PRE_RELEASE_MAIN_SHA" not in agents and "git merge --no-ff" not in agents  # one canonical release procedure
    for rule in ("ONE WORKTREE = ONE ACTIVE CODING AGENT", "git push --force", "git reset --hard", "is not yours",
                 "explicit owner authorization", "never with force"):
        assert rule in agents, rule


@pytest.mark.skipif(not shutil.which("powershell"), reason="Windows PowerShell is not available")
def test_statusline_formats_sample_session_json():
    sample = {"model": {"display_name": "Opus 5.5"}, "workspace": {"current_dir": str(ROOT), "project_dir": str(ROOT)},
              "context_window": {"used_percentage": 42.4, "context_window_size": 200000}}
    result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                             str(ROOT / ".claude/statusline.ps1")], input=json.dumps(sample),
                            capture_output=True, text=True, timeout=60)
    line = result.stdout.strip()
    assert result.returncode == 0, result.stderr
    assert re.fullmatch(r"Opus 5\.5 \| \S.* \| " + re.escape(ROOT.name) + r" \| ctx 42% \| dirty \d+", line), line


# ---------------------------------------------------------------------------
# Lab-first release discipline (AGENTS.md "Lab-first lifecycle"). In 2026-09 ordinary releases
# started from main, production moved on and babdoduk-lab kept serving stale shared UI. These
# assertions keep the written contract from drifting back.
# ---------------------------------------------------------------------------
PROCESS_DOCS = ["AGENTS.md", "CLAUDE.md", "README.md", "docs/DEPLOYMENT_AND_BRANCHES.md", "docs/BRANCH_MERGE_CHECKLIST.md",
                "docs/REPOSITORY_HYGIENE.md"]
SKILL_DOCS = [f".claude/skills/{name}/SKILL.md" for name in ("session-start", "release-babdoduk", "handoff", "ui-review")]
# Other agents read their own always-on rules; they get the same contract as the process docs.
CURSOR_RULES = sorted(str(p.relative_to(ROOT)).replace("\\", "/") for p in (ROOT / ".cursor/rules").glob("*.mdc"))
DRIFT_CHECK = "git log --format='%h %an %s' origin/lab..origin/main"


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def lifecycle():
    agents = read("AGENTS.md")
    return agents[agents.index("## Lab-first lifecycle"):agents.index("## Before starting")]


def test_product_tasks_start_from_lab_and_a_production_destination_is_not_an_exception():
    agents = read("AGENTS.md")
    assert "unless the task explicitly targets production" not in agents  # the old escape hatch
    assert agents.index("## Lab-first lifecycle (non-negotiable)") < agents.index("## Before starting")  # prominent
    rules = lifecycle()
    assert "Product/UI/frontend tasks always start from the latest `origin/lab`" in rules
    assert "A production destination does not by itself authorize a main-based task" in rules
    for ordinary in ("Update the site", "refresh production", "prepare a release", "fix the page and deploy it"):
        assert ordinary in rules, ordinary
    bypass = rules[rules.index("allowed only for:"):rules.index("Record the owner's bypass")]
    assert bypass.count("explicitly") == 3 and "generated-data bot publication" in bypass
    start = read(".claude/skills/session-start/SKILL.md")
    assert "git worktree add --no-track -b agent/<tool>/<task> ../Babdoduk-wt/<task> origin/lab" in start
    assert not re.search(r"git worktree add [^\n`]*agent/[^\n`]* origin/main", start)
    assert "Product/UI work starts from the latest `origin/lab`" in read("CLAUDE.md")


def test_lab_deployment_and_approval_precede_main_promotion():
    rules = lifecycle()
    steps = ["**Task:**", "**Lab integration:**", "**Lab deployment:**", "**Lab verification:**",
             "**Owner approval**", "**Release candidate:**", "**Production:**", "**Back-sync:**"]
    assert [rules.index(step) for step in steps] == sorted(rules.index(step) for step in steps)
    release = read(".claude/skills/release-babdoduk/SKILL.md")
    for field in ("LAB_TASK_SHA", "LAB_INTEGRATION_SHA", "LAB_VERCEL_DEPLOYMENT_STATUS", "LAB_URL_TESTED", "OWNER_APPROVAL"):
        assert release.count(field) >= 2, field  # recorded in the gate and in the report
    assert "git merge-base --is-ancestor <LAB_TASK_SHA> origin/lab" in release
    assert "Local tests passing is not a substitute" in release
    sections = ["## 0. Lab acceptance", "## 1. Start from production", "## 2. Promote only the approved commits",
                "## 6. Production merge", "## 7. Verify production", "## 8. Back-sync lab"]
    assert [release.index(s) for s in sections] == sorted(release.index(s) for s in sections)
    assert "LAB_URL_TESTED" in read(".claude/skills/ui-review/SKILL.md")


def test_release_starts_from_latest_main_and_promotes_selectively():
    release = read(".claude/skills/release-babdoduk/SKILL.md")
    assert "git worktree add --no-track -b release/<name> ../Babdoduk-wt/release-<name> origin/main" in release
    assert "git cherry-pick -x <LAB_TASK_SHA>" in release
    assert "Never `git merge lab` or `git merge origin/lab` into a release" in release
    assert "goes back through lab first" in release  # behavior-changing conflict resolution
    # No document offers a whole-lab merge into main as a way to release.
    for rel in PROCESS_DOCS + SKILL_DOCS + CURSOR_RULES:
        for line in read(rel).splitlines():
            if re.search(r"git merge (origin/)?lab\b", line):
                assert re.search(r"[Nn]ever|not|않|아닙니다|금지", line), (rel, line)


def test_back_sync_is_required_and_drift_is_checked():
    rules = lifecycle()
    assert "**Lab never trails production.**" in rules and "not operationally complete" in rules
    release = read(".claude/skills/release-babdoduk/SKILL.md")
    back_sync = release[release.index("## 8. Back-sync lab"):release.index("## 9.")]
    assert "the release is not complete without it" in release and DRIFT_CHECK in back_sync
    assert "BACK_SYNC_LAB_SHA" in back_sync and "babdoduk-lab" in back_sync
    for rel in (".claude/skills/session-start/SKILL.md", ".claude/skills/handoff/SKILL.md"):
        assert DRIFT_CHECK in read(rel), rel
    assert "LAB BEHIND PRODUCTION" in read(".claude/skills/session-start/SKILL.md")
    for rel in ("README.md", "docs/DEPLOYMENT_AND_BRANCHES.md", "docs/BRANCH_MERGE_CHECKLIST.md"):
        text = read(rel)
        assert "back-sync" in text and "origin/lab..origin/main" in text, rel


def test_generated_data_bot_remains_an_exception():
    agents = read("AGENTS.md")
    assert "### Generated-data bot" in agents and "generated-data bot publication" in lifecycle()
    release = read(".claude/skills/release-babdoduk/SKILL.md")
    assert "`babdoduk-content-bot` with data-only paths: integrate from the newest `origin/main`" in release


def test_no_document_instructs_a_cli_production_deploy():
    docs = PROCESS_DOCS + SKILL_DOCS + CURSOR_RULES
    docs += [str(p.relative_to(ROOT)).replace("\\", "/") for p in (ROOT / "docs").glob("*.md")]
    for rel in sorted(set(docs)):
        for line in read(rel).splitlines():
            if re.search(r"vercel (deploy )?--prod", line):
                assert re.search(r"[Nn]ever|not|않|금지|block", line), (rel, line)


def test_cursor_rules_defer_to_the_lab_first_contract():
    """An always-applied Cursor rule once said lab was approved by default, told agents to commit and
    push without asking and to deploy with `npx vercel --prod --yes`. Cursor rules may only point back
    to AGENTS.md and its lifecycle."""
    assert CURSOR_RULES, "the repository keeps a Cursor rule that points to AGENTS.md"
    for rel in CURSOR_RULES:
        text = read(rel)
        for anchor in ("AGENTS.md", "Lab-first lifecycle", ".claude/skills/release-babdoduk"):
            assert anchor in text, (rel, anchor)
        for stale in ("승인된 상태", "커밋·푸시가 기본", "다시 묻지 않는다", "--yes", "git push origin lab"):
            assert stale not in text, (rel, stale)


def test_cleanup_is_classified_first_and_never_forced():
    hygiene = read("docs/REPOSITORY_HYGIENE.md")
    for required in ("git cherry origin/lab <branch>", "git diff-tree --cc", "git worktree remove <path>",
                     "git worktree prune", "git branch -d <branch>", "status --short --ignored", "release-YYYY-MM-DD-<slug>",
                     # Unmerged work is preserved as a verified remote tag before anything local is cleaned up.
                     "archive-YYYY-MM[-DD]-<slug>", 'git ls-remote origin "refs/tags/', "자동으로 지우지 않는 것",
                     "거부되면 그 브랜치는 멈추고 소유자에게 보고합니다"):
        assert required in hygiene, required
    for label in ("ACTIVE", "SAFE_TO_DELETE", "KEEP_FOR_RELEASE_HISTORY", "OWNER_REVIEW_REQUIRED"):
        assert f"`{label}`" in hygiene, label
    assert hygiene.index("## 10. 보고 형식") > hygiene.index("## 9. 정리도 lab 을 먼저 거칩니다")
    # Deletion waits for the owner's approval of the exact list, and forced forms are never instructions.
    assert "승인받기 전에는 아무것도 지우지 않습니다" in hygiene
    for line in hygiene.splitlines():
        if re.search(r"--force|-D\b|stash drop|git push origin --delete", line):
            assert re.search(r"않|막|소유자", line), line
    for rel in ("README.md", "docs/DEPLOYMENT_AND_BRANCHES.md", "docs/BRANCH_MERGE_CHECKLIST.md"):
        assert "REPOSITORY_HYGIENE.md" in read(rel), rel
