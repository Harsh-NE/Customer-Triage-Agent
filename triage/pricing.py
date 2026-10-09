"""pricing.py -- what an LLM call cost, from triage/pricing.json (USD per 1M tokens, with its source and date).

A model that is not in the table has NO price: cost_usd() returns None (never 0, never a guess), so the dashboard can say
"n calls unpriced" instead of silently under-reporting. Point PRICING_FILE at another JSON file to override the table.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

DEFAULT_FILE = Path(__file__).with_name("pricing.json")


@lru_cache(maxsize=4)
def _table(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def table() -> dict:
    return _table(os.environ.get("PRICING_FILE") or str(DEFAULT_FILE))


def normalize(model: str) -> str:
    """'google/gemini-3.5-flash-lite' and 'gemini-3.5-flash-lite' are the same model."""
    return (model or "").strip().lower().split("/")[-1]


def price_for(model: str) -> Optional[dict]:
    return table().get("models", {}).get(normalize(model))


def cost_usd(model: str, usage: dict) -> Optional[float]:
    """usage: {input_tokens, output_tokens, cached_input_tokens?}. None when the model is unpriced."""
    p = price_for(model)
    if p is None:
        return None
    inp = int(usage.get("input_tokens") or 0)
    out = int(usage.get("output_tokens") or 0)
    cached = min(int(usage.get("cached_input_tokens") or 0), inp)
    cached_rate = p.get("cached_input", p["input"])
    return round(((inp - cached) * p["input"] + cached * cached_rate + out * p["output"]) / 1e6, 8)
