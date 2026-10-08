"""
state.py -- A7: the shared data contracts (Phase 0) for the triage agents.

This file is the single hand-off surface between Member A's Clarifier and Member B's
Resolver / cache / logging. Everything that crosses that boundary is defined here and
nowhere else:

  ExtractedFields    what we understood from the customer so far
  Candidate          one retrieved KB chunk (the Retrieval interface's return type)
  Hypothesis         one candidate *cause* -- retrieved chunks grouped into an issue
  ProblemSignature   Clarifier -> Resolver hand-off (and the semantic-cache key)
  NeedClarification  Resolver -> Clarifier callback ("I need field X to continue")
  TriageRecord       the durable per-ticket record every ticket writes on close

SCHEMA_VERSION is bumped on any breaking change; both members' code should assert on it.
Plain stdlib dataclasses on purpose (no pydantic) -- JSON round-trips via to_dict/from_dict.
"""

from __future__ import annotations

import dataclasses
import types
import typing
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

SCHEMA_VERSION = "1.0.0"

SEVERITY_LEVELS = ["Low", "Medium", "High", "Critical"]
FRUSTRATION_LEVELS = ["Low", "Medium", "High"]
IMPACT_SCOPE_LEVELS = ["Individual", "Team", "Organization", "Unknown"]
PLATFORMS = ["windows", "mac", "linux"]


class ClarifierStatus(str, Enum):
    ASK = "ask"                # a question for the customer is pending; wait for the reply
    READY = "ready"            # enough context; signature is confident, hand off to Resolver
    UNRESOLVED = "unresolved"  # budget spent (or nothing left to ask) but still ambiguous;
                               # signature + ranked hypotheses are attached, Resolver decides


class Outcome(str, Enum):
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    ESCALATED = "escalated"
    ABANDONED = "abandoned"


# ---------------------------------------------------------------------------
# Understanding
# ---------------------------------------------------------------------------

@dataclass
class ExtractedFields:
    product_area: str | None = None       # normalized to the KB taxonomy when possible
    component: str | None = None
    symptoms: list[str] = field(default_factory=list)       # short, lowercased, de-duplicated
    error_messages: list[str] = field(default_factory=list)  # verbatim lines (regex, never LLM)
    error_codes: list[str] = field(default_factory=list)     # "HTTP 429 response code", "exit code 137"
    platform: str | None = None           # one of PLATFORMS
    environment: str | None = None        # free text OS/setup detail
    versions: dict[str, str] = field(default_factory=dict)   # {"docker desktop": "4.30.0"}
    category: str | None = None           # optional; kept for contract continuity with 09_understand.py
    severity: str = "Medium"
    frustration: str = "Medium"
    impact_scope: str = "Unknown"


@dataclass
class Gap:
    field: str          # which ExtractedFields attribute is missing
    hard: bool          # hard = cannot search without it; soft = would help, may be skippable
    reason: str


# ---------------------------------------------------------------------------
# Retrieval interface types (what the Retriever contract returns)
# ---------------------------------------------------------------------------

@dataclass
class TicketHit:
    """One historical resolved ticket (Tier 2) -- COMMUNITY evidence, never official documentation. Returned by
    triage.hybrid.TicketRetriever. `score` is in (0, 1], higher is better, and already folds in trust, resolution kind,
    recency and exact error / exit-code matches; `matched` says why it ranked where it did."""
    ticket_id: str
    title: str
    problem_excerpt: str              # first ~400 chars of the problem
    resolution: str                   # FULL resolution; trim with triage.hybrid.render_ticket_card
    score: float
    url: str = ""
    license: str = ""
    source: str = ""                  # stackoverflow | github/docker/compose | forums.docker.com | ...
    source_type: str = ""
    trust_tier: str = ""              # high | medium | low
    trust_score: float = 0.0
    resolution_kind: str = ""
    kind_guess: str = ""              # troubleshooting | how_to | concept
    age_years: float | None = None
    topics: list[str] = field(default_factory=list)
    error_lines: list[str] = field(default_factory=list)     # cleaned, error-looking lines only
    exit_codes: list[str] = field(default_factory=list)
    docker_versions: list[str] = field(default_factory=list)
    matched: list[str] = field(default_factory=list)         # "vector", "bm25", "exit_code:137", "error_line", "topic:build"

