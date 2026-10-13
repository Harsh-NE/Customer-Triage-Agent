# End-to-end evaluation (Clarifier -> Resolver)

_Generated 2026-10-13 12:10 by `python -m triage.eval.e2e_eval`._

Real stores, simulated customer, oracle feedback (see the module docstring). 29 same-author scenarios and thresholds that are starting guesses: this shows how the pieces fit, not quality.

```json
{
  "meta": {
    "retriever": "hybrid",
    "resolver_llm": "gemini",
    "resolver_model": "gemini-3.5-flash-lite",
    "seconds": 326.1,
    "scenario_file": "scenarios.jsonl",
    "llm_calls": 64,
    "input_tokens": 64106,
    "output_tokens": 4754,
    "cost_usd": 0.0311,
    "llm_latency_ms_p50": 3256.45,
    "llm_latency_ms_p95": 4902.6
  },
  "summary": {
    "scenarios": 29,
    "with_gold": 20,
    "out_of_scope": 6,
    "no_gold_other": 3,
    "gold_resolved_rate": 0.85,
    "gold_first_attempt_rate": 0.85,
    "gold_escalated_rate": 0.15,
    "wrong_fix_sent_rate_gold": 0.0,
    "oos_resolved_rate": 0.0,
    "oos_fix_sent_rate": 0.0,
    "oos_escalated_or_rejected_rate": 1.0,
    "no_gold_other_fix_sent_rate": 0.0,
    "kb_gap": 0,
    "kb_gap_kb_fix_sent_rate": null,
    "kb_gap_any_fix_sent_rate": null,
    "first_fix_tier": {
      "kb": 17
    },
    "mean_questions": 1.17,
    "outcomes": {
      "resolved": 17,
      "escalated": 8,
      "rejected": 4
    }
  }
}
```

| id | opening | outcome | q | fixes sent (tier: gold?) | first fix cites |
|---|---|---|---|---|---|
| S01 | docker pull fails with 'You have reached your pu | resolved | 1 | kb:yes | You have reached your pull rate limit (429 response code) |
| S02 | Docker Hub pulls are failing with a 429 error | resolved | 1 | kb:yes | Too many requests (429 response code) |
| S03 | getting a 429 when our CI pulls images from Dock | resolved | 2 | kb:yes | You have reached your pull rate limit (429 response code) |
| S04 | pulling from Docker Hub gives a 500 error | resolved | 1 | kb:yes | 500 response code |
| S05 | docker commands fail and say they can't connect  | resolved | 1 | kb:yes | Unable to connect to the Docker daemon |
| S06 | containers on our Linux server can't resolve hos | resolved | 1 | kb:yes | DNS resolver issues |
| S07 | Docker Desktop won't start on my Windows laptop | escalated/LOW_EVIDENCE | 2 | - | - |
| S08 | Docker isn't starting | escalated/LOW_EVIDENCE | 3 | - | - |
| S09 | I get an error that a port is already allocated  | resolved | 1 | kb:yes | `port already allocated` errors |
| S10 | pulling from our private registry fails with a T | resolved | 1 | kb:yes | Certificates not set up correctly |
| S11 | Docker Desktop on my Mac says my CPU is incompat | resolved | 0 | kb:yes | Incompatible CPU detected |
| S12 | shell scripts I mount into containers fail with  | resolved | 1 | kb:yes | Unexpected syntax errors, use Unix style line endings for fi |
| S13 | SSO sign in isn't working for my team | resolved | 2 | kb:yes | Not enough seats in organization |
| S14 | our users can't sign in to Docker with SSO | escalated/LOW_EVIDENCE | 2 | - | - |
| S15 | SSO says our domain isn't verified | resolved | 1 | kb:yes | Domain is not verified for SSO connection |
| S16 | SCIM provisioning is not updating users that alr | resolved | 1 | kb:yes | SCIM updates don't apply to existing users |
| S17 | docker pull fails for me on rootless Docker | resolved | 1 | kb:yes | `docker pull` errors |
| S18 | I can't remove a docker volume, it says unable t | resolved | 1 | kb:yes | Unable to remove filesystem |
| S19 | my containers keep getting killed, I think they  | resolved | 1 | kb:yes | Out of memory issues |
| S20 | my Docker sandbox ran out of disk space | resolved | 1 | kb:yes | Sandbox runs out of disk space |
| S21 | our kubernetes ingress controller returns 502 ba | escalated/LOW_EVIDENCE | 1 | - | - |
| S22 | how do I reset my Netflix password | rejected/OUT_OF_SCOPE | 0 | - | - |
| S23 | it doesn't work | escalated/LOW_EVIDENCE | 3 | - | - |
| S24 | help | escalated/LOW_EVIDENCE | 3 | - | - |
| S25 | docker | escalated/VERIFICATION_FAILED | 1 | - | - |
| S26 | my python script throws a KeyError when it reads | rejected/OUT_OF_SCOPE | 0 | - | - |
| S27 | how do I install nginx on ubuntu and configure a | rejected/OUT_OF_SCOPE | 0 | - | - |
| S28 | my AWS lambda function times out after 3 seconds | rejected/OUT_OF_SCOPE | 0 | - | - |
| S29 | kubernetes pods are stuck in CrashLoopBackOff af | escalated/LOW_EVIDENCE | 1 | - | - |
