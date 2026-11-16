# Project Evaluation Report: Evidence-First Customer Support Triage Agent

Review of the repository as an academic Agentic-AI project (Clarifier agent + Resolver agent, hybrid RAG, confidence gate, FastAPI + React).
No application code was changed for this review. Everything below is either read from the code or measured by running something; each
number names its source. What was **not** run is stated in section 5 and section 9.

**State of the tree reviewed:** branch `feature/integrated`, merge commit `32a3728` plus uncommitted work from the previous task (screenshot
OCR, API upload, React upload, two new test files). The evaluation runs used commit `32a3728` with the fake drafting model, fixed
`PYTHONHASHSEED=0`. Raw outputs are in `reports/regression/` (`before_*.json|md`, `ontology_eval.*`, `gate_calibration.json`,
`normalization_probe.json`, `pytest_full.log`), and the probe scripts in `reports/regression/probes/`.

---

## 1. Project overview

A customer describes a Docker problem. A **Clarifier** agent works out what is wrong, asking only questions that tell likely causes apart.
A **Resolver** agent then drafts a fix that must cite retrieved documentation. A rule-based **confidence gate** decides whether to answer,
go back for more information, or escalate to a human. The customer can also attach a screenshot, which is read with OCR.

| Layer | What exists | Size |
|---|---|---|
| Knowledge base | Docker docs, 11,440 chunks (6,029 docs, 2,185 release notes, 1,694 guides, 763 archive, 486 reference, **187 troubleshooting, 96 FAQ**); 661 third-party "community" chunks as a lower-trust tier; 13,092 indexed historical Stack Overflow tickets (13,899 rows) | `data/processed/docker/` |
| Retrieval | Dense (bge-base-en-v1.5, Chroma) + BM25, fused with reciprocal-rank fusion, plus a 153-node ontology (alias expansion, entity lists) | `triage/hybrid.py`, `triage/ontology/` |
| Agents | Clarifier (`triage/clarifier.py`, `understand.py`, `differential.py`, `symptoms.py`), Resolver (`triage/resolver/`) | ~6,700 lines |
| Orchestration | LangGraph: one joint graph, SQLite checkpointer | `triage/joint.py` |
| Backend | FastAPI, SQLAlchemy/SQLite (users, conversations, messages, agent_events, case notes/actions), login tokens, analytics | `triage/api/` |
| Frontend | React + TypeScript (customer chat, engineer queue/case page, analytics), 26 unit tests | `frontend/` |
| Evaluation tooling | Clarifier eval, end-to-end eval, ontology ablation, gate calibration, faithfulness judge, metrics script | `triage/eval/` |
| Size | 81 Python files, 15,186 lines (3,977 in `scripts/`, 3,887 in `triage/`, 2,791 in `triage/resolver/`, 2,317 in `triage/eval/`); 1,824 lines of TypeScript; 24 test files | |

Datasets used for evaluation: `scenarios.jsonl` (29 hand-written scenarios, 20 with a gold KB issue, 6 out of scope, 3 other),
`paraphrases.jsonl` (42 single queries with a gold issue), `heldout_scenarios.jsonl` (65 real Stack Overflow questions;
**all 65 labels are unverified drafts**, 13 "gold", 52 "KB gap").

---

## 2. Existing architecture

### 2.1 Component diagram

```
                       +--------------------------- React UI (frontend/) ----------------------------+
 customer ------------>| chat, quick-reply buttons, symptom tick-list, screenshot attach (OCR preview) |
 engineer  ----------->| case queue, case page (agent trace, evidence, screenshot), analytics          |
                       +-------------------------------------+---------------------------------------+
                                                             | HTTP /api (login token)
                       +-------------------------------------v---------------------------------------+
                       | FastAPI  triage/api/app.py     ConversationService (service.py)               |
                       |  - one lock per conversation   - persists every turn   - /attachments -> OCR  |
                       +----------+--------------------------------------------------+-----------------+
                                  | graph.invoke / Command(resume)                    | SQLAlchemy
        +-------------------------v--------------------------+                  +-----v--------------+
        |  Joint LangGraph (triage/joint.py)  state=TriageState                  |  app.db (SQLite)    |
        |  checkpointer: checkpoints.sqlite  (survives restarts)                 |  users, conversations|
        |                                                                         |  messages,          |
        |  [clarifier node]  handoff.py                                           |  agent_events,      |
        |    1 redact PII; injection/secret regex -> straight to Resolver guard   |  case_notes/actions |
        |    2 out-of-scope: rule check, then ONE scope LLM call (first message)  +--------------------+
        |    3 Clarifier.turn:                                                    |
        |         extract fields (heuristic; LLM optional, off in API)            |
        |         -> gaps -> hybrid search (<=3 queries) -> hypotheses (softmax   |
        |         over KB issues) -> decide: clear / ask / give up                |
        |         ask = interrupt() -> question card -> wait for the customer     |
        |    READY / UNRESOLVED -> to_resolver_signature (translation layer)      |
        |                         |                                               |
        |  [resolver subgraph]    v                                               |
        |    guard (input rules, hard escalation: data loss / security / critical)|
        |    -> cache_lookup (semantic cache of confirmed fixes)                  |
        |    -> retrieve  KB tier (1 Evidence per issue) -> community tier        |
        |                 -> tickets tier (fallback)                              |
        |    -> gate (top score, margin, agreement, completeness -> confidence)   |
        |         resolve / clarify / escalate                                    |
        |    -> draft (LLM, evidence-only JSON) -> verify (deterministic)         |
        |    -> send (cited fix) -> await_reply (interrupt) -> classify           |
        |         resolved | not fixed -> retry (max 2) | new info -> Clarifier   |
        |         | partial | off topic -> nudge | frustrated -> escalate          |
        |    -> escalate (reason, priority P1-P4, payload for the engineer)       |
        +------------+--------------------------------+--------------------------+
                     |                                |
        +------------v-------------+      +-----------v--------------+
        | Stores (read-only)       |      | LLM provider layer        |
        | Chroma + BM25: KB 11,440 |      | triage/llm.py (Gemini /   |
        | community 661, tickets   |      | Anthropic / OpenAI),      |
        | 13,092; ontology YAML    |      | resolver/llm.py wrappers, |
        | semantic + negative cache|      | FakeLLM for offline runs  |
        +--------------------------+      +--------------------------+
```

