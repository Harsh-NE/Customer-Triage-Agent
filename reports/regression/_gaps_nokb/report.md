# Ticket gap analysis

_Generated 2026-11-03 19:08 by `python scripts/13_ticket_gaps.py`. Method and limits are in the script's docstring._

* 13092 indexed tickets; **66 excluded as leakage** (65 held-out source tickets; 1 near-copy titles (Jaccard >= 0.7)).
* 109 error groups with at least 4 tickets, covering 879 tickets (7% of the store).
* KB check skipped (`--no-kb`).
* 0 draft cards written to `data/curated/cards.jsonl` (status `draft`; nothing is loaded into the system until a person approves).

`kb_contained` is a ranking aid: wording overlap cannot reliably tell a gap from a hit. The CSV has a VERDICT column for a person to fill.

## Biggest gap candidates

| tickets | error (normalised) | kb_contained | closest KB issue |
|---|---|---|---|
