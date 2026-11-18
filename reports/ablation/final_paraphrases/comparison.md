# Ablation: baseline, + KG, + KG + Jev

```json
{
  "date": "2026-11-16 13:43",
  "git_commit": "daa7b2f",
  "git_dirty": false,
  "pythonhashseed": "0",
  "llm": "gemini",
  "model": "gemini-3.5-flash-lite",
  "seconds": 929.2,
  "scenario_files": [
    "reports\\regression\\paraphrase_scenarios.jsonl"
  ],
  "scenarios": 40,
  "stream": {
    "first_ask": 40,
    "repeat": 0,
    "seed": 0
  },
  "arms": {
    "A": {
      "use_kg": false,
      "use_jev": false,
      "use_semantic_cache": true,
      "name": "baseline (no KG, no Jev)"
    },
    "B": {
      "use_kg": true,
      "use_jev": false,
      "use_semantic_cache": true,
      "name": "+ KG"
    }
  },
  "baseline_arm": "A",
  "notes": []
}
```

## Core metrics (first ask)

| Metric | A baseline (no KG, no Jev) | B + KG |
|---|---|---|
| 1 First-attempt correct | 57.5% [42.2-71.5] (23/40) | 60.0% [44.6-73.7] (24/40) |
| 2 Wrong-fix rate | 5.0% [1.4-16.5] (2/40) | 5.0% [1.4-16.5] (2/40) |
| 2 Wrong first fix, answerable cases | 5.0% [1.4-16.5] (2/40) | 5.0% [1.4-16.5] (2/40) |
| 3 Escalation recall | n/a | n/a |
| 4 Escalation precision | 0.0% [0.0-19.4] (0/16) | 0.0% [-0.0-20.4] (0/15) |
| 4 Unnecessary escalation | 40.0% [26.3-55.4] (16/40) | 37.5% [24.2-53.0] (15/40) |
| 5 Recall@3 | 85.0% [70.9-92.9] (34/40) | 90.0% [76.9-96.0] (36/40) |
| 5 MRR | 0.771 | 0.798 |
| 6 Questions per case (mean) | 1.6 | 1.4 |
| 7 Time to first fix p50 (ms) | 4,350 | 5,310 |
| 7 Time to first fix p95 (ms) | 7,610 | 8,130 |
| 8 Citation validity | 100.0% [87.5-100.0] (27/27) | 100.0% [87.9-100.0] (28/28) |
| 9 Retrieval time p50 (ms) | 356 | 458 |
| 9 Retrieval time p95 (ms) | 1,003 | 913 |
| 9 Repeat speed-up (x) | n/a | n/a |

## Cache, latency and cost (whole stream)

| Metric | A baseline (no KG, no Jev) | B + KG |
|---|---|---|
| Cache hit rate | n/a | n/a |
| Cache precision | n/a | n/a |
| Cache false-hit rate | n/a | n/a |
| End-to-end latency p50 (ms) | 5,560 | 6,930 |
| End-to-end latency p95 (ms) | 15,550 | 15,260 |
| Model calls | 72 | 76 |
| Failed model calls (must be 0) | 0 | 0 |
| Retried model calls (their cases ran slower) | 0 | 0 |
| Input tokens (model + Jev) | 97,532 | 106,676 |
| Cost (USD) | 0.0448 | 0.0492 |
| Calls saved vs baseline arm (%) | 0 | -5.6 |
| Tokens saved vs baseline arm (%) | 0 | -9.4 |
| Cost saved vs baseline arm (%) | 0 | -9.8 |
| Calls avoided by the cache (est.) | 0 | 0 |
| Cost avoided by the cache (est., USD) | 0 | 0 |

## Definitions

* **1 First-attempt correct**: Of the questions the documentation answers (gold), the share whose first fix cites the gold issue.
* **2 Wrong-fix rate**: Cases that got a fix that is not the gold one, or a documentation fix where there is no answer, / all cases.
* **2 Wrong first fix, answerable cases**: Answerable cases whose first fix is not the gold one / answerable cases.
* **3 Escalation recall**: Of the cases that should reach a person (out of scope, or no documented answer), the share that did.
* **4 Escalation precision**: Of the cases that ended with a person or a refusal, the share that needed it.
* **4 Unnecessary escalation**: Answerable cases that ended with a person or a refusal / answerable cases.
* **5 Recall@3**: Answerable cases whose gold issue is in the top 3 chunks of the first documentation search / answerable cases searched.
* **5 MRR**: Mean of 1 / (rank of the first gold chunk in the first documentation search), over answerable cases searched.
* **6 Questions per case (mean)**: Mean number of clarifying questions asked per case.
* **7 Time to first fix p50 (ms)**: Milliseconds from the first customer message until the first fix is sent, over cases that sent one.
* **7 Time to first fix p95 (ms)**: As above, 95th percentile.
* **8 Citation validity**: Sent fixes whose every cited evidence id was among the evidence shown to the drafter / sent fixes.
* **9 Retrieval time p50 (ms)**: Milliseconds spent in one retrieval call, over the first ask.
* **9 Retrieval time p95 (ms)**: As above, 95th percentile.
* **9 Repeat speed-up (x)**: Median end-to-end time of a first ask that was searched and resolved / median of a repeat answered from the cache.
