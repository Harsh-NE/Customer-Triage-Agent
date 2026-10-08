# Member B — Retrieval & Resolver Track

Evidence-First Support Triage. This package is everything Member B owns in the
workplan (B1–B8), built so it drops into the joint LangGraph (J1) without changes
on either side.

```
customer ─► [A: Clarifier] ─► signature ─► [B: Resolver] ─► resolved / escalated / back to Clarifier
```

Runs fully offline (FakeLLM + fixtures) so you can develop and test without an API
key; switch to a real model with one environment variable.

## Quick start

```bash
pip install -r requirements.txt
pytest -q                                          # 19 tests, all branches of the Resolver
python -m triage.eval.eval_resolver                # B6 eval report -> reports/
python -m triage.eval.calibrate_cache              # B4 calibration -> reports/
python scripts/demo_chat.py                        # talk to the joint graph in the terminal
LLM_PROVIDER=anthropic python scripts/demo_chat.py # same, with Claude (needs ANTHROPIC_API_KEY)
```

### With your own processed Docker KB

```bash
python scripts/convert_kb.py --input <your_chunks.jsonl|json|csv> --inspect   # see your fields
python scripts/convert_kb.py --input <your_chunks> --output data/kb_docker.jsonl [--map text=<field> ...]
python scripts/try_resolver.py --kb data/kb_docker.jsonl --tickets <docker_tickets_v3.jsonl> \
    --query "docker desktop stuck on starting on windows" --product docker-desktop --show-evidence
python scripts/demo_chat.py --kb data/kb_docker.jsonl --tickets <docker_tickets_v3.jsonl>
```

The fixture numbers (100% on 9 cases) only prove the harness works. They are not
results — real numbers come from the extended eval set on the real corpus.

## What each task is and where it lives

| Task | What it does | File |
|---|---|---|
| Phase 0 | Shared contracts: `ProblemSignature`, `Evidence`, `TriageRecord`, `TriageState`, enums | `triage/contracts.py` |
| B1/B2 | `Retriever` interface; `PhaseAAdapter` wraps your existing hybrid pipeline; `LexicalRetriever` for fixtures and the Tier 2 ticket index; `TieredRetriever` routes kb/tickets | `triage/retrieval/interface.py` |
| B3 | Resolver agent as a LangGraph subgraph: guard → cache → retrieve → gate → draft → verify → send → await reply → classify → retry / fallback / escalate | `triage/resolver/graph.py`, `gate.py`, `steps.py` |
| B4 | Semantic cache: exact tier, hard metadata gate, graduated thresholds, confirmed-only writes, invalidation from `store_manifest.json` | `triage/cache.py`, `triage/eval/calibrate_cache.py` |
| B5 | Escalation payload with reason code, priority, attempts, evidence, PII-masked transcript, markdown summary | `triage/escalate.py` |
| B6 | Guardrails (injection, secret requests, out-of-scope, security/data-loss override, PII masking) and the evaluation runner | `triage/guardrails.py`, `triage/eval/eval_resolver.py` |
| B7 | Structured JSONL event log for every LLM/retrieval/cache/gate event with latency and cost | `triage/oplog.py` |
| B8 | Documentation — this README plus `docs/resolver_design.md` | `docs/` |
| J1 preview | Joint graph with a stub Clarifier obeying A's contract | `triage/graph_integration.py` |

## How the Resolver decides

1. **Guard** — blocks prompt injection, secret harvesting and non-Docker requests
   (`rejected`); critical severity or security/data-loss always escalates. A
   signature below `min_completeness` goes back to the Clarifier.
2. **Cache** — exact hash hit or semantic hit reuses a confirmed answer; a
   mid-similarity hit reuses the evidence but re-drafts.
3. **Retrieve + gate** — confidence = weighted top score, top-1/top-2 margin,
   agreement among top-k, signature completeness. Weak KB evidence falls back to
   Tier 2 tickets; weak ticket evidence escalates `LOW_EVIDENCE`.
