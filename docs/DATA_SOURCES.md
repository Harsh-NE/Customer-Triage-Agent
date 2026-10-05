# Data Sources — Curated Knowledge Base & Historical Ticket Corpus

**Status:** Sourcing plan for Milestones M1–M3 (dataset foundation → historical ingestion → Tier 1 KB).
**Scope of this document:** *where the data comes from*, under what licence, in what shape, and why it fits. No ingestion code, no schemas — those follow once sources are approved.
**Last verified:** 2026-08-28 (sections 1–9, the Microsoft-era plan). Section 0 below was added 2026-10-05.

---

## 0. Status update (2026-10-05) — the project moved to Docker

Sections 1–9 are the **original Microsoft-era sourcing plan, kept as history**. On 2026-09-24 the target application
changed to **Docker**, so the "recommended Option A" below is **no longer what the system uses**. The principles (Tier 1 vs
Tier 2 quality bars, PII stripping, attribution, "don't commit raw corpora") still apply. What is actually in use:

### 0.1 Tier 1 — curated knowledge base (in use)

| Source | Licence | Status |
|---|---|---|
| **`docker/docs`** (GitHub, shallow clone) | Apache License 2.0 — the repo `LICENSE`, read 2026-10-05 | **Used.** 1,434 Markdown files → 961 kept → 10,031 chunks. Excluded: `_vendor/` (vendored third-party docs), `layouts/`, `content/includes/`, files under 20 words. Every chunk carries `source_url` and `license` |

Attribution: Apache-2.0 requires retaining the licence and notices when redistributing; the chunk-level `source_url` covers
citation. The licence applies to the repository as a whole; vendored content under `_vendor/` and fonts under `static/`
carry their own terms and are **not** ingested. Docker's trademarks are not licensed by Apache-2.0.

### 0.2 Tier 2 — historical resolved tickets (dataset built, **not yet used by any code**)

Collected by `notebooks/02–05` (Colab), consolidated to `docker_tickets_v5_fixed.csv` — 13,899 rows, each with a `license`
and `url` column. Per-source terms as far as they were checked:

| Source | Rows (v5) | Terms | Verified? |
|---|---:|---|---|
| Stack Overflow, accepted answers | 6,352 | CC BY-SA 4.0 (Stack Exchange network content) | standard network licence, **not re-checked per post** |
| Stack Exchange: serverfault, superuser, askubuntu, unix, devops | 763 | CC BY-SA 4.0 | as above |
| GitHub issues (`moby/moby`, `docker/for-win`, `compose`, `for-mac`, `hub-feedback`, `buildx`, `cli`, `for-linux`): maintainer-resolved / community-resolved | 4,593 / 499 | Issue text is user content under GitHub's terms; cite by URL | **not reviewed in detail** |
| Docker community forum (Discourse JSON): solved / inferred-resolved | 752 / 32 | **Forum content terms were not reviewed** | **no** |
| Official docs FAQ entries (`docker/docs`) | 152 | Apache-2.0 (as §0.1) | yes; flagged `overlaps_kb` |
| Hugging Face `pavanmantha/devops-v1` and `sequelbox/Titanium` | 756 (101 `hf_qa_unspecified` + 655 `hf_synthetic_qa`; which dataset produced which was not re-derived here) | both dataset cards state `apache-2.0` (read via the Hub API 2026-10-05). `Titanium` is LLM-generated, so synthetic rows are flagged `is_synthetic` and sit at the lowest trust | card only; provenance of the underlying generated text was not audited |

Collector settings (from the notebooks): Stack Exchange 2014 onward, question score ≥ 2, problem-shaped questions only; GitHub
repos capped per repo; forum categories `docker-desktop`, `docker-engine`, `docker-hub`, `general-discussions`,
`image-builds`, `support`. An optional Reddit collector exists, is off by default, and was never run.

**Treat the mixed CC BY-SA content as a share-alike obligation** if any Tier 2 text is ever promoted into a curated KB article
or redistributed — keep it attributed and separate, as §5 and §7 below already advise. Raw ticket text must not be committed.

### 0.3 Considered and not used

* **Book extraction** (using Docker books as KB content or to synthesise tickets) was discussed and deliberately **not done**:
  most Docker books are commercially licensed, and synthesising tickets from them would also stack synthetic data on synthetic data.
