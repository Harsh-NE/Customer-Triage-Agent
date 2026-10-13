# Docker ontology (lightweight knowledge graph on top of RAG)

**Status: built and tested on branch `feature/docker-ontology`, not yet merged.** 22 offline tests in `tests/test_ontology.py`
(303 in the whole suite). Retrieval and Clarifier results below are measured; the Resolver "background" prompt is **not**
measured with a real LLM and is off by default.

## What it is, and what it is not

A small, human-edited graph of what Docker *is*: products, components, features, tools, platforms, concepts, use cases,
error strings and the common issues customers hit, with aliases ("compose v2", "docker for mac", "dockerd"), parent/related
links, platform limits ("WSL 2 means Windows") and links from each known issue to the KB section that documents it.

It is a **domain pack**: one YAML file (`triage/ontology/docker.yaml`), reviewed in git like code. It is not a graph database,
not auto-extracted, and not a source of facts for answers. The KB and the ticket store stay the only evidence. A node's
`summary` is a definition of a name, never a fix.

Why it helps: vector search alone misses queries worded differently from the docs ("docker for mac slow files", "toomanyrequests").
The ontology resolves aliases to one canonical name, knows which documented issue a symptom points at, and knows
what platform a name implies.

## What is in the pack

153 entities: 24 concept, 18 product, 10 component, 23 feature, 7 tool, 4 platform, 7 use_case, 5 error, 55 issue; about 500 aliases.
Provenance is recorded per node: `kb` (120, from the docs), `tickets` (21, from community questions), `general` (12, author knowledge,
needs review). 50 issues link to a KB section by path fragment plus title prefix; all 50 resolve against the 11,440 chunks.
5 issues are real and common but **not documented** in the KB (`kb: []`): exec format error, docker socket permission denied,
no space left on device, pull access denied, `docker-compose` command not found.

Node fields: `id`, `type`, `name`, `summary`, `aliases`, `scoped` (alias counted only when context words are also present),
`parent`, `related`, `available_on` (platform limit), `kb_area`, `confused_with` (+ how they differ), `generic` (too common to
be a signal: "image", "container"), `symptoms` / `errors` (issues), `affects`, `kb` (links), `provenance`.

## How it is used

| Where | What the ontology does | Off switch |
|---|---|---|
| Retrieval (`triage/hybrid.py`) | Adds canonical names/aliases to the BM25 query (`expand`); adds two ranked lists to the rank fusion: chunks sharing the query's *specific* entities (weight 0.5) and chunks of a confidently matched known issue (weight 2.0). Returned scores stay vector similarity, so Clarifier thresholds are unchanged. | `ONTOLOGY_MODE=off\|expand\|entities\|both` (default `both`) |
| Clarifier (`triage/clarifier.py`) | Fills a *missing* platform/product the wording implies ("wsl 2", "hyperkit"). Never overrides anything the customer said. Puts the recognised entities on the signature. | `ONTOLOGY_MODE=off`, or `Clarifier(..., ontology=False)` |
| Resolver evidence (`triage/resolver/adapters.py`) | A KB section limited to another platform than the customer's ("Topics for Windows" for a Mac user) is demoted (x0.6) and marked in the evidence metadata. Unknown platform: marked, not demoted. | follows the retriever's ontology |
| Resolver draft (`triage/resolver/steps.py`) | Optionally prepends one-line definitions of the names in the problem, labelled "NOT evidence". The verifier is unchanged and still drops any command or URL not in the cited evidence. | **off** unless `ONTOLOGY_BACKGROUND=1` |
| Tickets (`TicketRetriever`) | Alias terms in the BM25 query. | **off** unless `use_ontology=True` (no labelled ticket set to justify it) |
| Engineer console | "Recognised in the request" badges on the case page. | n/a |

Matching is one compiled alternation regex over normalised aliases (hyphen/underscore to space, word boundaries, longest first).
Issue matching scores the idf-weighted share of a symptom phrase's content words present in the text, or 1.0 for a verbatim error
string. The index of entities per KB chunk is built at start-up from the stored documents (about a second): no re-embedding and
no change to the stores.

## Results (real KB, hybrid retriever; read the caveat first)

**Caveat.** The ontology, the 42 paraphrase queries and the scenarios were all written by the same author, and the fusion weights were
adjusted while looking at this same eval set. Treat the gains as an upper bound. The scenario openings were not used for tuning
beyond avoiding regressions on them.

Retrieval, rank of the first correct issue (`python -m triage.eval.ontology_eval`, `reports/ontology_eval.md`):

| set | mode | recall@1 | recall@3 | recall@8 | MRR |
|---|---|---|---|---|---|
| paraphrases (n=42) | off | 0.524 | 0.714 | 0.833 | 0.631 |
| | both | 0.500 | 0.786 | 0.976 | 0.663 |
| scenario openings (n=20) | off | 0.50 | 0.65 | 0.75 | 0.592 |
| | both | 0.50 | 0.65 | 0.80 | 0.603 |

On paraphrases `both` improved 9 queries and worsened 3 (P09, P12, P42, each by one rank); recall@1 is slightly lower. The gain is
mainly in not missing the right issue, not in ranking it first.

Clarifier offline evaluation (`python -m triage.eval.clarifier_eval`, scratch runs): gold issue first 0.85 to 0.90, questions per ticket
1.52 to 1.45, ready precision 1.0, wrong-ready 0 in both.

End to end, FakeLLM, rule-based customer, oracle that credits only the documented fix (`python -m triage.eval.e2e_eval`, 29 scenarios, 20 with a gold fix):

| | ontology off | ontology on |
|---|---|---|
| gold fix on first attempt | 16/20 (0.80) | 18/20 (0.90) |
| wrong fix sent (gold scenarios) | 0 | 0 |
| out-of-scope answered | 0/6 | 0/6 |
| mean questions | 1.45 | 1.38 |

Because the Resolver uses a FakeLLM here, this measures reaching the documented fix, not answer wording.

## Maintaining it

```bash
python -m triage.ontology check              # validate; resolve every KB link against the chunks; coverage on KB and tickets
python -m triage.ontology link "docker for mac is slow"   # what the ontology sees in a piece of text
python -m triage.eval.ontology_eval          # retrieval ablation; rerun after editing the pack
```

To add a node, append to `docker.yaml`, set `provenance`, run `check`. An alias claimed by two nodes, an unknown reference, an
unknown platform or an issue without symptoms/errors fails validation. For an issue the KB documents, give `kb:` a path fragment and
the heading as the KB writes it; `check` fails if it matches no chunk (so a docs update that renames a heading is caught).

## Known limitations

- Same-author evaluation (above); no held-out queries from real customers yet.
- Entity matching is exact on node ids: a query that resolves to a child ("docker for windows") does not get credit for chunks tagged
  only with the parent ("docker desktop"). Walking up the hierarchy in `EntityIndex.rank` is a likely improvement, not done because
  it would invalidate the measured weights.
- The background prompt and the ticket-side expansion are implemented but unmeasured, hence off.
- 12 `general` nodes and the 5 undocumented issues need review by someone who knows Docker support.
- Aliases are English only; the pack covers what the KB and the 13,092 indexed tickets cover.
