# Retrieval evaluation

_Generated 2026-11-13 21:21 by `python -m triage.eval.retrieval_eval`. Issue-level ranking of the gold KB issue, k=8, fake nothing: retrieval only, no LLM. Value (95% bootstrap interval over questions)._

## paraphrases (n=42)

| variant | recall@1 | recall@3 | recall@8 | MRR | NDCG@3 | NDCG@8 | search ms p50 / p95 |
|---|---|---|---|---|---|---|---|
| baseline | 0.524 (0.38-0.67) | 0.786 (0.67-0.90) | 0.952 (0.88-1.00) | 0.676 (0.57-0.78) | 0.677 (0.55-0.79) | 0.745 (0.66-0.83) | 415 / 596 |

## scenarios (n=20)

| variant | recall@1 | recall@3 | recall@8 | MRR | NDCG@3 | NDCG@8 | search ms p50 / p95 |
|---|---|---|---|---|---|---|---|
| baseline | 0.500 (0.30-0.70) | 0.650 (0.45-0.85) | 0.800 (0.60-0.95) | 0.603 (0.41-0.79) | 0.595 (0.39-0.79) | 0.651 (0.47-0.82) | 384 / 586 |

## gold_dev (n=15)

| variant | recall@1 | recall@3 | recall@8 | MRR | NDCG@3 | NDCG@8 | search ms p50 / p95 |
|---|---|---|---|---|---|---|---|
| baseline | 0.333 (0.13-0.60) | 0.533 (0.27-0.80) | 0.600 (0.33-0.87) | 0.428 (0.21-0.64) | 0.442 (0.21-0.68) | 0.471 (0.25-0.69) | 937 / 1345 |

## pooled (n=77)

| variant | recall@1 | recall@3 | recall@8 | MRR | NDCG@3 | NDCG@8 | search ms p50 / p95 |
|---|---|---|---|---|---|---|---|
| baseline | 0.480 (0.38-0.60) | 0.701 (0.60-0.81) | 0.844 (0.77-0.92) | 0.609 (0.52-0.70) | 0.610 (0.52-0.71) | 0.667 (0.59-0.75) | 423 / 1016 |

