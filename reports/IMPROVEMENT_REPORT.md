# Improvement phase: before and after

Date 2026-11-03. Follows `reports/PROJECT_EVALUATION_REPORT.md`. "Before" and "after" are both offline runs with a fake LLM at the same git commit base
(`32a3728`, uncommitted changes) and `PYTHONHASHSEED=0`, so they compare behaviour, not model quality. Files: `reports/regression/{before,after}_{scenarios,heldout}.md`.

## Changes

| Finding | Change | Where |
|---|---|---|
| Clarifier asked questions when the customer had pasted the documented error | `decide()` checks the verbatim-error shortcut before missing terms; the match also counts when the first sentence of the documented error is contained in the pasted text (CLI prefixes no longer defeat it) | `triage/differential.py` |
| Data loss / security complaints went through the question loop | Early escalation in the handoff node before the Clarifier; requires a Docker term so unrelated text is not escalated | `triage/resolver/handoff.py`, `guardrails.py` |
| "Critical" severity never produced | `looks_critical`: production AND outage marker | `triage/understand.py` |
| Vague input ("I have a problem with docker") declined as out of scope or answered from a demo corpus | `content_free` check; such conversations escalate with CLARIFY_LOOP_EXHAUSTED instead | `triage/resolver/guardrails.py`, `graph.py` |
| Malformed LLM draft broke the flow | `normalize_draft` / `MalformedDraft`, one retry, then INSUFFICIENT_EVIDENCE fallback | `triage/resolver/steps.py` |
| Wasted scope-classifier calls | Skipped when the message already matches strong Docker terms | `triage/resolver/handoff.py` |
| No provider time limits | 90 s timeout, one retry | `triage/llm.py`, `triage/resolver/llm.py` |

Each change has regression tests (`tests/test_review_fixes.py`, `test_differential.py`, `test_integration.py`, `test_api.py`, `test_resolver_extras.py`).

## Before / after (offline, fake LLM)

| set | metric | before | after |
|---|---|---|---|
| scenarios (29) | correct end state | 89.7% (26/29) | 89.7% (26/29) |
| | gold fixed first attempt | 90.0% (18/20) | 90.0% (18/20) |
| | wrong fix rate | 3.4% | 3.4% |
| | escalation recall | 100% (9/9) | 100% (9/9) |
| | LLM calls per case (mean) | 2.34 | **1.79** (-24%) |
| held-out (65) | correct end state | 81.5% (53/65) | 81.5% (53/65) |
| | gold fixed first attempt | 23.1% (3/13) | 23.1% (3/13) |
| | wrong fix rate | 3.1% | 3.1% |
| | escalation recall | 100% (52/52) | 100% (52/52) |
| | LLM calls per case (mean) | 1.18 | **0.26** (-78%) |

Outcomes did not change on any of the 94 cases; the gain is fewer model calls. The urgent, vague, Critical and malformed-response changes are covered by
unit and integration tests rather than by these two sets, which contain few such cases (the gold v1 set adds 6 urgent and 8 vague; see
`DATA_IMPROVEMENT_REPORT.md`).

## Held-out labels

The 13 Stack Overflow labels were reviewed (`reports/regression/heldout_gold_review.md`): 6 of the original gold labels were retrieval misses on documented
sections and were relabelled; the review was by a model, so labels are "reviewed", not verified.

## Not done

* **Faithfulness judge and fresh Gemini run: not completed.** The approved run (~$0.15) was interrupted after 3 of 29 scenarios (about $0.003 spent);
  the partial log is `reports/regression/gemini_after_scenarios.log`. No faithfulness number exists for the current code. To finish it:
  `bash scripts/run_gemini_after.sh` (needs the Gemini key).
* Gate calibration (F-03) and the low first-attempt rate on held-out questions are unchanged.

## Limits

Fake-LLM runs say nothing about draft quality. The label review and the scenarios were written by the same people who tuned the system.
