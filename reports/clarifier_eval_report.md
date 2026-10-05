# Clarifier evaluation report

_Generated 2026-10-05 23:03 by `python -m triage.eval.clarifier_eval`._

## Run configuration

```json
{
  "retriever": "chroma",
  "extractor": "heuristic",
  "customer": "rule",
  "style": "mixed",
  "seconds": 135.9,
  "llm_usage": null,
  "config": {
    "max_clarify_turns": 3,
    "max_tool_calls_per_turn": 3,
    "top_k": 8,
    "softmax_temperature": 0.08,
    "ready_p_top": 0.5,
    "ready_margin": 0.25,
    "min_top_score": 0.0,
    "mismatch_penalty": 0.15,
    "error_match_threshold": 0.6,
    "error_match_boost": 4.0,
    "min_discriminator_gain": 0.15,
    "min_option_weight": 0.05,
    "generic_title_weight": 0.5,
    "min_grounding": 0.34,
    "llm_phrase_questions": false,
    "max_options_in_question": 4,
    "context_token_budget": 700,
    "keep_last_turns": 4
  }
}
```

## Caveats (read before trusting any number)

- **29 scenarios, 20 with gold labels.** Differences of one scenario are 5 percentage points of gold@1. This is a smoke-level signal, not a benchmark.
- Gold labels and the simulated customer's hidden facts were written by the same author, from the same KB pages: optimistic by construction, and the rule-based customer answers menus perfectly.
- The retriever here is **vector-only** (or crude keyword). Member B's hybrid retriever should be plugged in via `--retriever-factory` and this report regenerated; thresholds were tuned against whatever retriever ran.

## Gap detection and extraction (opening message only)

| gap_precision | gap_recall | product_area_accuracy_on_opening | platform_accuracy_on_opening | error_code_recall_on_opening |
|---|---|---|---|---|
| 1.0 | 1.0 | 0.909 | 1.0 | 1.0 |

## Dialogue outcomes

| scenarios | with_gold | out_of_scope | ready_rate | unresolved_rate | stuck_rate | mean_questions_per_ticket | gold_top1 | gold_top3 | ready_precision | wrong_ready_rate | oos_false_ready_rate | redundant_question_rate | duplicate_question_rate | question_single_question | question_options_present | question_length_ok | mean_tool_calls_per_ticket |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 29 | 20 | 6 | 0.621 | 0.379 | 0.0 | 1.34 | 0.85 | 0.85 | 0.941 | 0.05 | 0.0 | 0.0 | 0.0 | 1.0 | 1.0 | 1.0 | 6.21 |

## Per-scenario

