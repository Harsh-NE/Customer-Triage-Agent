# Member A handbook — Understanding & Clarifier track

For **Member B** (Retrieval & Resolver track). This is the knowledge-transfer document for everything
Member A built: what exists, how to run it, the contracts you depend on, **every assumption I made**,
what was and was not verified, and how to plug your work in. Written against the Team Workplan v2
(tasks A1–A10).

> Read §1 (status), §2 (run it), §6 (integration) and §7 (assumptions) first. The rest is reference.

---

## 1. Status against the workplan

| Task | Deliverable (workplan) | Status | Where |
|---|---|---|---|
| A1 | Tier-2 ticket dataset + quality report | **Done earlier** (Colab notebooks 01–09, `docker_tickets_v5`, boolean-column patch). *Not consumed or re-verified in this session* — see assumption 17 | `notebooks/`, `docs/DATASET_QUALITY_REPORT.md` |
| A2 | `understand.py` + unit tests | **Done** | `triage/understand.py`, `tests/test_understand.py` (55 tests) |
| A3 | `clarifier.py` (LangGraph node) | **Done** | `triage/clarifier.py` |
| A4 | `ambiguity_check()` + retrieval stub | **Done**, extended into differential diagnosis | `triage/differential.py`, `triage/retrieval.py`, `triage/issues.py` |
| A5 | Simulated customer + labeled multi-turn set | **Done, with a deviation**: scenarios are hand-authored from real KB entries, **not** seeded from tickets | `triage/sim/`, `triage/eval/scenarios.jsonl` (29) |
| A6 | Eval report + guardrail suite | **Done** | `triage/eval/`, `reports/clarifier_eval_report.md`, `tests/test_guardrails.py` |
| A7 | `state.py` shared contract | **Done — awaiting your review** (it is the Joint task) | `triage/state.py` |
| A9 | `context_session.py` | **Done** | `triage/context_session.py` |
| A10 | `reflect_question()` | **Done** | `triage/reflect.py` |
| A8 | Documentation | This file | `docs/MEMBER_A_HANDBOOK.md` |

**Headline numbers** (offline, free, vector-only retriever — read the caveats in §8 before quoting these):

| Metric | Value |
|---|---|
| Tests | **152 pass** (140 offline + 12 against the real Docker store) |
| Gold issue is the Clarifier's #1 hypothesis | **0.85** (17 of 20 labeled scenarios) |
| READY precision (READY *and* correct) | **0.94** (16 of 17) |
| Wrong-READY rate | **0.05** (1 of 20: S07) |
| Out-of-scope false-READY | **0.0** (0 of 6) |
| Mean questions per ticket | 1.34 |
| Redundant / duplicate questions | 0.0 / 0.0 |
| Guardrail checks | 6 of 6 pass, each with a negative control |

---

## 2. Run it

```bash
pip install -r requirements.txt          # adds langgraph + pytest to the existing deps
python -m pytest                          # 152 tests; the 12 real-store tests skip if the store is absent
python -m pytest -m real_store -s         # only the real-store tests (~1.5 min: each runs full dialogues on the real store)
```

**Try it by hand** (free — heuristic extraction, no API key, no network after the first model download):

```bash
python -m triage.cli chat -v                       # you play the customer; /state, /record, /quit
python -m triage.cli replay --id S02 -v            # a labeled scenario with a simulated customer
python -m triage.cli replay --all                  # one line per scenario
```

**Evaluate** (offline, ~50 s; writes `reports/clarifier_eval_report.md` + `.json`):

```bash
python -m triage.eval.clarifier_eval                       # vector retriever, heuristic extractor, rule-based customer
python -m triage.eval.clarifier_eval --sweep               # + threshold calibration grid (~2.5 min, 81 configs)
python -m triage.eval.clarifier_eval --retriever keyword   # crude keyword retriever over the real chunks
python -m triage.eval.clarifier_eval --retriever-factory yourpkg.retrieve:make_retriever   # YOUR hybrid retriever
python -m triage.eval.clarifier_eval --extractor llm       # real LLM extraction  (costs API calls — you run it)
python -m triage.eval.clarifier_eval --extractor llm --customer llm   # LLM also plays the customer
```

