# Baseline preparation, part 1: free fixes and new measurement tooling

Date 2026-11-13. Branch `feature/integrated` (uncommitted). Everything here is offline and free: **no LLM was called**. Python suite: **644 passed**
(592 before this work). Run with `PYTHONHASHSEED=0 HF_HUB_OFFLINE=1`. Plan: items 1-4 and 7-9 of the baseline checklist; the Gemini runs (10-14), gold v2 (6)
and the context tuning (15) come next.

## Summary

| Item | Result | Changes shipped behaviour? |
|---|---|---|
| Log-noise robustness | **Fixed.** recall@8 under pasted logs 0.654 -> 0.84 (= unperturbed) | Yes: `condense_logs` |
| Retrieval tuning (14 variants) | **No variant beats the shipped setting.** Nothing changed | No |
| Typo robustness | Partly recovered, not proven. Opt-in `TYPO_FIX=1` | No (off by default) |
| Gate calibration | Data cannot support a change. Thresholds kept | No |
| New metrics (NDCG, BLEU, ROUGE, METEOR, intervals) | Built, tested | No |
| Per-stage latency | Every graph node now logs `stage_timing` | No (logging only) |
| OCR accuracy (CER / WER) | Built; 0.5-1% CER on clean screenshots | No |

The honest headline: two real improvements (log noise, typos partly), one confirmed "do not touch" (retrieval weights), and the measurement tools a
paper needs. Retrieval quality on **real** questions is still the dominant weakness and none of the free levers moves it.

## 1. Log noise: fixed

`triage.understand.condense_logs` removes routine log lines (timestamped or levelled INFO/DEBUG/WARN) from a message when at least 6 such lines make up
half or more of it. It keeps the customer's own words and up to 8 ERROR/FATAL or error-cue lines. It is applied in `extract()` and in the Resolver
hand-off, never to the stored transcript and never to the safety guard (a security word buried in a log still triggers escalation).