* **Version/release-notes feeds, a live incident/status feed, and sentiment-based inference of unmarked resolutions** were
  brainstormed only. Note that `docker/docs` already contains release notes and archived-version pages (~25% of the chunks).
* The Kaggle `suraj520` ticket dataset stays rejected (§6) — it is domain-wrong and synthetic.

---

## 1. What the pipeline needs

The architecture defines two distinct knowledge tiers plus supporting data. They have **different quality bars and must not be sourced from the same place**.

| Need | Role in system | Quality bar | What it must contain |
|---|---|---|---|
| **Tier 1 — Curated KB** | Authoritative first-hit source for routine issues | High. Trusted, verified, citable | SOPs, troubleshooting guides, product docs, known-issue articles. Structure: *symptom → cause → steps → verification*. Exact error codes preserved |
| **Tier 2 — Historical resolved tickets** | Fallback for non-standard / edge-case problems | Medium. Real, messy, but genuinely *resolved* | A real reported problem + a real accepted resolution, with metadata and a raw-case pointer |
| **Metadata / taxonomy source** | Category, severity, priority, resolution-type vocabularies | Structural only | Realistic ITSM field values, priority distributions, escalation/reassignment behaviour |
| **Evaluation set** | Retrieval + classification measurement (M5) | Labelled | 20–50 test queries with manually identified relevant docs/tickets; plus a labelled classification set |

**Non-negotiable for Tier 2:** a "ticket" without a real resolution is not a historical resolved ticket. It is a prompt without an answer, and it cannot back an evidence-first system. This rules out several popular datasets — see §6.

---

## 2. Domain scoping decision

The blueprint (§14) says to *"select a small initial product/category scope rather than trying to cover everything."* Two coherent options:

### Option A — Microsoft 365 / Windows / Azure endpoint & productivity support ✅ **Recommended**

The project's problem statement is a generic enterprise IT/productivity-support triage
scenario, and the blueprint's worked example is file-sync troubleshooting (e.g. OneDrive-
style sync errors). Choosing this domain gives an unusually strong alignment:

- Tier 1 is **exceptional** — Microsoft publishes tens of thousands of *dedicated troubleshooting articles* (not just reference docs) under CC-BY-4.0, already in the symptom→cause→resolution shape, dense with real error codes (`0x80070005`, `Event ID 4105`).
- Tier 2 is **real and abundant** — Microsoft Community forum dialogs (MSDialog), Super User / ServerFault Q&A on Microsoft products, and closed GitHub issues on Microsoft's own OSS products.
- Tier 1 and Tier 2 talk about **the same products**, so cross-tier evidence and the promote-to-KB loop actually make sense.
- The demo story writes itself when the KB and the target support domain are drawn from the same ecosystem.

### Option B — Cloud-native / DevOps platform support (Kubernetes + GitLab + PostgreSQL)

Viable fallback if Microsoft docs prove too large to scope. Also fully open-licensed (CC BY 4.0 / CC BY-SA 4.0), with Stack Exchange and GitHub issues as Tier 2. Weaker on dedicated *troubleshooting-article* structure — more reference docs, fewer SOPs.

> **Recommendation:** commit to Option A, narrowed further for v0.1 to **3–4 product areas** (suggested: OneDrive sync, Outlook/Exchange mail flow, Teams sign-in/meeting, Windows client authentication & update). Keep the pipeline domain-agnostic so Option B can be added as a second corpus later.

---

## 3. Selection criteria applied

Every source below was judged on:

1. **Licence** — redistributable, or at minimum usable for a non-commercial academic project with attribution.
2. **Evidence-bearing** — contains a real resolution, not just a complaint.
3. **Structure** — parseable hierarchy (headings, steps) that survives structure-aware chunking.
4. **Technical signal density** — error codes, component names, versions (needed for the sparse/BM25 half of hybrid retrieval).
5. **Metadata availability** — product, component, category, severity, timestamps.
6. **Acquisition cost** — bulk clone/dump preferred over per-page scraping; scraping only where a site's terms permit it.

**Verification legend:** ✅ = repo/dataset page and licence checked this session · ◐ = known source, confirm licence and current availability before ingesting.

