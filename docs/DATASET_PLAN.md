# Datasets: what we have, what is missing, how to get and use more

Everything here was measured on the files in this repository on 2026-11-03. The tools named below exist and are tested; the data collection
steps marked **you** cannot be done by code.

## 1. What each asset is, and its limits

| Asset | What it is | Main limits |
|---|---|---|
| Knowledge base | 11,440 chunks of the official Docker docs, 961 pages | Only 283 chunks (2.5%) are troubleshooting or FAQ (233 issues, 25 pages). 26% is release notes and archive. 18% of chunks are under 200 characters, 3% are exact duplicates. No platform or version metadata. CLI reference pages are not in it |
| Tickets | 13,092 indexed community Q&A (49% Stack Overflow, 35% GitHub maintainer replies) | Developer Q&A, not support tickets. Median age 5.5 years, 22% over 8 years. 7% carry an exit code, 25% a version. 55% CC BY-SA, 39% GitHub user content with no clear licence. An accepted answer is not a verified fix |
| Knowledge graph | 153 hand-written entities, 55 issue nodes | Links 51 of 137 troubleshooting issues and none of 96 FAQ entries (22% of 233). Sparse relations. No measurable gain on the real held-out questions |
| Test data | gold v1: 89 questions (19 answerable, 46 KB-gap, 8 vague, 6 urgent, 6 out of scope, 4 injection) | Real questions are 65 Stack Overflow posts that were looked at while diagnosing, so the test split is **not** untouched. Labels were reviewed by a model, not a second person. Target is about 150 |

## 2. Where real test data can come from

Docker's own support tickets are private. Candidate sources, best first:

1. **Your own users** (you). 10 to 20 classmates or friends use the app on real Docker problems. This is the only source of real screenshots and
   multi-turn conversations, and it is untouched. Get their agreement first and tell them what the data is for.
   Then `python scripts/14_export_for_labelling.py --i-have-consent` writes masked candidates and a blank labelling sheet.
2. **Stack Overflow, recent questions** (you; a download, so it needs your decision). Questions from the last two years in the `docker`,
   `docker-compose` and `dockerfile` tags (the Stack Exchange data dump, or the site's own export). CC BY-SA 4.0: keep the URL and licence with each
   question. Split by date from the ticket store so nothing leaks, and `scripts/13_ticket_gaps.py` shows how near-duplicates are excluded.
3. **GitHub issues** of `docker/for-win`, `for-mac`, `for-linux`, `compose`, `buildx`, `hub-feedback`. Closest to Docker Desktop problems.
   GitHub user content: cite by URL, use for evaluation.
4. **Lab-made errors** (you). Break Docker on purpose in the common ways and screenshot the result (dark and light theme, Windows and Mac fonts).
   `scripts/make_test_screenshots.py` shows the format of the existing 10 generated images.
5. **LLM-written customers** from each KB issue, for paraphrase variety. Label by construction, but the same-model bias is real: human-check 10 to 20%.

Not usable: private Slack/Discord, anything scraped against a site's terms, real user data without consent. This is not legal advice: check each
source's terms and licence yourself.

## 3. Labelling a question

For every question write down: (1) the class (`answerable`, `kb_gap`, `vague`, `urgent`, `out_of_scope`, `injection`), (2) for `answerable` the KB section that
fixes it (`confirmed` if it documents this exact problem, `weak` if it is on topic but implicit or only half the answer), (3) nothing else: the system's
output must not influence the label. Two people label a sample independently:

```bash
python -m triage.eval.gold_v1 sheet sheet_a.csv      # blank sheet, the current label is not shown
python -m triage.eval.gold_v1 agreement sheet_a.csv sheet_b.csv      # Cohen's kappa; disagreements are listed
```

Aim for kappa of about 0.7 or more on a 40-question overlap before trusting the labels. About 100 questions are needed for a ±10 point interval
on a rate near 50%; with 13 one query moves a rate by 8 points.

## 4. Using the data, step by step (each step has a measurement)

| Step | Tool | Result so far |
|---|---|---|
| Freeze the gold set; score every change per class | `python -m triage.eval.gold_v1 build / validate / score` | baseline per class in `reports/DATA_IMPROVEMENT_REPORT.md` (terminal action 80.9%, gold first fix 4/19) |
| Clean the KB cheaply (opt-in) | `KB_FILTERS=dedupe,archive,notes`; `python -m triage.eval.kb_filter_eval` | no reliable gain; left off |
| Find what real tickets hit that the KB does not document | `python scripts/13_ticket_gaps.py` -> `data/curated/ticket_gap_clusters.csv`, draft `cards.jsonl` | 37 gap candidates, 25 draft cards to review |
| Drop stale ticket advice (opt-in) | `TICKET_LEGACY_PENALTY=0.5`; `python -m triage.eval.ticket_freshness_eval` | top-1 changed for 2 of 136; left off |
| Grow the knowledge graph | `python scripts/15_kg_candidates.py` | coverage 22%; 30 draft nodes in `data/curated/ontology_candidates.yaml` |
| Stress test messy input | `python -m triage.eval.perturb_eval` | log noise hurts retrieval most; chatter fixed by `strip_chatter` |
| Real traffic into the test set | `python scripts/14_export_for_labelling.py --i-have-consent` | needs your users |

Cards: `data/curated/cards.jsonl` holds DRAFTS built from tickets (extractive, with source URL and licence). A person must rewrite or approve each one
(`status: approved`, `reviewer: <name>`). Nothing loads cards yet: the approved ones would be added as chunks to the community-guide store
(`scripts/11_supplementary.py`), which is a re-embedding job you run.