4. **Draft + verify** — the LLM may only use supplied evidence and must cite it.
   A deterministic check drops any step with a missing/invalid citation or a
   command/URL not present in the cited passage.
5. **Customer turn** — `interrupt()` pauses the graph; the reply is classified
   `resolved` / `not_fixed` / `new_info` / `off_topic`.
6. **Outcome** — resolved fixes are written to the cache; failed fixes are excluded
   and retried up to `max_attempts`, then `RETRY_EXHAUSTED`; new information goes
   back to the Clarifier.

All thresholds live in `triage/config.py` and are starting guesses until B4/B6
calibration replaces them.

## Merging with Member A (J1)

The Resolver touches A's work at exactly three points:

1. **`state["signature"]`** — A's Clarifier writes `ProblemSignature(...).to_dict()`.
   The Resolver needs `completeness` (0–1) and, ideally, `product_area`, `component`,
   `error_strings`, `exit_codes`, `severity`, `security_or_data_loss`.
2. **`state["next"]`** — the Resolver sets `"clarifier"` (needs more info) or
   `"end"`. The parent graph routes on it. The Clarifier should set `next=""` when done.
3. **Customer turns** — both agents ask the customer via `langgraph.types.interrupt()`
   and the app resumes with `Command(resume=text)`. The interrupt payload has a
   `type` (`clarifier_question` / `resolver_message`) and a `message`.

To merge, A replaces the stub:

```python
from triage.graph_integration import build_triage_graph
from clarifier import clarifier_node            # A3
app = build_triage_graph(deps, clarifier_node=clarifier_node)
```

A4 (ambiguity check) calls the same `Retriever.retrieve(...)` — A can develop
against `LexicalRetriever` on the fixtures and swap to the real one at merge.

Contract rule: after Phase 0, add optional fields only. Renaming or removing a
field needs both members to agree.

## Plugging in the real data

**Tier 1 (your Phase A pipeline):**

```python
from retrieve import search                    # your existing function
from triage.retrieval.interface import PhaseAAdapter
kb = PhaseAAdapter(search, field_map={"rerank_score": "ce_score"}, score_is_logit=True)
```

Map your result keys in `field_map`. Set `score_is_logit=True` if the
cross-encoder returns raw logits — the gate needs scores in 0–1.

**Tier 2 (A1's tickets):**

```python
tickets = LexicalRetriever(load_tickets_jsonl("docker_tickets_v3.jsonl",
                           exclude_synthetic=True, holdout_ids=eval_ticket_ids), "tickets")
```

Use the `.jsonl` (the v3 CSV has 82 corrupted rows). Pass eval ticket IDs as
`holdout_ids` so evaluation isn't circular. Upgrade to hybrid (add embeddings) once
the pipeline is stable.

**Check first:** Tier 1 and Tier 2 must cover the same product. If Tier 1 is still
the Microsoft support corpus and Tier 2 is Docker, the fallback is meaningless —
re-run B1 on Docker's documentation (`docker/docs`) or agree on another pairing.

## Your next steps

1. Agree the contracts in `triage/contracts.py` with A (Phase 0). Edit together.
2. Wire `PhaseAAdapter` to your existing `retrieve.py`; produce `store_manifest.json`
   with `doc_hashes`; run the Recall@5/10 report.
3. Build the real eval set (extend the 52 queries; add expected outcome, reason and
   evidence doc). Hold out ~100 real Docker tickets with known fixes.
4. Run `eval_resolver.py` with a real LLM; calibrate the gate thresholds from the
   accuracy-vs-confidence curve.
5. Build 50+ cache pairs (paraphrases and hard negatives) and run
   `calibrate_cache.py --embedder st:BAAI/bge-small-en-v1.5`.
6. Record every chosen threshold and the report behind it in `docs/`.
