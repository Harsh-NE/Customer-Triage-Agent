# Data improvement: the seven steps, measured

Date 2026-11-03. Plan: `docs/DATASET_PLAN.md`. Every number below comes from a file in `reports/` or `reports/regression/` produced by a command named
in the same row; nothing was estimated. Python suite at the end of this work: **592 passed**; frontend: tsc clean, 26 vitest tests passed.
Retrieval and Clarifier evaluations run offline (fake LLM, `PYTHONHASHSEED=0`, `HF_HUB_OFFLINE=1`). **No paid model was called in this phase.**

## Summary

| # | Step | Result | Changes behaviour? |
|---|---|---|---|
| 1 | Gold test set v1 | 89 questions, per-class baseline recorded | No (measurement) |
| 2 | KB hygiene (dedupe / archive / notes filters) | No reliable gain; filters stay **off** | No (opt-in, off) |
| 3 | Tickets to curated cards | 105 error groups, 37 gap candidates, 25 **draft** cards | No (drafts not loaded) |
| 4 | Ticket freshness penalty | No gain; stays **off** | No (opt-in, off) |
| 5 | Knowledge-graph growth | Coverage measured (22%); 30 draft nodes; 1 wrong "undocumented" claim fixed earlier | One ontology link added |
| 6 | Real-user export | Tool built and tested; needs consenting users | No |
| 7 | Stress tests | Typos, log noise, two issues hurt retrieval; chatter fix added | **Yes: `strip_chatter`** |

The honest headline: most of this phase produced *measurements and tools*, and three of the four candidate improvements (filters, freshness,
reranker earlier) measured as no benefit and were left off. The one behaviour change that survived is the chatter filter.

## 1. Gold test set v1

`python -m triage.eval.gold_v1 build / validate / score`; files `triage/eval/gold_v1_{dev,test}.jsonl`, manifest `gold_v1_manifest.json`.
89 questions: 19 answerable, 46 KB-gap (documented nowhere), 8 vague, 6 urgent, 6 out of scope, 4 injection. Stratified dev/test split.

Baseline on current code (`reports/regression/gold_v1_baseline.md`, fake LLM, 89 cases):

| metric | value |
|---|---|
| terminal action correct | 80.9% (72/89) |
| gold fixed on first attempt | 21.1% (4/19); 15/19 escalated instead |
| escalation recall | 100% (70/70 cases that should escalate) |
| wrong fix rate | 2.2% (2/89); 0 of 19 gold got a wrong first fix |
| gold retrieval recall@1 / @3 / @8 | 21.1% / 63.2% / 78.9% |
| fixes sent with a valid citation | 100% (7/7) |

Limits, stated plainly: 65 of the questions are Stack Overflow posts that were read while diagnosing the system, so the **test split is not
untouched**; labels were reviewed by a model (every row carries a reviewer note, none is marked "verified"); n=19 answerable means a single case is
5 points. Treat this as a regression baseline, not a generalisation estimate. Two-person labelling and kappa tooling exist (`gold_v1 sheet / agreement`).

## 2. KB hygiene

`KB_FILTERS=dedupe,archive,notes`, `python -m triage.eval.kb_filter_eval` (`reports/regression/kb_filter_eval.md`).
On 19 held-out gold the filters moved recall@8 from 0.632 to 0.737 but recall@1 fell from 0.316 to 0.263 and MRR was flat (0.418 vs 0.408-0.417), with
2 improved / 2 worsened. On 42 paraphrases recall@8 fell (0.952 to 0.88-0.905) and on 20 scenario openings it was flat to slightly down. Mixed and within
noise: **not adopted**. Default unchanged.

## 3. Tickets to curated cards

`python scripts/13_ticket_gaps.py` (`reports/TICKET_GAP_ANALYSIS.md`, `data/curated/ticket_gap_clusters.csv`, `cards.jsonl`).
13,092 tickets; 66 excluded as leakage against the gold set; 105 error groups of 4+ tickets covering only **846 tickets (6%)**; 37 gap candidates.
Top gaps: `executable file not found in $PATH` (22), the Docker socket permission error (21; this one *is* documented, the script's overlap measure missed
it), Docker Desktop VM networking check failures (18), `failed to solve` BuildKit errors (several groups of 5 to 16 tickets).
The 25 cards are extractive **drafts**; grouping by first error line is coarse (the largest group is 22 different programs), so many must be rejected or
narrowed by a person. Nothing loads them. **Unresolved:** a person must review them, then a re-embedding job adds the approved ones to the community tier.

