"""B7 — operational event log (named oplog.py so it never shadows stdlib `logging`).

One JSON line per event: LLM call, retrieval call, cache lookup, gate decision,
escalation. B4 calibration and B6 evaluation read these files, so log early.

Usage:
    log = EventLogger("logs/events.jsonl")
    with log.timed("retrieval", ticket_id=tid, node="retrieve_kb") as ev:
        results = retriever.retrieve(...)
        ev["top_score"] = results[0].rerank_score
"""
from __future__ import annotations

import functools
import json
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

# Prices live in triage/pricing.json (USD per 1M tokens, with source and date); see triage/pricing.py.


def estimate_cost(model: str, usage: dict[str, int]):
    """USD for one call from triage/pricing.json, or None when the model has no price (never a made-up default)."""
    from triage.pricing import cost_usd
    return cost_usd(model, usage)


class EventLogger:
    def __init__(self, path: Optional[str | Path] = None):
        self.path = Path(path) if path else None
        self.events: list[dict[str, Any]] = []        # in-memory copy for tests/eval
        self._lock = threading.Lock()
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, event_type: str, **fields: Any) -> dict[str, Any]:
        ev = {"ts": datetime.now(timezone.utc).isoformat(), "event": event_type, **fields}
        with self._lock:
            self.events.append(ev)
            if self.path:
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(ev, default=str) + "\n")
        return ev

    @contextmanager
    def timed(self, event_type: str, **fields: Any) -> Iterator[dict[str, Any]]:
        extra: dict[str, Any] = {}
        start = time.perf_counter()
        status = "ok"
        try:
            yield extra
        except Exception as e:  # log, then re-raise
            status = f"error:{type(e).__name__}"
            raise
        finally:
            self.log(event_type, **fields, **extra, status=status,
                     latency_ms=round((time.perf_counter() - start) * 1000, 2))

    def of_type(self, event_type: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e["event"] == event_type]


def timed_node(logger: "EventLogger", stage: str, fn):
    """Wrap a graph node so every run logs one `stage_timing` event (stage name, wall milliseconds, inclusive of the LLM and retrieval calls inside
    it). Behaviour is unchanged; exceptions pass through after the timing is logged. agent_metrics turns these into per-stage latency."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        try:
            return fn(*args, **kwargs)
        finally:
            logger.log("stage_timing", stage=stage, latency_ms=round((time.perf_counter() - start) * 1000, 2))
    return wrapper


NULL_LOGGER = EventLogger(None)