| id | opening | status | q | gold_rank | first_top_score | top hypothesis |
|---|---|---|---|---|---|---|
| S01 | docker pull fails with 'You have reached your pull | ready | 1 | 1 | 0.706 | Troubleshoot Docker Hub > You have reached your pull ra |
| S02 | Docker Hub pulls are failing with a 429 error | ready | 1 | 1 | 0.603 | Troubleshoot Docker Hub > Too many requests (429 respon |
| S03 | getting a 429 when our CI pulls images from Docker | ready | 2 | 1 | 0.613 | Troubleshoot Docker Hub > You have reached your pull ra |
| S04 | pulling from Docker Hub gives a 500 error | ready | 1 | 1 | 0.632 | Troubleshoot Docker Hub > 500 response code |
| S05 | docker commands fail and say they can't connect to | ready | 1 | 1 | 0.669 | Troubleshooting the Docker daemon > Unable to connect t |
| S06 | containers on our Linux server can't resolve hostn | ready | 0 | 1 | 0.65 | Troubleshooting the Docker daemon > DNS resolver issues |
| S07 | Docker Desktop won't start on my Windows laptop | ready | 0 | None | 0.679 | FAQs for Docker Desktop for Windows > Can I run Docker  |
| S08 | Docker isn't starting | unresolved | 3 | None | 0.669 | Troubleshoot Docker Hub > 500 response code |
| S09 | I get an error that a port is already allocated wh | ready | 1 | 1 | 0.665 | Troubleshoot topics for Docker Desktop > `port already  |
| S10 | pulling from our private registry fails with a TLS | ready | 0 | 1 | 0.741 | Troubleshoot topics for Docker Desktop > Certificates n |
| S11 | Docker Desktop on my Mac says my CPU is incompatib | ready | 0 | 1 | 0.677 | Troubleshoot topics for Docker Desktop > Incompatible C |
| S12 | shell scripts I mount into containers fail with we | ready | 1 | 1 | 0.627 | Troubleshoot topics for Docker Desktop > Unexpected syn |
| S13 | SSO sign in isn't working for my team | ready | 2 | 1 | 0.606 | Troubleshoot single sign-on > Not enough seats in organ |
| S14 | our users can't sign in to Docker with SSO | unresolved | 2 | 1 | 0.685 | Troubleshoot single sign-on > User is not assigned to t |
| S15 | SSO says our domain isn't verified | ready | 1 | 1 | 0.683 | Troubleshoot single sign-on > Domain is not verified fo |
| S16 | SCIM provisioning is not updating users that alrea | ready | 1 | 1 | 0.712 | Troubleshoot provisioning > SCIM updates don't apply to |
| S17 | docker pull fails for me on rootless Docker | unresolved | 2 | None | 0.653 | Install Docker Engine on CentOS > Install using the rpm |
| S18 | I can't remove a docker volume, it says unable to  | ready | 1 | 1 | 0.686 | Troubleshooting the Docker daemon > Unable to remove fi |
| S19 | my containers keep getting killed, I think they ru | ready | 1 | 1 | 0.661 | Troubleshooting the Docker daemon > Out of memory issue |
| S20 | my Docker sandbox ran out of disk space | ready | 1 | 1 | 0.614 | Troubleshooting > Sandbox runs out of disk space |
| S21 | our kubernetes ingress controller returns 502 bad  | unresolved | 1 | n/a | 0.53 | Troubleshoot Docker Hub > Too many requests (429 respon |
| S22 | how do I reset my Netflix password | unresolved | 2 | n/a | 0.598 | Troubleshoot single sign-on > Unable to find session |
| S23 | it doesn't work | unresolved | 3 | n/a | 0.651 | Explore the Kubernetes view > Troubleshooting |
| S24 | help | unresolved | 3 | n/a | 0.654 | Gordon use cases and examples > Debug a failed build |
| S25 | docker | ready | 1 | n/a | 0.657 | Install Docker Desktop on Windows > Start Docker Deskto |
| S26 | my python script throws a KeyError when it reads t | unresolved | 2 | n/a | 0.61 | Go language-specific guide > Local database and contain |
| S27 | how do I install nginx on ubuntu and configure a r | unresolved | 3 | n/a | 0.604 | Store configuration data using Docker Configs > Advance |
| S28 | my AWS lambda function times out after 3 seconds | unresolved | 1 | n/a | 0.548 | Frequently asked questions about Docker Compose > Why d |
| S29 | kubernetes pods are stuck in CrashLoopBackOff afte | unresolved | 1 | n/a | 0.607 | Explore the Kubernetes view > Troubleshooting |

## Guardrails

| check | result | detail |
|---|---|---|
| vague_queries_ask_for_symptoms | PASS | 8 vague queries all asked for symptoms |
| injection_treated_as_data | PASS | 4 injections neutralised |
| hostile_llm_output_sanitised | PASS | all fields sanitised; no stray tool calls |
| pii_never_stored | PASS | redacted 4 items before storage |
| tool_registry_enforces_allowlist_and_budget | PASS | allowlist and budgets enforced |
| llm_failure_degrades_gracefully | PASS | fell back to heuristic extraction |

## Threshold sweep (best 10 by READY precision, then wrong-READY, then questions)

| temperature | ready_p_top | ready_margin | min_grounding | gold_top1 | ready_precision | wrong_ready_rate | oos_false_ready_rate | mean_questions | oos_mean_questions | stuck_rate |
|---|---|---|---|---|---|---|---|---|---|---|
| 0.08 | 0.4 | 0.35 | 0.0 | 0.85 | 0.941 | 0.05 | 0.167 | 1.66 | 2.67 | 0.0 |
| 0.08 | 0.5 | 0.35 | 0.0 | 0.85 | 0.941 | 0.05 | 0.167 | 1.66 | 2.67 | 0.0 |
| 0.03 | 0.4 | 0.25 | 0.34 | 0.85 | 0.941 | 0.05 | 0.0 | 1 | 1.67 | 0.0 |
| 0.03 | 0.5 | 0.15 | 0.34 | 0.85 | 0.941 | 0.05 | 0.0 | 1 | 1.67 | 0.0 |
| 0.03 | 0.5 | 0.25 | 0.34 | 0.85 | 0.941 | 0.05 | 0.0 | 1 | 1.67 | 0.0 |
| 0.03 | 0.6 | 0.15 | 0.34 | 0.85 | 0.941 | 0.05 | 0.0 | 1 | 1.67 | 0.0 |
| 0.03 | 0.6 | 0.25 | 0.34 | 0.85 | 0.941 | 0.05 | 0.0 | 1 | 1.67 | 0.0 |
| 0.03 | 0.4 | 0.35 | 0.34 | 0.85 | 0.941 | 0.05 | 0.0 | 1.03 | 1.67 | 0.0 |
| 0.03 | 0.5 | 0.35 | 0.34 | 0.85 | 0.941 | 0.05 | 0.0 | 1.03 | 1.67 | 0.0 |
| 0.03 | 0.6 | 0.35 | 0.34 | 0.85 | 0.941 | 0.05 | 0.0 | 1.03 | 1.67 | 0.0 |

Default config values were chosen from this table, preferring a setting that is robust to its neighbours over the single highest cell (with ~20 gold scenarios, the top cell is noise).