---

## 4. Tier 1 — Curated Knowledge Base sources

### 4.1 Primary (Option A)

| # | Source | Type | Licence | Why it fits |
|---|---|---|---|---|
| T1-1 | **MicrosoftDocs/SupportArticles-docs** ✅ | GitHub repo, Markdown | CC-BY-4.0 (content) + MIT (code) | **The single best Tier 1 source for this project.** Purpose-built troubleshooting/support articles |
| T1-2 | **MicrosoftDocs/microsoft-365-docs** ✅ | GitHub repo, Markdown | CC-BY-4.0 | M365 admin/service docs — configuration context behind the symptoms |
| T1-3 | **MicrosoftDocs/azure-docs** ◐ | GitHub repo, Markdown | CC-BY-4.0 | Huge; use only the `articles/<service>/troubleshoot*` subsets |
| T1-4 | **MicrosoftDocs/windowsserverdocs** ✅ | GitHub repo, Markdown | CC-BY-4.0 | Windows Server / RDS / AD troubleshooting |
| T1-5 | **MicrosoftDocs/entra-docs**, **sql-docs**, **memdocs** (Intune) ◐ | GitHub repos, Markdown | CC-BY-4.0 | Identity, database and device-management troubleshooting — add only if scope expands |

**T1-1 detail — MicrosoftDocs/SupportArticles-docs**

- URL: <https://github.com/MicrosoftDocs/SupportArticles-docs>
- Content: the public mirror of Microsoft's support-article corpus. Top-level areas confirmed present include Exchange, Microsoft365, Office, Outlook, SharePoint, SkypeForBusiness, Teams, Viva, plus a large `support/` tree (`windows-server/`, `mem/configmgr/`, `azure/`, `sql/`, …).
- Shape per article: YAML front-matter (`title`, `description`, `ms.date`, `ms.reviewer`, `ms.custom`, product/technology tags) followed by **Symptoms → Cause → Resolution → More information** headings. This maps almost 1:1 onto the blueprint's chunking hierarchy (§6.1) and metadata list (§6.3) — front-matter gives product/component/recency for free.
- Signal density: high. Articles are titled and bodied around exact error codes and event IDs.
- Acquisition: shallow `git clone`, then filter by path prefix to the 3–4 chosen product areas.
- Caveat: some articles are stubs or redirects; a few contain `[!INCLUDE]` transclusions that must be resolved during parsing.

### 4.2 Cross-domain candidates (Option B, or corpus diversity)

| # | Source | Licence | Notes |
|---|---|---|---|
| T1-6 | **kubernetes/website** ✅ — <https://github.com/kubernetes/website> | CC BY 4.0 (CNCF charter) | `content/en/docs/tasks/debug/` is genuinely troubleshooting-shaped |
| T1-7 | **GitLab docs** ✅ — `doc/` in <https://gitlab.com/gitlab-org/gitlab> | CC BY-SA 4.0 (content under `doc/`) | Large `administration/troubleshooting/` tree; enterprise-app flavour |
| T1-8 | **Mozilla SUMO KB** ✅ — <https://support.mozilla.org> | CC BY-SA | Consumer-support voice; the Kitsune platform exposes a **public API** for article export, so no HTML scraping needed |
| T1-9 | **PostgreSQL / Nextcloud / Odoo docs** ◐ | PostgreSQL licence / varies | Only if a second domain is added; verify each licence individually |

> **Attribution obligation:** CC-BY and CC-BY-SA both require visible attribution. Every KB chunk must carry `source_url` + `source_title` + `licence` in its metadata — which the design already requires for citations anyway, so this costs nothing extra. CC-BY-**SA** (GitLab, Mozilla, Stack Exchange) additionally imposes share-alike on *derived* content: keep those chunks attributed, and do not fold them into a promoted KB article that is later relicensed.

---

## 5. Tier 2 — Historical resolved ticket sources

Ranked by how closely each approximates a real enterprise support ticket with a real resolution.

