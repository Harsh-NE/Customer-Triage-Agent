# Experiment workplan: from a working system to a study (for the IEEE paper)

Status when written (2026-11-13): hybrid RAG over docs, community guides and tickets; 153-entity knowledge graph; OCR for screenshots; Clarifier + Resolver LangGraph; gold v1 (89 questions); one real-Gemini run (13 Oct, 94 cases). The numbers below marked "measured" come from files in `reports/`.

## 0. What "Jev" is, and where it fits (resolved)

Jev (TypeSafe AI, released 15 Sep 2026) is a fast "decision model": it answers a typed question about some text with a choice (Choice), a yes/no probability (Noul) or a score (Score), and does not write text. The supplied paper (*Jev in the Wild*, arXiv 2609.30216) analyses 2,170 public GitHub projects; it contains **no accuracy or latency results for the model itself**. Speed, cost and accuracy figures come from other, very new preprints (read as abstracts only) and vendor pages. Verdict and the experiment design are in section 3 (C4) and E7: useful for latency and call count, not for our main weakness (retrieval ranking). Treat every Jev number as unverified until we measure it ourselves.

## 1. Research questions and hypotheses

The claim of the paper must be one the data can support. Hypotheses are written before the experiments and are reported whether or not they hold.

| # | Research question | Hypothesis (to test, not a promise) |
|---|---|---|
| RQ1 | Does structure-aware retrieval (heading context, error-line extraction, knowledge graph) improve ranking over plain RAG? | MRR and Recall@k improve over a naive-RAG baseline; the gain over our current hybrid retriever is smaller. |
| RQ2 | Does better context management cut cost and latency without hurting answer quality? | Evidence packing (sentence-level extraction, token budget, de-duplication) cuts input tokens per case by about a third with first-fix rate not worse by more than 2 points. |
| RQ3 | Does a fast path and calibrated decision layer cut time to resolution? | Fewer LLM calls, fewer questions and a lower p95 latency, with escalation recall unchanged. |
| RQ4 | Does the Clarifier help? | One well-chosen question raises MRR/Recall@1 over asking none (as in Qulac). |
| RQ5 | Is the agent safe? | Wrong-fix rate and unsupported-claim rate are lower than for plain RAG, at a stated cost in coverage. |

Reference point: the LinkedIn paper (SIGIR 2024) reports MRR 0.522 → 0.927 and Recall@1 0.400 → 0.860 on its own curated set. Our result must be reported relative to **our own baselines** on our own data, never as "we beat LinkedIn".

## 2. Baselines and ablation ladder

Each rung adds one thing, so every gain is attributable. All rungs use the same LLM, the same embedding model and the same test set.

