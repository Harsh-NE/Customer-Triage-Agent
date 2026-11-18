# Agent metrics

_Generated 2026-11-03 20:38 by `python -m triage.eval.agent_metrics`._

```json
{
  "git_commit": "32a3728",
  "pythonhashseed": "0",
  "date": "2026-11-03 20:33",
  "env": {},
  "resolver_llm": "fake",
  "resolver_model": null,
  "seconds": 176.9,
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
| mrr | 0.393 |
| precision@5 | 0.137 |
| context_precision | 0.394 |
| top_rerank_score_gold | p50 0.56 / p95 0.89 / mean 0.58 / max 0.89 (n=19) |
| top_rerank_score_no_gold | p50 0.51 / p95 0.64 / mean 0.51 / max 0.69 (n=45) |

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
| escalation_reasons.LOW_EVIDENCE | 58 |
| escalation_reasons.RETRY_EXHAUSTED | 2 |
| escalation_reasons.OUT_OF_SCOPE | 13 |
| escalation_reasons.CLARIFY_LOOP_EXHAUSTED | 6 |
| escalation_reasons.SECURITY_OR_DATA_LOSS | 5 |
| escalation_reasons.CRITICAL_SEVERITY | 1 |
| note | per-turn answer/ask/escalate accuracy needs a label for every turn; this is the end-of-case version |

### 5_customer_effort

| metric | value |
|---|---|
| questions_per_case | p50 2 / p95 3 / mean 1.76 / max 3 (n=89) |
| questions_histogram.0 | 13 |
| questions_histogram.1 | 30 |
| questions_histogram.2 | 11 |
| questions_histogram.3 | 35 |
| zero_question_rate | 14.6% (13/89) |
| zero_question_rate_clear_openings | n/a (0 of 0) |
| redundant_question_rate | 0.0% (0/157) |
| repeated_question_rate | 0.0% (0/157) |
| not_sure_answer_rate | 24.2% (38/157) |
| question_type_mix.symptoms | 54 |
| question_type_mix.trait | 41 |
| question_type_mix.error_open | 32 |
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
| end_to_end_seconds | p50 1.59 / p95 5.18 / mean 1.99 / max 10.72 (n=89) |
| time_to_first_reply_seconds | p50 0.3 / p95 0.85 / mean 0.46 / max 9.6 (n=89) |
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
| events.clarifier_turn | 234 |
| events.cache_lookup | 64 |
| events.retrieval | 68 |
| events.gate | 68 |
| events.escalation | 85 |
| events.llm_call | 28 |
| events.verify | 7 |
| events.sentiment | 7 |
| events.outcome | 4 |
| events.guardrail | 25 |
| llm_errors | 0.0% (0/28) |
| llm_latency_ms | p50 0.04 / p95 1.96 / mean 0.37 / max 3.14 (n=28) |
| llm_calls_by_node.scope | 14 |
| llm_calls_by_node.draft | 7 |
| llm_calls_by_node.classify | 7 |
| cache_lookups.miss | 64 |
| cache_rejected_by_gate | 0 |
| retrieval_tiers.kb | 66 |
| retrieval_tiers.tickets | 2 |
| retrieval_latency_ms | p50 675.89 / p95 1960.7 / mean 795.39 / max 3381.98 (n=68) |
| gate_decisions.escalate | 59 |
| gate_decisions.resolve | 7 |
| gate_decisions.fallback | 2 |
| verifier_steps_dropped | 0 |
| verifier_steps_kept | 28 |
| escalation_events.LOW_EVIDENCE | 58 |
| escalation_events.RETRY_EXHAUSTED | 2 |
| escalation_events.OUT_OF_SCOPE | 13 |
| escalation_events.CLARIFY_LOOP_EXHAUSTED | 6 |
| escalation_events.SECURITY_OR_DATA_LOSS | 5 |
| escalation_events.CRITICAL_SEVERITY | 1 |

### clarifier

| metric | value |
|---|---|
| gap_and_extraction.gap_precision | 0.0 |
| gap_and_extraction.gap_recall | n/a |
| gap_and_extraction.product_area_accuracy_on_opening | n/a |
| gap_and_extraction.platform_accuracy_on_opening | n/a |
| gap_and_extraction.error_code_recall_on_opening | n/a |
| dialogue.scenarios | 89 |
| dialogue.with_gold | 19 |
| dialogue.out_of_scope | 10 |
| dialogue.ready_rate | 0.067 |
| dialogue.unresolved_rate | 0.933 |
| dialogue.stuck_rate | 0.0 |
| dialogue.mean_questions_per_ticket | 2.06 |
| dialogue.gold_top1 | 0.263 |
| dialogue.gold_top3 | 0.526 |
| dialogue.ready_precision | 1.0 |
| dialogue.wrong_ready_rate | 0.0 |
| dialogue.oos_false_ready_rate | 0.0 |
| dialogue.redundant_question_rate | 0.0 |
| dialogue.duplicate_question_rate | 0.0 |
| dialogue.question_single_question | 1.0 |
| dialogue.question_options_present | 1.0 |
| dialogue.question_length_ok | 0.995 |
| dialogue.mean_tool_calls_per_ticket | 8.25 |

### ontology_off_vs_on

| metric | value |
|---|---|
| off.scenarios.recall@1 | 0.263 |
| off.scenarios.recall@3 | 0.579 |
| off.scenarios.recall@8 | 0.684 |
| off.scenarios.mrr | 0.401 |
| off.scenarios.n | 19 |
| off.paraphrases.recall@1 | 0.524 |
| off.paraphrases.recall@3 | 0.714 |
| off.paraphrases.recall@8 | 0.833 |
| off.paraphrases.mrr | 0.631 |
| off.paraphrases.n | 42 |
| both.scenarios.recall@1 | 0.316 |
| both.scenarios.recall@3 | 0.526 |
| both.scenarios.recall@8 | 0.632 |
| both.scenarios.mrr | 0.418 |
| both.scenarios.n | 19 |
| both.paraphrases.recall@1 | 0.524 |
| both.paraphrases.recall@3 | 0.786 |
| both.paraphrases.recall@8 | 0.952 |
| both.paraphrases.mrr | 0.676 |
| both.paraphrases.n | 42 |

