"""
agent.py -- J1: the integrated triage agent (real Clarifier + Resolver in one LangGraph).

    clarify ──ASK──► ask_customer (interrupt) ──► clarify
       │ READY / UNRESOLVED
       ▼
    resolver (subgraph) ──next="clarifier"──► handoff ──► clarify
       │ next="end"
       ▼
      END

The two tracks keep their own contracts; this module is the only place that translates:
  * Clarifier ProblemSignature (triage.state)  -> Resolver ProblemSignature dict (triage.resolver.contracts)
  * Clarifier retriever (search -> Candidate) and Resolver retriever (retrieve -> Evidence) are built
    over the SAME KB file, so both agents see the same documents.
  * One LLM provider drives both agents (TextToJsonLLM adapts complete() to complete_json()).

Customer turns: both agents pause with interrupt(); resume with TriageAgent.reply().
SessionMemory is kept in state as JSON so the checkpointer only ever stores plain data.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any, Optional

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from triage import understand as U
from triage.clarifier import Clarifier
from triage.config import PROJECT_ROOT, ClarifierConfig
from triage.context_session import SessionMemory
from triage.llm import parse_json
from triage.resolver.cache import SemanticCache
from triage.resolver.contracts import Severity, TriageState
from triage.resolver.guardrails import check_input
from triage.resolver.graph import ResolverDeps, build_resolver_graph
from triage.resolver.llm import FakeLLM
from triage.resolver.oplog import EventLogger
from triage.resolver.retrieval import LexicalRetriever, TieredRetriever, load_kb_jsonl, load_tickets_jsonl
from triage.retrieval import MockRetriever
from triage.state import ClarifierResult, ClarifierStatus, NeedClarification, to_dict

DEFAULT_KB = PROJECT_ROOT / "data" / "kb_docker.jsonl"
DEFAULT_TICKETS = PROJECT_ROOT / "fixtures" / "tickets_mini.jsonl"
_EXIT_CODE = re.compile(r"exit code (\d+)", re.I)


class AgentState(TriageState, total=False):
    session_json: str                 # Clarifier SessionMemory, serialised
    clarifier_input: Optional[str]    # customer text the Clarifier has not ingested yet (None = Resolver callback)
    clarifier_status: str
    clarifier_reason: str
    clarifier_meta: dict[str, Any]
    clarifier_signature: dict[str, Any]
    pending_question: str


# ---------------------------------------------------------------------------
# Contract bridge
# ---------------------------------------------------------------------------

def completeness(fields) -> float:
    """Share of the four things the Resolver searches with: product, symptom, error evidence, platform."""
    have = [fields.product_area, fields.symptoms, fields.error_messages or fields.error_codes, fields.platform]
    return round(sum(bool(v) for v in have) / len(have), 2)


def to_resolver_signature(res: ClarifierResult, session: SessionMemory) -> dict[str, Any]:
    f = res.signature.fields
    comp = completeness(f)
    if res.status is ClarifierStatus.READY:
        comp = max(comp, 0.6)         # the Clarifier judged it sufficient: don't bounce it straight back
    severity = f.severity.lower() if f.severity.lower() in {s.value for s in Severity} else Severity.MEDIUM.value
    top = res.signature.hypotheses[0].label if res.signature.hypotheses else None
    return {
        "raw_query": " ".join(t.text for t in session.turns if t.role == "customer"),
        "product_area": f.product_area,
        "component": f.component,
        "symptom": "; ".join(f.symptoms) or top,
        "error_strings": list(f.error_messages),
        "exit_codes": [int(m) for c in f.error_codes for m in _EXIT_CODE.findall(c)],
        "versions": dict(f.versions),
        "environment": {k: v for k, v in {"os": f.platform, "detail": f.environment}.items() if v},
        "severity": severity,
        "security_or_data_loss": False,          # the Resolver's guard re-checks the raw text itself
        "missing_fields": [g.field for g in U.detect_gaps(f)],
        "completeness": comp,
        "clarify_turns": session.questions_asked,
    }


class TextToJsonLLM:
    """Lets the Clarifier's text LLM (ProviderLLM) serve the Resolver's complete_json() interface."""

    def __init__(self, llm) -> None:
        self.llm = llm
        self.model = getattr(llm, "model", "unknown")
        self.name = f"{getattr(llm, 'provider', 'llm')}:{self.model}"
        self.last_usage: dict[str, int] = {}

    def complete_json(self, system: str, user: str, max_tokens: int = 1200) -> dict[str, Any]:
        return parse_json(self.llm.complete(f"{system}\nRespond with a single JSON object and nothing else.\n\n{user}"))


# ---------------------------------------------------------------------------
# Shared KB: one file, two retriever interfaces
# ---------------------------------------------------------------------------

def _doc_kind(path: str) -> str:
    if "release-notes" in path or "release_notes" in path:
        return "release_notes"
    if "previous-versions" in path or "/archive" in path:
        return "archive"
    return "troubleshooting" if "troubleshoot" in path else "docs"


def clarifier_corpus(rows: list[dict]) -> list[dict]:
    """Resolver-format KB rows -> the corpus shape MockRetriever expects (issue = section title)."""
    out = []
    for r in rows:
        meta = dict(r.get("metadata") or {})
        if meta.get("product_area") == "content":     # convert_kb mapped non-manual pages to "content"
            meta.pop("product_area")
        meta["doc_kind"] = _doc_kind(r["doc_id"])
        article = Path(r["doc_id"]).stem.replace("_index", Path(r["doc_id"]).parent.name)
        out.append({"chunk_id": r["chunk_id"], "text": r["text"], "source_path": r["doc_id"],
                    "article_title": article, "heading_path": [article, r.get("title") or article],
                    "metadata": meta})
    return out


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

def build_agent_graph(clarifier: Clarifier, deps: ResolverDeps, checkpointer=None):
    def clarify(state: AgentState) -> dict[str, Any]:
        session = (SessionMemory.from_json(state["session_json"]) if state.get("session_json")
                   else clarifier.start(state.get("ticket_id")))
        message = state.get("clarifier_input")
        if message and not session.turns and check_input(message).detail in ("prompt_injection", "secret_request"):
            # Hostile opener: don't interview it, let the Resolver's guard reject it.
            return {"signature": {"raw_query": message, "completeness": 1.0}, "customer_message": message,
                    "clarifier_status": "skipped", "clarifier_reason": "blocked_by_guardrail", "next": ""}
        if message:
            res = clarifier.turn(session, message)
        else:   # Resolver sent it back without new customer text: ask for its most important missing field
            missing = (state.get("signature") or {}).get("missing_fields") or ["symptoms"]
            res = clarifier.reenter(session, NeedClarification(missing[0]))
        upd: dict[str, Any] = {
            "session_json": session.to_json(), "clarifier_input": None,
            "clarifier_status": res.status.value, "clarifier_reason": res.reason,
            "clarifier_meta": {k: res.meta[k] for k in ("confidence", "hypotheses", "uncovered_terms", "inferred")
                               if k in res.meta}}
        if res.status is ClarifierStatus.ASK:
            upd["pending_question"] = res.question.text
            upd["transcript"] = list(state.get("transcript") or []) + [
                {"role": "assistant", "content": res.question.text}]
        else:
            upd["signature"] = to_resolver_signature(res, session)
            upd["customer_message"] = upd["signature"]["raw_query"]   # the Resolver's guard screens the whole request
            upd["clarifier_signature"] = to_dict(res.signature)
            upd["next"] = ""
        return upd

    def ask_customer(state: AgentState) -> dict[str, Any]:
        # Nothing before interrupt() may have side effects: the node re-runs on resume.
        reply = str(interrupt({"type": "clarifier_question", "ticket_id": state.get("ticket_id"),
                               "message": state.get("pending_question", "")}))
        return {"clarifier_input": reply, "customer_message": reply,
                "transcript": list(state.get("transcript") or []) + [{"role": "user", "content": reply}]}

    def handoff(state: AgentState) -> dict[str, Any]:
        new_info = state.get("reply_label") == "new_info"
        return {"clarifier_input": state.get("customer_message") if new_info else None,
                "reply_label": None, "next": ""}

    g = StateGraph(AgentState)
    g.add_node("clarify", clarify)
    g.add_node("ask_customer", ask_customer)
    g.add_node("resolver", build_resolver_graph(deps).compile())
    g.add_node("handoff", handoff)
    g.add_edge(START, "clarify")
    g.add_conditional_edges("clarify", lambda s: "ask_customer" if s.get("clarifier_status") == "ask" else "resolver",
                            ["ask_customer", "resolver"])
    g.add_edge("ask_customer", "clarify")
    g.add_conditional_edges("resolver", lambda s: "handoff" if s.get("next") == "clarifier" else END,
                            ["handoff", END])
    g.add_edge("handoff", "clarify")
    return g.compile(checkpointer=checkpointer or MemorySaver())


class TriageAgent:
    """Thin driver around the compiled graph: start a ticket, send customer replies, read state."""

    def __init__(self, llm_mode: str = "offline", kb_path: str | Path = DEFAULT_KB,
                 tickets_path: str | Path = DEFAULT_TICKETS, log_path: str | Path | None = None) -> None:
        if llm_mode == "offline":
            clarifier_llm, resolver_llm = None, FakeLLM()        # heuristic extraction, template drafting
        else:
            from triage.llm import ProviderLLM
            clarifier_llm = ProviderLLM()                        # LLM_PROVIDER / LLM_MODEL / key from .env
            resolver_llm = TextToJsonLLM(clarifier_llm)
        kb_rows = load_kb_jsonl(kb_path)
        self.clarifier = Clarifier(clarifier_llm, MockRetriever(clarifier_corpus(kb_rows)), ClarifierConfig())
        deps = ResolverDeps(
            retriever=TieredRetriever(LexicalRetriever(kb_rows, "kb"),
                                      LexicalRetriever(load_tickets_jsonl(tickets_path), "tickets")),
            llm=resolver_llm, cache=SemanticCache(path=PROJECT_ROOT / "data" / "cache.json"),
            logger=EventLogger(log_path or PROJECT_ROOT / "logs" / "agent_events.jsonl"))
        self.app = build_agent_graph(self.clarifier, deps)

    @staticmethod
    def _cfg(ticket_id: str) -> dict:
        return {"configurable": {"thread_id": ticket_id}}

    def start(self, message: str, ticket_id: str | None = None) -> str:
        tid = ticket_id or f"T-{uuid.uuid4().hex[:8]}"
        self.app.invoke({"ticket_id": tid, "customer_message": message, "clarifier_input": message,
                         "transcript": [{"role": "user", "content": message}]}, self._cfg(tid))
        return tid

    def reply(self, ticket_id: str, message: str) -> None:
        self.app.invoke(Command(resume=message), self._cfg(ticket_id))

    def state(self, ticket_id: str) -> dict[str, Any]:
        snap = self.app.get_state(self._cfg(ticket_id), subgraphs=True)
        values = dict(snap.values)
        for t in snap.tasks:      # a paused Resolver subgraph holds the newest transcript / evidence
            if t.state is not None and getattr(t.state, "values", None):
                values.update(t.state.values)
        waiting = [i.value for t in snap.tasks for i in t.interrupts]
        return {**values, "waiting_for": waiting[0] if waiting else None}


if __name__ == "__main__":   # quick terminal smoke run: python -m triage.agent
    agent = TriageAgent()
    tid = agent.start(input("customer> "))
    while (st := agent.state(tid))["waiting_for"]:
        print(f"agent> {st['waiting_for']['message']}")
        agent.reply(tid, input("customer> "))
    print(json.dumps({k: st.get(k) for k in ("outcome", "escalation_reason", "confidence")}, indent=2))