### 2.2 Execution flow, from the first complaint to the final reply

1. **Input.** The React app posts `POST /api/conversations {message, attachment_id?, screenshot_text?}`. A screenshot is uploaded first
   (`POST /api/attachments`: size/type/dimension checks, OCR with Tesseract, secrets masked, shown to the customer to correct).
2. **Persist and run.** `ConversationService.create` writes the conversation and the customer message, then invokes the joint graph on
   thread `C-xxxxxxxx` under a per-conversation lock.
3. **Clarifier node** (`resolver/handoff.py`): masks PII; prompt-injection or secret-request text skips the interview and goes straight
   to the Resolver's guard, which declines it; an obviously non-Docker message is declined by rule; otherwise one scope LLM call (first
   message only) can decline it when it is sure.
4. **Understanding** (`understand.py`): heuristic extraction (LLM extraction exists but the API builds the Clarifier with no LLM) fills
   `ExtractedFields` (product area, platform, error messages/codes, symptoms, severity); `detect_gaps` marks what is missing.
5. **Differential diagnosis** (`differential.py`): up to 3 searches against the hybrid KB retriever; chunks are grouped into one hypothesis per
   KB issue; scores become probabilities (softmax); a customer-quoted documented error can lift a cause (verbatim shortcut).
6. **Decision.** One cause clearly leads -> READY with no question. Otherwise the most discriminating question: yes/no for 1-2 close
   causes, a symptom tick-list for 3 or more, a missing fact (platform, error text, product), or an open "tell me more". Budget: 3 questions.
   Each question is an `interrupt()`; the service stores it as a `question` message and returns.
7. **Resolver** (`resolver/graph.py`): guard -> cache -> retrieve (KB, then community, then tickets when the best KB evidence is weak) ->
   gate -> draft -> verify -> send.
8. **Gate** (`resolver/gate.py`): confidence = 0.45 top score + 0.15 margin + 0.20 agreement + 0.20 completeness; strong only if top >= 0.55,
   confidence >= 0.6 and not (low margin and low agreement). Weak evidence -> escalate; a thin signature -> back to the Clarifier.
9. **Draft and verify.** The model must cite evidence ids; `verify_draft` drops steps with no valid citation or with a backticked command
   or URL that is not in the cited evidence; fewer than half surviving -> verification fails -> ticket tier or escalate.
10. **Reply.** The customer sees the steps with sources (official / community / community guide) and two buttons. "That fixed it" and
    "still the same error" skip the classifier model; typed replies are classified by one LLM call.
11. **End states.** resolved (the fix is cached), retry (up to 2 fixes, evidence never repeated), escalated (reason + priority + payload
    for the engineer queue), declined (out of scope). Every step is logged to `agent_events` with latency, tokens and cost.

---

## 3. Component-wise functional evaluation

Numbers: **S29** = the 29 hand-written scenarios, **H65** = the 65 held-out real questions (labels unverified, only 13 have a documented
answer), fake drafting model, seed 0. The simulated customer is rule-based and the "oracle" says a fix worked only when it cites the gold issue.

### A. Clarification