@dataclass
class Candidate:
    chunk_id: str
    text: str
    score: float                     # CONTRACT: higher is better, normalized to (0, 1]
    source_path: str = ""
    article_title: str = ""
    heading_path: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)  # product_area, component, doc_kind, error_signals...


@dataclass
class Hypothesis:
    """One candidate cause: retrieved chunks that belong to the same KB issue."""
    key: str                          # "<source_path>::<issue title>"
    label: str                        # "<article> > <issue>"
    weight: float                     # probability over the full retrieved pool. A signature keeps only the
                                      # top few, so their weights sum to <= 1 (consistent with confidence.p_top)
    best_score: float
    chunk_ids: list[str] = field(default_factory=list)
    features: dict[str, str] = field(default_factory=dict)  # platform, product_area, component, error_message, ...
    grounding: float = 1.0   # share of the customer's content words found in this issue's text (1.0 = n/a)
    missing_terms: list[str] = field(default_factory=list)  # customer terms that are RARE in the retrieved pool (so they
                                                            # discriminate) yet absent from this issue's text. Added after
                                                            # 1.0.0 with a default: non-breaking, no version bump.


# ---------------------------------------------------------------------------
# Clarifier -> Resolver hand-off
# ---------------------------------------------------------------------------

@dataclass
class SignatureConfidence:
    p_top: float = 0.0
    margin: float = 0.0
    top_score: float = 0.0
    ambiguous: bool = True
    reason: str = ""


@dataclass
class ProblemSignature:
    canonical_string: str             # "product|component|symptom; symptom" -- the cache key (see below)
    nl_text: str                      # natural-language form used to embed / to query retrieval
    fields: ExtractedFields
    confidence: SignatureConfidence = field(default_factory=SignatureConfidence)
    hypotheses: list[Hypothesis] = field(default_factory=list)  # ranked differential, best first
    embedding: list[float] | None = None
    schema_version: str = SCHEMA_VERSION

    # Cache-key rule (agreed in the design): ONLY product|component|symptoms. Tone
    # (frustration) and blast radius (impact_scope) describe the ticket instance, not the
    # problem, and platform/version are matched as metadata gates, not part of the key.


@dataclass
class QuestionPlan:
    """A question the Clarifier intends to send: which feature it targets and the answer
    options (empty = open-ended). `text` is what the customer actually sees."""
    feature: str
    text: str
    options: list[str] = field(default_factory=list)


@dataclass
class ClarifierResult:
    """What one Clarifier turn returns. ASK -> send `question`, wait for the reply, call the
    Clarifier again. READY/UNRESOLVED -> `signature` is set; hand it to the Resolver."""
    status: ClarifierStatus
    question: QuestionPlan | None = None
    signature: ProblemSignature | None = None
    reason: str = ""
    questions_asked: int = 0
    meta: dict[str, Any] = field(default_factory=dict)  # extraction_source, tool_calls, reflection, ...


@dataclass
class NeedClarification:
    """Resolver -> Clarifier callback. Counts against the same attempt budget."""
    field: str
    reason: str = ""
    requested_by: str = "resolver"


# ---------------------------------------------------------------------------
# Triage Record (durable, one per ticket)
# ---------------------------------------------------------------------------

@dataclass
class TurnRecord:
    idx: int
    role: str                         # "customer" | "assistant"
    text: str                         # always PII-redacted before it is stored
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class QuestionRecord:
    turn_idx: int
    feature: str                      # which field/discriminator the question targets
    text: str
    options: list[str] = field(default_factory=list)
    answered: bool = False
    answer_value: str | None = None


