# Ablation: baseline, + KG, + KG + Jev

```json
{
  "date": "2026-11-16 11:10",
  "git_commit": "598a894",
  "git_dirty": false,
  "pythonhashseed": "0",
  "llm": "gemini",
  "model": "gemini-3.5-flash-lite",
  "seconds": 119.2,
  "scenario_files": [
    "triage/eval/scenarios.jsonl"
  ],
  "scenarios": 3,
  "stream": {
    "first_ask": 3,
    "repeat": 1,
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
| 1 First-attempt correct | 100.0% [43.8-100.0] (3/3) | 100.0% [43.8-100.0] (3/3) |
| 2 Wrong-fix rate | 0.0% [0.0-56.2] (0/3) | 0.0% [0.0-56.2] (0/3) |
| 2 Wrong first fix, answerable cases | 0.0% [0.0-56.2] (0/3) | 0.0% [0.0-56.2] (0/3) |
| 3 Escalation recall | n/a | n/a |
| 4 Escalation precision | n/a | n/a |
| 4 Unnecessary escalation | 0.0% [0.0-56.2] (0/3) | 0.0% [0.0-56.2] (0/3) |
| 5 Recall@3 | 100.0% [34.2-100.0] (2/2) | 100.0% [34.2-100.0] (2/2) |
| 5 MRR | 1 | 1 |
| 6 Questions per case (mean) | 0.67 | 1 |
| 7 Time to first fix p50 (ms) | 3,880 | 4,090 |
| 7 Time to first fix p95 (ms) | 3,980 | 4,580 |
| 8 Citation validity | 100.0% [34.2-100.0] (2/2) | 100.0% [34.2-100.0] (2/2) |
| 9 Retrieval time p50 (ms) | 260 | 331 |
| 9 Retrieval time p95 (ms) | 349 | 367 |
| 9 Repeat speed-up (x) | 1.79 | 1.71 |

## Cache, latency and cost (whole stream)

| Metric | A baseline (no KG, no Jev) | B + KG |
|---|---|---|
| Cache hit rate | 50.0% [15.0-85.0] (2/4) | 50.0% [15.0-85.0] (2/4) |
| Cache precision | 100.0% [34.2-100.0] (2/2) | 100.0% [34.2-100.0] (2/2) |
| Cache false-hit rate | 0.0% [0.0-65.8] (0/2) | 0.0% [0.0-65.8] (0/2) |
| End-to-end latency p50 (ms) | 4,680 | 5,200 |
| End-to-end latency p95 (ms) | 6,680 | 6,920 |
| Model calls | 6 | 6 |
| Failed model calls (must be 0) | 0 | 0 |
| Retried model calls (their cases ran slower) | 0 | 0 |
| Input tokens (model + Jev) | 5,894 | 5,669 |
| Cost (USD) | 0.003 | 0.0028 |
| Calls saved vs baseline arm (%) | 0 | 0 |
| Tokens saved vs baseline arm (%) | 0 | 3.8 |
| Cost saved vs baseline arm (%) | 0 | 6.7 |
| Calls avoided by the cache (est.) | 2 | 2 |
| Cost avoided by the cache (est., USD) | 0.0024 | 0.0024 |

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
