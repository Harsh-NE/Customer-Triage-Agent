# Agent metrics

_Generated 2026-11-03 12:01 by `python -m triage.eval.agent_metrics`._

```json
{
  "git_commit": "32a3728",
  "pythonhashseed": "0",
  "date": "2026-11-03 11:55",
  "env": {},
  "resolver_llm": "fake",
  "resolver_model": null,
  "seconds": 210.1,
  "scenario_file": "triage\\eval\\heldout_scenarios.jsonl",
  "scenarios": 65,
  "repeats": 1,
  "unverified_labels": "65 of 65"
}
```

## Headline metrics

### 1_resolution

| metric | value |
|---|---|
| gold_first_attempt_correct | 23.1% (3/13) |
| gold_fixed_within_2_attempts | 23.1% (3/13) |
| gold_escalated_instead | 76.9% (10/13) |
| attempts_per_resolved_gold | p50 1 / p95 1 / mean 1 / max 1 (n=3) |
| correct_end_all_scenarios | 81.5% (53/65) |
| outcomes.escalated | 60 |
| outcomes.resolved | 3 |
| outcomes.rejected | 2 |

### 2_faithfulness

| metric | value |
|---|---|
| note | not run: pass --judge gemini (the judge is a model call per sent fix) |

### 3_retrieval

| metric | value |
|---|---|
| gold_scenarios | 13 |
| no_kb_evidence | 0 |
| recall@1 | 30.8% (4/13) |
| recall@3 | 69.2% (9/13) |
| recall@8 | 84.6% (11/13) |
| mrr | 0.487 |
| precision@5 | 0.154 |
| context_precision | 0.49 |
| top_rerank_score_gold | p50 0.56 / p95 0.89 / mean 0.6 / max 0.89 (n=13) |
| top_rerank_score_no_gold | p50 0.52 / p95 0.67 / mean 0.52 / max 0.69 (n=50) |

### 4_safe_decisions

| metric | value |
|---|---|
| wrong_fix_rate | 3.1% (2/65) |
| wrong_first_fix_on_gold | 0.0% (0/13) |
| kb_fix_on_no_answer_cases | 3.8% (2/52) |
| escalation_recall | 100.0% (52/52) |
| escalation_precision | 83.9% (52/62) |
| unnecessary_escalation_rate | 76.9% (10/13) |
| terminal_action_accuracy | 81.5% (53/65) |
| escalation_reasons.LOW_EVIDENCE | 58 |
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
| not_sure_answer_rate | 30.6% (41/134) |
| question_type_mix.symptoms | 39 |
| question_type_mix.trait | 41 |
| question_type_mix.error_open | 27 |
| question_type_mix.product_area | 13 |
| question_type_mix.error_message | 12 |
| question_type_mix.pick | 2 |
| ready_precision_first_fix | 100.0% (3/3) |
| note | redundant = asked for a fact the opening message already gave (scenario opening_facts) |

### 6_cost_and_speed

| metric | value |
|---|---|
| total_cost_usd | n/a |
| cost_per_case_usd | n/a |
| cost_per_verified_resolution_usd | n/a |
| tokens_per_verified_resolution | 0 |
| llm_calls_per_case | p50 1 / p95 3 / mean 1.18 / max 5 (n=65) |
| end_to_end_seconds | p50 2.67 / p95 7.74 / mean 3.23 / max 13.79 (n=65) |
| time_to_first_reply_seconds | p50 0.46 / p95 1.19 / mean 0.74 / max 12.37 (n=65) |
| note | cost is null: the model is unpriced or no model was called (fake). Latency then covers retrieval and the Clarifier only. Add the model to triage/pricing.json to price it. |

## Minor metrics by stage

### drafting_and_sources

| metric | value |
|---|---|
| fixes_sent | 6 |
| citation_valid | 100.0% (6/6) |
| first_fix_tier.kb | 5 |
| ticket_fallback_rate | 20.0% (1/5) |
| cited_per_fix | p50 2 / p95 2 / mean 2 / max 2 (n=6) |

### event_log_of_this_run

| metric | value |
|---|---|
| events.llm_call | 77 |
| events.clarifier_turn | 199 |
| events.cache_lookup | 63 |
| events.retrieval | 67 |
| events.gate | 67 |
| events.escalation | 62 |
| events.verify | 6 |
| events.sentiment | 6 |
| events.outcome | 3 |
| events.guardrail | 2 |
| llm_errors | 0.0% (0/77) |
| llm_latency_ms | p50 0.03 / p95 1.47 / mean 0.17 / max 2.08 (n=77) |
| llm_calls_by_node.scope | 65 |
| llm_calls_by_node.draft | 6 |
| llm_calls_by_node.classify | 6 |
| cache_lookups.miss | 63 |
| cache_rejected_by_gate | 0 |
| retrieval_tiers.kb | 65 |
| retrieval_tiers.tickets | 2 |
| retrieval_latency_ms | p50 945.23 / p95 1682.3 / mean 1001.25 / max 2457.17 (n=67) |
| gate_decisions.escalate | 59 |
| gate_decisions.resolve | 6 |
| gate_decisions.fallback | 2 |
| verifier_steps_dropped | 0 |
| verifier_steps_kept | 24 |
| escalation_events.LOW_EVIDENCE | 58 |
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
| dialogue.with_gold | 13 |
| dialogue.out_of_scope | 0 |
| dialogue.ready_rate | 0.077 |
| dialogue.unresolved_rate | 0.923 |
| dialogue.stuck_rate | 0.0 |
| dialogue.mean_questions_per_ticket | 2.06 |
| dialogue.gold_top1 | 0.385 |
| dialogue.gold_top3 | 0.615 |
| dialogue.ready_precision | 1.0 |
| dialogue.wrong_ready_rate | 0.0 |
| dialogue.oos_false_ready_rate | n/a |
| dialogue.redundant_question_rate | 0.0 |
| dialogue.duplicate_question_rate | 0.0 |
| dialogue.question_single_question | 1.0 |
| dialogue.question_options_present | 1.0 |
| dialogue.question_length_ok | 0.993 |
| dialogue.mean_tool_calls_per_ticket | 8.85 |