`python -m triage.eval.perturb_eval --prep pipeline` (81 answerable questions, retrieval of the gold issue; the pipeline prep is `strip_chatter` +
`condense_logs` + the Resolver's 800-character query cap):

| input | recall@8 raw (old report) | recall@8 with pipeline prep | MRR with prep |
|---|---|---|---|
| original | 0.84 | 0.84 | 0.598 |
| chatter | 0.815 | 0.84 | 0.598 |
| log noise | **0.654** | **0.84** | 0.598 |
| typos | 0.778 | 0.778 | 0.548 |
| two issues | 0.79 | 0.79 | 0.538 |

The Clarifier's first decision is unchanged by the prep (leading issue right 17 of 39 on every row except two issues, 16; READY 2).
Files: `reports/regression/perturb_eval_pipeline.{md,json}`; tests `tests/test_condense_logs.py` (9).

**Caveats.** The log perturbation (1,200 characters of timestamped INFO lines) was written by us and so was the filter, so this is partly circular. It
handles `2026-03-02T10:00:01Z INFO ...`, `12:00:01 INFO ...` and `INFO: ...` lines. It does not handle other log shapes (Docker build step output, Java
stack traces, JSON logs); those pass through unchanged, which is safe but means they are not fixed. Real pasted logs from users are needed to know how
much of the real problem this covers.

## 2. Retrieval baseline and tuning sweep

`python -m triage.eval.retrieval_eval [--sweep]` (new). It scores one search on the **opening message**, issue-level, k=8, with 95% bootstrap intervals.
This is a different quantity from the end-to-end "recall@8 78.9%" in earlier reports, which comes from the full Clarifier flow (7-9 searches using
the customer's answers). A paper must say which one it reports.

Baseline (value, 95% interval):

| set | n | recall@1 | recall@3 | recall@8 | MRR | NDCG@8 |
|---|---|---|---|---|---|---|
| paraphrases (written by us) | 42 | 0.524 (0.38-0.67) | 0.786 (0.67-0.90) | 0.952 (0.88-1.00) | 0.676 (0.57-0.78) | 0.745 (0.66-0.83) |
| scenario openings (written by us) | 20 | 0.500 (0.30-0.70) | 0.650 (0.45-0.85) | 0.800 (0.60-0.95) | 0.603 (0.41-0.79) | 0.651 (0.47-0.82) |
| **gold_dev, real questions** | **15** | 0.333 (0.13-0.60) | 0.533 (0.27-0.80) | 0.600 (0.33-0.87) | 0.428 (0.21-0.64) | 0.471 (0.25-0.69) |
| pooled | 77 | 0.480 (0.38-0.60) | 0.701 (0.60-0.81) | 0.844 (0.77-0.92) | 0.609 (0.52-0.70) | 0.667 (0.59-0.75) |

The real-question row is the one that matters, and its interval is huge (n=15): recall@8 anywhere from 0.33 to 0.87. The gold_test split (4 answerable
questions) was not run.

**Sweep.** 14 variants (dense/keyword weight, RRF k, candidate pool, ontology modes, ontology entity weights), each compared with the baseline by a paired
bootstrap on the reciprocal rank. The adoption rule was fixed before the run: the interval on the pooled set must exclude zero on the positive side
and the real-question set must not get worse. **None passed** (`reports/regression/retrieval_sweep.{md,json}`). Notable:

* Keyword weight x1.5 or x2: pooled MRR +0.006 (interval -0.014 to +0.027), but recall@8 falls 0.844 -> 0.818. Not adopted.
* Dense weight x1.5 / x2, a larger pool (50), and every ontology-off or ontology-reduced variant are measurably **worse** (intervals reach zero
  from below; for "no ontology" pooled recall@8 falls 0.844 -> 0.779). The knowledge-graph layer helps on these sets, with the caveat that the
  paraphrases and scenarios were written by the same people who wrote the graph, so this favours it. On the 15 real questions it makes no difference.
* A smaller pool (20) changes ranking quality by less than the noise but halves search time (p50 ~380 ms vs ~420-620 ms). The latency columns of the
  sweep are contaminated by other jobs running at the same time; benchmark latency separately before quoting it.

Conclusion: the retrieval configuration is at a local optimum for this data. More tuning on 15 real questions would only fit noise. The remaining
levers are content (approved cards, new graph nodes) and more labelled data, not weights.

## 3. Typos

`triage/spell.py` fixes unknown words of 5+ letters to a one-edit neighbour in the knowledge base's own vocabulary (the BM25 index), and never touches a
known word, a capitalised acronym, or anything near `/ . _ - : @`. It is opt-in: `TYPO_FIX=1` or `HybridKBRetriever(typo_fix=True)`; default off.

| test | no fix | with fix |
|---|---|---|
| swapped-letter typos (the original perturbation) recall@8 / MRR | 0.778 / 0.548 | 0.84 / 0.595 |
| **independent** typos (a dropped or wrong letter), recall@8 / MRR | 0.778 / 0.550 | 0.802 / 0.587 |
| independent typos: questions better / worse | | 11 / 4; MRR difference +0.037, 95% interval -0.009 to +0.085 |
| clean text (no typos): questions the fixer altered | | 6 of 81; better 2, worse 0 |

The first row is partly circular (the fixer handles exactly the swap the test makes), so the independent test is the one to believe: a modest gain whose
interval includes zero, and no harm on clean text. Recommendation: keep it off for the baseline; evaluate it again on gold v2 (and on real typos from
users) before switching it on. Tests: `tests/test_spell.py` (12), two in `tests/test_hybrid.py`.

## 4. Gate calibration (`reports/regression/gate_calibration_v2.json`)

`calibrate_gate` replayed on the **current code**: tuned on gold-v1 dev + 29 scenarios (86 rows with a gate input), checked on gold-v1 test.

| gate | correct answers | wrong answers | coverage |
|---|---|---|---|
| current (top score 0.55, confidence 0.60) on tuning data | 20 | 3 (13% of 23 answered; 95% upper bound 32%) | 57% of 35 |
| recommended (0.55, 0.80) on tuning data | 13 | 0 (upper bound 23%) | 37% |
| both, on test | 1 | 0 | 1 of 4 |

The confidence score separates right from wrong well (AUC 0.986 on the tuning rows; 1.0 on test, but test has one right answer). Moving the confidence
threshold to 0.80 removes the 3 wrong answers at the cost of 7 correct ones. The test split has a single positive, so it cannot confirm either choice.
**The thresholds are unchanged.** These 3 wrong gate decisions are not necessarily wrong final answers: the verifier and the attempt/escalation logic
sit behind the gate. The decision should be made on gold v2 with the real-model end-to-end rows.

## 5. New measurement tooling (all tested)

| Tool | What it gives | Tests |
|---|---|---|
| `triage/eval/text_metrics.py` | Recall@K, MRR, NDCG@K; BLEU-4 (sentence, add-one smoothed), ROUGE-1/2/L, METEOR (real nltk METEOR with WordNet; the variant that ran is reported); optional embedding similarity; percentile bootstrap intervals and a paired bootstrap for "is A better than B on the same questions" | 15 |
| `triage/eval/retrieval_eval.py` | the tables above, with intervals; `--sweep` runs variants | via text_metrics |
| `triage/eval/generation_eval.py` | `sheet` writes `data/curated/reference_answers_sheet.csv` (19 answerable questions, the gold section text, an empty `reference` column); `score` computes BLEU/ROUGE/METEOR of the first fix sent against filled references; no-fix cases counted separately, not as zero | 5 |
| `triage/eval/ocr_eval.py` | character and word error rate of the screenshot reader on images with known text, plus a blur/scale degradation sweep | 4 |
| `stage_timing` events | per-node wall time (clarifier, guard, cache_lookup, retrieve, gate, draft, verify, send, ...) in the event log; `agent_metrics` reports p50/p95 per stage | 3 |

Not built: BERTScore (needs a model download; embedding cosine similarity is offered instead), a human-grading sheet for generation quality.

**OCR result** (`reports/regression/ocr_eval.md`; Tesseract; 6 clean screenshots and a 12-image degradation sweep of one screenshot): mean CER 1.2%,
key error line recovered exactly in 6 of 6; in the sweep CER stays at 0.5% until strong blur plus heavy downscaling (scale 0.4, blur 1.1: CER 38%,
engine confidence 0.40, which flags the bad read). These are clean synthetic images in one font: an upper bound for real screenshots. Real screenshots
are still needed.

## What is not done, and why

| Item | Why not | Who/what is needed |
|---|---|---|
| Review the 25 draft cards and 30 draft graph nodes | They need a person's judgement; approving them is the one lever left that adds content | you |
| Reference answers for generation metrics | A person must write them (the sheet is ready) | you or a classmate, ideally two people for agreement |
| Gold v2 (150 questions, fresh test split, second labeller, kappa) | Needs new questions and a second person | you |
| Real-Gemini re-runs and the faithfulness judge | Paid; waiting for your go-ahead (about $0.10-0.15 per full pass) | your approval |
| Pasted-log shapes other than timestamped lines; "two issues in one message" (recall@8 0.79) | No fix designed; the second needs splitting a message into issues | design first |

## Reproduce

```bash
PYTHONHASHSEED=0 HF_HUB_OFFLINE=1 python -m pytest -q
PYTHONHASHSEED=0 HF_HUB_OFFLINE=1 python -m triage.eval.perturb_eval --prep pipeline --out-json reports/regression/perturb_eval_pipeline.json --out-md reports/regression/perturb_eval_pipeline.md
PYTHONHASHSEED=0 HF_HUB_OFFLINE=1 python -m triage.eval.retrieval_eval --sweep --out-json reports/regression/retrieval_sweep.json --out-md reports/regression/retrieval_sweep.md
PYTHONHASHSEED=0 HF_HUB_OFFLINE=1 python -m triage.eval.perturb_eval --prep typofix --no-clarifier --kinds typos
python -m triage.eval.ocr_eval
python -m triage.eval.calibrate_gate --tune <dev+scenario rows.json> --test <gold test rows.json>
```
