# Ablation: baseline, + KG, + KG + Jev

```json
{
  "date": "2026-11-16 12:11",
  "git_commit": "598a894",
  "git_dirty": false,
  "pythonhashseed": "0",
  "llm": "gemini",
  "model": "gemini-3.5-flash-lite",
  "seconds": 1128.2,
  "scenario_files": [
    "reports\\regression\\gold_v1_all.jsonl"
  ],
  "scenarios": 89,
  "stream": {
    "first_ask": 89,
    "repeat": 27,
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
| 1 First-attempt correct | 10.5% [2.9-31.4] (2/19) | 15.8% [5.5-37.6] (3/19) |
| 2 Wrong-fix rate | 2.2% [0.6-7.8] (2/89) | 2.2% [0.6-7.8] (2/89) |
| 2 Wrong first fix, answerable cases | 10.5% [2.9-31.4] (2/19) | 0.0% [0.0-16.8] (0/19) |
| 3 Escalation recall | 100.0% [94.8-100.0] (70/70) | 100.0% [94.8-100.0] (70/70) |
| 4 Escalation precision | 80.5% [70.9-87.4] (70/87) | 81.4% [71.9-88.2] (70/86) |
| 4 Unnecessary escalation | 89.5% [68.6-97.1] (17/19) | 84.2% [62.4-94.5] (16/19) |
| 5 Recall@3 | 52.6% [31.7-72.7] (10/19) | 63.2% [41.0-80.9] (12/19) |
| 5 MRR | 0.393 | 0.393 |
| 6 Questions per case (mean) | 1.75 | 1.69 |
| 7 Time to first fix p50 (ms) | 6,620 | 4,990 |
| 7 Time to first fix p95 (ms) | 9,330 | 34,100 |
| 8 Citation validity | 100.0% [51.0-100.0] (4/4) | 100.0% [56.6-100.0] (5/5) |
| 9 Retrieval time p50 (ms) | 802 | 871 |
| 9 Retrieval time p95 (ms) | 4,064 | 5,442 |
| 9 Repeat speed-up (x) | 1.52 | 1.83 |

## Cache, latency and cost (whole stream)

| Metric | A baseline (no KG, no Jev) | B + KG |
|---|---|---|
| Cache hit rate | 1.2% [0.2-6.6] (1/82) | 1.2% [0.2-6.6] (1/82) |
| Cache precision | 100.0% [20.7-100.0] (1/1) | 100.0% [20.7-100.0] (1/1) |
| Cache false-hit rate | 0.0% [0.0-79.3] (0/1) | 0.0% [0.0-79.3] (0/1) |
| End-to-end latency p50 (ms) | 2,320 | 2,550 |
| End-to-end latency p95 (ms) | 11,190 | 17,920 |
| Model calls | 29 | 37 |
| Failed model calls (must be 0) | 0 | 0 |
| Retried model calls (their cases ran slower) | 0 | 0 |
| Input tokens (model + Jev) | 22,708 | 45,344 |
| Cost (USD) | 0.0114 | 0.0194 |
| Calls saved vs baseline arm (%) | 0 | -27.6 |
| Tokens saved vs baseline arm (%) | 0 | -99.7 |
| Cost saved vs baseline arm (%) | 0 | -70.2 |
| Calls avoided by the cache (est.) | 0.1667 | 0.3333 |
| Cost avoided by the cache (est., USD) | 0.000371 | 0.000615 |

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
