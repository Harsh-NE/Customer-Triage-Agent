# Third-party knowledge tier (supplementary chunks)

661 chunks of community tutorials and project docs are searchable as a **separate, lower-trust tier**. They are not Docker's
documentation and are never presented as such.

## What is in it

| Source (GitHub repo) | Chunks kept | Licence | Label shown |
|---|---|---|---|
| `bobbyiliev/introduction-to-docker-ebook` | 248 | MIT | Introduction to Docker ebook (community) |
| `moby/buildkit` (`docs/`) | 176 | Apache-2.0 | BuildKit documentation (moby/buildkit) |
| `docker/labs` | 146 | Apache-2.0 | docker/labs tutorials (community) |
| `prakhar1989/docker-curriculum` | 91 | MIT | docker-curriculum tutorial (community) |

Every chunk keeps a source link pinned to a commit and its licence. **MIT and Apache-2.0 require the licence notice to travel with the
content**: replies cite it as "(community guide, MIT)" and the UI shows the licence next to the source. If these sources are ever
redistributed, include their licence texts.

Origin: a teammate chunked these four repos (706 chunks, `data/raw/supplementary/chunks_extra_raw.jsonl`, checksum in
`supplementary_report.json`). Their merged file also contained an *older* copy of the official docs that differs from ours (485 of our
chunks missing, 1,110 with different text), so **only the 706 additions were taken**; the official knowledge base is unchanged.

## What was filtered or repaired (`scripts/11_supplementary.py`)

45 of 706 dropped: 36 under 30 tokens (navigation lines, stubs), 9 front/back matter (ebook "About the book", sponsors, licence page,
PDF tooling). 67 repaired rather than dropped: 44 HTML anchors removed from headings, 23 headings that were really `# comment` lines
inside code blocks (e.g. "list of cat images") removed, with article / section / subsection rebuilt from the repaired path so the
Clarifier's issue grouping and our citations work. Every rejection is listed with its reason in `chunks_supplementary_rejected.jsonl`.

## How it is used

- **Official first.** The Resolver consults the community tier only when the best official evidence scores below the confidence gate's
  threshold (0.55). When official evidence is strong, nothing changes by construction.
- **Discounted.** Community evidence uses the same relevance formula x 0.85, so official evidence wins ties.
- **Labelled.** Source `community: <name>`, its own URL and licence, `official: false` for the UI ("Community guide"), a rule in the
  drafting prompt (prefer official evidence; avoid legacy commands such as `docker-compose` v1 or `docker-machine`), and
  "(community guide, <licence>)" in the sources line of the reply.
- **Not used by the Clarifier.** Diagnosis and questions still come from the official knowledge base only.
- **Retry-safe.** A community fix the customer rejected is excluded on the next attempt like any other.
- **Cache-safe.** Cached answers that cite these chunks are invalidated when the chunk text changes.

Switch: `SUPPLEMENTARY_KB=off` disables it; it is skipped automatically when its store has not been built.

## Rebuild

```bash
HF_HUB_OFFLINE=1 python scripts/11_supplementary.py --build-store --rebuild
```

(`HF_HUB_OFFLINE=1` makes the build use the cached embedding model instead of contacting the model hub.) The store is
`data/processed/docker/store/supplementary/`; the official store is not touched.

## Measured effect (27 Oct 2026, offline stub model)

Controlled before/after with the tier off and on, same code, `PYTHONHASHSEED=0` (see the note below), real stores:

| Set | Summary metrics | Per-scenario outcomes | Fixes citing a community guide | Community evidence appeared in |
|---|---|---|---|---|
| 29 benchmark scenarios | identical | identical (17 resolved, 8 escalated, 4 rejected) | 0 | 6 of 26 KB retrievals |
| 65 real held-out questions | identical | identical (6 resolved, 57 escalated, 2 rejected) | 0 | 38 of 65 KB retrievals |

- **No regression**, by construction (official evidence at or above the gate is never touched) and in the measurement.
- **No measured gain either, yet.** Community evidence reached the lists but never outscored the official or ticket evidence enough to be
  cited. Evidence-level check on documented questions: the number of queries with the right issue ranked first was unchanged in every set (29 of 42
  paraphrases, 13 of 20 scenario openings, 4 of 13 documented held-out questions). Of 52 held-out questions with no documented answer, the top evidence was a community guide for 1
  (score 0.40, below the 0.55 gate). The tier is safe and mostly dormant. Raising its weight is a threshold decision that needs labelled data
  (is the community guide actually right?), not a change to make blind.
- Why not simply rank it as a peer? An in-memory trial (ontology off, plain rank fusion) lowered paraphrase recall@8 from 0.81 to 0.79 and
  recall@3 on documented real questions from 0.77 to 0.69, and surfaced front-matter chunks ("About the author") for unrelated questions.

**Measurement note.** Single end-to-end runs are noisy across processes: Python randomises string hashing per process, which changes
tie-breaking in the Clarifier (16 of 29 scenarios and 17 of 65 held-out questions differed between two identical-code runs; one real
question flipped between resolved and escalated). Compare configurations with the same `PYTHONHASHSEED` (for example `PYTHONHASHSEED=0`).
