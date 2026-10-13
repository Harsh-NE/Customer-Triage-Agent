# Ontology ablation: does it help retrieval find the documented issue?

_Generated 2026-10-12 10:12 by `python -m triage.eval.ontology_eval`. Real KB, hybrid retriever, rank = position of the first correct issue among the issues returned (8 chunks plus siblings). Queries and ontology share an author: gains are an upper bound._

## paraphrases (n=42)

| mode | recall@1 | recall@3 | recall@8 | MRR |
|---|---|---|---|---|
| off | 0.524 | 0.714 | 0.833 | 0.631 |
| expand | 0.5 | 0.738 | 0.905 | 0.634 |
| entities | 0.524 | 0.738 | 0.929 | 0.655 |
| both | 0.5 | 0.786 | 0.976 | 0.663 |

`expand` vs `off`: improved 4, worsened 4. Improved: P11 (None->6), P32 (None->5), P33 (None->2), P34 (None->7) Worsened: P12 (4->5), P23 (6->None), P30 (2->3), P42 (1->2)

`entities` vs `off`: improved 6, worsened 0. Improved: P01 (3->2), P10 (None->8), P23 (6->4), P32 (None->3), P34 (None->6), P37 (None->8)

`both` vs `off`: improved 9, worsened 3. Improved: P01 (3->2), P10 (None->8), P11 (None->3), P23 (6->4), P30 (2->1), P32 (None->3), P33 (None->2), P34 (None->4), P37 (None->8) Worsened: P09 (1->2), P12 (4->5), P42 (1->2)

## scenario_openings (n=20)

| mode | recall@1 | recall@3 | recall@8 | MRR |
|---|---|---|---|---|
| off | 0.5 | 0.65 | 0.75 | 0.592 |
| expand | 0.5 | 0.65 | 0.75 | 0.593 |
| entities | 0.5 | 0.65 | 0.8 | 0.6 |
| both | 0.5 | 0.65 | 0.8 | 0.603 |

`expand` vs `off`: improved 1, worsened 0. Improved: S03 (6->5)

`entities` vs `off`: improved 2, worsened 0. Improved: S02 (6->5), S17 (None->7)

`both` vs `off`: improved 3, worsened 0. Improved: S02 (6->5), S03 (6->5), S17 (None->6)

