# End-to-end evaluation (Clarifier -> Resolver)

_Generated 2026-10-13 11:44 by `python -m triage.eval.e2e_eval`._

Real stores, simulated customer, oracle feedback (see the module docstring). 29 same-author scenarios and thresholds that are starting guesses: this shows how the pieces fit, not quality.

```json
{
  "meta": {
    "retriever": "hybrid",
    "resolver_llm": "gemini",
    "resolver_model": "gemini-3.5-flash-lite",
    "seconds": 67.9,
    "scenario_file": "scenarios.jsonl",
    "llm_calls": 7,
    "input_tokens": 7158,
    "output_tokens": 410,
    "cost_usd": 0.0032,
    "llm_latency_ms_p50": 3128.41,
    "llm_latency_ms_p95": 4372.04
  },
  "summary": {
    "scenarios": 3,
    "with_gold": 2,
    "out_of_scope": 1,
    "no_gold_other": 0,
    "gold_resolved_rate": 1.0,
    "gold_first_attempt_rate": 1.0,
    "gold_escalated_rate": 0.0,
    "wrong_fix_sent_rate_gold": 0.0,
    "oos_resolved_rate": 0.0,
    "oos_fix_sent_rate": 0.0,
    "oos_escalated_or_rejected_rate": 1.0,
    "no_gold_other_fix_sent_rate": null,
    "kb_gap": 0,
    "kb_gap_kb_fix_sent_rate": null,
    "kb_gap_any_fix_sent_rate": null,
    "first_fix_tier": {
      "kb": 2
    },
    "mean_questions": 1.0,
    "outcomes": {
      "resolved": 2,
      "escalated": 1
    }
  }
}
```

| id | opening | outcome | q | fixes sent (tier: gold?) | first fix cites |
|---|---|---|---|---|---|
| S01 | docker pull fails with 'You have reached your pu | resolved | 1 | kb:yes | You have reached your pull rate limit (429 response code) |
| S17 | docker pull fails for me on rootless Docker | resolved | 1 | kb:yes | `docker pull` errors |
| S29 | kubernetes pods are stuck in CrashLoopBackOff af | escalated/LOW_EVIDENCE | 1 | - | - |
