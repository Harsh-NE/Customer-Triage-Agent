"""Part 8 — Feedback Loop, Trace Logging, and A/B Metrics.

Three capabilities:
  1. FeedbackCollector  — captures post-resolution CSAT / thumbs-up/down + free text
  2. TraceLogger        — structured trace of an entire ticket lifecycle (nodes visited,
                          latencies, LLM calls, evidence used, cache hits) for debugging
  3. ABMetrics          — lightweight experiment framework: assign tickets to variants,
                          record outcomes, compute aggregate stats
"""
from __future__ import annotations

import hashlib
import json
import statistics
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


# ========================================================================= 1. Feedback
@dataclass
class FeedbackEntry:
    ticket_id: str
    rating: Optional[int]          # 1-5 CSAT, or None for thumbs
    thumbs: Optional[str]          # "up" | "down" | None
    comment: str = ""
    resolution_attempts: int = 0
    was_escalated: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class FeedbackCollector:
    """Append-only JSONL store of post-resolution feedback."""

    def __init__(self, path: Optional[str | Path] = None):
        self.path = Path(path) if path else None
        self.entries: list[FeedbackEntry] = []
        if self.path and self.path.exists():
            for line in self.path.read_text().splitlines():
                if line.strip():
                    self.entries.append(FeedbackEntry(**json.loads(line)))

    def record(self, ticket_id: str, rating: Optional[int] = None,
               thumbs: Optional[str] = None, comment: str = "",
               resolution_attempts: int = 0, was_escalated: bool = False) -> FeedbackEntry:
        entry = FeedbackEntry(
            ticket_id=ticket_id, rating=rating, thumbs=thumbs,
            comment=comment, resolution_attempts=resolution_attempts,
            was_escalated=was_escalated)
        self.entries.append(entry)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(entry)) + "\n")
        return entry

    def avg_csat(self) -> Optional[float]:
        rated = [e.rating for e in self.entries if e.rating is not None]
        return round(statistics.mean(rated), 2) if rated else None

    def thumbs_ratio(self) -> dict[str, int]:
        up = sum(1 for e in self.entries if e.thumbs == "up")
        down = sum(1 for e in self.entries if e.thumbs == "down")
        return {"up": up, "down": down, "total": up + down}

    def summary(self) -> dict[str, Any]:
        return {
            "total_feedback": len(self.entries),
            "avg_csat": self.avg_csat(),
            "thumbs": self.thumbs_ratio(),
            "escalated_pct": round(
                sum(1 for e in self.entries if e.was_escalated) / max(len(self.entries), 1) * 100, 1),
        }


# ========================================================================= 2. Trace
@dataclass
class TraceSpan:
    node: str
    start_ts: str
    end_ts: str = ""
    latency_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TicketTrace:
    ticket_id: str
    trace_id: str = field(default_factory=lambda: f"T-{uuid.uuid4().hex[:12]}")
    spans: list[TraceSpan] = field(default_factory=list)
    cache_status: str = ""
    total_llm_calls: int = 0
    total_evidence: int = 0
    total_attempts: int = 0
    outcome: str = ""                    # resolved | escalated | abandoned
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class TraceLogger:
    """Collects per-ticket traces for debugging and analysis."""

    def __init__(self, path: Optional[str | Path] = None):
        self.path = Path(path) if path else None
        self._active: dict[str, TicketTrace] = {}

    def start(self, ticket_id: str) -> TicketTrace:
        trace = TicketTrace(ticket_id=ticket_id)
        self._active[ticket_id] = trace
        return trace

    def add_span(self, ticket_id: str, node: str, latency_ms: float = 0.0,
                 **metadata: Any) -> None:
        trace = self._active.get(ticket_id)
        if trace is None:
            trace = self.start(ticket_id)
        now = datetime.now(timezone.utc).isoformat()
        trace.spans.append(TraceSpan(
            node=node, start_ts=now, end_ts=now,
            latency_ms=latency_ms, metadata=metadata))

    def finalize(self, ticket_id: str, outcome: str,
                 cache_status: str = "", llm_calls: int = 0,
                 evidence_count: int = 0, attempts: int = 0) -> Optional[TicketTrace]:
        trace = self._active.pop(ticket_id, None)
        if trace is None:
            return None
        trace.outcome = outcome
        trace.cache_status = cache_status
        trace.total_llm_calls = llm_calls
        trace.total_evidence = evidence_count
        trace.total_attempts = attempts
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(trace), default=str) + "\n")
        return trace

    def get_active(self, ticket_id: str) -> Optional[TicketTrace]:
        return self._active.get(ticket_id)


# ========================================================================= 3. A/B Metrics
@dataclass
class ExperimentOutcome:
    ticket_id: str
    variant: str              # "control" | "treatment_a" | ...
    resolved: bool
    attempts: int
    latency_ms: float         # total wall-clock for the ticket
    csat: Optional[int] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ABMetrics:
    """Lightweight A/B experiment tracker.

    Assigns tickets to variants via deterministic hashing so the same
    ticket always lands in the same bucket (reproducible).
    """

    def __init__(self, experiment_name: str = "default",
                 variants: Optional[list[str]] = None,
                 path: Optional[str | Path] = None):
        self.experiment_name = experiment_name
        self.variants = variants or ["control", "treatment"]
        self.path = Path(path) if path else None
        self.outcomes: list[ExperimentOutcome] = []
        if self.path and self.path.exists():
            for line in self.path.read_text().splitlines():
                if line.strip():
                    self.outcomes.append(ExperimentOutcome(**json.loads(line)))

    def assign(self, ticket_id: str) -> str:
        """Deterministic variant assignment based on ticket_id hash."""
        h = int(hashlib.md5(f"{self.experiment_name}:{ticket_id}".encode()).hexdigest(), 16)
        return self.variants[h % len(self.variants)]

    def record(self, ticket_id: str, resolved: bool, attempts: int,
               latency_ms: float, csat: Optional[int] = None) -> ExperimentOutcome:
        variant = self.assign(ticket_id)
        outcome = ExperimentOutcome(
            ticket_id=ticket_id, variant=variant, resolved=resolved,
            attempts=attempts, latency_ms=latency_ms, csat=csat)
        self.outcomes.append(outcome)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(outcome)) + "\n")
        return outcome

    def stats(self) -> dict[str, dict[str, Any]]:
        """Per-variant aggregate stats."""
        result: dict[str, dict[str, Any]] = {}
        for v in self.variants:
            group = [o for o in self.outcomes if o.variant == v]
            if not group:
                result[v] = {"n": 0}
                continue
            resolved = [o for o in group if o.resolved]
            csats = [o.csat for o in group if o.csat is not None]
            result[v] = {
                "n": len(group),
                "resolution_rate": round(len(resolved) / len(group) * 100, 1),
                "avg_attempts": round(statistics.mean(o.attempts for o in group), 2),
                "avg_latency_ms": round(statistics.mean(o.latency_ms for o in group), 1),
                "avg_csat": round(statistics.mean(csats), 2) if csats else None,
            }
        return result
