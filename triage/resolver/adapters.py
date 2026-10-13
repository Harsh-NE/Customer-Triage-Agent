"""adapters.py -- Member A's retrievers behind Member B's `Retriever` interface (resolver/interface.py).

B's Resolver calls   retrieve(query, signature, k, tier, exclude_chunk_ids) -> list[Evidence]   (E1..Ek, rerank_score in 0..1).
A's retrievers (triage/hybrid.py) speak   search(query, top_k) -> list[Candidate | TicketHit].
These two classes translate, and use what the Clarifier already learned:

  KBEvidenceRetriever      Tier 1. ONE Evidence per KB *issue* (the unit the Clarifier reasons about and the customer is
                           told about), not per chunk: text = the best chunk, parent_text = the issue's chunks stitched
                           together so the drafting step and the command/URL verifier see the whole fix. The issue the
                           Clarifier ranked first is boosted and always included, because it was already grounded in the
                           customer's own words. rerank_score = vector similarity x lexical coverage of the customer's
                           words (+ the boost): dense similarity alone cannot tell a real match from junk, B's gate needs
                           an absolute 0..1 relevance, and this is the same grounding idea the Clarifier uses.
  TicketEvidenceRetriever  Tier 2. TicketHit -> Evidence; the PROBLEM / RESOLUTION layout B's drafting step expects.

Retry exclusion works at issue level: B records the chunk ids it cited; every chunk of those issues is excluded, so a retry
cannot send the same fix again from a sibling chunk.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable, Optional

from triage import config
from triage.config import ClarifierConfig
from triage.hybrid import TicketRetriever, query_coverage
from triage.issues import issue_key, issue_title
from triage.resolver.contracts import Evidence, ProblemSignature, Tier
from triage.resolver.interface import _number
from triage.state import Candidate

GITHUB_BASE_URL = "https://github.com/docker/docs/blob/main/"     # same citable link scripts/05_metadata.py writes
HYPOTHESIS_BOOST = 0.30        # relevance += this x the Clarifier's probability for the issue. The posterior includes everything the
                               # customer said and answered (a pasted error, a picked menu entry) which the raw query cannot see.
COVERAGE_FLOOR = 0.5           # rerank_score = similarity x (0.5 + 0.5 x coverage)
APPLICABILITY_PENALTY = 0.6    # the issue's heading is limited to platforms that exclude the customer's (soft, never a filter)
PARENT_TEXT_CHARS = 6000       # cap per issue; the prompt builder cuts further
QUERY_CHARS = 800
DOC_KIND_WEIGHT = ClarifierConfig().doc_kind_weight     # release notes x0.6, archive x0.4 ... the same soft weights the Clarifier uses


def sha(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def evidence_doc_id(source_path: str, chunk_id: str) -> str:
    """'<page>#<chunk>': B's gate groups evidence by the part before '#' (same page = agreeing evidence)."""
    return f"{source_path}#{chunk_id}"


def kb_doc_hashes(chunks_path: Path) -> dict[str, str]:
    """The {doc_id: hash} manifest B's cache needs to invalidate answers whose evidence changed (SemanticCache.
    invalidate_stale). Built from the enriched chunk file, with exactly the ids and hashes KBEvidenceRetriever emits."""
    out: dict[str, str] = {}
    for line in chunks_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            c = json.loads(line)
            out[evidence_doc_id(c["source_path"], c["chunk_id"])] = sha(c["text"])
    return out


def _query_for(query: str, signature: Optional[ProblemSignature]) -> str:
    return (signature.search_text() if signature else query)[:QUERY_CHARS] or query[:QUERY_CHARS]


def _customer_words(signature: Optional[ProblemSignature], query: str) -> str:
    """Text the evidence has to cover: symptom + error strings when we have them, else the raw query."""
    if signature and (signature.symptom or signature.error_strings):
        return " ".join([signature.symptom or "", *signature.error_strings])
    return query


# ---------------------------------------------------------------------------
# Tier 1
# ---------------------------------------------------------------------------

