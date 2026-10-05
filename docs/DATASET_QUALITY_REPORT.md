# Dataset Quality Report — `docker_tickets_v2.csv`

**Scope:** usability, clarity, and properness of the consolidated Docker ticket dataset produced by `notebooks/05_consolidate_docker_tickets.ipynb`.
**Method:** every finding below was measured directly against the actual file (`C:\Users\anura\Downloads\docker_tickets_v2.csv`, 14,279 rows), not estimated. Several checks that looked concerning at the regex level turned out to be false alarms on inspection — those are called out explicitly rather than reported as defects.

## 1. Overview

| | |
|---|---|
| Rows | 14,279 (71% of the 20,000 target — the shortfall already flagged when the pipeline was built) |
| Columns | 28 — includes `trust_tier`/`trust_score`/`trust_reasons`, `source_type`, `overlaps_kb`, plus derived fields (`topics`, `docker_versions`, `error_strings`, `exit_codes`) |
| Core text fields | No missing or whitespace-only `problem`/`resolution` values. No non-`http(s)` URLs. |

**By source type:**

| source_type | rows | share |
|---|---:|---:|
| stackoverflow_accepted | 6,355 | 44.5% |
| github_maintainer_resolved | 5,000 | 35.0% |
| stackexchange_accepted | 764 | 5.4% |
| forum_solved | 752 | 5.3% |
| hf_synthetic_qa | 655 | 4.6% |
| github_community_resolved | 500 | 3.5% |
| official_docs_entry | 152 | 1.1% |
| hf_qa_unspecified | 101 | 0.7% |

**By trust tier:** high 8,982 (62.9%) · medium 4,509 (31.6%) · low 788 (5.5%).

**Length:** problem median 180 words (mean 246, inflated by verbose GitHub issue bodies) · resolution median 61 words (mean 108). 452 rows have a problem over 800 words.

## 2. Real, fixable issues

| # | Issue | Rows | Share | Notes |
|---|---|---:|---:|---|
| 1 | **Leftover raw HTML** — `<img>`, `<a href>`, `<br>`, `<div>`/`<span>` pasted literally into GitHub markdown | 222 | 1.6% | An earlier, looser scan reported 749 rows, but that pattern also matched legitimate Markdown image syntax (`![alt](url)`), which isn't a defect — the corrected, HTML-only count is 222. Notebook 06 fully cleans 218 of these; the remaining 4 are cases where the HTML is real content the poster is showing (a pasted webpage's source, a Go program that prints HTML) rather than a rendering artifact, and are deliberately left untouched rather than mangling the actual example. |
| 2 | **Unbalanced / empty code fences** | 169 | 1.2% | Mostly GitHub issue templates left with an empty ` ```\n``` ` block, or a fence never closed before an `_No response_` placeholder section. All 169 are fully resolved by notebook 06 (empty pairs removed, any still-unclosed fence closed). |
| 3 | **Garbled/binary output** | 12 | 0.1% | Raw non-UTF-8 bytes from captured `stdout`/`exec` output (e.g. binary data printed by a container) rendered as `\ufffd`/control characters. Unusable as text; not worth trying to repair, only to remove. |
| 4 | **Exact-duplicate problem text from unfilled issue templates** | 393 rows in 25 groups | 2.8% | Different GitHub issues that share an identical, largely-unfilled template skeleton (e.g. `"* [x] This is a bug report... Steps to reproduce: 1. 2. 3."` with the steps never filled in). These evaded notebook 05's near-duplicate filter because that step compares `title + problem`, and differing titles diluted the similarity score below the 0.90 threshold even though the `problem` text is byte-for-byte identical. Verified directly on the file, not a heuristic. |
| 5 | **Verbose, template-heavy problem text** | 3,244 / 5,000 (65%) of `github_maintainer_resolved` | — | Issue-template scaffolding (`### Description`, `### Steps to reproduce`, checkboxes) mixed into the problem body, often alongside long `docker version`/`docker info` dumps. Legitimate structure, not corruption — but it's noisy signal for a system expecting a customer's plain-language complaint, and it's the main reason the mean problem length (246 words) is so much higher than the median (180). |

## 3. Checked and found to be non-issues

These looked like real problems from a first-pass regex scan, but manual inspection of the actual matched text showed otherwise — reported here so the false alarms aren't mistaken for defects in future audits:

- **"Repeated punctuation" (`...`) — 27.3% of problems.** On inspection this is overwhelmingly legitimate Docker CLI/log output (`Pulling...`, `Reading package lists... Done`), not writing-quality noise. Genuine `!!!`/`???`-style repeated punctuation is only 100 rows (0.7%), and even those are mostly authentic frustration ("Any help appreciated!!!") or inline code comments — low priority, arguably a useful signal rather than clutter.
- **"Doesn't end in terminal punctuation" — flagged 31.6% of resolutions.** Nearly all of these end in a code fence, a markdown list item, a filename, or a value — legitimate technical endings, not truncated sentences. This heuristic is unreliable for a technical corpus and is **not** being reported as a real defect count.
- **`>`-blockquote lines — 457 rows (3.2%).** Two different things were conflated here: GitHub's `> [!NOTE]`/`[!TIP]`/`[!IMPORTANT]` admonition callouts (10 rows, official docs — legitimate formatting) and genuine reply-quotes (451 rows). Spot-checking the reply-quotes showed they're mostly someone quoting a real command or a relevant doc excerpt for context (e.g. `> sysctl vm.max_map_count`), not email-signature-style clutter. Low severity, optional to strip.
- **`title == problem` — 903 rows (6.3%).** Concentrated entirely in FAQ/Q&A-style sources (`hf_synthetic_qa` 655, `official_docs_entry` 145, `hf_qa_unspecified` 100). This is expected for one-line FAQ entries, not a defect.
- **Negative `resolution_score` — 40 rows.** A Stack Exchange accepted answer can still be net-downvoted; this is a real platform phenomenon, already reflected in the trust-scoring rules from notebook 05.

## 4. Properness note (not a defect, but relevant to using the file)

`trust_reasons`, `topics`, `tags`, `docker_versions`, `error_strings`, and `exit_codes` are stored as JSON-array strings inside the CSV (e.g. `["base official_docs_entry"]`), because CSV has no native list type. They parse cleanly with `json.loads(...)` — confirmed directly — but a plain `pd.read_csv()` leaves them as un-parsed strings. Any code consuming this file needs that parsing step; notebook 06 (below) does it automatically.

## 5. Net assessment

**Usable as-is for most rows.** 794 rows (5.6%) have at least one of the four concrete defects above; the rest is clean or only structurally verbose. Of those 794, notebook 06 repairs the text in place for the HTML and fence cases (no rows lost) and removes 380 rows outright (12 garbled + 368 unfillable template duplicates) — a net **13,899 usable rows** out of 14,279. The verbosity in GitHub-sourced problems is the main remaining usability concern, not corruption — it dilutes the problem signal rather than making it unreadable.

**Recommended before use:** run `notebooks/06_clean_docker_tickets.ipynb` (below), which fixes issues #1–#4 above with verified, tested rules and leaves everything else untouched.
