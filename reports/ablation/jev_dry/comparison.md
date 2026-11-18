# Ablation: baseline, + KG, + KG + Jev

```json
{
  "date": "2026-11-18 19:27",
  "git_commit": "daa7b2f",
  "git_dirty": true,
  "pythonhashseed": "0",
  "llm": "gemini",
  "model": "gemini-3.5-flash-lite",
  "seconds": 295.1,
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
    "B": {
      "use_kg": true,
      "use_jev": false,
      "use_semantic_cache": true,
      "name": "+ KG"
    },
    "C": {
      "use_kg": true,
      "use_jev": true,
      "use_semantic_cache": true,
      "name": "+ KG + Jev"
    }
  },
  "baseline_arm": "B",
  "jev": {
    "backend": "openrouter",
    "model": "~typesafe/jev-latest",
    "answer_above": 0.9,
    "items": 5,
    "chars": 500,
    "shadow": false
  },
  "notes": []
}
```

## Core metrics (first ask)

| Metric | B + KG | C + KG + Jev |
|---|---|---|
| 1 First-attempt correct | 100.0% [43.8-100.0] (3/3) | 100.0% [43.8-100.0] (3/3) |
| 2 Wrong-fix rate | 0.0% [0.0-56.2] (0/3) | 0.0% [0.0-56.2] (0/3) |
| 2 Wrong first fix, answerable cases | 0.0% [0.0-56.2] (0/3) | 0.0% [0.0-56.2] (0/3) |
| 3 Escalation recall | n/a | n/a |
| 4 Escalation precision | n/a | n/a |
| 4 Unnecessary escalation | 0.0% [0.0-56.2] (0/3) | 0.0% [0.0-56.2] (0/3) |
| 5 Recall@3 | 100.0% [43.8-100.0] (3/3) | 100.0% [43.8-100.0] (3/3) |
| 5 MRR | 1 | 1 |
| 6 Questions per case (mean) | 1 | 1 |
| 7 Time to first fix p50 (ms) | 11,540 | 11,650 |
| 7 Time to first fix p95 (ms) | 22,440 | 12,430 |
| 8 Citation validity | 100.0% [43.8-100.0] (3/3) | 100.0% [43.8-100.0] (3/3) |
| 9 Retrieval time p50 (ms) | 277 | 235 |
| 9 Retrieval time p95 (ms) | 447 | 511 |
| 9 Repeat speed-up (x) | n/a | n/a |

## Cache, latency and cost (whole stream)

| Metric | B + KG | C + KG + Jev |
|---|---|---|
| Cache hit rate | n/a | n/a |
| Cache precision | n/a | n/a |
| Cache false-hit rate | n/a | n/a |
| End-to-end latency p50 (ms) | 21,340 | 21,540 |
| End-to-end latency p95 (ms) | 31,410 | 53,140 |
| Model calls | 8 | 8 |
| Failed model calls (must be 0) | 0 | 0 |
| Retried model calls (their cases ran slower) | 0 | 0 |
| Input tokens (model + Jev) | 10,450 | 10,465 |
| Jev calls | 0 | 0 |
| Jev overrides (refusals turned into answers) | 0 | 0 |
| Jev errors (the rules decided) | 0 | 0 |
| Cost (USD) | 0.0052 | 0.0049 |
| Calls saved vs baseline arm (%) | 0 | 0 |
| Tokens saved vs baseline arm (%) | 0 | -0.1 |
| Cost saved vs baseline arm (%) | 0 | 5.8 |
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
