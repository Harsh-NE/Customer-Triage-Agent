# Metrics for the presentation

Measured 2026-11-03 on the current code (branch `feature/integrated`, uncommitted changes), `PYTHONHASHSEED=0`, offline. **The drafting model is a fake**:
these numbers show retrieval, routing, safety and Clarifier behaviour. They do **not** show how good the written fixes are (no faithfulness or quality score
exists for the current code; the paid Gemini run was not completed). Source files: `reports/presentation/gold_v1.md`,
`reports/regression/presentation_{scenarios,heldout,clarifier}.md`. Reproduce with the commands at the bottom.

## Real LLM run (Gemini 3.5 Flash-Lite, 13 Oct 2026): the numbers used in the deck

Files: `reports/e2e_eval_gemini.{md,json}` (29 scenarios) and `reports/e2e_heldout_gemini.{md,json}` (65 forum questions, 13 with gold labels at the time). Simulated customer, oracle feedback.
Code of that date: **before** the later fixes (early escalation, chatter filter, retry/validation), and the held-out labels were the earlier 13, not the later 19. No faithfulness judge was run.

| Metric | 29 scenarios | 65 forum questions | Both (94) |
|---|---|---|---|
| Right final action | 89.7% (26/29) | 84.6% (55/65) | **86.2% (81/94)** |
| Fixed on first attempt (gold cases) | 85.0% (17/20) | 23.1% (3/13) | 20 of 33 |
| Wrong first fix on a gold case | 0 of 20 | 2 of 13 | 2 of 33 |
| Fix sent on a no-answer case | 0 of 9 | 2 of 52 | 2 of 61 |
| No-answer cases ending in escalation or rejection | 9/9 | 52/52 | **61/61 (100%)** |
| Wrong-fix rate (wrong first fix + fix on no-answer case) | 0/29 | 4/65 | **4/94 = 4.3%** |
| Fixes sent that cite evidence | 17/17 | 10/10 | 27/27 |
| Questions asked per case (mean) | 1.17 | 1.88 | |
| LLM calls per case | 2.2 | 1.4 | 1.65 |
| Cost | $0.0311 | $0.0379 | **$0.069** |
| Time per case (whole loop, with simulated customer) | 11.2 s | 9.6 s | |
| LLM latency per call, median / p95 | 3.3 s / 4.9 s | 3.0 s / 4.4 s | |

Cost is the harness's estimate from token counts. Recall@8 (78.9%) is a retrieval number from the offline gold set and does not depend on the LLM.

## Headline slide: pick these

| What it shows | Number | Set |
|---|---|---|
| Never misses a case that must go to a human | **100% escalation recall** (70/70) | gold v1, 89 questions |
| Rarely sends a wrong fix | **2.2% wrong-fix rate** (2/89); **0 wrong first fixes** on the 19 answerable | gold v1 |
| Fixes it sends are cited | **100% valid citations** (7/7 on gold v1, 20/20 on scenarios) | both |
| When the Clarifier says READY, it is right | **100% READY precision** (4/4 gold v1; 18/18 scenarios) | both |
| Right final action (answer / ask / escalate) | **80.9%** (72/89) gold v1; **89.7%** (26/29) scenarios | both |
| Retrieval on guided scenarios | gold recall@1 **90%**, @3 95%, MRR 0.925 | 29 scenarios (20 with gold) |
| Clarifier on its own | gold top-1 **90%**, top-3 95%; gap detection precision and recall **1.0**; 0 wrong READY, 0 duplicate questions, 0 stuck | 29 scenarios |
| Questions asked | mean **1.5** per case (scenarios), 1.8 (gold v1), max 3 | |
| Speed (retrieval + Clarifier, no LLM) | median **1.6 s** end to end, first reply 0.3 s (gold v1) | |

## The honest weak point (put it on a slide, it is a strength to know)

| Metric | Number | Meaning |
|---|---|---|
| Real-question answerable cases fixed on first attempt | **21% (4/19)** | Real Stack Overflow questions; the other 15 are escalated rather than answered wrongly |
| Retrieval of the documented section for those | recall@1 21%, @3 63%, **@8 79%** | The right section is usually found, but not ranked first |
| Unnecessary escalation on answerable real questions | 79% (15/19) | The system is cautious: it prefers handing off to a wrong answer |
| Ontology on vs off, real questions | recall@1 0.263 to 0.316, recall@8 0.684 to 0.632 | Mixed; no clear gain on real questions (n=19) |

The scenarios (90% first-attempt) were written by the same team from the same KB pages, so they are optimistic. The gold v1 real questions are the fairer number.

