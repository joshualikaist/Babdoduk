#!/usr/bin/env python3
"""The review panel's split screen: what each reviewer is doing, as a timeline (docs/PANEL.md).

    python scripts/panel/live.py export --run <workflow run dir>   write data/panel/timeline.json (lab replay)
    python scripts/panel/live.py watch [--run <dir>] [--port 8765]  serve the site on 127.0.0.1 with a live timeline

A run dir is a workflow's subagent folder (`.../subagents/workflows/wf_*`): `journal.jsonl` says which agent
is which reviewer, and each `agent-<id>.jsonl` holds that agent's steps with timestamps. Without `--run`,
`watch` follows the newest run. Steps are turned into short Korean lines; file paths become base names and
commands are never shown, so nothing local or private reaches the page.
"""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "panel" / "timeline.json"
PROJECTS = Path.home() / ".claude" / "projects"
PANES = [
    {"id": "designer1", "name": "디자이너 1", "emoji": "🎨"},
    {"id": "designer2", "name": "디자이너 2", "emoji": "🎨"},
    {"id": "developer1", "name": "개발자 1", "emoji": "🛠️"},
    {"id": "developer2", "name": "개발자 2", "emoji": "🛠️"},
    {"id": "copy1", "name": "문구 담당", "emoji": "✍️"},
    {"id": "founder1", "name": "창업가", "emoji": "🚀"},
    {"id": "critic", "name": "비판자", "emoji": "🧐"},
]
PHASES = {"Review": "각자 평가", "Critic": "비판자가 합치기", "Discuss": "서로 의견", "Reply": "답변", "Verdict": "최종 판정"}
STANCE = {"agree": "동의", "disagree": "반대", "add": "보탬"}
VERDICT = {"accept": "인정", "question": "질문", "reject": "기각"}
IMAGE = re.compile(r"\.(jpe?g|png|webp)$", re.I)
TEXT_MAX = 400


def pane_of(label: str) -> str:
    kind, _, who = (label or "").partition(":")
    if kind == "critic":
        return "critic"
    if kind == "review":
        return who if any(p["id"] == who for p in PANES) else ""
    if kind in ("discuss", "reply"):
        who = re.sub(r"\d+$", "", who)
        return f"{who}1" if any(p["id"] == f"{who}1" for p in PANES) else ""
    return ""


def when(stamp: str) -> float | None:
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return None


def name_of(path: str) -> str:
    path = str(path or "")
    m = re.search(r"/Babdoduk(?:-wt/[^/]+)?/(.+)$", path)
    return m.group(1) if m and not m.group(1).startswith(".") else Path(path).name


def step(tool: str, args: dict) -> str:
    if tool == "Read":
        name = name_of(args.get("file_path"))
        return f"📷 화면 보기: {Path(name).stem}" if IMAGE.search(name) else f"📄 읽기: {name}"
    if tool in ("Grep", "Glob"):
        return f"🔎 찾기: {str(args.get('pattern', ''))[:60]}"
    if tool == "Bash":
        head = str(args.get("command", "")).split("|")[0]
        if re.search(r"\b(grep|rg|find)\b", head):
            return "🔎 코드에서 찾는 중"
        if re.search(r"\bpython", head):
            return "🧮 숫자 확인하는 중"
        return "⌨️ 명령 실행"
    if tool == "StructuredOutput":
        return "📝 결과 정리"
    if tool in ("WebSearch", "WebFetch"):
        return "🌐 자료 찾는 중"
    return "🔧 도구 사용"


def result_lines(result) -> list[tuple[str, str]]:
    if not isinstance(result, dict):
        return []
    lines = []
    if result.get("summary"):
        lines.append(("say", str(result["summary"])))
    for f in result.get("findings") or []:
        lines.append(("finding", f"심각도 {f.get('severity', '?')} · {f.get('title', '')}"))
    groups = result.get("groups") or []
    if groups:
        counts = {v: sum(1 for g in groups if g.get("verdict") == v) for v in VERDICT}
        lines.append(("say", f"지적을 {len(groups)}개로 합쳤어요. 인정 {counts['accept']}, 질문 {counts['question']}, 기각 {counts['reject']}."))
        for g in groups:
            lines.append(("finding", f"{VERDICT.get(g.get('verdict'), '')} · {g.get('title', '')}"))
    for c in result.get("comments") or []:
        lines.append(("comment", f"[{STANCE.get(c.get('stance'), '의견')}] {c.get('text', '')}"))
    for r in result.get("replies") or []:
        lines.append(("comment", str(r.get("text", ""))))
    if result.get("overall"):
        lines.append(("say", str(result["overall"])))
    if result.get("top"):
        lines.append(("say", f"먼저 고칠 것 {len(result['top'])}개를 골랐어요."))
    return [(k, t.strip()[:TEXT_MAX]) for k, t in lines if t and t.strip()]


