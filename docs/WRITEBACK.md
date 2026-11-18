# Write-back: new resolved cases join the historical dataset

Code: [triage/writeback.py](../triage/writeback.py) (what to keep, is it safe) and [triage/ticket_ingest.py](../triage/ticket_ingest.py) (put it in the store).
Tests: `tests/test_writeback.py`, `tests/test_ticket_ingest.py`, and the write-back tests at the end of `tests/test_api.py`.

## What it does

```
customer says "that worked"  ─┐
                              ├─> candidate ─> checks ─> queue ─> daily ingest ─> historical ticket dataset
engineer resolves + "promote" ─┘                          (writeback.db)
```

| Source | Kind | Trust | Approval |
|---|---|---|---|
| The customer confirms a fix | `customer_confirmed` | medium (0.6), rank weight 0.9 | automatic, if the checks pass |
| An engineer closes an escalated case and ticks "promote" | `engineer_resolved` | high (0.8), rank weight 1.0 | the engineer's tick |

The semantic cache is separate and unchanged: it reuses a ready answer for a repeat of the same problem (fast). The dataset gives evidence for
similar but different future problems (better). A fix served from the cache is not written back again.

## Switches

| Setting | Default | Meaning |
|---|---|---|
| `TICKET_WRITEBACK=1` | off | record resolved cases at all. **Leave it off while evaluating** |
| `WRITEBACK_REVIEW=all` | off | hold every candidate until `python -m triage.writeback approve ID` |

## Checks (a failed check rejects the candidate and records why)

Title, problem and fix long enough to mean something; personal data and secrets masked; no prompt-injection or secret-request wording;
not an evaluation question (scenarios, held-out, gold v1, paraphrases); not already queued. At ingest time: not a near-duplicate
(cosine similarity about 0.97) of an existing ticket or of another candidate in the same batch.

## Running it

```bash
python -m triage.writeback status                 # how many are waiting, approved, rejected, ingested
python -m triage.writeback list rejected          # what was refused, and why
python -m triage.ticket_ingest ingest --dry-run   # what would be added
python -m triage.ticket_ingest ingest --due       # add them if 25 are approved or the oldest has waited 24 h (schedule this daily)
python -m triage.ticket_ingest purge --yes        # remove everything written back: the original dataset again
```

Each ingest embeds the new tickets, adds them to Chroma and SQLite, rebuilds the keyword index (it cannot be appended to; the old one is kept as
`bm25_index.pkl.prev`), then writes the manifest with a new version number. A running retriever reloads on its own when the manifest changes.
Every step can be repeated, so a crash half way is fixed by running it again. A lock file stops two runs from overlapping.

## For evaluation

* Keep `TICKET_WRITEBACK` off while measuring, and run `purge --yes` to get back to dataset version 0 (the baseline).
* Report the dataset version (`python -m triage.ticket_ingest status`) with every result.
* The learning-effect experiment: ingest a batch, then re-measure. Test questions can never be ingested (the evaluation-question check).

## Measured on a copy of the real store (13,092 tickets, real embedding model)

Two good candidates ingested in 8 s including the keyword-index rebuild. A candidate that copied a test question, one with an injection, and a
near-duplicate of a real ticket were all rejected. Of 42 queries, only the 2 aimed at the new tickets changed their top 5 (both now include a
written-back ticket, not necessarily first); no other query changed. After `purge`, results were identical to before.

## Limits

* A customer who says "resolved" about a wrong fix would add a wrong ticket. The lower trust weight and the near-duplicate check limit the harm;
  `WRITEBACK_REVIEW=all` removes the risk at the cost of manual review.
* Written-back customer-confirmed fixes are often rewordings of what the documentation already says; their value is mapping real customer wording to
  the fix. Engineer-resolved fixes on documentation gaps are the most valuable part.
* Nothing here has been evaluated for effect on answer quality yet; that is the learning-effect experiment.
