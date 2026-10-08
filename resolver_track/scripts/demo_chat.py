"""Interactive terminal demo of the joint graph (stub Clarifier + real Resolver).

    python scripts/demo_chat.py                         # fixtures + FakeLLM, fully offline
    LLM_PROVIDER=anthropic python scripts/demo_chat.py  # real model
    python scripts/demo_chat.py --tickets /path/docker_tickets_v3.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langgraph.types import Command  # noqa: E402

from triage.cache import SemanticCache  # noqa: E402
from triage.graph_integration import build_triage_graph  # noqa: E402
from triage.llm import get_llm  # noqa: E402
from triage.oplog import EventLogger  # noqa: E402
from triage.resolver.graph import ResolverDeps  # noqa: E402
from triage.retrieval.interface import (LexicalRetriever, TieredRetriever, load_kb_jsonl,  # noqa: E402
                                        load_tickets_jsonl)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kb", default="fixtures/kb_mini.jsonl")
    ap.add_argument("--tickets", default="fixtures/tickets_mini.jsonl")
    a = ap.parse_args()
    deps = ResolverDeps(
        retriever=TieredRetriever(LexicalRetriever(load_kb_jsonl(a.kb), "kb"),
                                  LexicalRetriever(load_tickets_jsonl(a.tickets), "tickets")),
        llm=get_llm(), cache=SemanticCache(path="data/cache.json"),
        logger=EventLogger("logs/demo_events.jsonl"))
    app = build_triage_graph(deps)
    while True:
        first = input("\nCustomer (blank to quit): ").strip()
        if not first:
            break
        tid = f"DEMO-{uuid.uuid4().hex[:6]}"
        cfg = {"configurable": {"thread_id": tid}}
        out = app.invoke({"ticket_id": tid, "customer_message": first, "transcript": []}, cfg)
        while "__interrupt__" in out:
            print(f"\nAgent:\n{out['__interrupt__'][0].value['message']}")
            out = app.invoke(Command(resume=input("\nCustomer: ")), cfg)
        st = app.get_state(cfg).values
        print(f"\nAgent: {st['transcript'][-1]['content']}")
        print(f"\n[outcome={st.get('outcome')} reason={st.get('escalation_reason')} "
              f"confidence={st.get('confidence')} cache={st.get('cache_status')}]")
        if st.get("escalation_payload"):
            print(st["escalation_payload"]["summary_md"])


if __name__ == "__main__":
    main()
