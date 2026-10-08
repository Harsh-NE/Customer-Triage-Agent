"""Evidence / confidence gate.

Explainable rule-based score so reviewers can see WHY a ticket was resolved or
escalated. B6 calibrates the weights and thresholds on the eval set.

confidence = w_top*top + w_margin*margin_n + w_agree*agreement + w_comp*completeness
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from triage.config import GateConfig
from triage.contracts import Evidence, ProblemSignature


@dataclass
class GateResult:
    confidence: float
    strong: bool
    top: float
    margin: float
    agreement: float
    completeness: float
    reasons: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def _family(doc_id: str) -> str:
    """'docs/desktop/networking.md#3' -> 'docs/desktop/networking.md'."""
    return re.split(r"[#]", doc_id)[0]


def _agrees(a: Evidence, b: Evidence) -> bool:
    if _family(a.doc_id) == _family(b.doc_id):
        return True
    ca, cb = a.metadata.get("component"), b.metadata.get("component")
    if ca and ca == cb:
        return True
    ta, tb = set(a.metadata.get("topics") or []), set(b.metadata.get("topics") or [])
    return bool(ta & tb)


def assess(evidence: list[Evidence], signature: ProblemSignature, cfg: GateConfig) -> GateResult:
    if not evidence:
        return GateResult(0.0, False, 0.0, 0.0, 0.0, signature.completeness, ["no_evidence"])
    top = evidence[0].rerank_score
    second = evidence[1].rerank_score if len(evidence) > 1 else 0.0
    margin = max(top - second, 0.0)
    margin_n = min(margin / 0.2, 1.0)
    pool = evidence[1:cfg.agreement_k]
    agreement = (sum(_agrees(evidence[0], e) for e in pool) / len(pool)) if pool else 1.0
    comp = max(0.0, min(signature.completeness, 1.0))
    w = cfg.weights
    conf = w["top"] * top + w["margin"] * margin_n + w["agreement"] * agreement + w["completeness"] * comp

    reasons = []
    if top < cfg.min_top_score:
        reasons.append(f"top_score {top:.2f} < {cfg.min_top_score}")
    if margin < cfg.min_margin and agreement < cfg.min_agreement:
        reasons.append("ambiguous: low margin and low agreement")
    if conf < cfg.resolve_confidence:
        reasons.append(f"confidence {conf:.2f} < {cfg.resolve_confidence}")
    strong = not reasons
    return GateResult(round(conf, 4), strong, top, round(margin, 4), round(agreement, 4), comp,
                      reasons or ["ok"])
