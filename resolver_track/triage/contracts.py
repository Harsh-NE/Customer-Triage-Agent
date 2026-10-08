"""Phase 0 shared contracts — the ONLY coupling between Member A and Member B.

Ownership (per workplan):
  * ProblemSignature  -> drafted by A (Clarifier output), reviewed by B
  * TriageRecord      -> drafted by A (A7), reviewed by B
  * Evidence + Retriever interface -> owned by B, called by both

Everything here is plain dataclasses / enums so either side can import it without
pulling in LangGraph, an LLM client or a vector store.

Rule for changes after Phase 0: add optional fields only; never rename or remove a
field without agreeing with the other member (the merge in J1 depends on it).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional, TypedDict
import uuid


# --------------------------------------------------------------------------- enums
class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class GateDecision(str, Enum):
    RESOLVE = "resolve"          # evidence strong enough to draft a fix
    FALLBACK = "fallback"        # KB weak -> try Tier 2 historical tickets
    CLARIFY = "clarify"          # signature too incomplete -> hand back to Clarifier
    ESCALATE = "escalate"        # go to a human engineer


class ReplyLabel(str, Enum):
    RESOLVED = "resolved"
    NOT_FIXED = "not_fixed"
    NEW_INFO = "new_info"        # customer added facts -> Clarifier should re-normalise
    OFF_TOPIC = "off_topic"


class CacheStatus(str, Enum):
    MISS = "miss"
    HIT_EXACT = "hit_exact"
    HIT_SEMANTIC = "hit_semantic"          # reuse answer as-is
    HIT_REDRAFT = "hit_redraft"            # reuse evidence, re-draft answer
    BYPASSED = "bypassed"


class Outcome(str, Enum):
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    ESCALATED = "escalated"
    NEEDS_CLARIFICATION = "needs_clarification"
    REJECTED = "rejected"                  # blocked by an input guardrail


class EscalationReason(str, Enum):
    LOW_EVIDENCE = "LOW_EVIDENCE"
    CRITICAL_SEVERITY = "CRITICAL_SEVERITY"
    SECURITY_OR_DATA_LOSS = "SECURITY_OR_DATA_LOSS"
    RETRY_EXHAUSTED = "RETRY_EXHAUSTED"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    CLARIFY_LOOP_EXHAUSTED = "CLARIFY_LOOP_EXHAUSTED"


Tier = Literal["kb", "tickets"]


# --------------------------------------------------------------------------- A -> B
@dataclass
class ProblemSignature:
    """Normalised description of the customer's problem (Clarifier output).

    B depends on: product_area, component, error_strings, exit_codes, severity,
    completeness, missing_fields, and raw_query (for BM25).
    """
    raw_query: str
    product_area: Optional[str] = None          # e.g. "docker-desktop", "compose"
    component: Optional[str] = None             # e.g. "networking", "build", "volumes"
    symptom: Optional[str] = None               # short normalised symptom phrase
    error_strings: list[str] = field(default_factory=list)
    exit_codes: list[int] = field(default_factory=list)
    versions: dict[str, str] = field(default_factory=dict)   # {"docker": "24.0.7"}
    environment: dict[str, str] = field(default_factory=dict)  # {"os": "windows", "wsl": "2"}
    severity: Severity = Severity.MEDIUM
    security_or_data_loss: bool = False
    missing_fields: list[str] = field(default_factory=list)
    completeness: float = 0.0                   # 0..1, set by A's understand.py
    clarify_turns: int = 0

    def search_text(self) -> str:
        """Text used for retrieval. Error strings first: BM25 loves exact codes."""
        parts = [*self.error_strings, self.symptom or "", self.component or "",
                 self.product_area or "", self.raw_query]
        return " ".join(p for p in parts if p).strip()

    def cache_key_text(self) -> str:
        """Canonical, order-stable string used by the semantic cache."""
        errs = "|".join(sorted(e.lower().strip() for e in self.error_strings))
        codes = "|".join(str(c) for c in sorted(self.exit_codes))
        return " ; ".join([
            f"product={(self.product_area or '').lower()}",
            f"component={(self.component or '').lower()}",
            f"errors={errs}",
            f"exit={codes}",
            f"symptom={(self.symptom or '').lower().strip()}",
        ])

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ProblemSignature":
        d = dict(d)
        if "severity" in d and not isinstance(d["severity"], Severity):
            d["severity"] = Severity(d["severity"])
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["severity"] = self.severity.value
        return d


# --------------------------------------------------------------------------- B -> both
@dataclass
class Evidence:
    """One retrieved passage. evidence_id is what the Resolver cites ("E1")."""
    evidence_id: str
    chunk_id: str
    doc_id: str
    tier: Tier
    text: str
    url: str = ""
    source: str = ""
    parent_text: Optional[str] = None
    trust: Optional[float] = None               # Tier 2 only (trust_score)
    fused_score: float = 0.0
    rerank_score: float = 0.0                   # normalised to 0..1 by the retriever
    doc_hash: str = ""                          # for cache invalidation
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def full_text(self) -> str:
        return self.parent_text or self.text

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Evidence":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


# --------------------------------------------------------------------------- record
@dataclass
class ResolutionStep:
    text: str
    evidence_ids: list[str]


@dataclass
class Attempt:
    attempt_no: int
    diagnosis: str
    steps: list[ResolutionStep]
    evidence_ids: list[str]
    tier: Tier
    customer_reply: Optional[str] = None
    reply_label: Optional[ReplyLabel] = None


@dataclass
class TriageRecord:
    """Written for EVERY ticket regardless of outcome (A7, reviewed by B)."""
    ticket_id: str = field(default_factory=lambda: f"TR-{uuid.uuid4().hex[:12]}")
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    signature: Optional[dict[str, Any]] = None
    transcript: list[dict[str, str]] = field(default_factory=list)   # [{"role","content"}]
    # ---- B-owned fields
    evidence_used: list[dict[str, Any]] = field(default_factory=list)
    attempts: list[dict[str, Any]] = field(default_factory=list)
    confidence: Optional[float] = None
    gate_decision: Optional[str] = None
    cache_status: str = CacheStatus.MISS.value
    escalation_reason: Optional[str] = None
    escalation_payload: Optional[dict[str, Any]] = None
    outcome: str = Outcome.IN_PROGRESS.value
    human_confirmed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------- graph state
class TriageState(TypedDict, total=False):
    """Shared LangGraph state. A writes `signature`; B writes everything below it.

    Keys must stay JSON-serialisable (dicts, lists, str, numbers) so the
    checkpointer can persist conversations between customer turns.
    """
    # --- written by A / the entry point
    ticket_id: str
    customer_message: str
    signature: dict[str, Any]
    transcript: list[dict[str, str]]
    # --- written by B
    evidence: list[dict[str, Any]]
    tier: str
    confidence: float
    gate_decision: str
    gate_detail: dict[str, Any]
    cache_status: str
    cache_entry_id: Optional[str]
    draft: Optional[dict[str, Any]]
    attempts: list[dict[str, Any]]
    tried_evidence_ids: list[str]
    reply_label: Optional[str]
    last_assistant_message: str
    off_topic_count: int
    clarify_returns: int          # times the Resolver handed back to the Clarifier
    escalation_reason: Optional[str]
    escalation_payload: Optional[dict[str, Any]]
    outcome: str
    next: str                    # routing hint for the parent graph: "clarifier" | "end"
