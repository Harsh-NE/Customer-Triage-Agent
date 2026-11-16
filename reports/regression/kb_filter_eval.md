# KB filters: results

_Generated 2026-11-03 19:30 by `python -m triage.eval.kb_filter_eval`. Real KB, hybrid retriever, opt-in filters. Retrieval only; see the module docstring for what this cannot say._

## paraphrases (n=42)

| variant | recall@1 | recall@3 | recall@8 | MRR | improved / worsened vs off |
|---|---|---|---|---|---|
| off | 0.524 | 0.786 | 0.952 | 0.676 | 0 / 0 |
| dedupe | 0.524 | 0.69 | 0.881 | 0.639 | 0 / 9 |
| archive | 0.548 | 0.714 | 0.905 | 0.663 | 2 / 7 |
| notes | 0.548 | 0.714 | 0.905 | 0.658 | 1 / 9 |
| dedupe+archive | 0.548 | 0.714 | 0.905 | 0.663 | 2 / 7 |
| dedupe+archive+notes | 0.571 | 0.762 | 0.905 | 0.68 | 3 / 7 |

## scenario_openings (n=20)

| variant | recall@1 | recall@3 | recall@8 | MRR | improved / worsened vs off |
|---|---|---|---|---|---|
| off | 0.5 | 0.65 | 0.8 | 0.603 | 0 / 0 |
| dedupe | 0.5 | 0.65 | 0.75 | 0.59 | 0 / 3 |
| archive | 0.55 | 0.65 | 0.75 | 0.615 | 1 / 3 |
| notes | 0.5 | 0.65 | 0.8 | 0.603 | 1 / 1 |
| dedupe+archive | 0.55 | 0.65 | 0.75 | 0.615 | 1 / 3 |
| dedupe+archive+notes | 0.55 | 0.65 | 0.8 | 0.628 | 2 / 1 |

## heldout_gold (n=19)

| variant | recall@1 | recall@3 | recall@8 | MRR | improved / worsened vs off |
|---|---|---|---|---|---|
| off | 0.316 | 0.526 | 0.632 | 0.418 | 0 / 0 |
| dedupe | 0.263 | 0.579 | 0.737 | 0.408 | 2 / 2 |
| archive | 0.263 | 0.579 | 0.737 | 0.408 | 2 / 2 |
| notes | 0.263 | 0.579 | 0.737 | 0.417 | 2 / 2 |
| dedupe+archive | 0.263 | 0.579 | 0.737 | 0.408 | 2 / 2 |
| dedupe+archive+notes | 0.263 | 0.579 | 0.737 | 0.417 | 2 / 2 |

## heldout_confirmed_only (n=11)

| variant | recall@1 | recall@3 | recall@8 | MRR | improved / worsened vs off |
|---|---|---|---|---|---|
| off | 0.364 | 0.455 | 0.545 | 0.417 | - |
| dedupe | 0.273 | 0.545 | 0.727 | 0.405 | - |
| archive | 0.273 | 0.545 | 0.727 | 0.405 | - |
| notes | 0.273 | 0.545 | 0.727 | 0.42 | - |
| dedupe+archive | 0.273 | 0.545 | 0.727 | 0.405 | - |
| dedupe+archive+notes | 0.273 | 0.545 | 0.727 | 0.42 | - |

## Does the top score tell answerable from unanswerable? (what the gate relies on)

| variant | scenarios AUC (20 vs 9) | held-out AUC (13 vs 52) | held-out median top score: gold / KB-gap |
|---|---|---|---|
| off | 0.928 | 0.697 | 0.683 / 0.663 |
| dedupe | 0.933 | 0.722 | 0.683 / 0.663 |
| archive | 0.928 | 0.722 | 0.683 / 0.663 |
| notes | 0.933 | 0.709 | 0.683 / 0.663 |
| dedupe+archive | 0.928 | 0.722 | 0.683 / 0.663 |
| dedupe+archive+notes | 0.928 | 0.709 | 0.683 / 0.662 |

AUC 0.5 means no better than chance; 1.0 is perfect. The held-out "KB gap" labels are unverified drafts.
