# Paper: evidence-first support triage, evaluated on Docker support

IEEE conference format (`ieeeconf` class, two columns, US Letter), written to the guidelines in `conference_format.pdf`.
The guidelines say the LaTeX template is the only accepted format (Word is not), so this is LaTeX.

## Files

| File | What it is |
|---|---|
| `main.tex` | The paper (abstract, 7 sections, 14 references) |
| `references.bib` | BibTeX entries, all checked against the arXiv, ACL Anthology or publisher page |
| `tables/*.tex` | The three tables, generated from the run logs in `reports/ablation/final_*` (not typed by hand) |
| `figures/*.png` | Fig. 1 (pipeline) and Fig. 2 (results), grayscale-safe, both spanning two columns |

## Before you compile

1. **Get the template** (the link in the format PDF: https://bit.ly/SPSpapertemplate) and put `ieeeconf.cls` and `IEEEtran.bst` in this folder, or paste `main.tex`'s body into the template's own `main.tex`.
2. **Fill in the authors.** The title block in `main.tex` has placeholders (`Author A`, `Affiliation`). I did not have the template's author macros, so if its sample `main.tex` formats authors differently, copy its block over mine.
3. **Choose the document option.** `[cameraready]` shows authors. For a review submission use `[singleanonymous]` or `[doubleanonymous]`.
4. **Build:** `pdflatex main`, `bibtex main`, `pdflatex main`, `pdflatex main`. Overleaf does this automatically.

## What was and was not checked

* **Not compiled.** No TeX engine was available where this was written. The sources were checked statically: braces and environments balance, every `\cite` and `\ref` resolves, all 14 references are cited, no special character is unescaped, no spacing commands are used (the guidelines discourage them). A first compile may still show small warnings; send them and they are quick to fix.
* **Length.** About 3,300 words of text plus 2 full-width figures and 3 tables, so roughly 6 pages plus references in 10 pt. The page limit is set by the conference, which I do not know. To shorten: use the `9pt` class option, or cut Section 2 (Related work) to its first two paragraphs, or move the faithfulness subsection into the discussion.
* **Numbers.** Every figure in the text and tables comes from the saved run logs. Runs: `final_gold_nocache`, `final_gold_cache`, `final_29` (commit `598a894`) and `final_paraphrases` (commit `daa7b2f`, which adds only the paraphrase converter). All used the same model (gemini-3.5-flash-lite), seed 0 and 0 failed model calls.
* **One figure is from an earlier run:** the "2 false hits of 8" before the cache fix (run `gemini_29`, seed 0, uncommitted code) and the retrieval-only Recall@8 of 0.833 to 0.976 on the 42 original paraphrases (`reports/ontology_eval.md`). The text labels both as earlier runs.

## Things only you can supply

* Author names, affiliations, and an acknowledgements paragraph (camera-ready only).
* A statement of the conference's page limit and whether appendices are allowed (the guidelines say to follow the conference's own rules).
