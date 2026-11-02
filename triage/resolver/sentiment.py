"""Sentiment tracking across conversation turns.

Detects frustration signals in customer replies and maintains a running
frustration score. Used by the resolver to trigger early escalation when
a customer is increasingly unhappy.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Frustration signal patterns (weighted)
_FRUSTRATION_SIGNALS: list[tuple[re.Pattern, float]] = [
    (re.compile(r"\b(still not|still doesn'?t|still can'?t|still broken|still failing)\b", re.I), 0.3),
    (re.compile(r"\b(this is ridiculous|waste of time|terrible|horrible|awful|useless)\b", re.I), 0.4),
    (re.compile(r"\b(already tried|i told you|i already said|i mentioned)\b", re.I), 0.25),
    (re.compile(r"\b(nothing works|none of .* work|doesn'?t help|didn'?t help)\b", re.I), 0.3),
    (re.compile(r"\b(frustrated|frustrating|annoyed|angry|upset|furious)\b", re.I), 0.35),
    (re.compile(r"\b(hours|days|weeks)\b.*\b(trying|spent|wasted)\b", re.I), 0.25),
    (re.compile(r"\b(give up|giving up|done with|fed up)\b", re.I), 0.4),
    (re.compile(r"[!?]{2,}", re.I), 0.15),  # multiple punctuation
    (re.compile(r"\b[A-Z]{4,}\b"), 0.15),  # SHOUTING
    (re.compile(r"\b(escalate|manager|supervisor|human|real person)\b", re.I), 0.35),
]

# De-escalation signals
_CALM_SIGNALS: list[tuple[re.Pattern, float]] = [
    (re.compile(r"\b(thanks|thank you|ok|okay|sure|alright|got it)\b", re.I), -0.15),
    (re.compile(r"\b(makes sense|understand|i see|good point)\b", re.I), -0.1),
]


@dataclass
class SentimentState:
    """Tracks frustration across turns."""
    scores: list[float] = field(default_factory=list)  # per-turn scores
    current: float = 0.0  # running frustration (0..1)

    def to_dict(self) -> dict:
        return {"scores": self.scores, "current": round(self.current, 3)}

    @classmethod
    def from_dict(cls, d: dict | None) -> "SentimentState":
        if not d:
            return cls()
        return cls(scores=d.get("scores", []), current=d.get("current", 0.0))


def score_frustration(text: str) -> float:
    """Score a single message for frustration (0..1)."""
    total = 0.0
    for pattern, weight in _FRUSTRATION_SIGNALS:
        if pattern.search(text):
            total += weight
    for pattern, weight in _CALM_SIGNALS:
        if pattern.search(text):
            total += weight  # weight is negative
    return max(0.0, min(1.0, total))


def update_sentiment(state: SentimentState, reply: str, decay: float = 0.7) -> SentimentState:
    """Update running frustration with a new customer reply.
    Uses exponential decay so recent turns matter more."""
    turn_score = score_frustration(reply)
    state.scores.append(round(turn_score, 3))
    # Exponential moving average: old frustration decays, new adds
    state.current = decay * state.current + (1 - decay) * turn_score
    state.current = max(0.0, min(1.0, state.current))
    return state


def should_early_escalate(state: SentimentState, attempt_count: int,
                          threshold: float = 0.55, min_attempts: int = 2) -> bool:
    """Returns True if frustration is high enough to warrant early escalation."""
    return state.current >= threshold and attempt_count >= min_attempts
