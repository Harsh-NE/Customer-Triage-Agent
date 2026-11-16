# Robustness to messy input

_Generated 2026-11-13 21:18 by `python -m triage.eval.perturb_eval`; 81 answerable questions (42 paraphrases, 20 scenario openings, 19 held-out gold) before perturbation. Retrieval only plus the Clarifier's first turn; see the module docstring._

## Retrieval of the gold issue

| input | recall@1 | recall@3 | recall@8 | MRR | improved / worsened vs original |
|---|---|---|---|---|---|
| original | 0.469 | 0.691 | 0.84 | 0.598 | - |
| typos | 0.42 | 0.63 | 0.778 | 0.548 | 2 / 15 |
| shouting | 0.469 | 0.691 | 0.84 | 0.598 | 0 / 0 |
| lowercase | 0.469 | 0.691 | 0.84 | 0.598 | 0 / 0 |
| chatter | 0.469 | 0.691 | 0.84 | 0.598 | 0 / 0 |
| log_noise | 0.469 | 0.691 | 0.84 | 0.598 | 0 / 0 |
| two_issues | 0.432 | 0.605 | 0.79 | 0.538 | 6 / 21 |

## The Clarifier's first decision (scenario openings and held-out gold only)

| input | n | READY | READY about the right issue | leading issue right | gold in top 3 |
|---|---|---|---|---|---|
| original | 39 | 2 | 2 | 17 | 24 |
| typos | 39 | 2 | 2 | 17 | 27 |
| shouting | 39 | 2 | 2 | 17 | 24 |
| lowercase | 39 | 2 | 2 | 17 | 24 |
| chatter | 39 | 2 | 2 | 17 | 24 |
| log_noise | 39 | 2 | 2 | 17 | 24 |
| two_issues | 39 | 1 | 1 | 16 | 26 |
