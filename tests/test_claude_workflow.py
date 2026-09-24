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
