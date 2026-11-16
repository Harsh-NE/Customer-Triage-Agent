# Robustness to messy input

_Generated 2026-11-13 21:38 by `python -m triage.eval.perturb_eval`; 81 answerable questions (42 paraphrases, 20 scenario openings, 19 held-out gold) before perturbation. Retrieval only plus the Clarifier's first turn; see the module docstring._

## Retrieval of the gold issue

| input | recall@1 | recall@3 | recall@8 | MRR | improved / worsened vs original |
|---|---|---|---|---|---|
| original | 0.469 | 0.704 | 0.84 | 0.602 | - |
| typos | 0.457 | 0.704 | 0.84 | 0.595 | 0 / 1 |
