"""events.py -- the Resolver's event log, written into the case store.

B's `EventLogger` records every guardrail, cache lookup, retrieval, gate decision, LLM call, verification and outcome with
latency. This subclass also stores each event as an `agent_events` row keyed by the ticket (= conversation) id, with the
token counts and cost of LLM calls pulled out into columns so the dashboard can sum them in SQL. Events without a ticket id
are ignored. Nothing is kept in memory (a long-running server must not accumulate them).
"""

from __future__ import annotations

import json
from typing import Any

from triage.api.db import AgentEvent, utcnow
from triage.resolver.oplog import EventLogger


def _json_safe(fields: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(fields, default=str))


class DBEventLogger(EventLogger):
    def __init__(self, session_factory, path=None) -> None:
        super().__init__(path)
        self._sf = session_factory

    def log(self, event_type: str, **fields: Any) -> dict[str, Any]:
        ev = super().log(event_type, **fields)
        self.events.clear()
        conversation_id = fields.get("ticket_id")
        if conversation_id:
            with self._sf() as s:
                s.add(AgentEvent(
                    conversation_id=conversation_id, ts=utcnow(), event=event_type, node=fields.get("node"),
                    model=fields.get("model"), latency_ms=fields.get("latency_ms"),
                    input_tokens=int(fields.get("input_tokens") or 0), output_tokens=int(fields.get("output_tokens") or 0),
                    cost_usd=fields.get("cost_usd") if event_type == "llm_call" else None,
                    data=_json_safe({k: v for k, v in fields.items() if k != "ticket_id"})))
                s.commit()
        return ev
