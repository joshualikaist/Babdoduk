"""Salvage of an interrupted panel run: synthetic journals only, no provider."""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/panel"))
for name in ("salvage", "publish"):
    spec = importlib.util.spec_from_file_location(f"panel_{name}", ROOT / f"scripts/panel/{name}.py")
    globals()[name] = module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)


def finding(title, severity=2):
    return {"title": title, "page": "index.html", "device": "iphone", "evidence": "facts.json", "shot": "index-iphone.jpg",
            "standard": "닐슨 4번", "severity": severity, "detail": "자세히", "fix": "이렇게", "ask": ""}


def journal(tmp_path, rows):
    (tmp_path / "journal.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return tmp_path


def rows(*, merged=True):
    out = [{"type": "launched"}]
    for agent, label in (("a1", "review:designer1"), ("a2", "review:developer1"), ("a3", "review:copy1")):
        out.append({"type": "started", "agentId": agent, "label": label, "phase": "Review"})
    out += [{"type": "result", "agentId": "a1", "result": {"summary": "디자인", "findings": [finding("잘림", 3), finding("간격", 1)]}},
            {"type": "result", "agentId": "a2", "result": {"summary": "개발", "findings": [finding("느림", 2)]}},
            {"type": "result", "agentId": "a3", "result": {"summary": "문구", "findings": [finding("말투", 2)]}},
            {"type": "started", "agentId": "c1", "label": "critic:merge", "phase": "Critic"}]
    if merged:
        groups = [{"gid": "g1", "title": "잘림", "fids": ["designer1-1", "developer1-1"], "verdict": "accept", "severity": 3, "note": "맞아요"},
                  {"gid": "g2", "title": "말투", "fids": ["copy1-1"], "verdict": "accept", "severity": 2, "note": "맞아요"},
                  {"gid": "g3", "title": "간격", "fids": ["designer1-2"], "verdict": "reject", "severity": 1, "note": "아니에요"}]
        out.append({"type": "result", "agentId": "c1", "result": {"groups": groups}})
    out += [{"type": "started", "agentId": "d1", "label": "discuss:designer", "phase": "Discuss"}]
    return out


def test_finished_reviews_and_the_critics_merge_are_kept_and_ranked(tmp_path):
    result = salvage.salvage(journal(tmp_path, rows()))
    assert [r["id"] for r in result["reviews"]] == ["designer", "developer", "copy"]
    assert [f["fid"] for f in result["all"]] == ["designer1-1", "designer1-2", "developer1-1", "copy1-1"]
    assert result["replies"] == [] and result["comments"] == []
    assert result["final"]["top"] == ["g1", "g2"]  # g1: severity 3 x two reviewers, rejected g3 is not ranked
    assert "중간에 멈췄어요" in result["final"]["overall"] and "최종 판정은 하지 못했어요" in result["final"]["overall"]


def test_nothing_is_salvaged_without_a_critic_merge_or_reviews(tmp_path, capsys):
    assert salvage.salvage(journal(tmp_path, rows(merged=False))) is None
    other = tmp_path / "empty"
    other.mkdir()
    journal(other, [{"type": "launched"}])
    out = tmp_path / "result.json"
    assert salvage.main(["--run", str(other), "--out", str(out)]) == 3 and not out.exists()


def test_the_salvaged_result_publishes_without_discussion(tmp_path):
    result = salvage.salvage(journal(tmp_path, rows()))
    report, shots = publish.build(result, {"at": "2026-11-26T23:35:00+09:00", "base": "x", "pages": {"index.html": {"iphone": {}}}})
    assert [t["id"] for t in report["threads"]] == ["g1", "g2", "g3"]
    assert report["top"] == ["g1", "g2"] and "중간에 멈췄어요" in report["overall"]
    assert report["threads"][0]["by"] == ["designer", "developer"] and shots == {"index-iphone"}


def test_the_runner_publishes_an_interrupted_run_and_keeps_the_usage_wait():
    script = (ROOT / "scripts/panel/auto.sh").read_text(encoding="utf-8")
    assert "scripts/panel/salvage.py" in script
    assert script.index("salvage.py") < script.index("usage limit reached; wait for the next explicit start request")
    # After a usage-limit stop the wait is recorded again after publishing, not replaced by "complete".
    tail = script[script.index('if [ "$limited" = 1 ]; then\n  "$PY"'):]
    assert "auto_state.py\" --result" in tail and "phase complete" in tail
