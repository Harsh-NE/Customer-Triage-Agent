"""Test the Resolver directly with a hand-written signature (skips the stub Clarifier).

    python scripts/try_resolver.py --kb data/kb_docker.jsonl \
        --query "docker desktop stuck on starting on windows" \
        --product docker-desktop --component startup

    # show what retrieval returned and why the gate decided what it did
    python scripts/try_resolver.py --kb data/kb_docker.jsonl --query "..." --show-evidence
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
from triage.contracts import ProblemSignature  # noqa: E402
from triage.llm import get_llm  # noqa: E402
from triage.oplog import EventLogger  # noqa: E402
from triage.resolver.graph import ResolverDeps, build_resolver_app  # noqa: E402
from triage.retrieval.interface import (LexicalRetriever, TieredRetriever, load_kb_jsonl,  # noqa: E402
                                        load_tickets_jsonl)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kb", default="fixtures/kb_mini.jsonl")
    ap.add_argument("--tickets", default="fixtures/tickets_mini.jsonl")
    ap.add_argument("--query", required=True)
    ap.add_argument("--product", default=None)
    ap.add_argument("--component", default=None)
    ap.add_argument("--error", action="append", default=[], help="repeatable")
    ap.add_argument("--severity", default="medium")
    ap.add_argument("--completeness", type=float, default=0.8)
    ap.add_argument("--show-evidence", action="store_true")
    a = ap.parse_args()

    print("Loading indexes…")
    kb = LexicalRetriever(load_kb_jsonl(a.kb), "kb")
    tickets = LexicalRetriever(load_tickets_jsonl(a.tickets), "tickets") if Path(a.tickets).exists() else None
    log = EventLogger("logs/try_events.jsonl")
    deps = ResolverDeps(retriever=TieredRetriever(kb, tickets), llm=get_llm(),
                        cache=SemanticCache(path="data/cache.json"), logger=log)
    sig = ProblemSignature(raw_query=a.query, product_area=a.product, component=a.component,
                           symptom=a.query, error_strings=a.error, completeness=a.completeness)
    sig.severity = sig.severity.__class__(a.severity)

    if a.show_evidence:
        for tier in ("kb", "tickets"):
            res = deps.retriever.retrieve(a.query, sig, k=5, tier=tier)
            print(f"\n--- top {tier} evidence ---")
            for e in res:
                print(f"{e.evidence_id} {e.rerank_score:.3f} {e.chunk_id}\n    {e.text[:160]!r}")

    app = build_resolver_app(deps)
    cfg = {"configurable": {"thread_id": f"TRY-{uuid.uuid4().hex[:6]}"}}
    out = app.invoke({"ticket_id": cfg["configurable"]["thread_id"], "signature": sig.to_dict(),
                      "transcript": []}, cfg)
    while "__interrupt__" in out:
        print(f"\nAgent:\n{out['__interrupt__'][0].value['message']}")
        out = app.invoke(Command(resume=input("\nYou (as customer): ")), cfg)
    st = app.get_state(cfg).values
    print(f"\nAgent: {st['transcript'][-1]['content'] if st.get('transcript') else ''}")
    print("\n=== RESULT ===")
    print(json.dumps({k: st.get(k) for k in ("outcome", "escalation_reason", "confidence",
                                             "cache_status", "next")}, indent=2))
    print("gate:", json.dumps(st.get("gate_detail"), indent=2))
    if st.get("escalation_payload"):
        print(st["escalation_payload"]["summary_md"])
    print("\nFull event log: logs/try_events.jsonl")


if __name__ == "__main__":
    main()