**Live-LLM runs were never executed by me** (assumption 11). Rough cost of `--extractor llm`: one extraction
call per customer message, ~2 messages × 29 scenarios ≈ 60 calls; `--customer llm` roughly doubles that. These
are estimates, not measurements — `meta.llm_usage` in the JSON report records the real count after your run.

**Prerequisite data:** the Docker store at `data/processed/docker/store/` (built by `scripts/01–06`). The offline
tests need nothing; the real-store tests and the default eval do.

---

## 3. Architecture at a glance

```
customer message
      │
      ▼  ┌────────────────────────── Clarifier.turn(session, message) ──────────────────────────┐
         │ ingest      redact PII → store turn → match it to any OPEN question's options          │
         │ understand  extract fields (LLM, or heuristic fallback) → merge into SessionMemory     │
         │             → detect gaps                                                              │
         │   ┌─ hard gap (no specific symptom)?  ──► ask_gap ─────────────────► ASK               │
         │   └─ else diagnose: search_kb ×3 → cluster chunks into HYPOTHESES (one per KB issue)   │
         │            decide: does one cause clearly lead AND is it grounded in the customer's    │
         │                    words?  ──────────────────────────────────────────► READY           │
         │            else rank discriminating questions → reflect (redundant?) ─► ASK            │
         │            else ask for the exact error text, once (last resort) ────► ASK             │
         │            else / budget spent ──────────────────────────────────────► UNRESOLVED      │
         └──────────────────────────────────────────────────────────────────────────────────────┘
READY / UNRESOLVED carry a ProblemSignature (+ ranked hypotheses) → Resolver
Resolver → Clarifier.reenter(session, NeedClarification(field)) → one more question, same budget
```

| File | Role | Task |
|---|---|---|
| `triage/state.py` | All shared dataclasses, JSON round-trip, `validate_signature`, `SCHEMA_VERSION` | A7 |
| `triage/understand.py` | PII redaction, product/platform normalization, regex extractors, heuristic + LLM extraction, merge, gap detection, signature | A2 |
| `triage/clarifier.py` | The agent: stages, question templates, `turn`, `reenter`, `build_graph`, `as_node` | A3 |
| `triage/differential.py` | Hypotheses, ambiguity decision, discriminating-question ranking, soft re-weighting | A4 |
| `triage/issues.py` | What counts as "one KB issue" (heading-depth quirks of the real KB) | A4 |
| `triage/retrieval.py` | `Retriever` contract; `MockRetriever`, `ChromaRetriever` (vector-only stand-ins) | A4 |
| `triage/tools.py` | Tool Registry: allowlist + per-turn budget + call log | Phase 0 |
| `triage/answers.py` | Deterministic mapping of a customer reply to an offered option | A3 |
| `triage/context_session.py` | `SessionMemory`: working memory, compaction, retry history, persistence | A9 |
| `triage/reflect.py` | Redundant-question check | A10 |
| `triage/llm.py`, `triage/config.py` | One-method LLM interface (Gemini/Anthropic/OpenAI), `ScriptedLLM` for tests; env + thresholds | — |
| `triage/sim/`, `triage/eval/` | Simulated customer, dialogue driver, scenarios, metrics, guardrails, report | A5, A6 |
| `triage/cli.py` | `chat` / `replay` | — |

### How the differential diagnosis works (the part most worth understanding)

A symptom like *"docker pull fails with 429"* matches several different KB issues. Instead of a generic
"can you give more detail?", the Clarifier:

