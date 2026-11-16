# Robustness to messy input

_Generated 2026-11-14 19:40 by `python -m triage.eval.perturb_eval`; 81 answerable questions (42 paraphrases, 20 scenario openings, 19 held-out gold) before perturbation. Retrieval only plus the Clarifier's first turn; see the module docstring._

## Retrieval of the gold issue

| input | recall@1 | recall@3 | recall@8 | MRR | improved / worsened vs original |
|---|---|---|---|---|---|
| original | 0.469 | 0.691 | 0.84 | 0.598 | - |
| log_noise | 0.469 | 0.691 | 0.84 | 0.598 | 0 / 0 |
| chatter | 0.469 | 0.691 | 0.84 | 0.598 | 0 / 0 |
