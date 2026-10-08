"""J1 preview — how the Resolver plugs into the joint graph.

Until Member A's clarifier.py lands, `stub_clarifier` stands in for it. It obeys
the same contract the real Clarifier must:
  * reads state["customer_message"] (+ existing signature, if any)
  * writes state["signature"] (ProblemSignature.to_dict())
  * asks the customer via interrupt() when it needs more information
  * clears state["next"] so the Resolver runs next

Swap: build_triage_graph(deps, clarifier_node=clarifier.clarifier_node)
"""
from __future__ import annotations

import re
from typing import Any, Callable, Optional

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from triage.contracts import ProblemSignature, Severity, TriageState
from triage.resolver.graph import ResolverDeps, build_resolver_graph

PRODUCTS = {"docker-desktop": r"docker desktop|wsl|hyper-v|mac|windows",
            "compose": r"compose|docker-compose|yaml",
            "engine": r"daemon|dockerd|engine|containerd",
            "hub": r"docker hub|pull rate|registry|login|push"}
COMPONENTS = {"networking": r"port|network|dns|bridge|connect|localhost",
              "build": r"build|dockerfile|buildkit|layer",
              "volumes": r"volume|mount|bind|permission denied",
              "auth": r"login|auth|unauthori[sz]ed|denied: requested access",
              "startup": r"start|starting|won'?t start|stuck"}
ERROR_RX = re.compile(r"(?:error[:\s][^\n.]{5,80}|\"[^\"]{6,80}\"|exit code \d+)", re.I)


def stub_understand(text: str, prev: Optional[dict[str, Any]] = None) -> ProblemSignature:
    """Very rough stand-in for A2 (understand.py). Do not evaluate this."""
    low = text.lower()
    sig = ProblemSignature.from_dict(prev) if prev else ProblemSignature(raw_query=text)
    if prev:
        sig.raw_query = f"{sig.raw_query}\n{text}"
    sig.product_area = sig.product_area or next(
        (p for p, rx in PRODUCTS.items() if re.search(rx, low)), None)
    sig.component = sig.component or next(
        (c for c, rx in COMPONENTS.items() if re.search(rx, low)), None)
    sig.error_strings = list(dict.fromkeys(sig.error_strings + [m.strip('" ') for m in ERROR_RX.findall(text)]))
    sig.exit_codes = list(dict.fromkeys(sig.exit_codes + [int(c) for c in re.findall(r"exit code (\d+)", low)]))
    if re.search(r"production|all users|outage|data loss", low):
        sig.severity = Severity.CRITICAL
    have = [sig.product_area, sig.component, sig.error_strings]
    sig.missing_fields = [n for n, v in zip(["product_area", "component", "error_strings"], have) if not v]
    sig.completeness = round(sum(bool(v) for v in have) / 3, 2)
    return sig


def stub_clarifier(state: TriageState) -> dict[str, Any]:
    sig = stub_understand(state.get("customer_message", ""), state.get("signature"))
    transcript = list(state.get("transcript") or [])
    if not transcript or transcript[-1].get("content") != state.get("customer_message"):
        transcript.append({"role": "user", "content": state.get("customer_message", "")})
    if sig.completeness < 0.5 and sig.clarify_turns < 2:
        question = "Could you share the exact error message and which Docker product (Desktop, Engine, Compose) you're using?"
        answer = interrupt({"type": "clarifier_question", "message": question})
        transcript += [{"role": "assistant", "content": question}, {"role": "user", "content": str(answer)}]
        sig = stub_understand(str(answer), sig.to_dict())
        sig.clarify_turns += 1
    return {"signature": sig.to_dict(), "transcript": transcript, "next": ""}


def build_triage_graph(deps: ResolverDeps,
                       clarifier_node: Callable[[TriageState], dict[str, Any]] = stub_clarifier,
                       checkpointer=None):
    resolver = build_resolver_graph(deps).compile()
    g = StateGraph(TriageState)
    g.add_node("clarifier", clarifier_node)
    g.add_node("resolver", resolver)
    g.add_edge(START, "clarifier")
    g.add_edge("clarifier", "resolver")
    g.add_conditional_edges("resolver", lambda s: "clarifier" if s.get("next") == "clarifier" else END,
                            ["clarifier", END])
    return g.compile(checkpointer=checkpointer or MemorySaver())