## 4. Ticket freshness

`TICKET_LEGACY_PENALTY=0.5`, `python -m triage.eval.ticket_freshness_eval` (`ticket_freshness_eval.json`). 136 queries: median age of results 5.1 years
with or without the penalty; share of results flagged stale 0.4% vs 0.1%; top-1 changed for only **2 of 136** queries (the two examples recorded in the JSON are not clearly better or worse; no gold labels exist for them).
The age problem is in the corpus, not the ranking. **Not adopted.**

## 5. Knowledge-graph growth

`python scripts/15_kg_candidates.py` (`reports/KG_COVERAGE.md`, `data/curated/ontology_candidates.yaml`).
Coverage: 51 of 137 troubleshooting issues (37%), 0 of 96 FAQ entries, **51 of 233 overall (22%)**. 30 informative draft nodes written (16 with an error
line, 18 with a symptom-like title); 152 uncovered issues have only generic headings and need a person. Claim check: `issue-no-space` says it has no
documentation, but the KB mentions its error in two troubleshooting pages (a lead to review, not a verdict). Earlier in this phase the claim check helped
find that `issue-socket-permission` was documented in `engine/install/linux-postinstall.md`; that link is now in `docker.yaml`.
Drafts are structural (no aliases/summary) and are *not* expected to change retrieval by themselves. No link-prediction model was built: with 55 issue
nodes and no relation labels there is nothing to train or validate on.

## 6. Real-user export

`python scripts/14_export_for_labelling.py --i-have-consent`. Refuses to run without the flag; masks emails, passwords and tokens; hides usernames and
conversation ids; exports the system's outcome only as a labelled *hint*, never as a label; skips engineers, screenshot-only openings and questions
already in the gold set. Tested offline on a throwaway database (6 tests). **Unresolved:** there is no real data until users agree to try the app.

## 7. Stress tests and the one fix

`python -m triage.eval.perturb_eval` (`reports/regression/perturb_eval.md`): 81 answerable questions perturbed six ways.

Retrieval of the gold issue (recall@8, original 0.84): typos 0.778, log noise **0.654**, two issues 0.79, shouting and lowercase unchanged, chatter 0.815.
The Clarifier's first decision is stable across perturbations (leading issue right 17 of 39 for original, typos, shouting, lowercase and log noise; 16 for
two issues).

The chatter row exposed a defect: before the fix the Clarifier's leading issue fell **17 to 13 of 39** under chatter, because the extractor kept
"thanks in advance, been stuck on this for hours" inside the symptom text. `triage.understand.strip_chatter` removes leading greetings and trailing
pleas before extraction and before the Resolver's search text (the stored transcript is unchanged; a message that is only chatter is left as is).
After: **17 of 39**, equal to the original; READY counts unchanged (2); the 592-test suite passes, with 12 new tests in `tests/test_strip_chatter.py`
(chatter removed, content such as "stuck on starting" and "highlight" kept, only-chatter returned unchanged, extractor symptom clean).

Caveats: the chatter perturbation was written by us and the filter was written after seeing it, so this is partly circular; recall@8 of the raw-query
retrieval in this eval is not affected by the fix (it perturbs the query directly). The filter is deliberately conservative (a short list of phrases) and
will miss other chatter. Typos and log noise remain open: log noise is the larger loss (recall@8 0.84 to 0.654), though the Clarifier still reaches the
same leading issue.

## What is still open

1. Retrieval of documented docs sections: 4 of 19 answerable gold reach a first-attempt fix; 15 escalate. This is the dominant quality gap, and a
   measured reranker, KB filters and ticket penalty did not close it. The KB has few troubleshooting pages (2.5% of chunks), so more curated content
   (approved cards, new KG nodes) is the remaining lever.
2. Gate threshold calibration (`reports/regression/gate_calibration.json`) rests on very few real positives.
3. Cards and KG drafts need human review before they can be used.
4. Labels need a second reviewer; the test split needs fresh, untouched questions (real users, Stack Overflow questions from the last two years).
5. Log-noise robustness: extract the error lines from long pasted logs before retrieval.
