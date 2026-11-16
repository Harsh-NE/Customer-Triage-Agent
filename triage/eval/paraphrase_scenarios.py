"""
paraphrase_scenarios.py -- the paraphrase set as end-to-end scenarios, so the ablation harness can run it.

triage/eval/paraphrases.jsonl holds customer wordings of documented issues (written to test whether the knowledge graph helps when the customer's
words differ from the documentation's). It was only ever used for retrieval. As scenarios, the whole agent runs on them: Clarifier, gate, drafting.

Two of the 42 accept either of two headings as the right answer, and a scenario has one gold issue, so they are left out (40 remain).
The simulated customer has no hidden facts beyond the wording itself, as for the gold set. The wordings were written by the authors of the
knowledge graph, so a gain here is an upper bound.

    python -m triage.eval.paraphrase_scenarios            # writes reports/regression/paraphrase_scenarios.jsonl
    python -m triage.eval.ablation --arms A B --llm gemini --scenarios reports/regression/paraphrase_scenarios.jsonl --cache off --repeat-fraction 0
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "paraphrases.jsonl"
OUT = HERE.parents[1] / "reports" / "regression" / "paraphrase_scenarios.jsonl"


def to_scenario(item: dict) -> dict | None:
    """One paraphrase as a scenario record, or None when it has more than one acceptable answer."""
    if len(item["gold"]) != 1:
        return None
    gold = item["gold"][0]
    return {"id": item["id"], "opening": item["query"], "vagueness": "unknown", "expected_hard_gaps": [], "opening_facts": {}, "oos": False,
            "hidden": {"product_area": None, "platform": None, "error_text": None, "symptom_detail": item["query"]},
            "gold": {"source_path_contains": gold["path"], "issue_contains": gold["issue"]},
            "note": "paraphrase of a documented issue, written by the knowledge graph's authors; label verified=author"}


def main() -> None:
    items = [json.loads(line) for line in SOURCE.read_text(encoding="utf-8").splitlines() if line.strip()]
    scenarios = [s for s in map(to_scenario, items) if s]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("".join(json.dumps(s) + "\n" for s in scenarios), encoding="utf-8")
    print(f"{len(scenarios)} of {len(items)} paraphrases written to {OUT} ({len(items) - len(scenarios)} left out: more than one acceptable answer)")


if __name__ == "__main__":
    main()
