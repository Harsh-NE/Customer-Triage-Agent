# Ablation: baseline, + KG, + KG + Jev

```json
{
  "date": "2026-11-16 10:13",
  "git_commit": "7191c5d",
  "pythonhashseed": null,
  "llm": "gemini",
  "model": "gemini-3.5-flash-lite",
  "seconds": 907.9,
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
  "notes": []
}
```

## Core metrics (first ask)

| Metric | A baseline (no KG, no Jev) | B + KG |
|---|---|---|
| 1 First-attempt correct | 85.0% [64.0-94.8] (17/20) | 80.0% [58.4-91.9] (16/20) |
| 2 Wrong-fix rate | 6.9% [1.9-22.0] (2/29) | 13.8% [5.5-30.6] (4/29) |
| 2 Wrong first fix, answerable cases | 5.0% [0.9-23.6] (1/20) | 15.0% [5.2-36.0] (3/20) |
| 3 Escalation recall | 100.0% [70.1-100.0] (9/9) | 100.0% [70.1-100.0] (9/9) |
| 4 Escalation precision | 81.8% [52.3-94.9] (9/11) | 81.8% [52.3-94.9] (9/11) |
| 4 Unnecessary escalation | 10.0% [2.8-30.1] (2/20) | 10.0% [2.8-30.1] (2/20) |
| 5 Recall@3 | 94.4% [74.2-99.0] (17/18) | 94.4% [74.2-99.0] (17/18) |
| 5 MRR | 0.944 | 0.944 |
| 6 Questions per case (mean) | 1.28 | 1.28 |
| 7 Time to first fix p50 (ms) | 7,800 | 5,210 |
| 7 Time to first fix p95 (ms) | 10,570 | 7,260 |
| 8 Citation validity | 100.0% [83.2-100.0] (19/19) | 100.0% [83.9-100.0] (20/20) |
| 9 Retrieval time p50 (ms) | 793 | 318 |
| 9 Retrieval time p95 (ms) | 1,803 | 889 |
| 9 Repeat speed-up (x) | 1.43 | 1.44 |

## Cache, latency and cost (whole stream)

| Metric | A baseline (no KG, no Jev) | B + KG |
|---|---|---|
| Cache hit rate | 18.2% [8.6-34.4] (6/33) | 21.2% [10.7-37.8] (7/33) |
| Cache precision | 100.0% [61.0-100.0] (6/6) | 85.7% [48.7-97.4] (6/7) |
| Cache false-hit rate | 0.0% [0.0-39.0] (0/6) | 14.3% [2.6-51.3] (1/7) |
| End-to-end latency p50 (ms) | 8,940 | 5,710 |
| End-to-end latency p95 (ms) | 17,540 | 14,770 |
| Model calls | 64 | 70 |
| Failed model calls (must be 0) | 0 | 0 |
| Input tokens (model + Jev) | 80,568 | 89,082 |
| Cost (USD) | 0.0367 | 0.0409 |
| Calls saved vs baseline arm (%) | 0 | -9.4 |
| Tokens saved vs baseline arm (%) | 0 | -10.6 |
| Cost saved vs baseline arm (%) | 0 | -11.4 |
| Calls avoided by the cache (est.) | 5.214 | 7.5 |
| Cost avoided by the cache (est., USD) | 0.006771 | 0.00885 |

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
