"""joint.py -- the integrated triage graph (J1): Member A's Clarifier + Member B's Resolver.

    START -> clarifier --(needs an answer)--> clarifier        (interrupt() each time; one Clarifier turn per execution)
                 |
                 +--(READY / UNRESOLVED)--> resolver --(next == "clarifier": new info / signature too thin)--> clarifier
                                                |
                                                +--> END  (resolved | escalated | rejected)

Everything in the shared state is JSON-serialisable, so a checkpointer can persist the conversation between customer turns.
`build_default_deps` wires the real stores (hybrid KB + ticket store), one shared embedding model, B's semantic cache and
B's event log. For offline development pass `retriever=` (e.g. MockRetriever-backed adapters) and a FakeLLM.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Optional

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from triage import config
from triage.clarifier import Clarifier
from triage.config import ClarifierConfig
from triage.resolver.cache import SemanticCache
from triage.resolver.config import ResolverConfig
from triage.resolver.contracts import TriageState
from triage.resolver.graph import ResolverDeps, build_resolver_graph
from triage.resolver.handoff import make_clarifier_node
from triage.resolver.llm import LLM, get_llm
from triage.resolver.oplog import EventLogger


def build_joint_graph(clarifier: Clarifier, deps: ResolverDeps, checkpointer=None):
    resolver = build_resolver_graph(deps).compile()
    g = StateGraph(TriageState)
    g.add_node("clarifier", make_clarifier_node(clarifier, scope_llm=deps.llm, logger=deps.logger))
    g.add_node("resolver", resolver)
    g.add_edge(START, "clarifier")
    g.add_conditional_edges("clarifier", lambda s: "clarifier" if s.get("clarifier_pending") else "resolver",
                            ["clarifier", "resolver"])
    g.add_conditional_edges("resolver", lambda s: "clarifier" if s.get("next") == "clarifier" else END,
                            ["clarifier", END])
    return g.compile(checkpointer=checkpointer or MemorySaver())


SUPPLEMENTARY_DEFAULT = "on"      # SUPPLEMENTARY_KB=on|off


class SharedModelEmbedder:
    """B's cache embedder on the same bge model the KB and ticket stores use (normalised, no query prefix)."""

    def __init__(self, model) -> None:
        self.model = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self.model.encode(texts, normalize_embeddings=True).tolist()


def build_supplementary(model):
    """The optional third-party tier (scripts/11_supplementary.py): a second hybrid retriever over its own small store, consulted only
    when the official evidence is weak. SUPPLEMENTARY_KB=off disables it; it is also skipped when the store has not been built."""
    if os.environ.get("SUPPLEMENTARY_KB", SUPPLEMENTARY_DEFAULT).lower() == "off":
        return None
    root = config.PROJECT_ROOT / "data" / "processed" / "docker" / "store" / "supplementary"
    if not (root / "vector").exists() or not (root / "bm25" / "bm25_index.pkl").exists():
        return None
    from triage.hybrid import HybridKBRetriever
    return HybridKBRetriever(model=model, vector_db_path=str(root / "vector"), bm25_path=str(root / "bm25"))


def build_default_deps(llm: Optional[LLM] = None, *, cache_path: Optional[Path] = None, log_path: Optional[Path] = None,
                       resolver_cfg: Optional[ResolverConfig] = None, logger: Optional[EventLogger] = None):
    """Real stores, one shared embedding model. Returns (retrievers, ResolverDeps): the KB retriever is also what the
    Clarifier searches with, so both agents see the same index."""
    from sentence_transformers import SentenceTransformer

    from triage.hybrid import HybridKBRetriever, TicketRetriever
    from triage.resolver.adapters import KBEvidenceRetriever, TicketEvidenceRetriever, kb_doc_hashes
    from triage.resolver.interface import TieredRetriever

    env = config.get_env()
    try:                                                  # local cache first: no network round-trip
        model = SentenceTransformer(env["EMBEDDING_MODEL"], local_files_only=True)
    except Exception:  # noqa: BLE001
        model = SentenceTransformer(env["EMBEDDING_MODEL"])
    kb = HybridKBRetriever(model=model)
    tickets = TicketRetriever(model=model)
    root = config.PROJECT_ROOT / "data" / "processed" / "docker" / "resolver"
    llm = llm or get_llm()
    # The cache holds DRAFTED answers, so it is per LLM: answers written by the offline FakeLLM must never be served to a
    # customer in a run that uses a real model (and vice versa).
    tag = re.sub(r"[^a-z0-9]+", "-", str(getattr(llm, "name", "llm")).lower()).strip("-")
    cache = SemanticCache(embedder=SharedModelEmbedder(model), path=cache_path or root / f"cache__{tag}.json")
    supplementary = build_supplementary(model)
    chunks = config.PROJECT_ROOT / "data" / "processed" / "docker" / "chunks_metadata.jsonl"
    if chunks.exists():
        hashes = kb_doc_hashes(chunks)
        supp_chunks = root.parent / "chunks_supplementary.jsonl"
        if supplementary is not None and supp_chunks.exists():       # answers citing third-party chunks are checked like official ones
            hashes.update(kb_doc_hashes(supp_chunks))
        cache.invalidate_stale({"doc_hashes": hashes})              # answers whose evidence changed are dropped
    cfg = resolver_cfg or ResolverConfig()
    if os.environ.get("ONTOLOGY_BACKGROUND") == "1":
        cfg.use_background = True
    deps = ResolverDeps(retriever=TieredRetriever(KBEvidenceRetriever(kb, supplementary=supplementary), TicketEvidenceRetriever(tickets)),
                        llm=llm, cache=cache, logger=logger or EventLogger(log_path or root / "events.jsonl"),
                        cfg=cfg, ontology=kb.ontology)
    return kb, deps


def build_default_app(llm: Optional[LLM] = None, clarifier_cfg: Optional[ClarifierConfig] = None, **kw) -> Any:
    """The whole system on the real stores. `llm` drives the Resolver's draft/classify steps (default: LLM_PROVIDER env,
    'fake' offline). The Clarifier stays on its deterministic default (heuristic extraction)."""
    kb, deps = build_default_deps(llm, **kw)
    return build_joint_graph(Clarifier(None, kb, clarifier_cfg), deps)
