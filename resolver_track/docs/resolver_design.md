# Resolver & Retrieval Layer — Design Log (B8)

Record each decision with the evidence behind it. Reviewers will ask "why this value?".

## Decisions

| Date | Decision | Value | Evidence / report |
|---|---|---|---|
| | Retrieval stays deterministic (not an agent) | — | Workplan; predictable, testable |
| | Gate weights (top, margin, agreement, completeness) | 0.45 / 0.15 / 0.20 / 0.20 | Starting guess — replace after B6 calibration |
| | Gate resolve threshold | 0.60 | Starting guess — set from accuracy-vs-confidence curve |
| | Cache thresholds (lower / upper) | 0.85 / 0.92 | Starting guess — set by `calibrate_cache.py` at max false-hit ≤ X% |
| | Max fix attempts before escalation | 2 | |
| | Tier 2 excludes synthetic tickets | yes | `is_synthetic` flag in docker_tickets_v3 |
| | Cache writes only confirmed resolutions | yes | Avoids caching unverified answers |

## Escalation reason codes

LOW_EVIDENCE · CRITICAL_SEVERITY · SECURITY_OR_DATA_LOSS · RETRY_EXHAUSTED ·
OUT_OF_SCOPE · VERIFICATION_FAILED · CLARIFY_LOOP_EXHAUSTED

## Open questions for the joint review

- Who computes `completeness` and how (A2)? The gate and the clarify hand-back depend on it.
- Should `new_info` always return to the Clarifier, or only when the signature fields change?
- Which embedding model is shared by the KB, the ticket index and the cache?
