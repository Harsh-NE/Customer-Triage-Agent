"""features.py -- the three switches that define an ablation arm, so every arm runs the same code.

    use_kg              the knowledge graph: alias and entity matching in retrieval, and what the Clarifier infers from it
    use_jev             the Jev decision layer (triage/jev.py)
    use_semantic_cache  the cache of confirmed fixes and the negative cache of failed ones

Unset, they leave the system as it was: KG on (unless ONTOLOGY_MODE=off), Jev off, cache on.
Set USE_KG, USE_JEV or USE_SEMANTIC_CACHE to 0 or 1 to override, or pass a Features to build_default_deps.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass

_ON, _OFF = ("1", "on", "true", "yes"), ("0", "off", "false", "no")


def _flag(name: str, default: bool) -> bool:
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    if value not in _ON + _OFF:                  # a typo must not silently run the wrong arm
        raise ValueError(f"{name} must be one of {_ON + _OFF}, got '{value}'")
    return value in _ON


@dataclass(frozen=True)
class Features:
    use_kg: bool = True
    use_jev: bool = False
    use_semantic_cache: bool = True

    @classmethod
    def from_env(cls) -> "Features":
        return cls(use_kg=_flag("USE_KG", os.environ.get("ONTOLOGY_MODE", "both") != "off"),
                   use_jev=_flag("USE_JEV", False),
                   use_semantic_cache=_flag("USE_SEMANTIC_CACHE", True))

    def to_dict(self) -> dict:
        return asdict(self)


# The three-stage ablation: plain RAG, then + knowledge graph, then + Jev decision layer.
ARMS = {"A": Features(use_kg=False), "B": Features(), "C": Features(use_jev=True)}
ARM_NAMES = {"A": "baseline (no KG, no Jev)", "B": "+ KG", "C": "+ KG + Jev"}