| Rung | System | Purpose |
|---|---|---|
| B0 | Closed-book LLM (no retrieval) | Shows what retrieval adds |
| B1 | Naive RAG: dense top-5 chunks pasted into one prompt, no clarifier, no gate, no verifier | The "plain RAG" baseline (the paper's headline comparison) |
| B2 | B1 + BM25 + rank fusion (hybrid) | Retrieval ablation |
| B3 | B2 + knowledge graph | KG ablation (our `ontology_eval` already has on/off) |
| B4 | B3 + Clarifier | RQ4 |
| B5 | B4 + gate + verifier + escalation rules (= current system, 13 Oct design) | RQ5 |
| B6 | B5 + proposed improvements C1 to C4 (final system) | RQ1 to RQ3 |

## 3. What to build (the improvements)

Each item has a cheap deterministic version first, tested before any model-based version.

- **C1 Context management.**
  - Today the draft prompt holds up to 8 evidence items of up to 1,800 characters each. The real run averaged about 930 to 1,000 input tokens per LLM call (measured: 64,106 tokens / 64 calls and 84,859 / 91 calls).
  - Build: sentence-level extraction of the passages that answer the question (CRAG's decompose-then-recompose idea), de-duplication across items, a token budget with score-ordered packing, and an adaptive k (stop when the gate is already strong).
  - Conversation side: the Clarifier already keeps 4 turns and a 700-token budget; test a running summary instead of raw turns for long chats.
- **C2 Retrieval quality.**
  - Prepend the heading path and page title to each chunk before embedding and BM25 (free version of contextual retrieval).
  - Extract error lines from pasted logs before search (measured weakness: recall@8 0.84 to 0.65 with log noise).
  - Evaluate the existing query expansion option (off by default) and a HyDE-style hypothetical answer.
  - Promote approved ticket cards and knowledge-graph drafts (25 and 30 drafts exist) after human review.
- **C3 Latency.**
  - Run the retrieval tiers in parallel instead of in sequence where the gate allows it.
  - Skip the LLM when the evidence is a verbatim match: return an extractive, cited answer.
  - Cache with calibrated thresholds (they are uncalibrated guesses today).
  - Stream the draft to the UI.
  - Per-stage timing from the event log shows where the time goes before optimising anything.
- **C4 Fast decision layer (Jev-style cascade).**
  - Replace the small LLM calls with a typed decision model and fall back to Gemini when its confidence is below a threshold fitted on dev (the cascade pattern in the Jev-as-a-judge and REFLEX preprints).
  - Candidate decisions: scope check (Noul), reply classification (Choice: resolved / not fixed / new info / off-topic), frustration (Score), per-evidence "does this passage answer the question?" (Noul, used to drop evidence before drafting, which also cuts context), and a one-sided risk screen that may only add escalations, never remove a code-rule escalation.
  - Not candidates: drafting, Clarifier question wording, retrieval ranking as the primary ranker.
  - Compare four deciders on the same labelled inputs: Gemini (reference), Jev (API), an open-weight local decision model if licence and quality allow, and a plain logistic regression on the signals we already compute (top score, margin, agreement, p_top, grounding, completeness, error match).
  - Evaluate by risk against coverage and by end-to-end outcomes, not by agreement alone.
- **C5 Evaluation completeness.** See sections 4 and 5. This is the largest piece of work.

## 4. Data and ground truth

The current test set is not clean (we looked at it while building, and a model reviewed the labels). The paper needs a fresh one.

1. **Freeze before tuning:** commit and tag the current code (`v0-baseline`). Create **gold v2** with a locked test split nobody looks at until the final run.
2. **Size:** about 150 questions minimum (about 100 gives plus or minus 10 points at a 50% rate). Sources: recent Stack Overflow, GitHub issues of docker/for-win, for-mac, compose and buildx (cite URL and licence), lab-made errors, and a small user pilot. Remove near-duplicates of anything in the knowledge base or ticket store.
3. **Per-question labels:** class (answerable, KB gap, vague, urgent, out of scope, injection), the correct doc section with relevance grade (confirmed or weak), and a **reference resolution** (a short written answer) for answerable questions. The reference resolutions are what make BLEU, ROUGE and METEOR computable.
4. **Two labellers** on at least 40 overlapping questions; report Cohen's kappa (the tooling exists: `triage.eval.gold_v1 agreement`). Target about 0.7 or more.
5. **Screenshot set:** 40 to 60 real screenshots (Windows and Mac, light and dark) with the true error text typed out, for OCR evaluation.
6. **Keep gold v1** as a second, labelled "development-contaminated" set and say so in the paper.

## 5. Metrics

| Group | Metric | Notes |
|---|---|---|
| Retrieval | MRR, Recall@1/3/8, NDCG@1/3/8 | At doc-section level; NDCG uses the confirmed/weak grades. MRR and recall exist; **NDCG needs adding** |
| Generation | BLEU, ROUGE-L, METEOR vs reference resolution | **To add.** Also BERTScore, since overlap metrics undervalue paraphrase |
| Faithfulness | Fraction of steps entailed by their cited text (LLM judge, RAGAS/ARES style); citation validity | Judge exists in `agent_metrics --judge`; never run. Run with `--self-check` planted faults so the judge is validated |
| Task outcome | First-fix rate, wrong-fix rate, escalation precision/recall/F1, right final action | Exist |
| Efficiency | LLM calls, input/output tokens, cost per case | Exist in the event log |
| Latency | p50/p95 end-to-end and per stage (retrieval, LLM, verify), time to first reply | Partly exist; per-stage report to add |
| Time to resolution | (a) machine time and turns to a correct resolution in simulated sessions; (b) **human time-to-resolution in a small pilot** | (a) is a proxy. (b) is the only real measure (LinkedIn measured real hours) |
| Reliability | pass^k (k = 3) | `--repeats` exists |
| OCR | Character error rate on the error line; end-to-end first-fix with vs without OCR | **To add** |
| Robustness | Recall@k under typos, log noise, chatter, two issues | `perturb_eval` exists |

## 6. Experiments

| # | Experiment | Compares | Primary metric | Success criterion (pre-set) | Cost |
|---|---|---|---|---|---|
| E1 | Retrieval ladder | B0 to B3 | MRR, Recall@k, NDCG | Report all; no threshold | Free, offline |
| E2 | Retrieval improvements C2, one at a time and combined | B3 vs +each | MRR, Recall@8 | At least +10% relative MRR on real questions, paired CI above 0 | Free, offline (re-embed for heading prefix) |
| E3 | Clarifier value | B3 vs B4 | MRR/Recall@1 with vs without the question; questions per case | Non-negative gain; cost in questions reported | Free |
| E4 | Context packing C1 | B5 vs +C1 | Tokens per case, first-fix rate, faithfulness | Tokens down about 30% with first-fix rate within 2 points | Gemini |
| E5 | Latency C3 | B5 vs +C3 | p95 latency, LLM calls per case | p95 down about 30%, escalation recall unchanged | Gemini |
| E6 | Safety | B1 vs B5 vs B6 | Wrong-fix rate, unsupported-claim rate, escalation recall | Wrong-fix lower than B1 at a stated coverage | Gemini + judge |
| E7 | Fast decision layer C4 | Gemini vs Jev vs local model vs logistic regression, per decision; then end-to-end | Accuracy and macro-F1 vs Gemini labels, calibration (ECE, Brier), accuracy-vs-fraction-sent-to-Gemini curve, LLM calls and p50/p95 latency per case, first-fix / wrong-fix / escalation recall | End-to-end outcomes within 2 points of B5 and escalation recall unchanged, with fewer LLM calls and lower latency; label-name sensitivity test passed (run each Noul/Choice with neutral option names) | Labels from Gemini plus a human-checked sample; Jev API cost is negligible, but access is early-access |
| E8 | Generation quality | B1 vs B5 vs B6 | BLEU, ROUGE-L, METEOR, BERTScore, faithfulness | Report; no threshold | Gemini + judge |
| E9 | Time-to-resolution pilot | Agent vs docs search | Minutes to a correct resolution; turns | Only if consenting participants are available | People, not money |
| E10 | Robustness and OCR | B5 vs B6 | Recall@8 under perturbations; OCR CER | Log-noise loss reduced from 0.84 to 0.65 | Free |

The success criteria are targets, not forecasts. Our retrieval is already hybrid, so a gain of the LinkedIn size (77.6%) is plausible only against B1 and not against B5. Say so in the paper.

## 6a. Order of work

Cheapest and most informative first: E1, E2, E3, E10 (all free and offline) → then C1 and C3 and E4, E5 → then judge-based E6 and E8 → then E7 → E9 last because it needs people.

## 7. Statistics and reproducibility

- Report 95% confidence intervals by bootstrap over questions; use paired tests (paired bootstrap, McNemar for binary outcomes) between rungs. With about 150 questions, only large differences will be significant; say so.
- Fix `PYTHONHASHSEED`, the retrieval seed, the model name and version, temperature 0, and a config hash in every result file. Run Gemini with 3 repeats and report pass^3.
- One results registry (`reports/study/`) with one JSON per run and a script that rebuilds every table and figure in the paper from those files.
- Never tune on the test split. All thresholds and the decision layer are fitted on dev only; the test split is run once per final configuration.

## 8. Timeline (about 4 weeks; compress or stretch to your deadline)

| Week | Work | Output |
|---|---|---|
| 0 (2 to 3 days) | Commit and tag baseline; freeze splits; add NDCG, BLEU/ROUGE/METEOR/BERTScore and per-stage latency to the tooling; write reference resolutions | `v0-baseline`, metrics tooling, gold v2 draft |
| 1 | Finish gold v2 (second labeller, kappa), screenshot set; run E1, E3, E10 | Baseline table, retrieval ladder |
| 2 | Build and test C2 and C1; run E2 and E4 | Retrieval and context results |
| 3 | Build C3 and C4; run E5, E6, E7, E8 (Gemini, 3 repeats, judge) | Latency, safety, generation, decision-layer results |
| 4 | E9 pilot if possible; final test-split run of the final system; figures and tables; start the paper | Complete results registry, draft outline |

## 9. Budget

The real run cost $0.0007 per case with Gemini 3.5 Flash-Lite (measured: $0.069 for 94 cases). Estimate: 150 questions × 6 systems × 3 repeats is about 2,700 runs, about $2 for the system plus about the same for the judge, so under $10 in total. Wall-clock is the larger cost: about 10 seconds per case in the simulated loop, so about 7 hours serial for the full grid; run it in parallel or trim repeats. Paid runs will each be proposed to you with a cost before they start.

## 10. Risks

| Risk | What to do |
|---|---|
| The knowledge base is the ceiling (only 2.5% troubleshooting), so retrieval changes may barely move real-question recall | Report it; add reviewed ticket cards and knowledge-graph nodes as a separate, labelled experiment |
| Small test set, wide confidence intervals | Say so; report effect sizes and paired CIs; do not over-claim |
| Labels are model-reviewed | Two human labellers and kappa for gold v2 |
| LLM judge bias | Validate with planted-fault controls; report agreement with a human sample of 30 |
| Gemini model or quota changes mid-study | Pin the model, save raw outputs, abstract the provider |
| A proposed improvement does not help | Report it as a negative result (we already have three: reranker, KB filters, ticket-age penalty) |
| No participants for E9 | Keep the machine-time proxy and state plainly that real time-to-resolution was not measured |

## 11. Mapping to the paper

Abstract and introduction: problem and RQ1 to RQ5. Related work: LinkedIn KG-RAG, τ-bench, Qulac, CRAG, Self-RAG, RAGAS/ARES, the abstention survey. Method: architecture and C1 to C4. Data: gold v2, KB, tickets, screenshots. Experiments: sections 2, 5 and 6. Results: baseline and ablation tables with confidence intervals, latency and cost figure, risk-coverage curve. Failure analysis and limitations: from the failure tables and section 10. Conclusion: only claims the tables support.

## 12. This week

1. Commit the current state and tag `v0-baseline` (there is a large uncommitted diff).
2. Answer the JEV question (section 0).
3. Decide the deadline, so the timeline can be fitted to it.
4. Start the reference resolutions for gold v2, since they gate BLEU/ROUGE/METEOR.
5. Recruit a second labeller and, if possible, 10 to 15 pilot participants.
