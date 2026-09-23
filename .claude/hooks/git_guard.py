#!/usr/bin/env python3
"""PreToolUse guard: deny destructive Git commands and manual production deploys.

Claude Code sends the pending Bash/PowerShell call as JSON on stdin. A blocked
command gets a PreToolUse "deny" decision with a readable reason on stdout;
anything else produces no output and exit code 0, so the normal permission
rules apply. Normal commits and normal pushes (including an owner-authorized
push to main) are never blocked here.

The command line is split into simple commands (on ; && || | & and newlines,
after removing heredoc bodies), and each argv is checked on its own. This is
deliberately small: it catches the destructive forms agents actually type, not
every conceivable shell trick.
"""
from __future__ import annotations

import json
import re
import shlex
import sys

HEREDOC = re.compile(r"(?<!<)<<(?!<)-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
PS_HERE_STRING = re.compile(r"@(['\"])\s*$")
SEPARATORS = {";", ";;", "&", "&&", "|", "||", "|&", "(", ")"}
WRAPPERS = {"env", "command", "builtin", "nohup", "time", "sudo", "exec"}
GIT_OPTIONS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env"}
BROAD_PATHSPECS = {".", "./", ":/", ":(top)", "*"}
FALLBACK = [
    (re.compile(r"\bgit\b[^\n]*\bpush\b[^\n]*(--force|--mirror|\s-[a-z]*f)"), "force push"),
    (re.compile(r"\bgit\b[^\n]*\breset\b[^\n]*--hard"), "git reset --hard"),
    (re.compile(r"\bgit\b[^\n]*\bclean\b[^\n]*(\s-[a-z]*f|--force)"), "git clean -f"),
    (re.compile(r"\bvercel\b[^\n]*(--prod\b|--production\b)"), "vercel --prod"),
]


def strip_heredocs(command: str) -> str:
    """Drop heredoc and PowerShell here-string bodies, so text written into files
    or commit messages is not treated as commands."""
    kept, pending, ps_close = [], [], None
    for line in command.replace("\r\n", "\n").split("\n"):
        if ps_close:
            if line.startswith(ps_close):
                ps_close = None
            continue
        if pending:
            if line.strip() == pending[0]:
                pending.pop(0)
            continue
        kept.append(line)
        pending.extend(match.group(2) for match in HEREDOC.finditer(line))
        here = PS_HERE_STRING.search(line)
        if here and not pending:
            ps_close = here.group(1) + "@"
    return "\n".join(kept)


def simple_commands(command: str) -> list[list[str]]:
    """Split a shell line into argv lists; raises ValueError on unbalanced quotes."""
    result: list[list[str]] = []
    for line in strip_heredocs(command).split("\n"):
        lexer = shlex.shlex(line, posix=True, punctuation_chars=";&|()")
        lexer.whitespace_split = True
        lexer.commenters = ""
        current: list[str] = []
        for token in lexer:
            if token in SEPARATORS:
                if current:
                    result.append(current)
                current = []
            else:
                current.append(token)
        if current:
            result.append(current)
    return result


def unwrap(argv: list[str]) -> list[str]:
    """Remove VAR=value assignments and wrappers such as env or sudo."""
    i = 0
    while i < len(argv) and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", argv[i]) or argv[i] in WRAPPERS):
        i += 1
    return argv[i:]


def short_flags(args: list[str]) -> str:
    """All single-letter flags, e.g. '-fd' and '-x' -> 'fdx'."""
    return "".join(a[1:] for a in args if re.fullmatch(r"-[A-Za-z]+", a))


def check_git(args: list[str]) -> str | None:
    i = 0
    while i < len(args) and args[i].startswith("-"):
        i += 2 if args[i] in GIT_OPTIONS_WITH_VALUE else 1
    if i >= len(args):
        return None
    sub, rest = args[i], args[i + 1:]
    flags = short_flags(rest)
    words = [a for a in rest if not a.startswith("-")]
    if sub == "push":
        if {"--force", "--force-with-lease", "--force-if-includes", "--mirror"} & set(rest) or "f" in flags \
                or any(a.startswith("--force-with-lease=") for a in rest) or any(w.startswith("+") for w in words):
            return "`git push --force` (or an equivalent) rewrites remote history. Push normally; a non-fast-forward rejection means fetch, report and integrate deliberately."
        if "--delete" in rest or "d" in flags or "--prune" in rest or any(w.startswith(":") for w in words):
            return "This push deletes remote branches. Deleting remote refs needs the owner's explicit authorization."
    if sub == "reset" and "--hard" in rest:
        return "`git reset --hard` discards work and history. Use a new commit or `git revert`; resetting needs the owner's explicit authorization."
    if sub == "clean" and ("f" in flags or "--force" in rest):
        return "`git clean -f` permanently deletes untracked files, which may be someone else's work."
    if sub == "checkout" and ("--force" in rest or "f" in flags or BROAD_PATHSPECS & set(words)):
        return "`git checkout -- .` (or --force) discards every uncommitted change in the tree, including other people's."
    if sub == "restore" and BROAD_PATHSPECS & set(words):
        staged_only = ("--staged" in rest or "S" in flags) and not ("--worktree" in rest or "W" in flags)
        if not staged_only:
            return "`git restore .` discards every uncommitted change in the tree, including other people's."
    if sub == "stash" and rest[:1] in (["drop"], ["clear"]):
        return "Dropping or clearing stashes deletes saved work that may belong to the owner."
    if sub == "branch" and ("D" in flags or ("--delete" in rest and ("--force" in rest or "f" in flags))):
        return "`git branch -D` force-deletes a branch that may hold unmerged work."
    if sub == "worktree" and rest[:1] == ["remove"] and ("--force" in rest or "f" in flags):
        return "Force-removing a worktree deletes its uncommitted files; another agent may be using it."
    return None


def check_vercel(args: list[str]) -> str | None:
    if "--prod" in args or "--production" in args or args[:1] in (["promote"], ["rollback"]) or args[:2] == ["alias", "set"]:
        return "Production deploys go through Git (a reviewed push to main). `vercel --prod`, promote, rollback and alias changes need the owner's explicit authorization."
    return None


def check_argv(argv: list[str], depth: int = 0) -> str | None:
    argv = unwrap(argv)
    if not argv:
        return None
    name = re.split(r"[\\/]", argv[0])[-1].lower().removesuffix(".exe")
    if name == "git":
        return check_git(argv[1:])
    if name == "vercel":
        return check_vercel(argv[1:])
    if name in ("npx", "pnpm", "yarn", "bunx") and "vercel" in argv[1:3]:
        return check_vercel(argv[argv.index("vercel") + 1:])
    if depth == 0 and name in ("bash", "sh", "zsh", "powershell", "pwsh", "cmd"):
        for flag in ("-c", "-Command", "-command", "/c", "/C"):
            if flag in argv[1:-1]:
                return evaluate(argv[argv.index(flag) + 1], depth + 1)
    return None


def evaluate(command: str, depth: int = 0) -> str | None:
    """Return a denial reason for a dangerous command line, or None when it may proceed."""
    try:
        commands = simple_commands(command)
    except ValueError:  # unbalanced quotes: fall back to a conservative scan
        text = strip_heredocs(command)
        for pattern, label in FALLBACK:
            if pattern.search(text):
                return f"Could not parse this command safely and it looks like `{label}`. Rewrite it without ambiguous quoting."
        return None
    for argv in commands:
        reason = check_argv(argv, depth)
        if reason:
            return reason
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 0
    if payload.get("tool_name") not in ("Bash", "PowerShell"):
        return 0
    command = (payload.get("tool_input") or {}).get("command") or ""
    reason = evaluate(command)
    if reason:
        json.dump({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": f"Blocked by .claude/hooks/git_guard.py: {reason}",
        }}, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
