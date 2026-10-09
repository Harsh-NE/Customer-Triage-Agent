"""All tunable numbers in one place.

Every threshold here is a STARTING GUESS. B6 (confidence calibration) and B4
(cache calibration) replace them with values chosen from the eval set; record the
chosen values and the report that justified them in docs/.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class GateConfig:
    min_top_score: float = 0.55        # top rerank score (0..1) needed to resolve
    min_margin: float = 0.05           # top1 - top2; tiny margins mean ambiguity
    min_agreement: float = 0.4         # share of top-k agreeing with top1 (same doc/component)
    min_completeness: float = 0.5      # below this, send back to Clarifier
    resolve_confidence: float = 0.6    # combined confidence needed to draft
    weights: dict = field(default_factory=lambda: {
        "top": 0.45, "margin": 0.15, "agreement": 0.2, "completeness": 0.2})
    agreement_k: int = 5


@dataclass
class CacheConfig:
    upper: float = 0.92                # >= upper: reuse answer as-is
    lower: float = 0.85                # lower..upper: reuse evidence, re-draft
    require_confirmed: bool = True     # only cache customer/human-confirmed fixes


@dataclass
class ResolverConfig:
    k: int = 8
    max_attempts: int = 2              # fixes tried before RETRY_EXHAUSTED
    max_clarify_returns: int = 2       # times we may bounce back to the Clarifier
    use_ticket_fallback: bool = True
    gate: GateConfig = field(default_factory=GateConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)

    @classmethod
    def load(cls, path: str | os.PathLike | None = None) -> "ResolverConfig":
        path = path or os.getenv("RESOLVER_CONFIG")
        if not path or not Path(path).exists():
            return cls()
        raw = json.loads(Path(path).read_text())
        cfg = cls(**{k: v for k, v in raw.items() if k not in ("gate", "cache")})
        if "gate" in raw:
            cfg.gate = GateConfig(**raw["gate"])
        if "cache" in raw:
            cfg.cache = CacheConfig(**raw["cache"])
        return cfg

    def to_dict(self) -> dict:
        return asdict(self)