| # | Source | Volume | Real resolutions? | Licence | Verdict |
|---|---|---|---|---|---|
| T2-1 | **MSDialog** ✅ | ~35.5k dialogs, 76 Microsoft product categories | Yes — forum answers, with intent annotations on a labelled subset | Research use; check terms on the download page | **Primary Tier 2 choice for Option A** |
| T2-2 | **Closed GitHub issues from Microsoft OSS** ✅ (`microsoft/vscode`, `microsoft/WSL`, `microsoft/PowerToys`, `microsoft/terminal`, `dotnet/runtime`) | 10k–200k+ closed issues per repo | Yes — maintainer diagnosis + fix/workaround, often with linked commit | Repo licence covers code; issue text is user content under GitHub ToS. Fine for academic use, attribute by URL | **Strong secondary.** Best "difficult ticket" analogue available |
| T2-3 | **Stack Exchange data dump** ✅ — Super User, Server Fault, Ask Ubuntu | Millions; filter by Microsoft tags | Yes — accepted answers with vote signal | CC BY-SA 4.0, **with a caveat (below)** | **Strong, but read the caveat** |
| T2-4 | **UCI Incident Management Process Enriched Event Log** ✅ | 24,918 incidents / 141,712 events, 36 attributes, ServiceNow audit data, Mar 2016–Feb 2017 | No free-text resolution — **metadata only** | UCI ML Repository terms | **Use for metadata/priority/escalation realism, not retrieval** |
| T2-5 | **Tobi-Bueck/customer-support-tickets** ✅ (HF + Kaggle) | Balanced multilingual helpdesk tickets | Yes — includes an agent-answer field | **CC BY-NC 4.0** (non-commercial) | Usable for an academic project; flag the NC restriction |
| T2-6 | **Bitext customer-support LLM training dataset** ✅ | ~27k intent-tagged pairs | Synthetic but coherent Q/A | CDLA-Sharing-1.0 | Useful for intent/normalisation experiments, weak as evidence |
| T2-7 | **NLBSE tool-competition issue datasets** ✅ | 800k (’22) / 1.4M (’23) / 3k (’24) labelled issue reports | Labels only (bug/enhancement/question/doc) | Open, per competition repo | **Best off-the-shelf labelled set for classification evaluation** |
| T2-8 | **Customer Support on Twitter** (Kaggle, `thoughtvector`) ◐ | 3M+ tweets | Rarely — mostly "DM us" deflections | Verify on dataset page | Low value for resolution retrieval; possible tone/summarisation data only |
| T2-9 | **Ubuntu Dialogue Corpus** ◐ | ~1M dialogues | Partially — IRC technical help | Open | Only if a Linux/OSS domain is added |

**T2-1 detail — MSDialog**

- Download: <https://ciir.cs.umass.edu/downloads/NeuralResponseRanking> (UMass CIIR). Crawled from Microsoft Community.
- Two versions: `MSDialog-Complete` (~35.5k dialogs) and `MSDialog-Intent` (~2k+ conversations / ~10k utterances, crowd-annotated with user intent at the utterance level).
- Why it is the right Tier 2: it is *literally* multi-turn technical support on Microsoft products (Windows, Office, Skype, Surface, Xbox, IE) — the same domain as Tier 1, carrying exactly the conversational noise that the blueprint's pre-summarisation stage (§6.2) exists to strip. The intent annotations are a bonus for the Understanding stage.
- Caveat: forum answers are community-provided, not vendor-verified. That is *correct* for Tier 2 — it is precisely why the design ranks curated KB above historical tickets and requires human review before promotion.

**T2-3 caveat — Stack Exchange licensing**

