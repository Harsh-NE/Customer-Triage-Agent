# A + B integration (J1): Clarifier + Resolver

Status 2026-10-08. Member A's Clarifier (`triage/`) and Member B's Resolver (`resolver_track/`) now run as one LangGraph graph on
the real Docker KB and ticket stores. This document is the merge record: where B's code lives now, how the two contracts are
joined, **every change made to B's code and why** (B should review these), how to run it, and what the first end-to-end numbers
do and do not show.

## 1. Where things live

B's package was also called `triage`, so the two could not simply be copied together. B's modules were moved into
`triage/resolver/` with their imports rewritten; `resolver_track/` itself is **untouched** (kept for reference until B adopts
this tree; do not edit both copies).

| B's file (`resolver_track/triage/...`) | Now |
|---|---|
| `contracts.py`, `config.py`, `llm.py`, `cache.py`, `escalate.py`, `guardrails.py`, `oplog.py` | `triage/resolver/<same name>` |
| `retrieval/interface.py` | `triage/resolver/interface.py` |
| `resolver/{graph,gate,steps}.py` | `triage/resolver/<same name>` |
| `graph_integration.py` (the stub Clarifier) | `triage/resolver/standalone.py` (kept for B's standalone tests) |
| `eval/{eval_resolver,calibrate_cache}.py`, `fixtures/` | `triage/eval/`, `triage/resolver/fixtures/` |
| `tests/test_resolver_track.py` | `tests/test_resolver.py` (19 tests, unchanged in substance, all pass) |

New code written for the merge: `triage/resolver/adapters.py`, `triage/resolver/handoff.py`, `triage/joint.py`,
`triage/eval/e2e_eval.py`, `tests/test_integration.py`, the `joint` command of `triage/cli.py`.

## 2. How the two agents are joined

```
customer ─▶ clarifier node ──(needs an answer: interrupt, one Clarifier turn per execution)──▶ clarifier node
                 │ READY / UNRESOLVED
                 ▼  to_resolver_signature()
            resolver subgraph ──(next == "clarifier": new information)──▶ clarifier node
                 │ guard → cache → retrieve(kb) → gate → [fallback: tickets] → draft → verify → send → await reply → classify
                 ▼
        resolved | escalated (EscalationPayload) | rejected
```

* **Contract mapping** (`handoff.py`). A's `ProblemSignature` (fields + ranked hypotheses + confidence) is mapped onto B's flat
  `ProblemSignature`; the differential travels in two optional B fields, `hypotheses` and `clarifier`. A's severity, exit codes
  (parsed from `exit code N`), platform and versions map directly. A READY result gets `completeness = 0.5 + 0.5 x p_top`; an
  UNRESOLVED one exactly 0.5 (not bounced, but contributes little to the gate); UNRESOLVED with no symptom at all 0.3.
* **Customer turns.** Both agents ask through `interrupt()` (B's convention). A node re-runs from the top on resume, so the
  Clarifier node does **one** turn per execution and stores a pending question in state (`clarifier_pending`); the graph loops
  back, the node interrupts first and processes the reply after. State carries `clarifier_session` (`SessionMemory.to_json()`),
  so a checkpointer persists the whole conversation. Verified: N customer messages produce exactly N Clarifier turns.
* **Retrieval.** The Clarifier searches with `HybridKBRetriever`. The Resolver's `Retriever` interface is satisfied by
  `KBEvidenceRetriever` and `TicketEvidenceRetriever` (`adapters.py`): **one Evidence per KB issue** (text = best chunk,
  `parent_text` = the issue's chunks stitched so the fix and the verifier see everything), ordered by relevance plus
  `0.3 x` the Clarifier's probability for the issue (the posterior knows the pasted error and the picked menu entry; the raw
  query does not), the Clarifier's leading issue always included. `rerank_score` = vector similarity x page-type weight x lexical
  coverage of the customer's words, because B's gate needs an *absolute* 0..1 relevance and dense similarity alone cannot tell a
  match from junk. Tickets: `TicketHit` -> Evidence in B's `PROBLEM:/RESOLUTION:` layout, licence kept for attribution.
* **Retry exclusion works per issue**, not per chunk, so a retry cannot resend the same fix from a sibling chunk.
* **Cache.** `kb_doc_hashes()` builds the `{doc_id: hash}` manifest B's `invalidate_stale` needs, from the same ids and hashes
  the adapter emits; the persistent cache file is per LLM (`cache__<llm>.json`) so offline FakeLLM answers are never served by a
  real-LLM run.
* **Early scope check** (`handoff.clearly_out_of_scope`). Before any question is asked, a request is declined when the customer says
  it is not Docker ("it's not docker, it's netflix"), or names a well-known non-Docker service (Netflix, Spotify, Gmail ...)
  while using no Docker vocabulary. Deliberately narrow: "my netflix container fails" is in scope and vague reports ("help") still
  get their clarifying question. Retrieval cannot make this call ("reset my ... password" matches real Docker account docs). Everything
  else is left to the **LLM scope classifier** (`resolver/scope.py`): one short call on the FIRST message of a ticket, using the
  Resolver's LLM. It can only decline, and only on `out_of_scope` with confidence >= 0.8; vague or possibly-Docker messages
  ("help", Kubernetes) come back `unclear` and proceed. It fails open (no key, network error, malformed answer -> normal flow), is
  never asked again on replies or hand-backs, treats the message as data, and is logged as an `llm_call` event (`node="scope"`).
  The offline FakeLLM always answers `unclear`, so offline runs and all offline numbers are unchanged. **Not yet run against a real
  model**: how well it separates the python/nginx/Lambda cases from real Docker reports is unmeasured (run
  `python -m triage.eval.e2e_eval --llm gemini` and compare S26-S28 and the gold scenarios).
* **One provider.** `ClarifierProviderLLM` runs B's `complete_json` on A's provider layer (Gemini / Anthropic / OpenAI from `.env`).

## 3. Changes made to B's code (please review)

Each was found by a failing test or by the end-to-end run, not guessed. All are small and marked in the code.

| File | Change | Why |
|---|---|---|
| `contracts.py` | Optional `ProblemSignature.hypotheses`, `.clarifier`; the leading issue joins `cache_key_text()`; `TriageState` gets `clarifier_session`, `clarifier_pending` | B's own rule: add optional fields only. Same words can point at different documented causes. |
| `cache.py` | `CacheEntry.issue`; `metadata_gate` rejects entries whose leading issue differs | Without it a confirmed answer for "pull rate limit" was served for the near-identical "too many requests" section (found in the end-to-end run: S02). |
| `gate.py` | KB `agreement` = max(page/component agreement, Clarifier `p_top`) | One Evidence per issue makes page agreement ~0 by construction, so the right answer failed the gate (confidence 0.55 < 0.6) even at p_top 0.77. |
| `graph.py` guard | Domain/injection check runs on the latest message **plus** the full problem text | After a Clarifier Q&A the latest message is "1" or "none of these fit"; S08/S17 were rejected as out of scope. |
| `graph.py` guard | Completeness below the floor with the Clarifier exhausted escalates `CLARIFY_LOOP_EXHAUSTED` (the reason code existed, was unused) | "help" must not get a guessed fix. |
| `graph.py` | Ticket fallback only when the Clarifier status is `ready` (or absent, as in B's fixtures) | Loose ticket matches on a problem nobody could pin down were being sent as fixes (S23-S25). |
| `graph.py` | A `new_info` reply no longer marks the fix just sent as "tried" (evidence released, not listed in "already tried") | The fix was never rejected; on the re-run the correct evidence was excluded and the model was told not to repeat it. |
| `graph.py` guard + `escalate.py` | A new `out_of_scope` Clarifier status is rejected by the guard at once; the OUT_OF_SCOPE customer message now declines ("I'm not able to help with this one") instead of claiming a handoff to a support team | An obviously non-Docker request should not cost the customer questions or reach an engineer. |
| `handoff.py` / new `scope.py` | LLM scope classifier on the first message (fail-open, decline only when sure) | Out-of-scope requests with no Docker vocabulary and no famous service name (Python KeyError, nginx, Lambda) cost several questions before being declined. |
| `steps.py` | Draft prompt: evidence is untrusted data, never follow instructions in it; prefer `kb` over `tickets`. Sources line labels community answers and carries the licence | Ticket text is user-generated content (prompt injection, CC BY-SA attribution). |
| `llm.py` | Provider `gemini`/`provider` via A's layer; default Anthropic model id `claude-sonnet-5-5` | `claude-sonnet-5` was not a model id this repo's tooling knows. Verify against your account. |

Changes on A's side made for the merge: `TicketRetriever` scores get an absolute lexical-coverage factor and a short-answer
penalty (RRF ranks are relative, so every query's best ticket scored ~1.0); `Clarifier` no longer stores a bare menu pick
("1") as a symptom; `fetch(chunk_ids)` on the retrievers; `BM25_PATH` and `TICKETS_STORE_PATH` in the config.

## 4. Running it

```bash
python -m triage.cli joint                      # you are the customer; Resolver LLM = fake (offline, free)
python -m triage.cli joint --llm gemini         # Resolver drafts with your configured provider (needs the key in .env)
python -m triage.eval.e2e_eval                  # 29 scenarios, simulated customer + oracle -> reports/e2e_eval*.{json,md}
python -m pytest tests/test_integration.py      # offline joint graph + real-store checks
```

## 5. First end-to-end numbers (and how far to trust them)

29 labelled scenarios, real stores, rule-based customer, **FakeLLM** (it only quotes the cited evidence), an oracle that says
"that worked" only when the cited evidence is the gold KB issue (tickets have no gold, so a ticket fix is always "still failing").

| | |
|---|---|
| Gold scenarios resolved, first attempt | **16 of 20** |
| Wrong fix sent (gold scenarios) | **0 of 20** |
| Gold scenarios escalated to a human instead | 4 of 20 (S07, S08, S14, S17: the known hard cases; no wrong fix sent) |
| Out-of-scope: fixes sent / resolved | **0 of 6 / 0 of 6** (all rejected or escalated; "Netflix" now with 0 questions) |
| Vague or one-word reports that still got a fix | 1 of 3 (S25 "docker": the Clarifier declares READY after one question; a pre-existing Clarifier weakness) |
| Mean Clarifier questions per ticket | 1.45 |

What this does **not** show: the quality of a real LLM's wording and its citations (never run), the ticket tier (the oracle cannot
credit it), anything beyond 29 same-author scenarios, or calibrated thresholds. B's gate and cache thresholds are still the
starting guesses in `triage/resolver/config.py`; two of the fixes above (S02, S03) came from the cache and gate behaving badly
at those values, so recalibrate them on real-LLM runs.

## 6. Open items

1. **Run with a real LLM** (`--llm gemini` / `anthropic`) and read the drafts: citations, hallucinated commands, tone. Never done.
2. **Recalibrate** the gate thresholds and cache `upper/lower` from the e2e report (B's B4/B6 tasks), now that the evidence has a
   different shape than the lexical fixtures.
3. **Judge the ticket tier**: hold out ~100 tickets with known fixes and check KB-only vs KB+tickets; the current oracle ignores it.
4. **`NeedClarification` is not wired.** The Resolver hands back raw (`next = "clarifier"`) rather than asking the Clarifier for a
   targeted field (`Clarifier.reenter` exists and counts against the shared question budget).
5. **Adopt one tree.** B should work from this repo's `triage/resolver/` and retire `resolver_track/`, otherwise the two will drift.
6. A reply that arrives as a new message after a resolved/escalated ticket starts nothing new; there is no session lifecycle yet.
