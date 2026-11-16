# Reranker experiment: does a cross-encoder fix the ranking?

**Verdict: no. Keep it off.** On the only independent set (13 held-out real questions) the reranker made ranking worse, it did not improve how
well the confidence gate's input separates answerable from unanswerable queries, and it multiplied the time per search by 8-14. The
experiment is built and stays in the repo as an opt-in switch (`RERANK=`), off by default.

## Why we tried

The review found the weak point on real questions is ordering, not recall: on the 13 held-out questions the right issue was in the top 8 for
77-85% but ranked first for 31-46% (the number depends on the ontology setting). A cross-encoder reads the query and each passage together,
which is the textbook fix, and the README listed "no cross-encoder rerank" as a known gap.

## What was built (nothing changes unless `RERANK` is set)

* `triage/rerank.py`: `CrossEncoderReranker` (`ms-marco-MiniLM-L-6-v2`, already cached locally, loaded lazily, score cache), the pure
  `rerank_candidates()` and `settings_from_env()`. Raw logits (about -12 to +4) are squashed with a sigmoid to a 0-1 relevance.
* Two ways to use the score, because the Clarifier's thresholds and the gate were calibrated on vector similarity (0.5-0.8):
  **`order`** lets the cross-encoder choose the order but hands out the *same similarity values* best-first (scale untouched);
  **`blend`** scores `(1 - w) x similarity + w x relevance` (scale moves).
* `HybridKBRetriever`: `rerank_mode` / `RERANK=off|order|blend`, `RERANK_POOL` (default 20 fused candidates re-read), `RERANK_BLEND` (0.5),
  `set_rerank()`. It **fails open**: if the model cannot load or errors, the result is exactly what the rerank-off path returns (a unit test
  found my first version did not, and it was fixed).
* `triage/eval/rerank_eval.py`: the sweep below. 13 new tests in `tests/test_rerank.py`; full suite 499 passed.

## Results (`reports/regression/rerank_eval.md`, retrieval only, no paid calls)

Baseline "off" already includes the ontology. Issue-level rank of the gold issue among the 8 returned.

| set | variant | recall@1 | recall@3 | recall@8 | MRR | improved / worsened |
|---|---|---|---|---|---|---|
| **held-out real questions** (n=13) | off | 0.46 | 0.69 | 0.77 | 0.57 | |
| | order@20 | 0.15 | 0.46 | 0.62 | 0.31 | 1 / 7 |
| | blend 0.5 @20 | 0.31 | 0.46 | 0.69 | 0.41 | 1 / 5 |
| | blend 0.5 @10 | 0.31 | 0.46 | 0.77 | 0.41 | 0 / 5 |
| held-out, 7 reviewer-confirmed only | off | 0.57 | 0.57 | 0.71 | 0.61 | |
| | blend 0.5 @20 | 0.43 | 0.57 | 0.86 | 0.53 | |
| paraphrases (n=42, same author) | off | 0.52 | 0.79 | 0.95 | 0.68 | |
| | best (order@10) | 0.62 | 0.79 | 0.93 | 0.73 | 11 / 9 |
| scenario openings (n=20, same author) | off | 0.50 | 0.65 | 0.80 | 0.60 | |
| | best (order@10) | 0.60 | 0.65 | 0.80 | 0.66 | 4 / 2 |

**Separation** (can the top score tell an answerable query from an unanswerable one, which is what the gate relies on; AUC 0.5 is chance):

| | scenarios (20 vs 9) | held-out (13 vs 52) |
|---|---|---|
| off | 0.928 | 0.645 |
| best blend | 0.944 | 0.655 (blend 0.3) |
| cross-encoder alone | 0.883 | **0.522** |

**Cost** (CPU, model already loaded, cache cleared before each search, 25 queries): off 414 ms; rerank over 20 candidates **5,977 ms**; over 10 candidates
**3,444 ms**. A ticket makes 7-9 Clarifier searches plus 1-2 Resolver retrievals, so reranking every search would add roughly 25-50 s per ticket.

## What this says, and does not say

* **No gain where it matters.** On held-out questions the rerank worsened 5-7 of 13 queries and improved 0-1. The small gains on the
  same-author sets (+0.07 to +0.10 recall@1) are within the noise of 42 and 20 queries, come with lower recall@3/8 in places, and
  those sets are the ones the system was tuned on.
* **The gate's input does not improve.** Real questions are no better separated; using the cross-encoder alone is near chance (0.52) and
  puts both answerable and unanswerable queries at about 0.96-0.97.
* **Probable reasons (not tested):** this model is trained on short web-search queries, while held-out questions are long forum posts
  with code and logs; and the labelled docs are often topical rather than literal answers, which a passage-level relevance model
  scores low. Six of the 13 labels are only "weak".
* **Limits.** n=13 held-out queries; labels are reviewer drafts, not human-verified; one cross-encoder model; no end-to-end run with
  the rerank on (it would add about 50 s per ticket, about 80 minutes for the 94 scenarios, and the retrieval result already rules it out).
  Different or larger rerankers (for example a bge reranker, a download that needs approval) were not tried.

## Decision and what to do instead

1. Leave `RERANK` off. Nothing to recalibrate, no extra model on the request path.
2. The ordering weakness is more likely about **coverage and label quality** than ranking: only 2.5% of the KB is troubleshooting/FAQ, and
   6 of the 13 gold labels are weak. Verify the remaining labels before spending more on retrieval.
3. If a reranking step is still wanted for the project's story, the cheapest next trial is a **small LLM rerank of the top 5 issue titles**
   (one call, 3-9 s, paid) rather than a passage model; it would need your approval and the same held-out comparison.

## Reproduce

```bash
PYTHONHASHSEED=0 HF_HUB_OFFLINE=1 python -m triage.eval.rerank_eval                   # about 30 minutes on a CPU, free
python -m triage.eval.rerank_eval --variants blend0.5@20 --limit 10                   # a quick look
RERANK=blend uvicorn "triage.api.app:create_app" --factory --port 8000                # to try it in the app (off by default)
```
