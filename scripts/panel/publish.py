#!/usr/bin/env python3
"""Turn a review panel run into the lab page's data (docs/PANEL.md).

    python scripts/panel/publish.py --result <workflow result.json> --capture .local/panel/<run>

Writes data/panel/latest.json (the conversation, as plain text) and data/panel/shots/*.webp (480 px wide
copies of only the screenshots a thread cites). Old shots are removed so the folder holds one run.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "panel"
SHOT_WIDTH = 480
SHOT_MAX_HEIGHT = 2400
MEMBERS = [
    {"id": "designer", "name": "디자이너", "emoji": "🎨", "role": "시각 디자인과 사용성 (두 번 평가)"},
    {"id": "developer", "name": "개발자", "emoji": "🛠️", "role": "속도, 오류, 접근성, 유지보수 (두 번 평가)"},
    {"id": "copy", "name": "문구 담당", "emoji": "✍️", "role": "한국어 문장"},
    {"id": "founder", "name": "창업가", "emoji": "🚀", "role": "다시 오고 알리게 만드는 힘"},
    {"id": "critic", "name": "비판자", "emoji": "🧐", "role": "증거 확인, 합치기, 순위"},
]
WEIGHT = {"designer": 0, "developer": 1, "copy": 2, "founder": 3}
STANCE = {"agree": "[동의]", "disagree": "[반대]", "add": "[보탬]"}
EFFORT = {"small": "고치는 품: 작음", "medium": "고치는 품: 중간", "large": "고치는 품: 큼"}


def shot_name(name: str) -> str:
    stem = Path(name or "").stem
    return stem if re.fullmatch(r"[a-z0-9]+-(iphone|android|desktop)", stem) else ""


def finding_text(f: dict) -> str:
    parts = [f["title"], f["detail"], f"근거: {f['evidence']} ({f['standard']})"]
    if f.get("fix"):
        parts.append(f"고칠 방법: {f['fix']}")
    return "\n\n".join(p.strip() for p in parts if p and p.strip())


def build(result: dict, facts: dict) -> tuple[dict, set[str]]:
    findings = {f["fid"]: f for f in result["all"]}
    replies, comments = {}, {}
    for r in result.get("replies") or []:
        replies.setdefault(r["gid"], []).append(r)
    for c in result.get("comments") or []:
        comments.setdefault(c["gid"], []).append(c)
    final = result.get("final") or {}
    verdicts = {v["gid"]: v for v in final.get("verdicts") or []}
    threads, shots = [], set()
    for g in result["groups"]:
        own = [findings[i] for i in g["fids"] if i in findings]
        if not own:
            continue
        own.sort(key=lambda f: (WEIGHT.get(f["from"], 9), -f["severity"]))
        messages = [{"from": f["from"], "kind": "finding", "text": finding_text(f)} for f in own]
        messages.append({"from": "critic", "kind": "question" if g["verdict"] == "question" else "verdict", "text": g["note"]})
        verdict, severity, decision = g["verdict"], g["severity"], ""
        for r in replies.get(g["gid"], []):
            messages.append({"from": r["from"], "kind": "reply", "text": r["text"]})
        for c in sorted(comments.get(g["gid"], []), key=lambda c: WEIGHT.get(c["from"], 9)):
            label = STANCE.get(c["stance"], "")
            effort = EFFORT.get(c.get("effort"), "")
            messages.append({"from": c["from"], "kind": "comment",
                             "text": f"{label} {c['text'].strip()}" + (f"\n\n{effort}" if effort else "")})
        if g["gid"] in verdicts:
            v = verdicts[g["gid"]]
            if g["verdict"] == "question" or comments.get(g["gid"]):
                messages.append({"from": "critic", "kind": "verdict", "text": v["note"]})
            verdict, severity = v["verdict"], v["severity"]
            if comments.get(g["gid"]) or g["verdict"] == "question":
                decision = v["note"]
        shot = next((shot_name(f.get("shot")) for f in own if shot_name(f.get("shot"))), "")
        if shot:
            shots.add(shot)
        threads.append({
            "id": g["gid"], "title": g["title"], "severity": severity, "verdict": verdict,
            "by": list(dict.fromkeys(f["from"] for f in own)),
            "page": own[0]["page"], "device": own[0]["device"],
            "shot": f"data/panel/shots/{shot}.webp" if shot else "",
            "fix": next((f["fix"] for f in own if f.get("fix")), ""),
            "decision": decision,
            "ask": next((f["ask"] for f in own if f.get("ask")), ""),
            "messages": messages,
        })
    order = {"accept": 0, "question": 1, "reject": 2}
    threads.sort(key=lambda t: (order.get(t["verdict"], 3), -t["severity"], -len(t["by"])))
    accepted = {t["id"] for t in threads if t["verdict"] == "accept"}
    summary = {}
    for review in result.get("reviews") or []:
        summary.setdefault(review["id"], review["summary"])
    report = {
        "run": {"at": facts.get("at", ""), "base": facts.get("base", ""), "pages": len(facts.get("pages", {})),
                "views": sum(len(d) for d in facts.get("pages", {}).values())},
        "overall": final.get("overall", ""),
        "members": MEMBERS,
        "summary": summary,
        "top": [g for g in final.get("top") or [] if g in accepted][:10],
        "threads": threads,
    }
    return report, shots


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--result", type=Path, required=True)
    ap.add_argument("--capture", type=Path, required=True)
    args = ap.parse_args(argv)
    result = json.loads(args.result.read_text(encoding="utf-8"))
    facts = json.loads((args.capture / "facts.json").read_text(encoding="utf-8"))
    report, shots = build(result, facts)
    (OUT / "shots").mkdir(parents=True, exist_ok=True)
    for old in (OUT / "shots").glob("*.webp"):
        if old.stem not in shots:
            old.unlink()
    for name in sorted(shots):
        src = args.capture / "shots" / f"{name}.jpg"
        if not src.is_file():
            continue
        with Image.open(src) as im:
            im = im.convert("RGB")
            height = round(im.height * SHOT_WIDTH / im.width)
            im = im.resize((SHOT_WIDTH, height), Image.LANCZOS).crop((0, 0, SHOT_WIDTH, min(height, SHOT_MAX_HEIGHT)))
            im.save(OUT / "shots" / f"{name}.webp", "WEBP", quality=72, method=6)
    (OUT / "latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    counts = {v: sum(1 for t in report["threads"] if t["verdict"] == v) for v in ("accept", "question", "reject")}
    print(f"{len(report['threads'])} threads {counts}, top {len(report['top'])}, shots {len(shots)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