@dataclass
class AttemptRecord:
    attempt: int
    chunk_ids_tried: list[str] = field(default_factory=list)
    outcome: str = ""                 # resolved | not_resolved | partial | unclear
    customer_feedback: str = ""


@dataclass
class TriageRecord:
    ticket_id: str
    created_at: str
    transcript: list[TurnRecord] = field(default_factory=list)
    fields: ExtractedFields = field(default_factory=ExtractedFields)
    signature: ProblemSignature | None = None
    questions: list[QuestionRecord] = field(default_factory=list)
    evidence_chunk_ids: list[str] = field(default_factory=list)
    attempts: list[AttemptRecord] = field(default_factory=list)
    outcome: str = Outcome.IN_PROGRESS.value
    closed_at: str | None = None
    flagged_incorrect: bool | None = None   # set later by the feedback loop (reopen / review)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    schema_version: str = SCHEMA_VERSION


# ---------------------------------------------------------------------------
# JSON round-tripping (generic over the dataclasses above)
# ---------------------------------------------------------------------------

def to_dict(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_dict(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, list):
        return [to_dict(x) for x in obj]
    if isinstance(obj, dict):
        return {k: to_dict(v) for k, v in obj.items()}
    return obj


def from_dict(cls: type, data: Any) -> Any:
    """Rebuild a dataclass tree from to_dict() output. Unknown keys are ignored so an older
    reader can still load a newer record; missing keys fall back to the field default."""
    if data is None:
        return None
    hints = typing.get_type_hints(cls)
    kwargs = {}
    for f in dataclasses.fields(cls):
        if f.name not in data:
            continue
        kwargs[f.name] = _decode(hints[f.name], data[f.name])
    return cls(**kwargs)


def _decode(tp: Any, value: Any) -> Any:
    if value is None:
        return None
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)
    if origin in (typing.Union, types.UnionType):
        inner = [a for a in args if a is not type(None)]
        return _decode(inner[0], value) if inner else value
    if origin is list:
        return [_decode(args[0], v) for v in value]
    if origin is dict:
        return dict(value)
    if dataclasses.is_dataclass(tp):
        return from_dict(tp, value)
    return value


# ---------------------------------------------------------------------------
# Contract checks (Member B can call these in their own tests)
# ---------------------------------------------------------------------------

def canonical_string(fields: ExtractedFields) -> str:
    product = (fields.product_area or "?").strip().lower()
    component = (fields.component or "?").strip().lower()
    symptoms = "; ".join(sorted({s.strip().lower() for s in fields.symptoms if s.strip()}))
    return f"{product}|{component}|{symptoms}"


def validate_signature(sig: ProblemSignature) -> list[str]:
    """Returns a list of contract violations; empty list means the signature is well-formed."""
    problems: list[str] = []
    if sig.schema_version != SCHEMA_VERSION:
        problems.append(f"schema_version {sig.schema_version} != {SCHEMA_VERSION}")
    if sig.canonical_string != canonical_string(sig.fields):
        problems.append("canonical_string does not match product|component|symptoms of fields")
    if sig.canonical_string.count("|") != 2:
        problems.append("canonical_string must contain exactly two '|' separators")
    if sig.fields.platform is not None and sig.fields.platform not in PLATFORMS:
        problems.append(f"platform {sig.fields.platform!r} not in {PLATFORMS}")
    if sig.fields.severity not in SEVERITY_LEVELS:
        problems.append(f"severity {sig.fields.severity!r} invalid")
    total = sum(h.weight for h in sig.hypotheses)
    if total > 1.0 + 1e-6:
        problems.append(f"hypothesis weights sum to {total:.4f}, which exceeds 1.0")
    if any(h.weight < 0 for h in sig.hypotheses):
        problems.append("negative hypothesis weight")
    return problems
