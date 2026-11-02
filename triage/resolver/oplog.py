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

import json
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

# USD per 1M tokens — edit to match the model you actually use.
PRICES = {"default": {"input": 3.0, "output": 15.0}}


def estimate_cost(model: str, usage: dict[str, int]) -> float:
    p = PRICES.get(model, PRICES["default"])
    return round(usage.get("input_tokens", 0) / 1e6 * p["input"]
                 + usage.get("output_tokens", 0) / 1e6 * p["output"], 6)


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


NULL_LOGGER = EventLogger(None)