## Full tables

### Three evaluation sets

| Metric | 29 scenarios | 65 held-out real questions | gold v1 (89) |
|---|---|---|---|
| Correct end state | 89.7% (26/29) | 73.8% (48/65) | 80.9% (72/89) |
| Answerable fixed on first attempt | 90.0% (18/20) | 21.1% (4/19) | 21.1% (4/19) |
| Escalated instead of answering | 10% (2/20) | 78.9% (15/19) | 78.9% (15/19) |
| Wrong-fix rate | 3.4% (1/29) | 3.1% (2/65) | 2.2% (2/89) |
| Escalation recall | 100% (9/9) | 100% (46/46) | 100% (70/70) |
| Escalation precision | 81.8% | 75.4% | 82.4% |
| KB fix sent on a case with no answer | 11.1% (1/9) | 4.3% (2/46) | 2.9% (2/70) |
| Recall@1 / @3 / @8 | 90% / 95% / 95% | 21% / 63% / 79% | 21% / 63% / 79% |
| MRR | 0.925 | 0.393 | 0.393 |
| Questions per case (mean) | 1.48 | 2.06 | 1.76 |
| Zero-question rate | 10.3% | 1.5% | 14.6% |
| Redundant question rate | 7.0% (3/43) | 0% | 0% |
| "Not sure" answers from customers | 11.6% | 27.6% | 24.2% |
| Fixes sent / citation valid | 20 / 100% | 7 / 100% | 7 / 100% |
| Ticket fallback used | 5.3% (1/19) | 16.7% (1/6) | 16.7% (1/6) |
| LLM calls per case (mean) | 1.79 | 0.29 | 0.31 |
| End to end seconds, median / p95 | 2.3 / 4.9 | 2.9 / 7.6 | 1.6 / 5.2 |

Note: the 65 held-out set and gold v1 share the same 19 answerable real questions, which is why those rows match. Earlier reports show 13 labelled held-out
questions and 81.5% correct end state; the label review raised the labelled answerable cases to 19, and the correct-end rate moved because the labels changed,
not the code (the same code gave 0 outcome changes on the earlier labels).

### Clarifier on its own (29 scenarios)

READY rate 65.5%, unresolved 34.5%, stuck 0%, mean 1.55 questions per ticket, READY precision 1.0, wrong-READY 0, out-of-scope false-READY 0,
duplicate or redundant questions 0, every question single and with options and within length limits. Opening-message extraction: gap precision and recall 1.0,
product area 90.9%, platform 100%, error code 100%. Rule-based simulated customer: optimistic.

### Robustness (`reports/regression/perturb_eval.md`, 81 answerable questions)

| Input perturbation | recall@8 of the right issue | Clarifier leading issue right (of 39) |
|---|---|---|
| original | 0.84 | 17 |
| typos | 0.78 | 17 |
| chatter ("hi... thanks in advance") | 0.82 | 17 (was 13 before `strip_chatter`) |
| two issues in one message | 0.79 | 16 |
| long pasted log noise | **0.65** | 17 |

### Dataset and knowledge facts (for a data slide)

* Knowledge base: 11,440 chunks, 961 pages; only 2.5% troubleshooting or FAQ. Community-guide tier 661 chunks. Tickets: 13,092 indexed, median 5.5 years old.
* Knowledge graph: 153 entities, links 51 of 233 support issues (22%). 30 draft nodes and 25 draft ticket cards waiting for human review.
* Gold v1: 89 questions (19 answerable, 46 KB-gap, 8 vague, 6 urgent, 6 out of scope, 4 injection). Labels reviewed by a model, not a second person.
* Tested and negative, left off: cross-encoder reranker, KB filters, ticket-age penalty.
* Tests: 592 Python and 26 frontend tests pass.

## What not to claim

* No answer-quality, faithfulness or cost number (fake LLM; Gemini judge run not completed).
* "90% resolution" applies to the team-written scenarios only; on real questions it is 21%, with 100% safe escalation.
* The ontology has no demonstrated gain on real questions.
* Gold labels are model-reviewed; the test split was looked at during development.

## Reproduce

```bash
PYTHONHASHSEED=0 HF_HUB_OFFLINE=1 python -m triage.eval.agent_metrics --clarifier --ontology --scenarios reports/regression/gold_v1_all.jsonl --out-json reports/presentation/gold_v1.json --out-md reports/presentation/gold_v1.md
bash scripts/run_clarifier_regression.sh presentation
PYTHONHASHSEED=0 HF_HUB_OFFLINE=1 python -m triage.eval.perturb_eval
```
