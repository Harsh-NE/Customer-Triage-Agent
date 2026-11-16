# Knowledge-graph coverage

_Generated 2026-11-03 20:01 by `python scripts/15_kg_candidates.py`._

| KB section kind | issues | linked from the ontology | share |
|---|---|---|---|
| troubleshooting | 137 | 51 | 37% |
| faq | 96 | 0 | 0% |
| **both** | 233 | 51 | 22% |

182 KB issues have no node. **30** of them are written to `data/curated/ontology_candidates.yaml` as drafts because the KB text gives something to start from (16 an error line, 18 a title that already reads like a symptom). The other 152 have only a generic heading ("Overview", "Run diagnostics") and need a person to write the customer-side wording from scratch. The drafts are structural: no aliases and no summary. They are unlikely to change retrieval by themselves, because the KB retriever already matches these titles; the value of a node is the wording customers use and the docs do not.

## Ontology issues that claim to be undocumented (`kb: []`): KB text that mentions their error (release notes and archive excluded)

| node | error text | found in |
|---|---|---|
| `issue-no-space` | no space left on device | ai/sandboxes/integrations/t3-code.md > Connect T3 Code to a sandbox > Troubleshoot a server that never becomes ready; engine/security/rootless/troubleshoot.md > Troubleshooting > Errors when starting the Docker daemon |

These are leads to review, not verdicts: the check matches the node's error text literally, so it can flag a page that only mentions the error and miss one that documents the fix in other words (the socket-permission fix in `engine/install/linux-postinstall.md` never quotes the error, so it is not listed here; a reviewer found it).