def agent_steps(path: Path) -> tuple[list[tuple[float, str, str]], float | None, float | None]:
    events, first, last = [], None, None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return events, None, None
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        at = when(row.get("timestamp"))
        if at is None:
            continue
        first = at if first is None else first
        last = at
        if row.get("type") != "assistant":
            continue
        for part in (row.get("message") or {}).get("content") or []:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "tool_use":
                events.append((at, "step", step(part.get("name", ""), part.get("input") or {})))
            elif part.get("type") == "text":
                text = str(part.get("text", "")).strip()
                if text and not text.startswith("<") and re.search(r"[가-힣]", text):
                    events.append((at, "say", text[:TEXT_MAX]))
    return events, first, last


def build(run: Path, live: bool = False) -> dict:
    started, results = {}, {}
    try:
        journal = (run / "journal.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        journal = []
    for line in journal:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("type") == "started" and pane_of(row.get("label")):
            for old in [a for a, s in started.items() if s["label"] == row["label"]]:
                started.pop(old)
                results.pop(old, None)
            started[row["agentId"]] = {"label": row["label"], "phase": row.get("phase", "")}
        elif row.get("type") == "result" and row.get("agentId") in started:
            results[row["agentId"]] = row.get("result")
    raw, phase_start, state = [], {}, {}
    for agent, info in started.items():
        steps, first, last = agent_steps(run / f"agent-{agent}.jsonl")
        if first is None:
            continue
        pane = pane_of(info["label"])
        phase = info["phase"]
        phase_start[phase] = min(phase_start.get(phase, first), first)
        raw.append((first, pane, "start", PHASES.get(phase, phase)))
        raw.extend((at, pane, kind, text) for at, kind, text in steps)
        if agent in results:
            raw.extend((last, pane, kind, text) for kind, text in result_lines(results[agent]))
            raw.append((last, pane, "done", "끝"))
            state[pane] = "done"
        else:
            state[pane] = "working"
    if not raw:
        return {"live": live, "run": run.name, "panes": PANES, "phases": [], "events": [], "end": 0}
    zero = min(r[0] for r in raw)
    raw.sort(key=lambda r: r[0])
    events = [{"t": round(at - zero, 1), "pane": pane, "kind": kind, "text": text} for at, pane, kind, text in raw]
    phases = sorted(({"t": round(at - zero, 1), "title": PHASES.get(p, p)} for p, at in phase_start.items()),
                    key=lambda p: p["t"])
    return {"live": live, "run": run.name, "at": datetime.fromtimestamp(zero).astimezone().isoformat(timespec="seconds"),
            "panes": PANES, "phases": phases, "events": events, "end": events[-1]["t"],
            "state": state}


def newest_run() -> Path | None:
    runs = sorted(PROJECTS.glob("*/*/subagents/workflows/wf_*/journal.jsonl"), key=lambda p: p.stat().st_mtime)
    return runs[-1].parent if runs else None


class Handler(http.server.SimpleHTTPRequestHandler):
    run: Path | None = None

    def do_GET(self):
        if self.path.split("?")[0] == "/data/panel/live.json":
            run = self.run or newest_run()
            body = json.dumps(build(run, live=True) if run else {"live": True, "events": []}, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def log_message(self, *args):
        pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("export")
    ex.add_argument("--run", type=Path, required=True)
    wa = sub.add_parser("watch")
    wa.add_argument("--run", type=Path)
    wa.add_argument("--port", type=int, default=8765)
    args = ap.parse_args(argv)
    if args.cmd == "export":
        data = build(args.run)
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"{len(data['events'])} events over {data['end']:.0f} s -> {OUT.relative_to(ROOT)}")
        return 0
    Handler.run = args.run
    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port),
                                             functools.partial(Handler, directory=str(ROOT)))
    print(f"http://127.0.0.1:{args.port}/panel.html  (live; Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