| Question | Evidence | Verdict |
|---|---|---|
| Understands vague complaints? | Guardrail suite: 8/8 vague queries asked for symptoms instead of guessing. "docker is broken" and "docker" end after 2 questions in a P3 escalation (probe). | PASS |
| Extracts relevant details? | On the 29 openings: gap precision/recall 1.0/1.0, product-area accuracy 0.909, platform 1.0, error-code recall 1.0 (a small labelled set). | PASS (small set) |
| Identifies missing information? | Same gap metrics; question mix on S29: 13 yes/no, 11 open "tell me more", 9 error-text, 4 symptom lists, 3 product, 3 error menus. | PASS |
| Focused, useful questions? | Format checks 100% (single question, options present, length). Usefulness to a real customer was never rated by a person. | PARTIAL |
| Avoids unnecessary questions? | S29: mean 1.48 questions, 3/29 zero-question cases (2/7 on "clear" openings), redundant 3/43 questions. H65: mean 2.06, **33/65 reached the 3-question cap**, Clarifier READY only 5/65 (7.7%). A real defect: an exactly quoted error plus one extra word triggers "tell me more" (issue F-02). | PARTIAL |

Clarifier alone on S29: READY 65.5%, gold top-1 0.90, top-3 0.95, READY precision 1.0, wrong-READY 0, out-of-scope false-READY 0.
On H65 (13 gold): top-1 0.385, top-3 0.615.

### B. Problem normalization

* Structure: `ExtractedFields` -> canonical string `product|component|symptoms`, validated; PII is masked before storage (guardrail PASS: 4 items redacted).
* The existing paraphrase file has **one query per gold issue (42 issues, 42 queries)**, so it cannot measure consistency.
* Probe written for this review (6 problems x 3-4 phrasings, 21 pairs; `probes/probe_normalization.py`): same `product_area` in
  **14/21 pairs (67%)**, same top-1 KB cause in **11/21 pairs (52%)**. Stable: rate limit (6/6), daemon not running (3/3). Unstable: WSL start
  (0/3), socket permission (0/3), OOM (1/3), port in use (1/3). Example: "docker inspect shows OOMKilled true and exit code 137" ranked an unrelated
  "Scan Docker Hardened Images" page first, while the two other OOM phrasings found "Out of memory issues".
* Verdict: structure PASS; consistency across paraphrases **PARTIAL** (a small probe written for this review, not a benchmark).

### C. Hybrid RAG

