"""
tools.py -- the Tool Registry (Phase 0 contract) with a per-turn call budget.

Design choice ("hybrid tool-calling"): the Clarifier's outer flow is a deterministic graph,
and *inside* a turn it reaches for tools -- search_kb, ask_customer -- through this registry.
The registry is the guardrail: only registered names can run, each has a max-calls-per-turn
budget, arguments are validated, and every call is logged (name, trimmed args, result size,
latency) so it can be copied into the Triage Record and the ops log.

Today the *calls are issued by deterministic code*, not by an LLM emitting function-calls
(see docs/MEMBER_A_HANDBOOK.md, "Assumptions"). The registry is the seam where LLM-driven
function-calling would plug in later without changing any tool.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

from triage.retrieval import Retriever
from triage.state import Candidate, QuestionPlan


class ToolNotAllowed(Exception):
    pass


class ToolBudgetExceeded(Exception):
    pass


@dataclass
class _Tool:
    fn: Callable[..., Any]
    description: str
    max_per_turn: int


class ToolRegistry:
    def __init__(self, default_max_per_turn: int = 3) -> None:
        self._tools: dict[str, _Tool] = {}
        self._used: dict[str, int] = {}
        self._default = default_max_per_turn
        self.log: list[dict[str, Any]] = []

    def register(self, name: str, fn: Callable[..., Any], description: str,
                 max_per_turn: int | None = None) -> None:
        self._tools[name] = _Tool(fn, description, max_per_turn or self._default)

    def begin_turn(self) -> None:
        self._used = {}

    def call(self, name: str, **kwargs: Any) -> Any:
        tool = self._tools.get(name)
        if tool is None:
            raise ToolNotAllowed(f"'{name}' is not a registered tool (allowed: {sorted(self._tools)})")
        if self._used.get(name, 0) >= tool.max_per_turn:
            raise ToolBudgetExceeded(f"'{name}' exceeded {tool.max_per_turn} calls this turn")
        self._used[name] = self._used.get(name, 0) + 1
        started = time.perf_counter()
        result = tool.fn(**kwargs)
        self.log.append({
            "tool": name,
            "args": {k: (v[:80] if isinstance(v, str) else v) for k, v in kwargs.items()},
            "result_size": len(result) if hasattr(result, "__len__") else None,
            "ms": round((time.perf_counter() - started) * 1000, 1),
        })
        return result

    def describe(self) -> list[dict[str, Any]]:
        return [{"name": n, "description": t.description, "max_per_turn": t.max_per_turn}
                for n, t in sorted(self._tools.items())]


MAX_QUERY_CHARS = 500


def make_clarifier_registry(retriever: Retriever, top_k: int, max_searches_per_turn: int) -> ToolRegistry:
    """search_kb(query) -> list[Candidate];  ask_customer(feature, text, options) -> QuestionPlan.
    ask_customer is a *terminal* tool: it does not block -- it returns the question to emit and
    the turn ends there (the next customer message starts the next turn)."""
    registry = ToolRegistry(default_max_per_turn=max_searches_per_turn)

    def search_kb(query: str) -> list[Candidate]:
        query = (query or "").strip()
        if not query:
            raise ValueError("search_kb requires a non-empty query")
        return retriever.search(query[:MAX_QUERY_CHARS], top_k=top_k)

    def ask_customer(feature: str, text: str, options: list[str] | None = None) -> QuestionPlan:
        if not text or not text.strip():
            raise ValueError("ask_customer requires question text")
        return QuestionPlan(feature=feature, text=text.strip(), options=list(options or []))

    registry.register("search_kb", search_kb, "Search the troubleshooting KB; returns ranked chunks.",
                      max_per_turn=max_searches_per_turn)
    registry.register("ask_customer", ask_customer, "Send ONE clarifying question to the customer (ends the turn).",
                      max_per_turn=1)
    return registry
