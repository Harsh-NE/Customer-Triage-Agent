# Ablation: baseline, + KG, + KG + Jev

```json
{
  "date": "2026-11-16 01:16",
  "git_commit": "7191c5d",
  "pythonhashseed": "0",
  "llm": "gemini",
  "model": "gemini-3.5-flash-lite",
  "seconds": 728.5,
  "scenario_files": [
    "triage/eval/scenarios.jsonl"
  ],
  "scenarios": 29,
  "stream": {
    "first_ask": 29,
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
| 1 First-attempt correct | 90.0% [69.9-97.2] (18/20) | 85.0% [64.0-94.8] (17/20) |
| 2 Wrong-fix rate | 3.4% [0.6-17.2] (1/29) | 6.9% [1.9-22.0] (2/29) |
| 2 Wrong first fix, answerable cases | 0.0% [-0.0-16.1] (0/20) | 5.0% [0.9-23.6] (1/20) |
| 3 Escalation recall | 100.0% [70.1-100.0] (9/9) | 100.0% [70.1-100.0] (9/9) |
| 4 Escalation precision | 81.8% [52.3-94.9] (9/11) | 81.8% [52.3-94.9] (9/11) |
| 4 Unnecessary escalation | 10.0% [2.8-30.1] (2/20) | 10.0% [2.8-30.1] (2/20) |
| 5 Recall@3 | 90.0% [69.9-97.2] (18/20) | 95.0% [76.4-99.1] (19/20) |
| 5 MRR | 0.9 | 0.925 |
| 6 Questions per case (mean) | 1.28 | 1.24 |
| 7 Time to first fix p50 (ms) | 4,530 | 4,720 |
| 7 Time to first fix p95 (ms) | 18,750 | 7,890 |
| 8 Citation validity | 100.0% [83.2-100.0] (19/19) | 100.0% [83.9-100.0] (20/20) |
| 9 Retrieval time p50 (ms) | 301 | 350 |
| 9 Retrieval time p95 (ms) | 900 | 1,230 |
| 9 Repeat speed-up (x) | n/a | n/a |

## Cache, latency and cost (whole stream)

| Metric | A baseline (no KG, no Jev) | B + KG |
|---|---|---|
| Cache hit rate | n/a | n/a |
| Cache precision | n/a | n/a |
| Cache false-hit rate | n/a | n/a |
| End-to-end latency p50 (ms) | 5,580 | 5,790 |
| End-to-end latency p95 (ms) | 28,250 | 10,570 |
| Model calls | 51 | 53 |
| Failed model calls (must be 0) | 0 | 0 |
| Input tokens (model + Jev) | 67,854 | 69,082 |
| Cost (USD) | 0.032 | 0.0333 |
| Calls saved vs baseline arm (%) | 0 | -3.9 |
| Tokens saved vs baseline arm (%) | 0 | -1.8 |
| Cost saved vs baseline arm (%) | 0 | -4.1 |
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