The dumps are CC BY-SA 4.0, but Stack Exchange has tightened distribution: recent dumps sit behind an agreement covering personal use and **excluding LLM training**. This project uses the data for *retrieval and citation*, not model training — a defensible reading, but not a settled one. Recommendation: use the Internet Archive dump (<https://archive.org/details/stackexchange>) for Super User / Server Fault, document the intended use in the repo, keep per-post attribution as CC BY-SA requires, and treat it as a secondary source so the project is not blocked if it must be dropped.

---

## 6. Rejected / use-with-care — including the dataset named in the problem statement

### ⚠️ Kaggle "Customer Support Ticket Dataset" (`suraj520`) — **not usable as Tier 2**

This is the dataset the problem statement suggests. I inspected the copy in `Downloads/customer_support_tickets.csv.zip` (8,469 rows, 17 columns) and it is **synthetic filler, not support data**:

- **Descriptions contain unrendered template placeholders.** Row 1 verbatim: `"I'm having an issue with the {product_purchased}. Please assist."` — the substitution never ran.
- **Resolutions are randomly generated word salad.** Actual values: `"Case maybe show recently my computer follow."` · `"Try capital clearly never color toward story."` · `"West decision evidence bit."` Only 2,769 of 8,469 rows have a resolution at all, and none of them are real.
- **Labels appear randomly assigned.** Priority splits almost exactly evenly (Medium 2192, Critical 2129, High 2085, Low 2063); channel splits 4 ways evenly; ticket type 5 ways evenly. There is no learnable signal — a classifier on this cannot beat chance, and any accuracy reported from it would be meaningless.
- **Wrong domain.** Products are consumer electronics (Canon EOS, GoPro Hero, Nest Thermostat, Roomba), not enterprise software.
- **Contains synthetic PII fields** (name, email, age, gender) that should be dropped on ingest regardless.

**Verdict:** keep it for exactly two things — (a) a realistic *column schema* for the ticket record, and (b) a smoke-test fixture for pipeline plumbing before real data lands. Do **not** index its resolutions, train classifiers on it, or report metrics from it. The problem statement explicitly permits an alternative ("Students can choose any alternative dataset if they could find a better match") — this finding is the justification, and it is worth stating in the final report as a data-quality result rather than hiding it.

### Other exclusions

- **Live web scraping of `learn.microsoft.com` / `support.microsoft.com` HTML** — unnecessary (the same content sits in the GitHub repos, cleaner, with front-matter metadata) and adds ToS risk. Use the repos.
- **Vendor KBs behind login or restrictive ToS** (Atlassian, Salesforce, Zendesk help centres) — no redistribution rights.
- **Kaggle datasets with no stated licence** — several ticket datasets have an empty licence field. Skip unless one is present.

---

## 7. Licence & compliance summary

| Licence | Sources | Obligation on us |
|---|---|---|
| CC-BY-4.0 | All MicrosoftDocs repos, Kubernetes website | Attribute source + link. Store `source_url` in chunk metadata |
| CC BY-SA 4.0 | GitLab `doc/`, Stack Exchange posts, Mozilla SUMO | Attribute **and** share-alike on derivatives. Do not silently fold into promoted KB articles |
| CC BY-NC 4.0 | Tobi-Bueck ticket dataset | Academic / non-commercial use only — must be stated in the report |
| CDLA-Sharing-1.0 | Bitext | Attribution + share-alike-style terms on redistributed data |
| MIT | Code in MicrosoftDocs repos | Attribution if code is reused |
| Platform ToS / dataset terms | GitHub issues, Stack Exchange dump agreement, UCI, MSDialog | Cite by URL; avoid redistributing bulk raw text in this repo |

**Repo policy:** do **not** commit raw corpora to git. Commit acquisition manifests (source, revision/commit SHA, date, filter paths, licence) so the corpus is reproducible; keep data in a gitignored `data/` tree, DVC-tracked if it grows.

**PII:** strip customer names, emails, phone numbers, tenant IDs and IP addresses at ingest from every ticket source, synthetic or not. Demonstrating this is expected of an enterprise support product regardless of dataset origin.

---

## 8. Recommended v0.1 starter bundle

The smallest set that makes M3–M5 (KB indexed → retrieval prototype → measured retrieval) real:

| Tier | Source | Filter | Target volume |
|---|---|---|---|
| Tier 1 | `MicrosoftDocs/SupportArticles-docs` | Paths for OneDrive/SharePoint sync, Outlook/Exchange mail flow, Teams sign-in, Windows client auth & update | 800–2,000 articles → ~8k–20k chunks |
| Tier 1 | `MicrosoftDocs/microsoft-365-docs` | Same product areas; `troubleshoot*` + admin config pages | 200–500 articles |
| Tier 2 | MSDialog | Categories matching the four product areas; keep dialogs with an accepted answer | 2,000–5,000 dialogs → pre-summarised units |
| Tier 2 | Closed GitHub issues — `microsoft/vscode`, `microsoft/WSL` | `state:closed`, has a maintainer answer | 2,000–5,000 issues |
| Metadata | UCI incident event log | All | Field vocabularies + priority/escalation distributions |
| Eval | Hand-built | Held-out MSDialog + GitHub issues | 30–50 queries with manually marked relevant documents |
| Eval | NLBSE'24 | 3k labelled issue reports | Classification baseline |

**Acquisition method per source** — no HTML scraping needed for any primary source:

- MicrosoftDocs repos → `git clone --depth 1`, path-filtered
- MSDialog → direct download from UMass CIIR
- GitHub issues → GitHub REST/GraphQL API (authenticated, paginated)
- Stack Exchange → Internet Archive dump (7z / XML per site)
- UCI → direct CSV download
- Kaggle / Hugging Face → `kaggle datasets download` / `huggingface_hub`

---

## 9. Open questions to settle before writing ingestion code

1. **Final product scope** — confirm the 3–4 product areas. Everything downstream (taxonomy, filters, eval set) depends on this.
2. **Tier 2 mix** — MSDialog alone, or MSDialog + GitHub issues? Two very different text shapes; the pre-summarisation prompt may need to differ per source.
3. **Taxonomy origin** — derive categories bottom-up from Tier 1 front-matter tags, or top-down from the ITSM vocabulary in the UCI log? The blueprint forbids hard-coding example buckets, so derive from data and validate.
4. **Stack Exchange in or out** — decide the licensing posture now, not after ingestion.
5. **Corpus versioning** — DVC, or manifest + checksums? Affects the reproducibility claim in the final evaluation.

---

## Sources

- [MicrosoftDocs/SupportArticles-docs](https://github.com/MicrosoftDocs/SupportArticles-docs) · [MicrosoftDocs org repositories](https://github.com/orgs/MicrosoftDocs/repositories) · [microsoft-365-docs](https://github.com/MicrosoftDocs/microsoft-365-docs) · [windowsserverdocs](https://github.com/MicrosoftDocs/windowsserverdocs)
- [kubernetes/website](https://github.com/kubernetes/website) · [kubernetes/website LICENSE](https://github.com/kubernetes/website/blob/main/LICENSE) · [GitLab docs licence change MR](https://gitlab.com/gitlab-org/gitlab-runner/-/merge_requests/893)
- [Mozilla SUMO API (MozillaWiki)](https://wiki.mozilla.org/Support/Kitsune/SUMO_API) · [mozilla/kitsune](https://github.com/mozilla/kitsune/)
- [MSDialog — Neural Response Ranking downloads (UMass CIIR)](https://ciir.cs.umass.edu/downloads/NeuralResponseRanking) · [Analyzing and Characterizing User Intent in Information-seeking Conversations (SIGIR'18)](https://dl.acm.org/doi/10.1145/3209978.3210124) · [User Intent Prediction in Information-seeking Conversations](https://arxiv.org/pdf/1901.03489)
- [UCI — Incident management process enriched event log](https://archive.ics.uci.edu/dataset/498/incident+management+process+enriched+event+log)
- [Stack Exchange Data Dump (Internet Archive)](https://archive.org/details/stackexchange) · [Stack Exchange dump access policy change (devclass)](https://devclass.com/2024/07/30/stack-exchange-restricts-access-to-dump-of-user-contributed-data-as-critics-complain-license-permits-reuse-for-any-purpose/)
- [Kaggle — Customer Support Ticket Dataset (suraj520)](https://www.kaggle.com/datasets/suraj520/customer-support-ticket-dataset) · [Kaggle — Customer IT Support Ticket Dataset (tobiasbueck)](https://www.kaggle.com/datasets/tobiasbueck/multilingual-customer-support-tickets) · [HF — Tobi-Bueck/customer-support-tickets](https://huggingface.co/datasets/Tobi-Bueck/customer-support-tickets)
- [HF — bitext/Bitext-customer-support-llm-chatbot-training-dataset](https://huggingface.co/datasets/bitext/Bitext-customer-support-llm-chatbot-training-dataset)
- [NLBSE'23 issue-report-classification](https://github.com/nlbse2023/issue-report-classification) · [NLBSE'24 tool competition](https://nlbse2024.github.io/tools/)
- [Kaggle — Customer Support on Twitter](https://www.kaggle.com/datasets/thoughtvector/customer-support-on-twitter)