| Check | Evidence | Verdict |
|---|---|---|
| Ingestion works | Pipeline scripts 02-06 produced 11,440 KB chunks; chunker, store-guard and ticket tests pass (16+4+15). | PASS |
| Relevant documents retrieved | Issue-level, on the opening message only (`ontology_eval`, 4 modes): paraphrases (n=42) Recall@1/3/8 = 0.52/0.79/0.95, MRR 0.68 with the ontology; 0.52/0.71/0.83, MRR 0.63 without. 20 scenario openings: 0.50/0.65/0.80, MRR 0.60. **In-flow** on S29 (after the Clarifier's questions): Recall@1 0.90, @3 0.95, MRR 0.925. **H65 gold (n=13): Recall@1 0.31, @3 0.69, @8 0.85, MRR 0.49.** | PARTIAL |
| Hybrid fuses correctly | Dense + BM25 + ontology lists fused by weighted RRF; the ontology helps recall (paraphrase R@8 0.83 -> 0.95; improved 9 queries, worsened 2) and never counts as evidence. | PASS |
| Irrelevant results filtered | Gate floor 0.55 on the top score. On S29 gold tops are higher than no-answer tops (median 0.78 vs 0.56). On H65 they are **nearly the same (0.56 vs 0.52)**, so the filter does not separate answerable from unanswerable real questions. | PARTIAL |
| Source information preserved | Every evidence item carries url, tier, trust, licence, source tier; the UI labels official / community answer / community guide; 100% of 26 fixes cite ids that exist. | PASS |

Only 283 of the 11,440 KB chunks (2.5%) are troubleshooting or FAQ content; most real problems have no matching documented issue (H65: 52 of 65 labelled "KB gap", unverified).

### D. Resolution

| Check | Evidence | Verdict |
|---|---|---|
| Uses retrieved evidence | Draft prompt contains only the evidence block; `verify_draft` enforces citation. Fake-model fixes quote the evidence; 26/26 sent fixes cited existing evidence ids. | PASS |
| Steps relevant to the actual issue | S29: first fix cites the gold issue 18/18 times it answered; H65: 3 of 5 KB-backed answers (2 were wrong, both on "KB gap" labels). With a real model (13 Oct run): 17/20 gold resolved, 0 wrong first fixes on S29, 2/13 wrong on H65. | PARTIAL |
| Citations accurate and traceable | Structure verified (ids, URLs, licences). **Whether each claim is supported by its cited text was not measured**: the judge exists (`triage/eval/judge.py`, with planted-fault controls) but there is no judge result anywhere in the repo, and it needs a model key. | NOT TESTED |
| Avoids unsupported claims | `verify_draft` drops steps whose backticked command or URL is not in the cited evidence (unit-tested). It does **not** check prose claims. | PARTIAL |
| Acknowledges insufficient evidence | Draft status INSUFFICIENT_EVIDENCE and an empty knowledge base both lead to escalation (probes). | PASS |

### E. Confidence gate

| Check | Evidence | Verdict |
|---|---|---|
| Distinguishes resolve / clarify / escalate | S29 gate decisions: resolve 20, escalate 6, fallback 1; H65: resolve 6, escalate 59, fallback 2. **The "clarify" decision never occurred in any evaluation run**; the Clarifier handles clarification itself. It is exercised only by unit tests. | PARTIAL |
| Decision rules implemented correctly | Matches its docstring; unit-tested (strong vs empty, thresholds). | PASS |
| Prevents unsafe or unsupported resolutions | S29: 0 wrong of 19 answered. Gate replay on H65 with the shipped thresholds: 3 correct, **2 wrong of 5 answered**. Thresholds "recommended" by the calibration tool (fitted on S29) give **4 correct, 20 wrong on H65**: they do not transfer, and the shipped values are still unvalidated starting guesses. S25 ("docker") got a KB fix plus a ticket fix, but see the correction under F-06: that was a retrieval-quality miss, not vague input getting through. | PARTIAL |
| Critical and uncertain issues | Data loss / security text -> P1 escalation (probe), but only after one unrelated question (F-04). The CRITICAL-severity rule cannot fire in the shipped configuration (F-05). Out of scope and prompt injection are declined with no interview (probe, 4/4 injections neutralised in the guardrail suite). | PARTIAL |

### F. End-to-end workflow

| Check | Evidence | Verdict |
|---|---|---|
| Components work together | 29 + 65 scenarios ran through the real graph on the real stores; 31 integration tests and 18+11 API tests pass. | PASS |
| Information passes correctly between agents | Signature translation (`handoff.py`) carries hypotheses, entities, p_top and uncovered terms; screenshot error lines reach both agents (verified by trace). | PASS |
| State and context maintained | SQLite checkpointer; `test_a_conversation_survives_a_server_restart` passes. | PASS |
| Failures handled | Provider errors and malformed drafts escalate as SYSTEM_ERROR instead of hanging (probe), but with no retry (R-01). | PARTIAL |
| Final response matches the gate's decision | S29: 20 "resolve" decisions = 20 fixes sent; H65: 6 = 6; every escalate decision produced an escalation message. | PASS |

---

## 4. End-to-end workflow evaluation

| Run | Result |
|---|---|
| S29, fake model, current code | Correct terminal action 26/29 (89.7%). Gold: answered right first time 18/20; the 2 misses (S08 "Docker isn't starting", S17 "rootless pull") escalated LOW_EVIDENCE. No-answer cases: escalation recall 9/9, precision 9/11; 1 wrong fix (S25: the opening was one word, but the scripted customer then said "docker desktop crashes at startup"; the first fix cited a navigation page, "Troubleshoot menu", a retrieval miss; see the correction under F-06). |
| H65, fake model, current code (labels unverified) | Correct terminal action 53/65 (81.5%) but mostly by escalating: resolved 3/65, escalated 60. Of the 13 documented problems only 3 were answered (23%). 2 KB fixes sent where the KB has no answer (H037, H047). |
| S29, Gemini `gemini-3.5-flash-lite`, 13 Oct (older code) | 17/20 gold resolved, 0 wrong first fixes, 4/4 out-of-scope declined, mean 1.17 questions. |
| H65, Gemini, 13 Oct (older code) | 3/13 gold resolved, 2/13 wrong first fix, 60 escalated. |
| Gate probes (offline, `probes/probe_gate_routing.py`) | clear documented error -> fix; production outage -> ordinary fix (no priority); vague/one word -> 2 questions then P3 escalation; not Docker and prompt injection -> declined at once; data loss and security -> 1 question then P1 escalation. |

Caveat: the simulated customer answers menus perfectly and the oracle credits only gold-issue citations; S29 was written by the project author and
the thresholds were tuned against it, so S29 numbers are an upper bound. H65 is the only independent set and its labels are drafts.

---

## 5. Functional requirements table

| # | Requirement | Status | Basis |
|---|---|---|---|
| A1 | Understand vague complaints | PASS | guardrail 8/8; probes |
| A2 | Extract relevant details | PASS | gap/extraction metrics (small set) |
| A3 | Identify missing information | PASS | gap precision/recall 1.0 |
| A4 | Focused, useful questions | PARTIAL | format 100%; usefulness never rated |
| A5 | Avoid unnecessary questions | PARTIAL | S29 good; H65 33/65 at cap; F-02 |
| B1 | Consistent structured representation | PASS | validated contract |
| B2 | Technical details preserved | PASS | error codes recall 1.0; PII masked |
| B3 | Paraphrases give similar signatures | PARTIAL | 52% same top-1 cause (probe) |
| C1 | Ingestion works | PASS | 11,440 chunks; pipeline tests |
| C2 | Relevant documents retrieved | PARTIAL | S29 0.90 R@1 in-flow; H65 0.31 |
| C3 | Hybrid search combines methods | PASS | RRF; ablation |
| C4 | Irrelevant results filtered | PARTIAL | weak score separation on real questions |
| C5 | Source information preserved | PASS | url/tier/licence/trust |
| D1 | Uses retrieved evidence | PASS | prompt + verify |
| D2 | Steps relevant to the issue | PARTIAL | 18/18 on S29; weak on H65 |
| D3 | Citations accurate and traceable | NOT TESTED | structure only; judge never run |
| D4 | Avoids unsupported claims | PARTIAL | commands/URLs checked, prose not |
| D5 | Acknowledges insufficient evidence | PASS | probes |
| E1 | Resolve / clarify / escalate | PARTIAL | clarify never seen outside unit tests |
| E2 | Rules implemented correctly | PASS | unit tests |
| E3 | Prevents unsafe resolutions | PARTIAL | S29 0 wrong; H65 2 of 5 wrong; no transfer of calibration |
| E4 | Critical and uncertain issues | PARTIAL | P1 for data loss; CRITICAL unreachable |
| F1 | Components work together | PASS | runs + tests |
| F2 | Information passed correctly | PASS | signature trace |
| F3 | State and context maintained | PASS | checkpointer + restart test |
| F4 | Failures handled | PARTIAL | escalates, no retry |
| F5 | Response matches gate decision | PASS | counts match |
| X1 | Screenshot upload and OCR | PASS | real Tesseract read the 9 readable test screenshots (the blurred one was flagged low-confidence, the blank one unreadable); 23 tests |
| X2 | Real-model end-to-end on current code | NOT TESTED | last real run 13 Oct, older code |
| X3 | Browser end-to-end UI | NOT TESTED | 26 unit tests, typecheck and build pass; no browser run in this review |

---

## 6. Performance evaluation

### 6.1 Measured on the current code (fake drafting model: retrieval + Clarifier + graph only)

| Measure | S29 | H65 |
|---|---|---|
| End-to-end time per case | p50 1.71 s, p95 6.80 s, max 16.2 s (first case, model warm-up) | p50 2.67 s, p95 7.74 s |
| Time to first reply | p50 0.41 s, p95 1.78 s | p50 0.46 s, p95 1.19 s |
| One Resolver retrieval | p50 0.36 s, p95 3.61 s (n=27) | p50 0.95 s, p95 1.68 s (n=67) |
| Clarifier searches per ticket | 7.0 | 8.85 |
| LLM calls per case | mean 2.34 (scope 28, draft 20, classify 20) | mean 1.18 (scope 65, draft 6, classify 6) |
| Semantic cache | 25 lookups, 25 misses | 63 lookups, 63 misses |

### 6.2 Real model (older code; from `reports/e2e_*_gemini.json`, 13 Oct, `gemini-3.5-flash-lite`)

| | S29 | H65 |
|---|---|---|
| Wall time | 326 s (11 s per scenario, includes simulated multi-turn) | 626 s (9.6 s per scenario) |
| LLM calls / tokens | 64 calls (2.2 per case); 64,106 in, 4,754 out (about 2,210 in and 164 out per case) | 91 calls; 84,859 in, 4,989 out |
| Cost | $0.0311 (about $0.0011 per case) | $0.0379 |
| LLM latency | p50 3.26 s, p95 4.90 s | p50 3.03 s, p95 4.39 s |

### 6.3 Live sessions (agent_events in `app.db`, 24 real calls; small and noisy)

| Node | Calls | Mean latency | Max |
|---|---|---|---|
| scope (first message) | 9 | 8.8 s | 17.4 s |
| classify (typed reply) | 4 | 11.4 s | 29.0 s |
| draft | 5 | 3.5 s | 8.3 s |

The two tiny classification calls were the slowest. A first reply to a new customer is scope + retrieval + draft, roughly 8-15 s on those numbers.
Not measured: current code with a real model end to end.

---

## 7. Code quality assessment

* **Structure is sound for a two-person academic project.** One package per agent, contracts in dataclasses, thresholds in config files, a thin API
  layer, offline fakes for the model and retrievers, and a large test suite (425 tests). Docstrings explain the "why" almost everywhere.
* **Long functions:** `build_resolver_graph` 323 lines and `create_app` 196 lines (nested closures/routes; normal for LangGraph and FastAPI, but hard to
  unit-test in isolation); `rank_discriminators` 85. Twelve functions exceed 60 lines, two exceed 100.
* **Duplication:** `triage/resolver/graph_integration.py` and `standalone.py` are byte-identical (81 lines each); three separate secret/PII maskers
  with different coverage; two signature contracts, two retriever interfaces and two LLM layers joined by adapters (a consequence of two authors; it works).
* **Unused code (referenced only by tests or nowhere):** `Clarifier.build_graph`, `Clarifier.as_node`, `SessionMemory.asked_features`,
  `render_retry_context`, `validate_signature`, `HashEmbedder`, `BgeEmbedder`, `Ontology.ancestors`, `Ontology.children`, `EventLogger.of_type`,
  `ocr.extract_text_from_image`. Stale pre-pivot scripts: `scripts/01_profile.py` (Microsoft support corpus) and `scripts/08_evaluate.py` (Azure/Windows queries).
* **Hardcoded values:** every gate/cache/Clarifier threshold is a tuned-by-hand constant in config files (acceptable), but also the foreign-service
  word list, the scope block confidence (0.8), timeouts, upload limits, default model names.
* **Dependencies:** all listed packages are used. `easyocr`/`rapidocr` are optional and not installed. No TODO/FIXME markers.
* **Docs drift:** README, ARCHITECTURE and the Clarifier handbook still say "356 tests", "no live LLM run", "not yet committed".

---

## 8. Reliability issues

Probes run through the real HTTP app with an offline stack (`probes/probe_reliability.py`):

| Input / fault | Result |
|---|---|
| Empty or whitespace message | 422 "message is empty" |
| 4,000 vs 4,001 characters | 201 vs 422 |
| Emoji/unicode, Korean, `<script>`, SQL-looking text, null byte, a 3,000-character single token | accepted; handled as ordinary text; no crash |
| Draft returns `steps` as a string / list of strings / a list instead of an object | escalated as SYSTEM_ERROR ("I ran into a technical problem") |
| Draft returns `{}` or `INSUFFICIENT_EVIDENCE` or `evidence_ids` as a string | escalated normally (no usable steps) |
| Draft raises `TimeoutError` / `RuntimeError` | escalated as SYSTEM_ERROR |
| `diagnosis` null | fix sent without a diagnosis line |
| Empty knowledge base | escalated |
| Scope classifier fails | fails open by design (code and guardrail test) |
| Gemini call hangs | 90 s timeout, one immediate retry (up to 3 minutes inside one HTTP request); Anthropic/OpenAI calls have no timeout |

---

## 9. Missing test cases and evaluation gaps

### Missing tests

1. Resolver-level malformed model output (string steps, wrong types): currently only a provider-failure test exists.
2. Data-loss / security opening escalates without a clarifying question first.
3. CRITICAL severity reachable from the default (heuristic) extractor, or the rule removed.
4. Vague input never produces a fix, and is not told "not Docker" (the real-store probe showed 3 of 8 vague openings declined as out of scope; see the correction under F-06).
5. A quoted documented error plus a descriptive sentence is READY with no question (two tests for this were added and currently fail, see below).
6. Gemini timeout/retry behaviour with a fake client; Anthropic/OpenAI timeouts.
7. Two simultaneous messages on one conversation (the lock).
8. Paraphrase-group consistency (needs paraphrase groups in the dataset).
9. OCR on real photos or low-resolution screenshots (all current OCR images are generated).
10. Browser end-to-end for upload, quick-reply buttons and the engineer console.
11. A regression test pinning faithfulness on a few judged fixes.

### Evaluation gaps (can the project be evaluated for ...)

| Item | Can it be evaluated now? |
|---|---|
| Clarification quality | Partly: gap/format/question-count metrics and a simulator exist; no human rating of usefulness and no real-customer data. |
| Normalization consistency | Not with the shipped data (one query per issue). The probe here is the only measurement. |
| Retrieval Recall@K / MRR | Yes (labels exist): 42 paraphrases, 20 scenario openings, 13 held-out gold (unverified). Chunk-level and issue-level versions give different numbers; report which. |
| Citation correctness | Structure: yes. Support by the cited text: judge exists, never run. |
| Hallucination rate | Same: `judge.py` + `--self-check` exist; no results. |
| Resolve-versus-escalate quality | Yes on proxies (S29, H65), with the caveats about labels and tuning. |
| End-to-end task success | Yes with the oracle; no real-customer or human-judged outcome. |
| Latency and tokens | Yes, but the only real-model figures are from 13 Oct (older code) and a handful of live calls. |

### Tests run in this review

Python: 425 collected, **423 passed, 2 failed**. The two failures are tests I added earlier in this session for the Clarifier change that was
requested but not yet applied (`test_a_verbatim_documented_error_wins_over_an_uncovered_filler_word`, `test_the_verbatim_shortcut_still_cannot_override_weak_evidence_or_ungrounded_leaders`).
The first fails because the fix is not in; **the second is mis-specified** (the Clarifier's `min_top_score` default is 0.0, so a 0.01 score is not "no evidence")
and must be corrected when the change is made. Frontend: 26 passed, typecheck and build clean.

---

## 10. Critical bugs and weaknesses (summary)

1. Real-question performance is much weaker than the scenario numbers suggest (F-01, F-03).
2. The gate's safety claim rests on same-author scenarios and does not transfer (F-03).
3. Faithfulness and hallucination have never been measured (Q-01).
4. One malformed draft ends the automated flow (R-01).
5. An exactly quoted error is not treated as clear when the message has one extra word (F-02).

---

## 11. Unnecessary code or complexity

| ID | File | What | Action |
|---|---|---|---|
| U-01 | `triage/resolver/graph_integration.py`, `standalone.py` | identical 81-line files | keep one, point the demo script and tests at it |
| U-02 | `scripts/01_profile.py`, `scripts/08_evaluate.py`, `notebooks/` | pre-pivot (Microsoft/Azure) corpus tooling | move to an `archive/` folder or delete |
| U-03 | 11 functions listed in section 7 | referenced only by tests or not at all | delete or mark "used by tests" |
| U-04 | `triage/understand.py` (3 PII/secret patterns across 3 files) | triplicated masking | one shared `redact()` |
| U-05 | `resolver/graph.py` opt-in features (query expansion, multi-draft, URL check) | three switches, none measured | keep off; decide after one A/B run or remove |

Not recommended: rewriting the two-contract design (Clarifier signature vs Resolver signature) or the two retriever interfaces; they work and are tested.

---

## 12. Issues and prioritized improvements

Severity: High / Medium / Low. Effort in brackets: S = under half a day, M = a day or two.

### High

| ID | Affected file | Problem | Why it matters | Sev | Suggested solution |
|---|---|---|---|---|---|
| F-01 | `triage/hybrid.py`, `triage/differential.py`, KB content | On real questions (H65, 13 gold): top-1 0.31, top-3 0.69, Clarifier READY 7.7%, 10 of 13 documented problems escalated. Only 2.5% of the KB is troubleshooting/FAQ. Labels are drafts. | The project looks strong on S29 (0.90) and weak on unseen questions; the headline claim needs the honest number. | High | [S] verify the 13 "gold" and a sample of "KB gap" labels first; [M] then examine misses (rank vs coverage) and favour troubleshooting/FAQ chunks in ranking; report H65 next to S29 everywhere. |
| F-03 | `triage/resolver/config.py` (`GateConfig`), `gate.py`, `eval/calibrate_gate.py` | Gate thresholds are unvalidated guesses. Replay on H65: 3 correct, 2 wrong of 5 answered. Tool-recommended thresholds (tuned on S29): 4 correct, 20 wrong on H65. Top-score medians gold 0.56 vs non-gold 0.52 on real questions. | "Prevents unsupported resolutions" is only shown on same-author data. | High | [S] keep the shipped thresholds, do not adopt the recommended ones; [M] tune on part of H65 and test on the rest once labels are verified; consider an agreement signal (does the draft's cited issue match the Clarifier's top cause?). |
| Q-01 | `triage/eval/judge.py`, `resolver/steps.py::verify_draft` | No faithfulness or hallucination result exists; `verify_draft` checks backticked commands/URLs only. | The core "evidence-first" claim is untested for prose claims. | High | [S, you run it] `python -m triage.eval.agent_metrics --llm gemini --judge gemini --self-check` on S29 and H65; report unsupported-claim rate and whether the planted-fault controls are caught. |

### Medium

| ID | Affected file | Problem | Why it matters | Sev | Suggested solution |
|---|---|---|---|---|---|
| F-02 | `triage/differential.py::decide` (line 225) | The uncovered-term check runs before the "clear" and verbatim-error checks. Customer text "Getting this error in while pulling nginx server" + the exact documented error (leader 0.556, margin 0.40) gets "tell me more" because "server" is not in the leading doc. | Defeats the "clear complaint, no questions" feature in a very common message shape (a sentence plus a pasted error). Frequency not measured. | Medium | [S] let a verbatim documented error win over an uncovered word (keep ungrounded/no-evidence checks first); run `scripts/run_clarifier_regression.sh before/after` (baseline already recorded in `reports/regression/before_*`). Fix the second pending test. |
| R-01 | `resolver/steps.py::draft_resolution`, `resolver/graph.py` draft node, `api/service.py::_fail` | A malformed model reply (string steps, wrong types) or one timeout escalates the whole conversation as SYSTEM_ERROR with no retry. 5 of 9 faulty-model probes ended that way. | One bad sample from a hosted model costs the customer the automated answer. | Medium | [S] validate the draft shape, retry the draft once, then escalate. |
| F-04 | `triage/resolver/handoff.py` (clarifier node) | Hard-escalation rules (data loss, security) run only in the Resolver guard, after the Clarifier's first question. | A customer reporting data loss first gets "copy the exact error message". | Medium | [S] run `hard_escalation` on the opening text in the Clarifier node and skip the interview. |
| F-05 | `triage/understand.py:286`, `resolver/guardrails.py:67` | The heuristic extractor never produces "Critical"; the LLM extractor is off in the API. `CRITICAL_SEVERITY` escalation cannot fire; "production outage, all users blocked" got an ordinary fix, no priority. | A documented escalation path is dead code in the shipped setup. | Medium | [S] map production/outage/all-users wording to Critical in the heuristic, or raise priority without escalating; add a test. |
| F-06 | `resolver/handoff.py::completeness_of`, `gate.py` | **Corrected in the follow-up (reports/IMPROVEMENT_REPORT.md): the original reading was wrong.** S25's fix came after the customer gave a concrete symptom; the first fix cited a navigation page (retrieval miss). Tracing vague input directly on the real stores found something else: 3 of 8 vague openings ("help", "it doesn't work", "error") were declined as out of scope, and on the offline demo corpus "I have a problem with docker" plus non-answers still got an unrelated fix. | Vague customers were told "not Docker", or could be handed a guess. | Medium | Escalate content-free conversations to a person; never draft when the Clarifier gave up and the customer only named the product. Done in the follow-up. |
| F-07 | `triage/understand.py`, `triage/hybrid.py` | Probe: same top-1 cause for 11/21 paraphrase pairs, same product area for 14/21. | Different wording of one problem gives different diagnoses. | Medium | [M] add paraphrase groups (3 per problem, about 20 problems) to the dataset, measure, then adjust alias tables/ontology. |
| P-01 | `resolver/handoff.py` | A scope LLM call on every first message (28 of 29 cases), about a quarter of all calls, 3-9 s each, even when the text has clear Docker vocabulary. | Adds seconds and cost to nearly every conversation. | Medium | [S] call it only when the message has no Docker terms (the rule check already exists). |
| P-02 | `triage/llm.py`, `resolver/llm.py`, `api/service.py` | Hosted-model latency varies from 3 s to 29 s; request is synchronous; Gemini 90 s x 2 tries inside one HTTP request; no timeout for Anthropic/OpenAI. | A stuck call can freeze the chat for minutes. | Medium | [S] cap total time per request (e.g. 45 s) with the existing escalation fallback; add a timeout to the other providers. |

### Low

| ID | Affected file | Problem | Why it matters | Sev | Suggested solution |
|---|---|---|---|---|---|
| P-03 | `triage/clarifier.py`, `resolver/graph.py` | 7-9 searches per ticket, plus Resolver retrieval; each embeds on CPU (p95 up to 3.6 s). | Wasted work on a CPU-only machine. | Low | [S] cache query embeddings within a conversation. |
| Q-02 | `triage/resolver/standalone.py`, `graph_integration.py` | Byte-identical duplicates. | Confusion; edits can diverge. | Low | Keep one. |
| Q-03 | `scripts/01_profile.py`, `scripts/08_evaluate.py` | Evaluate/profile the pre-pivot Microsoft corpus; `08_evaluate.py` cannot test the Docker KB. | Misleading for a reader. | Low | Archive or rewrite on `paraphrases.jsonl`. |
| Q-04 | `resolver/graph.py::build_resolver_graph` (323 lines), `api/app.py::create_app` (196) | Very long builder functions. | Harder to test and read. | Low | Leave; optionally split route groups into functions. |
| Q-05 | `understand.redact_pii`, `guardrails.mask_pii`, `ocr._SECRETS` | Three maskers with different patterns (e.g. `guardrails.mask_pii` misses `docker login -p`). | Inconsistent redaction. | Low | One shared function. |
| Q-06 | 11 functions (section 7) | Unused in production code. | Noise. | Low | Delete or document. |
| Q-07 | several | Hardcoded: foreign-service list, scope confidence 0.8, default model names, limits. | Hard to tune. | Low | Move to config files. |
| D-01 | `README.md`, `docs/ARCHITECTURE.md`, `docs/MEMBER_A_HANDBOOK.md`, `requirements.txt` | "356 tests" (now 425), "no live LLM run" (Gemini runs exist), "not yet committed"; a requirements comment names a route that does not exist (`/api/conversations/{id}/attachments`; the real one is `POST /api/attachments`, my mistake in the last task). | Credibility. | Low | Update numbers and wording. |
| T-01 | `tests/test_differential.py` | Two tests for the pending F-02 change fail (one is mis-specified). | Red suite. | Low | Apply F-02, fix the second test. |

### Order I would do them in

1. Verify the held-out labels (F-01) and run the faithfulness judge (Q-01): these two turn the report's biggest unknowns into numbers.
2. F-02, F-04, F-05, F-06: four small Clarifier/Resolver fixes with clear tests.
3. R-01, P-01, P-02: robustness and latency, a few lines each.
4. Housekeeping: U-01 to U-05, D-01, T-01.
5. Only after labels are verified: gate tuning (F-03) and paraphrase groups (F-07).

---

## Appendix: what was and was not run for this report

**Run now:** Clarifier-only eval (29), end-to-end eval on S29 and H65 (fake model, seed 0), ontology ablation (42 + 20 queries x 4 modes), gate replay and calibration
(S29 tune, H65 test), normalization probe, reliability probes, gate routing probes, full Python test suite, frontend tests/typecheck/build (earlier in the session, unchanged since), static analysis (size, long
functions, unused definitions, duplicate blocks).
**Read from earlier runs and labelled as such:** the 13 Oct Gemini reports, the 24 live LLM calls in `app.db`.
**Not run:** faithfulness judge (needs your key; you prefer to run paid calls), any current-code run with a real model, browser end-to-end.
