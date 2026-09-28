#!/usr/bin/env python3
"""Evaluate the Ggongbab stages against the gold set and the miss registry.

    python scripts/eval_ggongbab.py                      # deterministic stages, offline
    python scripts/eval_ggongbab.py --json               # the same, machine-readable
    python scripts/eval_ggongbab.py --ai luna --budget 40
    python scripts/eval_ggongbab.py --ai model:<name> --budget 20

Without --ai nothing leaves this machine. With --ai the samples (synthetic or sanitized,
see docs/GGONGBAB_DISCOVERY.md) go through the production sanitizer, prompt and
validator; --budget caps the number of model calls and is required. `luna` is the
configured primary model. `model:<name>` is an offline comparison only: it never
becomes a production fallback by being evaluated here.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ggongbab.config import KST, Settings  # noqa: E402
from ggongbab.parsers.rule_parser import (analyze, end_condition, explicit_food_evidence,  # noqa: E402
                                          extract_dates, extract_times, food_type_hint,
                                          registration_evidence, supply_limit)
from ggongbab.prefilter import classify  # noqa: E402

GOLD_DIR = ROOT / "tests/fixtures/ggongbab/gold"
MISS_DIR = ROOT / "tests/fixtures/ggongbab/misses"
REFERENCE = "2026-09-19T09:00:00+09:00"   # anchors year inference for gold samples without a mail time


def load_samples() -> list[dict]:
    samples = []
    for path in sorted(GOLD_DIR.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                samples.append(json.loads(line))
    for path in sorted(MISS_DIR.glob("MISS-*.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        want, rules = case["expected"], case["expected"]["rules"]
        samples.append({
            "id": case["id"], "kind": "miss", "subject": case["input"]["subject"], "body": case["input"]["body"],
            "received_at": case["input"]["received_at"],
            "expect": {"prefilter": want["prefilter"]["full_text_candidate"],
                       "food": want["validated"]["food_provided"], "food_type": want["validated"]["food_type"],
                       "registration": want["validated"]["registration_required"],
                       "supply": rules["supply_limited"], "end": rules["end_condition"],
                       "dates": rules["dates"], "times": rules["times"], "eligibility": want["validated"]["eligibility"],
                       "is_event": want["extraction"]["is_event"]}})
    return samples


def received(sample: dict) -> datetime:
    return datetime.fromisoformat(sample.get("received_at") or REFERENCE)


def ratio(hits: int, total: int):
    return round(hits / total, 4) if total else None


def evaluate_rules(samples: list[dict]) -> dict:
    """Prefilter and rule-parser accuracy. No network, no model."""
    miss: list[str] = []
    pre = Counter()
    food = Counter()
    fields = {name: Counter() for name in ("food_type", "registration", "supply", "end", "dates", "times")}
    for s in samples:
        want, text, ref = s["expect"], f"{s['subject']}\n{s['body']}", received(s)
        predicted = classify(s["subject"], s["body"], ref).candidate
        if want["prefilter"]:
            pre["positives"] += 1
            pre["found"] += predicted
            if not predicted:
                miss.append(f"{s['id']}: prefilter missed it")
        pre["candidates"] += predicted
        pre["correct_candidates"] += predicted and want["prefilter"]
        evidence = explicit_food_evidence(text)
        got_food = "true" if evidence else "unknown"
        if want["food"] == "true":
            food["expected"] += 1
            food["found"] += got_food == "true"
            if got_food != "true":
                miss.append(f"{s['id']}: no explicit food evidence found")
        elif got_food == "true":
            food["false_positive"] += 1
            miss.append(f"{s['id']}: food evidence on a non-provision text {evidence}")
        checks = {
            "food_type": (want.get("food_type"), food_type_hint(" ".join(evidence)) if evidence else "unknown")
            if want["food"] == "true" and want.get("food_type") else None,
            "registration": (want.get("registration"), registration_evidence(text)) if "registration" in want else None,
            "supply": (want.get("supply"), bool(supply_limit(text))) if "supply" in want else None,
            "end": (want.get("end"), end_condition(text)) if "end" in want else None,
            "dates": (True, set(want["dates"]) <= set(extract_dates(text, ref.date()))) if want.get("dates") else None,
            "times": (True, set(want["times"]) <= set(extract_times(text))) if want.get("times") else None,
        }
        for name, pair in checks.items():
            if pair is None:
                continue
            fields[name]["total"] += 1
            if pair[0] == pair[1]:
                fields[name]["correct"] += 1
            else:
                miss.append(f"{s['id']}: {name} expected {pair[0]!r}, got {pair[1]!r}")
    return {
        "samples": len(samples),
        "prefilter": {"recall": ratio(pre["found"], pre["positives"]),
                      "precision": ratio(pre["correct_candidates"], pre["candidates"]),
                      "candidates": pre["candidates"]},
        "rule_food": {"recall": ratio(food["found"], food["expected"]),
                      "precision": ratio(food["found"], food["found"] + food["false_positive"]),
                      "false_positives": food["false_positive"]},
        "fields": {name: ratio(c["correct"], c["total"]) for name, c in fields.items()},
        "mismatches": miss,
    }


def evaluate_ai(samples: list[dict], model: str, budget: int, extractor=None) -> dict:
    """The production path for up to `budget` samples: sanitizer -> prompt -> model -> validator."""
    from ggongbab.parsers.ai_parser import OpenAIExtractor, build_user_text
    from ggongbab.parsers.sanitizer import sanitize_for_ai
    from ggongbab.parsers.validator import validate
    from ggongbab.pricing import estimate_cost_usd

    if extractor is None:
        key = os.environ.get("OPENAI_API_KEY", "")
        if not key:
            raise SystemExit("OPENAI_API_KEY is not set; the AI stage needs it (nothing was sent)")
        extractor = OpenAIExtractor(key)
    tally, miss = Counter(), []
    tokens_in = tokens_out = 0
    for s in samples[:budget]:
        want, ref = s["expect"], received(s)
        body = sanitize_for_ai(s["body"])
        facts = analyze(f"{s['subject']}\n{body}", ref)
        text = build_user_text(subject=sanitize_for_ai(s["subject"]), body=body,
                               sent_at=ref.isoformat(timespec="minutes"), source_label="dooray")
        result = extractor.extract(text, [], model)
        tally["calls"] += 1
        tokens_in += result.usage.input_tokens
        tokens_out += result.usage.output_tokens
        if result.extraction is None:
            tally["errors"] += 1
            miss.append(f"{s['id']}: model error {result.category}")
            continue
        cand = validate(result.extraction, facts, body, source_type="dooray", reference=ref)
        row = cand.to_db_row()
        tally["review"] += row["needs_review"]
        comparisons = {
            "is_event": (want.get("is_event"), cand.is_event),
            "food_provided": (want["food"], row["food_provided"] if cand.is_event else "unknown"),
            "food_type": (want.get("food_type"), row["food_type"]) if want["food"] == "true" and want.get("food_type") else None,
            "registration": (want.get("registration"), row["registration_required"]) if "registration" in want else None,
            "eligibility": (want.get("eligibility"), row["eligibility"]) if "eligibility" in want else None,
            "date": (want["dates"][0], (row["event_start"] or "")[:10]) if want.get("dates") and cand.is_event else None,
            "time": (want["times"][0], (row["event_start"] or "")[11:16]) if want.get("times") and cand.is_event else None,
        }
        if want["food"] == "true":
            tally["food_expected"] += 1
            tally["food_found"] += row["food_provided"] == "true" and not row["needs_review"]
        elif row["food_provided"] == "true" and not row["needs_review"] and cand.is_event:
            tally["false_publication"] += 1
            miss.append(f"{s['id']}: would publish food on a non-provision text")
        for name, pair in comparisons.items():
            if pair is None or pair[0] is None and name != "eligibility":
                continue
            tally[f"{name}_total"] += 1
            if pair[0] == pair[1]:
                tally[f"{name}_correct"] += 1
            else:
                miss.append(f"{s['id']}: {name} expected {pair[0]!r}, got {pair[1]!r}")
    names = ("is_event", "food_provided", "food_type", "registration", "eligibility", "date", "time")
    return {
        "model": model, "calls": tally["calls"], "errors": tally["errors"],
        "free_food_recall": ratio(tally["food_found"], tally["food_expected"]),
        "false_publications": tally["false_publication"],
        "review_rate": ratio(tally["review"], tally["calls"] - tally["errors"]),
        "fields": {n: ratio(tally[f"{n}_correct"], tally[f"{n}_total"]) for n in names},
        "tokens": {"input": tokens_in, "output": tokens_out},
        "estimated_cost_usd": round(estimate_cost_usd(model, tokens_in, tokens_out), 4),
        "mismatches": miss,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument("--ai", help="'luna' (the configured primary model) or 'model:<name>' for an offline comparison")
    parser.add_argument("--budget", type=int, default=0, help="maximum number of model calls (required with --ai)")
    args = parser.parse_args(argv)
    samples = load_samples()
    report = {"generated_at": datetime.now(KST).isoformat(timespec="seconds"), "rules": evaluate_rules(samples)}
    if args.ai:
        if args.budget < 1:
            parser.error("--ai needs --budget N (N >= 1); nothing was sent")
        model = Settings().ai_model if args.ai == "luna" else args.ai.removeprefix("model:")
        report["ai"] = evaluate_ai(samples, model, args.budget)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    rules = report["rules"]
    print(f"samples: {rules['samples']}")
    print(f"prefilter  recall {rules['prefilter']['recall']}  precision {rules['prefilter']['precision']}")
    print(f"rule food  recall {rules['rule_food']['recall']}  precision {rules['rule_food']['precision']}"
          f"  false positives {rules['rule_food']['false_positives']}")
    for name, value in rules["fields"].items():
        print(f"  {name:13s} {value}")
    for line in rules["mismatches"]:
        print(f"  - {line}")
    if "ai" in report:
        ai = report["ai"]
        print(f"\nmodel {ai['model']}: calls {ai['calls']} errors {ai['errors']} review rate {ai['review_rate']}")
        print(f"free-food recall {ai['free_food_recall']}  false publications {ai['false_publications']}")
        for name, value in ai["fields"].items():
            print(f"  {name:13s} {value}")
        print(f"tokens in {ai['tokens']['input']} out {ai['tokens']['output']}  ~${ai['estimated_cost_usd']}")
        for line in ai["mismatches"]:
            print(f"  - {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
