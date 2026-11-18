# Ablation: baseline, + KG, + KG + Jev

```json
{
  "date": "2026-11-16 00:44",
  "git_commit": "7191c5d",
  "pythonhashseed": "0",
  "llm": "gemini",
  "model": "gemini-3.5-flash-lite",
  "seconds": 828.1,
  "scenario_files": [
    "triage/eval/scenarios.jsonl"
  ],
  "scenarios": 29,
  "stream": {
    "first_ask": 29,
    "repeat": 9,
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
  "notes": [],
  "recomputed": "2026-11-16 00:50"
}
```

## Core metrics (first ask)

| Metric | A baseline (no KG, no Jev) | B + KG |
|---|---|---|
| 1 First-attempt correct | 80.0% [58.4-91.9] (16/20) | 90.0% [69.9-97.2] (18/20) |
| 2 Wrong-fix rate | 10.3% [3.6-26.4] (3/29) | 3.4% [0.6-17.2] (1/29) |
| 2 Wrong first fix, answerable cases | 10.0% [2.8-30.1] (2/20) | 5.0% [0.9-23.6] (1/20) |
| 3 Escalation recall | 100.0% [70.1-100.0] (9/9) | 100.0% [70.1-100.0] (9/9) |
| 4 Escalation precision | 81.8% [52.3-94.9] (9/11) | 81.8% [52.3-94.9] (9/11) |
| 4 Unnecessary escalation | 10.0% [2.8-30.1] (2/20) | 10.0% [2.8-30.1] (2/20) |
| 5 Recall@3 | 94.4% [74.2-99.0] (17/18) | 94.4% [74.2-99.0] (17/18) |
| 5 MRR | 0.944 | 0.944 |
| 6 Questions per case (mean) | 1.28 | 1.34 |
| 7 Time to first fix p50 (ms) | 3,860 | 4,570 |
| 7 Time to first fix p95 (ms) | 7,820 | 6,480 |
| 8 Citation validity | 100.0% [83.9-100.0] (20/20) | 100.0% [81.6-100.0] (17/17) |
| 9 Retrieval time p50 (ms) | 315 | 377 |
| 9 Retrieval time p95 (ms) | 1,413 | 812 |
| 9 Repeat speed-up (x) | 1.67 | 1.15 |

## Cache, latency and cost (whole stream)

| Metric | A baseline (no KG, no Jev) | B + KG |
|---|---|---|
| Cache hit rate | 18.2% [8.6-34.4] (6/33) | 24.2% [12.8-41.0] (8/33) |
| Cache precision | 100.0% [61.0-100.0] (6/6) | 75.0% [40.9-92.9] (6/8) |
| Cache false-hit rate | 0.0% [0.0-39.0] (0/6) | 25.0% [7.1-59.1] (2/8) |
| End-to-end latency p50 (ms) | 4,660 | 5,360 |
| End-to-end latency p95 (ms) | 16,060 | 8,640 |
| Model calls | 68 | 62 |
| Failed model calls (must be 0) | 0 | 0 |
| Input tokens (model + Jev) | 86,172 | 71,476 |
| Cost (USD) | 0.0405 | 0.0331 |
| Calls saved vs baseline arm (%) | 0 | 8.8 |
| Tokens saved vs baseline arm (%) | 0 | 17.1 |
| Cost saved vs baseline arm (%) | 0 | 18.3 |
| Calls avoided by the cache (est.) | 6.071 | 6.143 |
| Cost avoided by the cache (est., USD) | 0.0071 | 0.007786 |

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
