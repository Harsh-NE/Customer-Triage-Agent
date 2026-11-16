# Agent metrics

_Generated 2026-11-03 11:55 by `python -m triage.eval.agent_metrics`._

```json
{
  "git_commit": "32a3728",
  "pythonhashseed": "0",
  "date": "2026-11-03 11:52",
  "env": {},
  "resolver_llm": "fake",
  "resolver_model": null,
  "seconds": 75.1,
  "scenario_file": "scenarios.jsonl",
  "scenarios": 29,
  "repeats": 1,
  "unverified_labels": "0 of 29"
}
```

## Headline metrics

### 1_resolution

| metric | value |
|---|---|
| gold_first_attempt_correct | 90.0% (18/20) |
| gold_fixed_within_2_attempts | 90.0% (18/20) |
| gold_escalated_instead | 10.0% (2/20) |
| attempts_per_resolved_gold | p50 1 / p95 1 / mean 1 / max 1 (n=18) |
| correct_end_all_scenarios | 89.7% (26/29) |
| outcomes.resolved | 18 |
| outcomes.escalated | 7 |
| outcomes.rejected | 4 |

### 2_faithfulness

| metric | value |
|---|---|
| note | not run: pass --judge gemini (the judge is a model call per sent fix) |

### 3_retrieval

| metric | value |
|---|---|
| gold_scenarios | 20 |
| no_kb_evidence | 0 |
| recall@1 | 90.0% (18/20) |
| recall@3 | 95.0% (19/20) |
| recall@8 | 95.0% (19/20) |
| mrr | 0.925 |
| precision@5 | 0.193 |
| context_precision | 0.925 |
| top_rerank_score_gold | p50 0.78 / p95 0.94 / mean 0.79 / max 0.95 (n=20) |
| top_rerank_score_no_gold | p50 0.56 / p95 0.64 / mean 0.5 / max 0.64 (n=5) |

### 4_safe_decisions

| metric | value |
|---|---|
| wrong_fix_rate | 3.4% (1/29) |
| wrong_first_fix_on_gold | 0.0% (0/20) |
| kb_fix_on_no_answer_cases | 11.1% (1/9) |
| escalation_recall | 100.0% (9/9) |
| escalation_precision | 81.8% (9/11) |
| unnecessary_escalation_rate | 10.0% (2/20) |
| terminal_action_accuracy | 89.7% (26/29) |
| escalation_reasons.LOW_EVIDENCE | 6 |
| escalation_reasons.OUT_OF_SCOPE | 4 |
| escalation_reasons.RETRY_EXHAUSTED | 1 |
| note | per-turn answer/ask/escalate accuracy needs a label for every turn; this is the end-of-case version |

### 5_customer_effort

| metric | value |
|---|---|
| questions_per_case | p50 1 / p95 3 / mean 1.48 / max 3 (n=29) |
| questions_histogram.0 | 3 |
| questions_histogram.1 | 15 |
| questions_histogram.2 | 5 |
| questions_histogram.3 | 6 |
| zero_question_rate | 10.3% (3/29) |
| zero_question_rate_clear_openings | 28.6% (2/7) |
| redundant_question_rate | 7.0% (3/43) |
| repeated_question_rate | 0.0% (0/43) |
| not_sure_answer_rate | 11.6% (5/43) |
| question_type_mix.error_open | 9 |
| question_type_mix.pick | 4 |
| question_type_mix.trait | 13 |
| question_type_mix.symptoms | 11 |
| question_type_mix.error_message | 3 |
| question_type_mix.product_area | 3 |
| ready_precision_first_fix | 100.0% (18/18) |
| note | redundant = asked for a fact the opening message already gave (scenario opening_facts) |

### 6_cost_and_speed

| metric | value |
|---|---|
| total_cost_usd | n/a |
| cost_per_case_usd | n/a |
| cost_per_verified_resolution_usd | n/a |
| tokens_per_verified_resolution | 0 |
| llm_calls_per_case | p50 3 / p95 3 / mean 2.34 / max 5 (n=29) |
| end_to_end_seconds | p50 1.71 / p95 6.8 / mean 2.59 / max 16.24 (n=29) |
| time_to_first_reply_seconds | p50 0.41 / p95 1.78 / mean 0.96 / max 16.04 (n=29) |
| note | cost is null: the model is unpriced or no model was called (fake). Latency then covers retrieval and the Clarifier only. Add the model to triage/pricing.json to price it. |

## Minor metrics by stage

### drafting_and_sources

| metric | value |
|---|---|
| fixes_sent | 20 |
| citation_valid | 100.0% (20/20) |
| first_fix_tier.kb | 19 |
| ticket_fallback_rate | 5.3% (1/19) |
| cited_per_fix | p50 2 / p95 2 / mean 2 / max 2 (n=20) |

### event_log_of_this_run

| metric | value |
|---|---|
| events.llm_call | 68 |
| events.clarifier_turn | 71 |
| events.cache_lookup | 25 |
| events.retrieval | 27 |
| events.gate | 27 |
| events.verify | 20 |
| events.sentiment | 20 |
| events.outcome | 18 |
| events.escalation | 11 |
| events.guardrail | 4 |
| llm_errors | 0.0% (0/68) |
| llm_latency_ms | p50 0.04 / p95 1.17 / mean 0.28 / max 3.34 (n=68) |
| llm_calls_by_node.scope | 28 |
| llm_calls_by_node.draft | 20 |
| llm_calls_by_node.classify | 20 |
| cache_lookups.miss | 25 |
| cache_rejected_by_gate | 0 |
| retrieval_tiers.kb | 26 |
| retrieval_tiers.tickets | 1 |
| retrieval_latency_ms | p50 362.98 / p95 3606.63 / mean 711.24 / max 5696.62 (n=27) |
| gate_decisions.resolve | 20 |
| gate_decisions.escalate | 6 |
| gate_decisions.fallback | 1 |
| verifier_steps_dropped | 0 |
| verifier_steps_kept | 80 |
| escalation_events.LOW_EVIDENCE | 6 |
| escalation_events.OUT_OF_SCOPE | 4 |
| escalation_events.RETRY_EXHAUSTED | 1 |

### clarifier

| metric | value |
|---|---|
| gap_and_extraction.gap_precision | 1.0 |
| gap_and_extraction.gap_recall | 1.0 |
| gap_and_extraction.product_area_accuracy_on_opening | 0.909 |
| gap_and_extraction.platform_accuracy_on_opening | 1.0 |
| gap_and_extraction.error_code_recall_on_opening | 1.0 |
| dialogue.scenarios | 29 |
| dialogue.with_gold | 20 |
| dialogue.out_of_scope | 6 |
| dialogue.ready_rate | 0.655 |
| dialogue.unresolved_rate | 0.345 |
| dialogue.stuck_rate | 0.0 |
| dialogue.mean_questions_per_ticket | 1.55 |
| dialogue.gold_top1 | 0.9 |
| dialogue.gold_top3 | 0.95 |
| dialogue.ready_precision | 1.0 |
| dialogue.wrong_ready_rate | 0.0 |
| dialogue.oos_false_ready_rate | 0.0 |
| dialogue.redundant_question_rate | 0.0 |
| dialogue.duplicate_question_rate | 0.0 |
| dialogue.question_single_question | 1.0 |
| dialogue.question_options_present | 1.0 |
| dialogue.question_length_ok | 1.0 |
| dialogue.mean_tool_calls_per_ticket | 7 |