class KBEvidenceRetriever:
    def __init__(self, kb, ontology=None) -> None:
        """kb: any A-side retriever with search(query, top_k) and fetch(chunk_ids) -- HybridKBRetriever, MockRetriever.
        ontology: used to check platform applicability; defaults to the retriever's own (None when it has none)."""
        self.kb = kb
        self.ontology = ontology if ontology is not None else getattr(kb, "ontology", None)

    def _fetch(self, chunk_ids: list[str]) -> list[Candidate]:
        return self.kb.fetch(chunk_ids) if chunk_ids else []

    def retrieve(self, query: str, signature: Optional[ProblemSignature] = None, k: int = 10, tier: Tier = "kb",
                 exclude_chunk_ids: Iterable[str] = ()) -> list[Evidence]:
        cands: dict[str, Candidate] = {c.chunk_id: c for c in self.kb.search(_query_for(query, signature), top_k=k)}

        hyps = list(signature.hypotheses) if signature else []
        hyp_ids = list(hyps[0].get("chunk_ids") or []) if hyps else []
        missing = [cid for cid in hyp_ids if cid not in cands]
        if missing:                                   # the Clarifier's leading issue must be on the table even if this query missed it
            floor = 0.9 * max((c.score for c in cands.values()), default=0.5)
            for c in self._fetch(missing):
                c.score = floor
                cands[c.chunk_id] = c

        excluded_issues = {issue_key(c) for c in self._fetch(list(set(exclude_chunk_ids)))}
        by_issue: dict[str, list[Candidate]] = {}
        for c in cands.values():
            key = issue_key(c)
            if key not in excluded_issues:
                by_issue.setdefault(key, []).append(c)

        customer_platform = ((signature.environment or {}).get("os") if signature else None) or None
        words = _customer_words(signature, query)
        weight_of = {cid: float(h.get("weight") or 0.0) for h in reversed(hyps) for cid in h.get("chunk_ids") or []}
        evidence: list[Evidence] = []
        for key, chunks in by_issue.items():
            chunks.sort(key=lambda c: c.chunk_id)
            best = max(chunks, key=lambda c: c.score)
            parent = "\n\n".join(c.text for c in chunks)[:PARENT_TEXT_CHARS]
            relevance = best.score * DOC_KIND_WEIGHT.get(str(best.metadata.get("doc_kind", "")), 0.9) * (COVERAGE_FLOOR + (1 - COVERAGE_FLOOR) * query_coverage(words, f"{issue_title(best)} {parent}"))
            relevance += HYPOTHESIS_BOOST * max((weight_of.get(c.chunk_id, 0.0) for c in chunks), default=0.0)
            meta = dict(best.metadata)
            limited_to = self.ontology.required_platforms(" ".join(best.heading_path)) if self.ontology is not None else frozenset()
            if limited_to:        # e.g. a section under "Topics for Windows", or about WSL 2: it applies to those platforms only
                meta["applicability"] = {"limited_to": sorted(limited_to), "customer_platform": customer_platform}
                if customer_platform and customer_platform not in limited_to:
                    relevance *= APPLICABILITY_PENALTY
            meta.update({"issue": issue_title(best), "heading_path": " > ".join(best.heading_path),
                         "chunk_ids": [c.chunk_id for c in chunks], "license": meta.get("license") or "Apache-2.0"})
            evidence.append(Evidence(
                evidence_id="", chunk_id=best.chunk_id, doc_id=evidence_doc_id(best.source_path, best.chunk_id), tier="kb",
                text=best.text, url=GITHUB_BASE_URL + best.source_path if best.source_path else "", source="docker/docs",
                parent_text=parent, fused_score=round(best.score, 4), rerank_score=round(min(relevance, 1.0), 4),
                doc_hash=sha(best.text), metadata=meta))
        evidence.sort(key=lambda e: -e.rerank_score)
        return _number(evidence[:k])


# ---------------------------------------------------------------------------
# Tier 2
# ---------------------------------------------------------------------------

class TicketEvidenceRetriever:
    PROBLEM_CHARS = 300          # keep the problem short: the prompt builder cuts a passage at ~1800 chars and the FIX is what matters

    def __init__(self, tickets: TicketRetriever, store_root: Optional[Path] = None) -> None:
        self.tickets = tickets
        root = Path(store_root or config.PROJECT_ROOT / config.get_env()["TICKETS_STORE_PATH"])
        manifest = root / "tickets_manifest.json"
        self.known_topics: set[str] = set(json.loads(manifest.read_text(encoding="utf-8")).get("topics", [])) if manifest.exists() else set()

    def retrieve(self, query: str, signature: Optional[ProblemSignature] = None, k: int = 10, tier: Tier = "tickets",
                 exclude_chunk_ids: Iterable[str] = ()) -> list[Evidence]:
        topics = sorted({t for t in (signature.product_area, signature.component) if t} & self.known_topics) if signature else []
        codes = [str(c) for c in signature.exit_codes] if signature else []
        hits = self.tickets.search(_query_for(query, signature), top_k=k, topics=topics, exit_codes=codes,
                                   exclude_ids=set(exclude_chunk_ids))
        out = []
        for h in hits:
            problem = (h.problem_excerpt or "")[: self.PROBLEM_CHARS]
            out.append(Evidence(
                evidence_id="", chunk_id=h.ticket_id, doc_id=h.ticket_id, tier="tickets",
                text=f"{h.title}\n{problem}".strip(), url=h.url, source=h.source_type or h.source,
                parent_text=f"PROBLEM: {h.title}. {problem}\n\nRESOLUTION: {h.resolution}", trust=h.trust_score,
                fused_score=0.0, rerank_score=round(h.score, 4), doc_hash=sha(h.resolution),
                metadata={"topics": h.topics, "license": h.license, "trust_tier": h.trust_tier, "matched": h.matched,
                          "resolution_kind": h.resolution_kind, "age_years": h.age_years, "error_lines": h.error_lines,
                          "exit_codes": h.exit_codes}))
        return _number(out)
