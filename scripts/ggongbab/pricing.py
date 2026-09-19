# -*- coding: utf-8 -*-
"""Estimated API cost from token usage.

Only numeric usage metadata is used. Mail content is never stored or read to
compute a cost, so a cost report can never leak what was extracted.

Prices are a local copy of a published list and will drift. Everything here is
labelled "estimated" for that reason: it tells you the order of magnitude of a
run, not what OpenAI will actually bill. The authoritative number is on the
OpenAI billing dashboard.
"""
from __future__ import annotations

# USD per 1,000,000 tokens.
# Source: OpenAI standard pricing, recorded 2026-09-20. Update the date when
# the table changes; a stale table produces a wrong estimate, not an error.
MODEL_PRICING_USD_PER_MTOK = {
    "gpt-5.6-luna": {"input": 0.20, "output": 1.20},
    "gpt-5.6-terra": {"input": 2.00, "output": 12.00},
}
PRICING_AS_OF = "2026-09-20"

_MILLION = 1_000_000


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimated USD for one model's usage. An unpriced model contributes 0.0.

    Returning 0.0 for an unknown model is deliberate: a made-up price would be
    worse than an obviously missing one, and the summary says which models were
    left out.
    """
    price = MODEL_PRICING_USD_PER_MTOK.get(model)
    if not price:
        return 0.0
    return (input_tokens * price["input"] + output_tokens * price["output"]) / _MILLION


def is_priced(model: str) -> bool:
    return model in MODEL_PRICING_USD_PER_MTOK


def total_cost_usd(model_usage: dict[str, dict[str, int]]) -> float:
    return sum(estimate_cost_usd(model, u.get("input_tokens", 0), u.get("output_tokens", 0))
               for model, u in model_usage.items())


def usage_lines(model_usage: dict[str, dict[str, int]]) -> list[str]:
    """Per-model calls, tokens and estimated cost. Numbers only, no content."""
    if not model_usage:
        return []
    lines = ["AI usage:"]
    unpriced = []
    for model in sorted(model_usage):
        usage = model_usage[model]
        tokens_in = usage.get("input_tokens", 0)
        tokens_out = usage.get("output_tokens", 0)
        lines.append(f"  {model}")
        lines.append(f"    calls: {usage.get('calls', 0)}")
        lines.append(f"    input tokens: {tokens_in}")
        lines.append(f"    output tokens: {tokens_out}")
        if is_priced(model):
            lines.append(f"    estimated cost: ${estimate_cost_usd(model, tokens_in, tokens_out):.4f}")
        else:
            lines.append("    estimated cost: unknown (model not in price table)")
            unpriced.append(model)
    lines.append("")
    lines.append("Total estimated API cost:")
    lines.append(f"  ${total_cost_usd(model_usage):.4f}")
    lines.append(f"  (estimate only, prices as of {PRICING_AS_OF}; see the OpenAI billing dashboard)")
    if unpriced:
        lines.append(f"  excludes unpriced model(s): {', '.join(unpriced)}")
    return lines
