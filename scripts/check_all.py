"""Babdoduk's checks in one command, as fast as they safely go (owner 2026-11-12: "뭐 하나 수정할때마다 코드
점검하는 시간이 너무 오래 걸리는 것 같아"; 2026-11-19: "효율적으로 시간을 줄이는 방향으로";
.claude/skills/verify-babdoduk/SKILL.md).

    python scripts/check_all.py --changed  while working: only the tests that load what this branch changed
    python scripts/check_all.py --quick    before pushing to lab (about 1 minute)
    python scripts/check_all.py            the five gates, before a production release (about 5 minutes)

Changed: shared chrome in sync, content valid, and the test files that name a changed file, a page that loads
a changed script or stylesheet, or a changed Python module (`select_tests`). A change to something every page
or test shares (`WIDE`), or a changed source file no test names, runs the whole quick set instead. It is for
iterating; it does not replace the quick check before a lab push.

Quick: shared chrome in sync, content valid, every test except the full site-UI run, on parallel workers.
After the push, GitHub's tests workflow runs the whole suite including the site-UI run
(scripts/ci_status.py reads its result). Full: the same, plus the site-UI run (its groups side by side,
scripts/check_site_ui.py) and the food-hub UI checker. Every stage runs even after a failure, and each
stage's first result is printed, never a rerun.

Before anything runs, the Python in use is checked for the parts the checks need (`NEEDED`). Without
pytest-xdist the tests run one at a time, several times slower; without pypdfium2 the mail-to-card test fails.
When one is missing, the run moves to the first Python that has them all (`$BABDODUK_PYTHON`, the repository's
`.venv`, the ops PC's `~/Babdoduk-ops/.venv`) and says so; if none has them, it says what is missing and goes on.

The chrome screenshot comparison is skipped unless --visual is given: its baselines exist for the pinned CI
container and the owner's Windows PC, not for this Linux PC, and ui-guardian compares them in CI
(docs/VISUAL_BASELINES.md). That is the same setting the tests workflow uses.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE_UI_TEST = "tests/test_site_ui.py::test_all_public_pages_windows_scrollbars_and_overflow"
NEEDED = {
    "xdist": "pytest-xdist (without it the tests run one at a time, several times slower)",
    "pypdfium2": "pypdfium2 (without it the mail-to-card test fails)",
    "playwright": "playwright (the browser tests)",
}
INSTALL = "pip install -r requirements-dev.txt -r requirements-ggongbab.txt"
SWITCHED = "BABDODUK_CHECK_PYTHON_CHOSEN"
# Shared by every page or every test: a change here runs the whole quick set.
WIDE = ("tests/conftest.py", "tests/ggongbab/conftest.py", "tests/fixtures/", "pytest.ini", "requirements",
        "shared/", "js/site.js", "css/site.css", "scripts/sync_site_chrome.py", "scripts/content_labels.py",
        "data/content/labels.json", "scripts/check_site_ui.py")
# Changes that need no test of their own when no test names them.
NO_TEST_NEEDED = (".md", ".txt", ".png", ".jpg", ".jpeg", ".webp", ".svg", ".ico", ".gitignore")


def missing_parts(python=None):
    """The NEEDED modules a Python lacks (this one when python is None)."""
    if python is None:
        return [m for m in NEEDED if importlib.util.find_spec(m) is None]
    probe = "import importlib.util as u, sys; print(' '.join(m for m in sys.argv[1:] if u.find_spec(m) is None))"
    try:
        out = subprocess.run([python, "-c", probe, *NEEDED], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return list(NEEDED)
    return out.stdout.split() if out.returncode == 0 else list(NEEDED)


def candidate_pythons():
    names = [os.environ.get("BABDODUK_PYTHON", ""), str(ROOT / ".venv/bin/python"),
             str(Path.home() / "Babdoduk-ops/.venv/bin/python")]
    seen = []
    for name in names:
        if name and Path(name).is_file() and os.access(name, os.X_OK) and name not in seen:
            seen.append(name)
    return seen


def choose_python(argv):
    """Move to a Python that has every NEEDED part, or report what is missing; returns the missing parts."""
    lacking = missing_parts()
    if not lacking or os.environ.get(SWITCHED):
        return lacking
    for python in candidate_pythons():
        # A venv's python links to the system one, so compare the paths themselves, not where they lead.
        if os.path.abspath(python) != os.path.abspath(sys.executable) and not missing_parts(python):
            print(f"this Python lacks {', '.join(lacking)}: running with {python}", flush=True)
            os.environ[SWITCHED] = "1"
            os.execv(python, [python, str(Path(__file__).resolve()), *argv])
    for part in lacking:
        print(f"warning: missing {NEEDED[part]}; install with: {INSTALL}", flush=True)
    return lacking


def workers():
    if importlib.util.find_spec("xdist") is None:
        return []
    return ["-n", str(min(8, max(2, (os.cpu_count() or 4) - 2)))]


def git_lines(*args):
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return [line.strip() for line in out.stdout.splitlines() if line.strip()] if out.returncode == 0 else []


def changed_files(base="origin/lab"):
    """Every path this branch changed against base: commits since the merge base, the index, the work tree,
    and new untracked files. None when the base is unknown."""
    merge_base = git_lines("merge-base", "HEAD", base)
    if not merge_base:
        return None
    paths = set(git_lines("diff", "--name-only", merge_base[0], "HEAD"))
    paths |= set(git_lines("diff", "--name-only", "HEAD"))
    paths |= set(git_lines("ls-files", "--others", "--exclude-standard"))
    return sorted(paths)


def mention(name):
    """A pattern for a file or module name standing on its own (my.js, not my.json or army.js)."""
    return re.compile(r"(?<![\w.-])" + re.escape(name) + r"(?![\w-])")


def keys_for(path, root=ROOT):
    """The names a test would use for path: the path, its file name, the pages that load it, its module."""
    p = Path(path)
    keys = {path, p.name}
    if p.suffix in (".js", ".css") and len(p.parts) > 1 and p.parts[0] in ("js", "css"):
        ref = re.compile(r'(?:src|href)="' + re.escape(path) + r'(?:[?"])')
        keys |= {page.name for page in root.glob("*.html") if ref.search(page.read_text(encoding="utf-8", errors="ignore"))}
    if p.suffix == ".py" and p.parts[0] == "scripts":
        keys.add(p.stem)
    if p.suffix == ".json" and p.parts[0] == "i18n":
        keys.add("i18n/")
    return keys


def select_tests(changed, root=ROOT):
    """(test files to run, reason) for a list of changed paths. None for the files means the whole quick set."""
    tests_dir = root / "tests"
    files = sorted(tests_dir.rglob("test_*.py"))
    texts = {f: f.read_text(encoding="utf-8", errors="ignore") for f in files}
    chosen, orphans = set(), []
    for path in changed:
        if path.startswith(WIDE):
            return None, f"{path} is shared by every page or test"
        if path.startswith("tests/") and Path(path).name.startswith("test_") and path.endswith(".py"):
            if (root / path).is_file():
                chosen.add(root / path)
            continue
        patterns = [mention(k) if k != "i18n/" else re.compile(re.escape(k)) for k in keys_for(path, root)]
        hits = {f for f, text in texts.items() if any(p.search(text) for p in patterns)}
        if hits:
            chosen |= hits
        elif not path.endswith(NO_TEST_NEEDED) and not path.startswith((".claude/", "docs/")):
            orphans.append(path)
    if orphans:
        return None, f"no test names {', '.join(orphans[:3])}"
    return sorted(chosen), f"{len(chosen)} test files for {len(changed)} changed paths"


def stages(quick, only=None):
    """The checks to run. only: a list of test files (the --changed selection); [] runs no tests."""
    py = sys.executable
    out = [
        ("chrome sync", [py, "scripts/sync_site_chrome.py", "--check"]),
        ("content", [py, "scripts/validate_content.py"]),
    ]
    targets = ["tests"] if only is None else [str(Path(f).relative_to(ROOT)) if Path(f).is_absolute() else str(f) for f in only]
    if targets:
        out.append(("tests", [py, "-m", "pytest", *targets, "-q", "-p", "no:cacheprovider", *workers(), "--deselect", SITE_UI_TEST]))
    if not quick:
        out += [
            ("site UI", [py, "-m", "pytest", SITE_UI_TEST, "-q", "-p", "no:cacheprovider"]),
            ("food hub UI", [py, "scripts/check_ggongbab_ui.py"]),
        ]
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--quick", action="store_true", help="before a lab push: no site-UI or food-hub browser run")
    mode.add_argument("--changed", action="store_true", help="while working: only the tests for what this branch changed")
    parser.add_argument("--base", default="origin/lab", help="what --changed compares against (default origin/lab)")
    parser.add_argument("--visual", action="store_true", help="also compare the chrome screenshots (needs this platform's baselines)")
    args = parser.parse_args(argv)
    choose_python(argv)
    env = dict(os.environ)
    if not args.visual:
        env["BABDODUK_CHROME_VISUAL"] = "skip"
    only = None
    if args.changed:
        changed = changed_files(args.base)
        if changed is None:
            print(f"--changed: {args.base} is unknown here, running the quick set", flush=True)
        else:
            only, why = select_tests(changed)
            print(f"--changed: {why}" + ("" if only is not None else ", running the quick set"), flush=True)
            for f in only or []:
                print(f"    {Path(f).relative_to(ROOT)}", flush=True)
    results = []
    began = time.time()
    for name, cmd in stages(args.quick or args.changed, only):
        start = time.time()
        proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
        took = time.time() - start
        tail = (proc.stdout + proc.stderr).strip().splitlines()
        results.append((name, proc.returncode, took))
        mark = "ok" if proc.returncode == 0 else f"FAILED (exit {proc.returncode})"
        print(f"{name:12s} {mark:18s} {took:5.0f}s", flush=True)
        if proc.returncode:
            print("\n".join("    " + line for line in tail[-25:]), flush=True)
    failed = [name for name, code, _ in results if code]
    print(f"{'total':12s} {'FAILED: ' + ', '.join(failed) if failed else 'all passed':18s} {time.time() - began:5.0f}s")
    if args.changed and not failed:
        print("before a lab push: python scripts/check_all.py --quick")
    elif args.quick and not failed:
        print("the full suite with the site-UI run follows on GitHub after the push: python scripts/ci_status.py <commit>")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
