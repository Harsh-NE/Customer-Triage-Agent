# Agent metrics

_Generated 2026-11-03 18:58 by `python -m triage.eval.agent_metrics`._

```json
{
  "git_commit": "32a3728",
  "pythonhashseed": "0",
  "date": "2026-11-03 18:51",
  "env": {},
  "resolver_llm": "fake",
  "resolver_model": null,
  "seconds": 302.5,
  "scenario_file": "reports\\regression\\gold_v1_all.jsonl",
  "scenarios": 89,
  "repeats": 1,
  "unverified_labels": "0 of 89"
}
```

## Headline metrics

### 1_resolution

| metric | value |
|---|---|
| gold_first_attempt_correct | 21.1% (4/19) |
| gold_fixed_within_2_attempts | 21.1% (4/19) |
| gold_escalated_instead | 78.9% (15/19) |
| attempts_per_resolved_gold | p50 1 / p95 1 / mean 1 / max 1 (n=4) |
| correct_end_all_scenarios | 80.9% (72/89) |
| outcomes.escalated | 72 |
| outcomes.resolved | 4 |
| outcomes.rejected | 13 |

### 2_faithfulness

| metric | value |
|---|---|
| note | not run: pass --judge gemini (the judge is a model call per sent fix) |

### 3_retrieval

| metric | value |
|---|---|
| gold_scenarios | 19 |
| no_kb_evidence | 0 |
| recall@1 | 21.1% (4/19) |
| recall@3 | 63.2% (12/19) |
| recall@8 | 78.9% (15/19) |
| mrr | 0.402 |
| precision@5 | 0.137 |
| context_precision | 0.404 |
| top_rerank_score_gold | p50 0.56 / p95 0.89 / mean 0.58 / max 0.89 (n=19) |
| top_rerank_score_no_gold | p50 0.51 / p95 0.64 / mean 0.51 / max 0.69 (n=47) |

### 4_safe_decisions

| metric | value |
|---|---|
| wrong_fix_rate | 2.2% (2/89) |
| wrong_first_fix_on_gold | 0.0% (0/19) |
| kb_fix_on_no_answer_cases | 2.9% (2/70) |
| escalation_recall | 100.0% (70/70) |
| escalation_precision | 82.4% (70/85) |
| unnecessary_escalation_rate | 78.9% (15/19) |
| terminal_action_accuracy | 80.9% (72/89) |
| escalation_reasons.LOW_EVIDENCE | 60 |
| escalation_reasons.RETRY_EXHAUSTED | 2 |
| escalation_reasons.OUT_OF_SCOPE | 13 |
| escalation_reasons.CLARIFY_LOOP_EXHAUSTED | 6 |
| escalation_reasons.CRITICAL_SEVERITY | 1 |
| escalation_reasons.SECURITY_OR_DATA_LOSS | 3 |
| note | per-turn answer/ask/escalate accuracy needs a label for every turn; this is the end-of-case version |

### 5_customer_effort

| metric | value |
|---|---|
| questions_per_case | p50 2 / p95 3 / mean 1.8 / max 3 (n=89) |
| questions_histogram.0 | 11 |
| questions_histogram.1 | 31 |
| questions_histogram.2 | 12 |
| questions_histogram.3 | 35 |
| zero_question_rate | 12.4% (11/89) |
| zero_question_rate_clear_openings | n/a (0 of 0) |
| redundant_question_rate | 0.0% (0/160) |
| repeated_question_rate | 0.0% (0/160) |
| not_sure_answer_rate | 23.7% (38/160) |
| question_type_mix.symptoms | 55 |
| question_type_mix.trait | 41 |
| question_type_mix.error_open | 34 |
| question_type_mix.product_area | 14 |
| question_type_mix.error_message | 14 |
| question_type_mix.pick | 2 |
| ready_precision_first_fix | 100.0% (4/4) |
| note | redundant = asked for a fact the opening message already gave (scenario opening_facts) |

### 6_cost_and_speed

| metric | value |
|---|---|
| total_cost_usd | n/a |
| cost_per_case_usd | n/a |
| cost_per_verified_resolution_usd | n/a |
| tokens_per_verified_resolution | 0 |
| llm_calls_per_case | p50 0 / p95 2 / mean 0.31 / max 4 (n=89) |
| end_to_end_seconds | p50 3.02 / p95 9.69 / mean 3.4 / max 17.75 (n=89) |
| time_to_first_reply_seconds | p50 0.55 / p95 1.5 / mean 0.78 / max 16.2 (n=89) |
| note | cost is null: the model is unpriced or no model was called (fake). Latency then covers retrieval and the Clarifier only. Add the model to triage/pricing.json to price it. |

## Minor metrics by stage

### drafting_and_sources

| metric | value |
|---|---|
| fixes_sent | 7 |
| citation_valid | 100.0% (7/7) |
| first_fix_tier.kb | 6 |
| ticket_fallback_rate | 16.7% (1/6) |
| cited_per_fix | p50 2 / p95 2 / mean 2 / max 2 (n=7) |

### event_log_of_this_run

| metric | value |
|---|---|
| events.clarifier_turn | 239 |
| events.cache_lookup | 66 |
| events.retrieval | 70 |
| events.gate | 70 |
| events.escalation | 85 |
| events.llm_call | 28 |
| events.verify | 7 |
| events.sentiment | 7 |
| events.outcome | 4 |
| events.guardrail | 23 |
| llm_errors | 0.0% (0/28) |
| llm_latency_ms | p50 0.14 / p95 4.11 / mean 0.85 / max 5.38 (n=28) |
| llm_calls_by_node.scope | 14 |
| llm_calls_by_node.draft | 7 |
| llm_calls_by_node.classify | 7 |
| cache_lookups.miss | 66 |
| cache_rejected_by_gate | 0 |
| retrieval_tiers.kb | 68 |
| retrieval_tiers.tickets | 2 |
| retrieval_latency_ms | p50 1231.41 / p95 2411.35 / mean 1330.01 / max 2711.17 (n=70) |
| gate_decisions.escalate | 61 |
| gate_decisions.resolve | 7 |
| gate_decisions.fallback | 2 |
| verifier_steps_dropped | 0 |
| verifier_steps_kept | 28 |
| escalation_events.LOW_EVIDENCE | 60 |
| escalation_events.RETRY_EXHAUSTED | 2 |
| escalation_events.OUT_OF_SCOPE | 13 |
| escalation_events.CLARIFY_LOOP_EXHAUSTED | 6 |
| escalation_events.CRITICAL_SEVERITY | 1 |
| escalation_events.SECURITY_OR_DATA_LOSS | 3 |