1. **Retrieves** chunks (3 queries, merged by best score: everything-we-know; the same prefixed with `troubleshoot`;
   the customer's verbatim error text) and **groups them into hypotheses** — one per KB *issue*, not per chunk.
2. **Weights** hypotheses: `softmax(score × doc_kind_weight × generic_title_weight / T)`. Release notes get ×0.6,
   archived versions ×0.4, "Overview" sections ×0.5. Then, if the customer pasted an error, hypotheses whose own
   documented error text matches get boosted (up to ×4).
3. **Decides.** READY needs `p_top ≥ 0.5`, `margin ≥ 0.25` **and** the top hypothesis must be *lexically grounded*
   (≥ 34% of the customer's content words appear in its text). Otherwise → ambiguous.
4. **Ranks questions** by *expected elimination* × *answerability*:
   `gain(f) = Σ_v P(answer=v)·(probability mass removed by answer v)`; hypotheses with no known value for `f`
   survive every answer, so features most candidates lack score low automatically. Answerability (platform 1.0,
   error text 0.9, product 0.8, "which of these sounds like yours" 0.6) makes an easier question beat a slightly
   more decisive one. `component` is **never asked** — it is an internal doc-path label ("troubleshoot-and-support")
   no customer can answer.
5. **Re-weights softly** after an answer (contradicting hypotheses ×0.15, never removed — the project's
   "soft signals, never hard filters" principle), and decides again.

An LLM is used for **one thing by default**: field extraction. Everything above is deterministic and auditable.

---

## 4. The contracts you depend on (`triage/state.py`)

`SCHEMA_VERSION = "1.0.0"`. Bump it on any breaking change; assert on it in your code. `from_dict` ignores unknown
keys and defaults missing ones, so an older reader can load a newer record.

### 4.1 `ProblemSignature` — Clarifier → Resolver, and the cache key

| Field | Meaning |
|---|---|
| `canonical_string` | `product\|component\|symptom; symptom` — **the cache key** (see below) |
| `nl_text` | text form of the key (`"docker-hub ?: pull fails"`), what gets embedded |
| `fields` | `ExtractedFields`: product_area, component, symptoms, error_messages, error_codes, platform, environment, versions, category, severity, frustration, impact_scope |
| `confidence` | `p_top`, `margin`, `top_score`, `ambiguous`, `reason` ∈ {`clear`, `split`, `ungrounded`, `no_candidates`, `no_evidence`, + the `unresolved` reasons below} |
| `hypotheses` | top 3 ranked candidate causes: `key` (`source_path::issue`), `label`, `weight`, `chunk_ids`, `features`, `grounding` |
| `embedding` | **`None` unless you pass an `embedder` to `Clarifier(...)`** — see assumption 6 |

* **Cache-key rule (agreed in the design):** only `product|component|symptoms`. Tone (`frustration`) and blast radius
  (`impact_scope`) describe the ticket instance, not the problem. `platform` and `versions` are **metadata gates**,
  not part of the key.
* `hypotheses[].weight` are **probabilities over the full retrieved pool**; the signature keeps only the top 3, so
  they sum to ≤ 1 (consistent with `confidence.p_top`). `validate_signature(sig)` checks this and every other rule —
  call it in your own tests.

### 4.2 `ClarifierResult` and what the Resolver should do with each status

| `status` | Meaning | Resolver action |
|---|---|---|
| `ask` | `question` is set; no signature | send `question.text`, wait, call `turn()` again with the reply |
| `ready` | signature is confident (`confidence.ambiguous == False`) | proceed normally; `hypotheses[0]` is the best-supported KB issue |
| `unresolved` | budget spent / nothing left to ask / no evidence | **Do not treat the signature as confident.** Either proceed conservatively (the gate should be stricter) or escalate. `hypotheses` is a ranked differential — attach it to the escalation payload; it is more useful to a human than "unclear" |

`unresolved` reasons you will see: `budget_exhausted`, `budget_exhausted_with_hard_gap`, `no_discriminating_question`,
`ungrounded`, `no_candidates`, `cannot_ask:<why>`, `cannot_clarify:<why>`, `gap_not_resolvable`.

`result.meta` always has `extraction_source` (`llm`/`heuristic`/`heuristic_fallback`), `tool_calls` (this turn only),
and when retrieval ran: `confidence`, `hypotheses` (top 5), `queries`. Copy these into your ops log (B7).

### 4.3 `NeedClarification` — Resolver → Clarifier

```python
res = clarifier.reenter(session, NeedClarification(field="platform", reason="evidence differs per OS"))
```
Asks **one** targeted question. Counts against the same `max_clarify_turns` (default 3) budget. Fields it can ask
about: `platform`, `product_area`, `symptoms`, `error_message` (open-ended), `component`. Returns `unresolved` with
`cannot_clarify:already_known` if the field is already filled, so a naive Resolver cannot loop.

### 4.4 `Retriever` — **the contract Member B's `retrieve.py` must satisfy**

```python
class Retriever(Protocol):
    def search(self, query: str, top_k: int = 8) -> list[Candidate]: ...
```
* `Candidate.score`: **higher is better, normalised to (0, 1]**. (Chroma stand-in: `1/(1+distance)`.) RRF scores are
  ~0.01–0.03, so you must rescale — the thresholds in `ClarifierConfig` assume a similarity-like scale.
* Return **chunk-level** hits, best first, **plus sibling chunks of the same issue** (see §6.3 — this is the most
  likely integration trap).
* `Candidate.heading_path` must be a **list** `[article, section, subsection?]` down to the *issue* level.
* `Candidate.metadata` keys the Clarifier reads: `doc_kind`, `product_area`, `component`. Others pass through.

### 4.5 `TriageRecord` and `SessionMemory`

`session.to_triage_record(outcome=..., signature=..., evidence_chunk_ids=[...], tool_calls=clarifier.registry.log)`
builds the durable record (transcript is **always** PII-redacted at `add_turn`). `closed_at` is set only when the
outcome is final. `flagged_incorrect` is left `None` for the feedback loop. `SessionMemory.to_json()/from_json()`
round-trips; `.save(dir)`/`.load(path)` write one JSON file per ticket.

**Retry history for the Resolver (B3):**
```python
session.record_attempt(chunk_ids, outcome="not_resolved", feedback=customer_reply)   # outcome: resolved|not_resolved|partial|unclear
session.rejected_chunk_ids()          # chunks from not_resolved attempts ("partial" is NOT rejected)
session.render_retry_context()        # prompt-ready text ending "Do not repeat the rejected evidence above."
session.render_context(max_tokens=700)  # compact KNOWN/ASKED + conversation, hard-capped
```

### 4.6 Tool Registry

`triage/tools.py`: only registered names can run; each has a per-turn budget; every call is logged
(`tool`, trimmed `args`, `result_size`, `ms`). Clarifier tools: `search_kb` (≤ 3/turn), `ask_customer` (1/turn,
terminal). Register your Resolver tools (`retrieve_evidence`, `check_cache`, `escalate`) in the same registry class.

---

## 5. Question flow, concretely

Real run against the Docker store (`replay --id S02`, free):

```
 customer: Docker Hub pulls are failing with a 429 error
assistant: Could you copy the exact error message you see, including any error code?
 customer: Too Many Requests
result: ready  gold_rank=1  questions=1
  (0.58) Troubleshoot Docker Hub > Too many requests (429 response code)
  (0.08) Troubleshoot Docker Hub > You have reached your pull rate limit (429 response code)
```
The KB has *two* near-identical 429 entries; only the error text separates them.

Question features: `symptoms` (open), `platform`, `error_message` (menu), `issue` (menu: "which sounds closest?"),
`product_area`, `error_open` (open-ended last resort). Replies are matched deterministically (`answers.py`): a number
or ordinal ("2", "the second one"), the option text, an alias, "none of these / not sure" (recorded as `unknown`
and counted as answered, so it is never re-asked). A reply that matches no option but *looks like an error message*
is kept as evidence rather than discarded.

Wording is **template-based** (variant 0 first ask, variant 1 on a re-ask). `cfg.llm_phrase_questions=True` makes
one extra LLM call per question to polish it; off by default (cost, auditability).

---

## 6. Integrating with Member B's track

### 6.1 Plug in your retriever
```python
from triage.clarifier import Clarifier
from triage.llm import ProviderLLM
from triage.understand import BgeEmbedder

clarifier = Clarifier(llm=ProviderLLM(), retriever=your_hybrid_retriever, embedder=BgeEmbedder())
session = clarifier.start()
result = clarifier.turn(session, customer_text)
```
Then **re-run the eval with your retriever** and compare to `reports/clarifier_eval_report.md`:
`python -m triage.eval.clarifier_eval --retriever-factory yourpkg.retrieve:make_retriever --sweep`.
Thresholds were tuned against vector-only scores; a different retriever can shift them (assumption 4).

### 6.2 Use it as a node in the integrated graph (J1)
`clarifier.as_node()` returns `node(state) -> {"clarifier_result": ...}` reading `state["session"]` and
`state["customer_message"]`. `clarifier.build_graph()` is the standalone Clarifier graph (ingest → understand →
{ask_gap | diagnose → decide}); a test asserts it behaves identically to the plain `turn()` call.
The graph state holds a live `SessionMemory` object. **I did not test it with a LangGraph checkpointer**; if J1 uses
one, store `session.to_json()` in state and rebuild with `SessionMemory.from_json()` rather than assume the object serialises.

### 6.3 The integration trap: chunk granularity
The Clarifier clusters candidates by **issue** (`source_path::issue title`), where *field-like sub-headings*
("Error message", "Possible causes", "Solution", …) belong to their parent. The real KB is inconsistent about
heading depth (`docker-hub/troubleshoot.md`: issue = H2, fields = H3; `desktop/.../topics.md`: issue = H3 under a
platform group, fields = H4), and this handles both.
**If your retriever returns whole expanded parent groups** (like `07_retrieve.py::expand_group`) with the group's
heading, a section such as *"Topics for Windows"* (many distinct issues) becomes **one** hypothesis, and the
differential collapses. Either return chunk-level hits + same-issue siblings (what `ChromaRetriever` does, at
0.9× the hit's score), or give each Candidate a `heading_path` down to the issue.

### 6.4 Stub-then-swap checklist (the workplan's dependencies)
| Dependency | State today | To swap |
|---|---|---|
| A4 ↔ B2 | `ChromaRetriever` (vector-only) / `MockRetriever` stand in | pass your retriever to `Clarifier(...)`; re-run eval |
| A7/B7 | `state.py` is the draft; `Clarifier.registry.log` and `result.meta` feed your logger | review `state.py`; bump `SCHEMA_VERSION` if you change it |
| B3 ↔ A2 | Resolver reads `ClarifierResult.signature` | use `validate_signature` in B3's tests |
| B4 ↔ A2 | cache key = `signature.canonical_string` | see assumption 6 about `component` and `embedding` |

---

## 7. Assumptions (every one of them)

Each is something I decided without being able to confirm it. "If wrong" says what breaks.

| # | Assumption | If wrong / how to check |
|---|---|---|
| 1 | **Retriever scores are similarity-like in (0,1], higher = better**, and decision thresholds transfer. | A retriever with a different scale mis-sets READY/ASK. Re-run `--sweep` with it. |
| 2 | **Product taxonomy = first path segment under `content/manuals/`**; `guides`, `reference`, `get-started` are used as sections; a hand-written alias table (43 phrases -> 14 products, `PRODUCT_ALIASES`) maps customer words to products. | A product missing from the alias table is only recognised if the KB taxonomy lists it with ≥ 30 chunks. Unknown products map to `None` (asked/inferred), never invented. |
| 3 | **Verbatim error text of an issue = the first non-command fenced block** in its chunks. | Pages that state errors in prose give no `error_message` feature, so that question is unavailable and the `issue` menu is the fallback. |
| 4 | **Thresholds** (`T=0.08`, `p_top≥0.5`, `margin≥0.25`, `min_grounding=0.34`, penalties/boosts) are from a sweep over **29 scenarios / 20 gold**, vector-only retriever, one author. | They are a starting point, not optima. Differences of one scenario are 5 points of gold@1. Re-calibrate on real traffic. |
| 5 | **Tool calls are issued by deterministic code**, not by an LLM emitting function-calls. | A deviation from the workplan's wording ("agent decides how many times to search"). The registry is the seam where LLM function-calling would plug in; no tool would change. |
| 6 | **`component` is almost always `?`** in the signature (the heuristic extractor can't infer it; the LLM extractor can), and **`embedding` is `None` unless you pass an `embedder`**. | Cache keys look like `docker-hub\|?\|pull fails with 429` — fewer, broader keys than intended. B4 must decide whether to require an embedding and whether `?` components are cacheable. |
| 7 | **`platform` and `doc_kind` are derived from paths/headings** (`macfaqs.md`, "Topics for Windows"). | Pages that scope to a platform only in prose give no platform feature. |
| 8 | **English-only, Docker-only, one problem per ticket.** | Other languages degrade to `ungrounded`/`ask`; a second problem in the same ticket is merged into the same symptom list. |
| 9 | **Question budget = 3 per ticket, shared** with Resolver callbacks. | `ClarifierConfig.max_clarify_turns`. |
| 10 | **Doc-kind weights**: release notes ×0.6, archive ×0.4 (~25% of the KB), reference/guide ×0.85, docs ×0.9. | Version-specific "known issues" live in release notes; if you build the version-notes feed, revisit this. |
| 11 | **No live LLM call was made by me.** Extraction prompt, LLM-phrased questions and `LLMCustomer` are covered only by `ScriptedLLM` tests. The default model name (`gemini-3.5-flash-lite`) is copied from `.env`/`09_understand.py` and **unverified**. | Run `--extractor llm` once and read `extraction_source` — any `heuristic_fallback` means the call failed or returned bad JSON. |
| 12 | **PII redaction covers**: emails, AWS/API/GitHub/Docker tokens, JWTs, bearer tokens, `password=`-style assignments. IPs are deliberately kept. | Names, phone numbers, addresses and free-text secrets are **not** redacted. |
| 13 | **Gap semantics changed from `09_understand.py`:** only `symptoms` is a *hard* gap; `product_area` is *soft* (retrieval infers it when the pool agrees). | A first version made product hard and asked "which Docker product?" for self-evident reports. |
| 14 | **An error *code* is not an error *message*.** `HTTP 429` is what near-duplicate issues share; only the text separates them. | Treating them as one disabled the best question (a real bug I fixed). |
| 15 | **`unknown` ("not sure") counts as an answer**, so that feature is never re-asked. | A customer who later remembers must volunteer it unprompted. |
| 16 | **Heuristic extraction is the default** (free, deterministic); it names a product only when exactly one is mentioned, and treats only fenced / quoted / `Label: detail` text as an error message. | Lower recall than an LLM on messy prose; precision-first by design. |
| 17 | **A1 (Tier-2 tickets) is not used here.** Scenarios are authored from KB entries; the workplan said "seeded from real tickets". The ticket CSV lives outside the repo (`data/` is git-ignored). | Build `sim/seed_from_tickets.py` using the validated loader rule from the dataset work (validate `source_type`, never bare `pd.read_csv` — the buildx-log row corrupts naive parsing). |
| 18 | **My local `data/processed/docker` store was patched in place** (see §9). The copy on S3/EC2 predates the fix. | Re-run `05_metadata.py` and `06_store.py --metadata-only` anywhere else the store is used. |

---

## 8. What is verified, and what is not

**Verified (by tests or a measured run):**
* 152 tests: contract round-trips, extractors, redaction, merging, session compaction under hard token caps,
  reflection rules, clustering for both heading layouts, discriminator ranking and soft re-weighting, the full
  turn on a demo corpus, LangGraph ≡ plain call, simulator behaviour, and 12 tests on the **real** store.
* **Negative controls** for the guardrail checks: break redaction → PII check fails; break vagueness detection →
  vague-query check fails; remove product validation → hostile-LLM check fails; etc. A green guardrail result
  therefore means something.
* Offline eval (§1 table) on the real 10,031-chunk Docker store.

**Not verified:**
* Any live LLM behaviour (assumption 11). Latency and cost per ticket (only tool-call counts are measured: ~6.2 per
  ticket, mostly the three `search_kb` calls per diagnosis turn).
* Your hybrid retriever — everything above ran on **vector-only** or a crude keyword retriever.
* Concurrency, multi-ticket isolation under load, non-English input, very long customers messages.
* The ticket-seeded simulator (not built).

**Caveats on the numbers — please do not quote them without these:**
* **Small, circular sample.** 29 scenarios (20 with gold, 6 out-of-scope). Gold labels, hidden customer facts and the
  scenario wording were written by the same person from the same KB pages, and the rule-based customer answers menus
  perfectly. Optimistic by construction.
* **Gap-detection 1.0/1.0 is partly circular:** I revised the labels when product became a soft gap.
* **Scenarios S23–S25 have no gold**, so a bad READY there is invisible to the metrics. S25 ("docker" → "docker
  desktop crashes at startup") ends READY on an *install* page, which is probably wrong.
* **`gold_top3 == gold_top1` (0.85)** is not suspicious: every hit is rank 1; the three misses are retrieval misses
  (the gold issue never reaches the top 3), not ranking errors.

**Known failure modes (all visible in `reports/clarifier_eval_report.md`):**
| Case | What happens | Why |
|---|---|---|
| S07 "Docker Desktop won't start on my Windows laptop" | READY at 0 questions on an FAQ about Windows Server | The KB has one Windows start-up entry (anti-virus); the symptom is genuinely under-specified, and an FAQ outscored it. The only wrong-READY. |
| S08 "Docker isn't starting" | unresolved after 3 questions | Inherently vague; gold never reaches the top 3. |
| S17 "docker pull fails … rootless" | unresolved | Vector retrieval misses "rootless" (a keyword hybrid should fix it). |
| S14 "users can't sign in with SSO" | unresolved but gold is rank 1 | Correct differential, below the READY thresholds; the Resolver still receives it. |
| S29 Kubernetes CrashLoopBackOff | unresolved | The KB does contain a Docker Desktop Kubernetes page; labelled out-of-scope on purpose as the hard case. |
| Borderline wording | `"…from Docker Hub"` → READY, `"…on Docker Hub"` → asks | A usage page quotes the same error as the troubleshooting page, so `p_top` lands at 0.487 vs the 0.5 threshold. Expected for threshold decisions; watch it in eval. |

**Retrieval observations that matter for you (B2):** vector search is weak on numbers ("429") and rare terms
("rootless"); a BM25 half should help the Clarifier directly. Only **171 troubleshooting + 96 FAQ chunks (~2.7%)**
exist in a 10,031-chunk store; **~25%** is release notes/archive.

---

## 9. Changes I made outside `triage/` (so nothing surprises you)

| Change | Why |
|---|---|
| `scripts/05_metadata.py`: fixed `product_area`; added `doc_kind` | **My earlier Docker adaptation had a bug**: only `content/manuals/` was stripped, so ~1,941 chunks from `guides`/`reference`/`get-started` were labelled `product_area="content"` and file names leaked (`retired.md`). Found by reading the real taxonomy. |
| `scripts/06_store.py`: `chunk_metadata` gains `doc_kind`; new `--metadata-only`; model-dimension deprecation fix | Apply metadata fixes to an existing store **without re-embedding** (the full embed took roughly 55 min on EC2). |
| Local `data/processed/docker/` | `05` re-run + `06_store.py --metadata-only` applied; the pre-fix `chunks_metadata.jsonl` and `taxonomy.json` were backed up to a temp folder on my machine (not in the repo). |
| `.gitignore`: `*.pem`, `*.key`, AWS scratch files | `docker-kb-key.pem` (a private key) was sitting untracked and un-ignored in the repo root — one `git add .` from being committed. |
| `requirements.txt`, `pytest.ini` | langgraph, pytest, test markers. |

**Not committed.** `git status` shows all of this as modified/untracked; nothing was committed or pushed.

---

## 10. Bugs found while building (so you recognise the pattern)

Most were found by running against the **real** store or by guardrail/negative-control tests, not by unit tests on
the mock corpus. In order of how much they would have hurt:

1. Prose containing "error"/"isn't" was stored as a verbatim error message → silently disabled the error-text question for the whole ticket.
2. The apostrophe in "isn't" was parsed as an opening quote → captured garbage and *missed the real quoted error*.
3. An error **code** suppressed the error-**message** question (assumption 14).
4. A *vague* symptom ("it doesn't work") counted as "already known", so the Clarifier couldn't ask for symptoms.
5. Dense retrieval always returns something and absolute scores don't separate junk from signal (0.669 vs 0.669) → needed the lexical-grounding check; out-of-scope false-READY went 24% → 0%.
6. Menus offered causes with 0.03% probability.
7. `product_area` as a hard gap asked pointless questions (assumption 13).
8. The guardrail for vague input still passed with vagueness detection broken, because an unrelated fallback also "asked" — tightened to require a *symptoms* question.
9. `product_area="content"` in the Docker store (§9).

---

## 11. Open questions / suggested next steps

1. **B:** review `state.py` (A7). Anything you need in `ProblemSignature` or `TriageRecord` should be added now, before more code depends on it.
2. **B:** run the eval with the hybrid retriever; share the report. If gold@1 or wrong-READY moves materially, re-run `--sweep` and update `ClarifierConfig`.
3. **Joint:** decide whether `component=?` keys are cacheable, and whether the cache requires `signature.embedding`.
4. **Joint:** one live run of `--extractor llm` (≈ 60 calls) to validate the prompt and the Gemini model name.
5. **A (next):** seed scenarios from the Tier-2 tickets; add a small gold-labelled set for the vague openings (S23–S25); consider an LLM-judge for question quality (the current rubric is structural only).
6. **Docs:** `docs/ARCHITECTURE.md` still describes the Microsoft-era pipeline and lists the agents as *"Designed, not yet built"*. I did not update it; it should be refreshed once the integrated graph exists.
7. **Both:** version-notes / live-status feeds were brainstormed but are **not** in this design; if added, `doc_kind` and the soft re-weighting are the places they would plug in.

---

## Appendix — quick API reference

```python
from triage.clarifier import Clarifier
from triage.config import ClarifierConfig
from triage.state import ClarifierStatus, NeedClarification, validate_signature

cl = Clarifier(llm=None, retriever=my_retriever, cfg=ClarifierConfig(), embedder=None)
s = cl.start("T-123")                          # SessionMemory
r = cl.turn(s, "docker pull fails with 429")   # ClarifierResult
r.status      # ask | ready | unresolved
r.question    # QuestionPlan(feature, text, options)   (when ask)
r.signature   # ProblemSignature                         (when ready / unresolved)
cl.reenter(s, NeedClarification("platform"))   # Resolver callback
cl.registry.log                                # every tool call, for logging
s.to_triage_record(outcome="escalated", signature=r.signature).closed_at
```

Config knobs worth knowing (`ClarifierConfig`): `max_clarify_turns`, `softmax_temperature`, `ready_p_top`,
`ready_margin`, `min_grounding`, `min_option_weight`, `mismatch_penalty`, `error_match_boost`,
`feature_answerability`, `doc_kind_weight`, `llm_phrase_questions`, `context_token_budget`.
