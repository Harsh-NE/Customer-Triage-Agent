# Agent metrics

_Generated 2026-11-03 20:48 by `python -m triage.eval.agent_metrics`._

```json
{
  "git_commit": "32a3728",
  "pythonhashseed": "0",
  "date": "2026-11-03 20:42",
  "env": {},
  "resolver_llm": "fake",
  "resolver_model": null,
  "seconds": 235.3,
  "scenario_file": "triage\\eval\\heldout_scenarios.jsonl",
  "scenarios": 65,
  "repeats": 1,
  "unverified_labels": "0 of 65"
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
| correct_end_all_scenarios | 73.8% (48/65) |
| outcomes.escalated | 59 |
| outcomes.resolved | 4 |
| outcomes.rejected | 2 |

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
| mrr | 0.393 |
| precision@5 | 0.137 |
| context_precision | 0.394 |
| top_rerank_score_gold | p50 0.56 / p95 0.89 / mean 0.58 / max 0.89 (n=19) |
| top_rerank_score_no_gold | p50 0.51 / p95 0.64 / mean 0.52 / max 0.69 (n=44) |

### 4_safe_decisions

| metric | value |
|---|---|
| wrong_fix_rate | 3.1% (2/65) |
| wrong_first_fix_on_gold | 0.0% (0/19) |
| kb_fix_on_no_answer_cases | 4.3% (2/46) |
| escalation_recall | 100.0% (46/46) |
| escalation_precision | 75.4% (46/61) |
| unnecessary_escalation_rate | 78.9% (15/19) |
| terminal_action_accuracy | 73.8% (48/65) |
| escalation_reasons.LOW_EVIDENCE | 57 |
| escalation_reasons.RETRY_EXHAUSTED | 2 |
| escalation_reasons.OUT_OF_SCOPE | 2 |
| note | per-turn answer/ask/escalate accuracy needs a label for every turn; this is the end-of-case version |

### 5_customer_effort

| metric | value |
|---|---|
| questions_per_case | p50 3 / p95 3 / mean 2.06 / max 3 (n=65) |
| questions_histogram.0 | 1 |
| questions_histogram.1 | 27 |
| questions_histogram.2 | 4 |
| questions_histogram.3 | 33 |
| zero_question_rate | 1.5% (1/65) |
| zero_question_rate_clear_openings | n/a (0 of 0) |
| redundant_question_rate | 0.0% (0/134) |
| repeated_question_rate | 0.0% (0/134) |
| not_sure_answer_rate | 27.6% (37/134) |
| question_type_mix.symptoms | 39 |
| question_type_mix.trait | 41 |
| question_type_mix.error_open | 27 |
| question_type_mix.product_area | 13 |
| question_type_mix.error_message | 12 |
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
| llm_calls_per_case | p50 0 / p95 2 / mean 0.29 / max 4 (n=65) |
| end_to_end_seconds | p50 2.87 / p95 7.55 / mean 3.62 / max 15.83 (n=65) |
| time_to_first_reply_seconds | p50 0.54 / p95 1.26 / mean 0.84 / max 14.04 (n=65) |
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
| events.clarifier_turn | 199 |
| events.cache_lookup | 63 |
| events.retrieval | 67 |
| events.gate | 67 |
| events.escalation | 61 |
| events.llm_call | 19 |
| events.verify | 7 |
| events.sentiment | 7 |
| events.outcome | 4 |
| events.guardrail | 2 |
| llm_errors | 0.0% (0/19) |
| llm_latency_ms | p50 0.07 / p95 1.38 / mean 0.52 / max 1.38 (n=19) |
| llm_calls_by_node.scope | 5 |
| llm_calls_by_node.draft | 7 |
| llm_calls_by_node.classify | 7 |
| cache_lookups.miss | 63 |
| cache_rejected_by_gate | 0 |
| retrieval_tiers.kb | 65 |
| retrieval_tiers.tickets | 2 |
| retrieval_latency_ms | p50 996.9 / p95 1581.16 / mean 1030.77 / max 2116.87 (n=67) |
| gate_decisions.escalate | 58 |
| gate_decisions.resolve | 7 |
| gate_decisions.fallback | 2 |
| verifier_steps_dropped | 0 |
| verifier_steps_kept | 28 |
| escalation_events.LOW_EVIDENCE | 57 |
| escalation_events.RETRY_EXHAUSTED | 2 |
| escalation_events.OUT_OF_SCOPE | 2 |

### clarifier

| metric | value |
|---|---|
| gap_and_extraction.gap_precision | n/a |
| gap_and_extraction.gap_recall | n/a |
| gap_and_extraction.product_area_accuracy_on_opening | n/a |
| gap_and_extraction.platform_accuracy_on_opening | n/a |
| gap_and_extraction.error_code_recall_on_opening | n/a |
| dialogue.scenarios | 65 |
| dialogue.with_gold | 19 |
| dialogue.out_of_scope | 0 |
| dialogue.ready_rate | 0.077 |
| dialogue.unresolved_rate | 0.923 |
| dialogue.stuck_rate | 0.0 |
| dialogue.mean_questions_per_ticket | 2.06 |
| dialogue.gold_top1 | 0.263 |
| dialogue.gold_top3 | 0.526 |
| dialogue.ready_precision | 1.0 |
| dialogue.wrong_ready_rate | 0.0 |
| dialogue.oos_false_ready_rate | n/a |
| dialogue.redundant_question_rate | 0.0 |
| dialogue.duplicate_question_rate | 0.0 |
| dialogue.question_single_question | 1.0 |
| dialogue.question_options_present | 1.0 |
| dialogue.question_length_ok | 0.993 |
| dialogue.mean_tool_calls_per_ticket | 8.85 |

