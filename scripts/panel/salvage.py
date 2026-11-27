#!/usr/bin/env python3
"""Rebuild a review panel result from an interrupted workflow's journal (docs/PANEL.md).

    python scripts/panel/salvage.py --run <.../subagents/workflows/wf_*> --out <result.json>

A run that stops early (usage limit, killed process) returns nothing, although the reviewers and the critic's
first merge may already be finished and written to `journal.jsonl`. This keeps those parts, leaves out the
discussion, replies and final verdict that never happened, ranks the accepted groups with the workflow's own
rule (severity x number of reviewers, plus one when the designer or developer raised it) and says so in the
overall text. When even the critic's merge is missing (stopped during the first phase), each finding becomes its
own group, all left as questions, with no ranking. Exit 0 when a result was written, 3 when no review finished.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

OVERALL = ("이번 평가는 중간에 멈췄어요({why}). 평가자들의 지적과 비판자의 1차 판정까지만 끝났고, "
           "서로 의견을 나누는 단계와 최종 판정은 하지 못했어요. 그래서 질문으로 남은 것은 답을 못 받았고, "
           "순위는 심각도 × 말한 평가자 수로 계산했어요.")


UNMERGED = ("이번 평가는 중간에 멈췄어요({why}). 평가자들의 지적까지만 끝났고, 비판자가 합치거나 확인하지 못했어요. "
            "그래서 지적은 모두 질문으로 두었고 순위는 없어요.")
UNMERGED_NOTE = "시간이 모자라 비판자가 확인하기 전이에요. 평가자가 쓴 그대로 보여 드려요."


def load(run: Path) -> tuple[dict[str, str], dict[str, dict]]:
    labels, results = {}, {}
    for line in (run / "journal.jsonl").read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("type") == "started":
            labels[row["agentId"]] = row.get("label", "")
        elif row.get("type") == "result" and isinstance(row.get("result"), dict):
            results[row["agentId"]] = row["result"]
    return labels, results


def salvage(run: Path, why: str = "사용량 한도") -> dict | None:
    labels, results = load(run)
    reviews, groups = [], None
    for agent, label in labels.items():
        out = results.get(agent)
        if not out:
            continue
        kind, _, who = label.partition(":")
        if kind == "review" and isinstance(out.get("findings"), list):
            match = re.fullmatch(r"([a-z]+)(\d+)", who)
            if match:
                reviews.append({"id": match[1], "run": int(match[2]), **out})
        elif label == "critic:merge" and isinstance(out.get("groups"), list):
            groups = out["groups"]
    if not reviews:
        return None
    order = {"designer": 0, "developer": 1, "copy": 2, "founder": 3}
    reviews.sort(key=lambda r: (order.get(r["id"], 9), r["run"]))
    everything = [{**f, "fid": f"{r['id']}{r['run']}-{i}", "from": r["id"]}
                  for r in reviews for i, f in enumerate(r["findings"], 1)]
    by_fid = {f["fid"]: f for f in everything}
    merged = bool(groups)
    if not merged:
        groups = [{"gid": f"g{n}", "title": f["title"], "fids": [f["fid"]], "verdict": "question",
                   "severity": f["severity"], "note": UNMERGED_NOTE} for n, f in enumerate(everything, 1)]

    def raised_by(group):
        return list(dict.fromkeys(by_fid[i]["from"] for i in group["fids"] if i in by_fid))

    accepted = [g for g in groups if g.get("verdict") == "accept" and raised_by(g)]
    accepted.sort(key=lambda g: (-(g["severity"] * len(raised_by(g))
                                   + (1 if {"designer", "developer"} & set(raised_by(g)) else 0)), -g["severity"]))
    return {"reviews": reviews, "all": everything, "groups": groups, "replies": [], "comments": [],
            "final": {"verdicts": [], "top": [g["gid"] for g in accepted[:10]],
                      "overall": (OVERALL if merged else UNMERGED).format(why=why)}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--why", default="사용량 한도")
    args = ap.parse_args(argv)
    result = salvage(args.run, args.why)
    if result is None:
        print("nothing to salvage: no review finished", file=sys.stderr)
        return 3
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"salvaged {len(result['reviews'])} reviews, {len(result['all'])} findings, {len(result['groups'])} groups")
    return 0


if __name__ == "__main__":
    sys.exit(main())
