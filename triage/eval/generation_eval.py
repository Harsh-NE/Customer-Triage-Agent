"""
generation_eval.py -- BLEU / ROUGE / METEOR (and optional embedding similarity) of the fixes the agent sent, against REFERENCE answers.

A reference answer is what a competent Docker support engineer would send for that question. It has to be written by a person (or at least
reviewed by one): scoring against text the system itself retrieved would measure copying, not quality. So this tool has two parts:

  sheet   writes a CSV for a person to fill in: the question, the documented KB section the gold label points to (to help them write the
          answer), and an empty `reference` column.   python -m triage.eval.generation_eval sheet references_sheet.csv
  score   reads the filled sheet (or a JSONL of {id, reference}) and an agent_metrics rows file, and scores the FIRST fix sent for every
          question that has a reference and got a fix.   python -m triage.eval.generation_eval score refs.csv reports/x_rows.json

What the score does NOT say. Overlap with a reference rewards the usual wording, not correctness: a right fix in other words scores low, a wrong
fix that repeats the question scores high. Report it next to the human-graded sample and the faithfulness judge, never alone. The fix text is
cleaned first: the "Sources:" footer, evidence tags like [E1] and the "To confirm:" line are removed, because they are formatting, not content.
Questions where the agent sent no fix are counted separately (`no_fix`): they are not given a zero, which would punish a correct escalation.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

from triage.eval import text_metrics as tm

HERE = Path(__file__).resolve().parent
REPORT_DIR = HERE.parents[1] / "reports"
_EVIDENCE_TAG = re.compile(r"\s*\[E\d+(?:[,\s]+E\d+)*\]")
_FOOTER = re.compile(r"(?is)\n\s*(?:To confirm:|Sources:).*$")


def clean_fix(message: str) -> str:
    """The content of a sent fix without its formatting: no source footer, no confirm line, no evidence tags, no markdown table rules."""
    text = _FOOTER.sub("", message or "")
    text = _EVIDENCE_TAG.sub("", text)
    text = re.sub(r"(?m)^\s*\|?[\s:\-|]{5,}\|?\s*$", "", text)
    text = re.sub(r"(?i)^\s*likely cause:\s*", "", text)
    return re.sub(r"\n{2,}", "\n", text).strip()


def load_references(path: Path) -> dict[str, str]:
    if path.suffix == ".csv":
        with path.open(encoding="utf-8", newline="") as f:
            return {r["id"]: r["reference"].strip() for r in csv.DictReader(f) if (r.get("reference") or "").strip()}
    return {r["id"]: r["reference"] for r in map(json.loads, filter(str.strip, path.read_text(encoding="utf-8").splitlines())) if r.get("reference")}


def score(references: dict[str, str], rows: list[dict], encode=None) -> dict:
    pairs, ids, no_fix, missing = [], [], [], []
    by_id = {r["id"]: r for r in rows}
    for qid, ref in references.items():
        row = by_id.get(qid)
        if row is None:
            missing.append(qid)
            continue
        if not row.get("fixes_sent"):
            no_fix.append(qid)
            continue
        pairs.append((ref, clean_fix(row["fixes_sent"][0]["message"])))
        ids.append(qid)
    rep = tm.generation_report(pairs, encode) if pairs else {"n": 0}
    rep.update({"scored_ids": ids, "no_fix": no_fix, "no_row": missing, "questions_with_reference": len(references)})
    return rep


def make_sheet(path: Path) -> int:
    """One row per answerable gold question: id, question, gold KB page and section, the section text, and an empty `reference`."""
    from triage.eval.gold_v1 import DEV, TEST, read_split
    kb = None
    out = []
    for r in read_split(DEV) + read_split(TEST):
        if not r.get("gold"):
            continue
        if kb is None:
            from triage.hybrid import HybridKBRetriever
            kb = HybridKBRetriever(rerank_mode="off", kb_filters="")
            kb._ensure()
        gold = {"path": r["gold"]["source_path_contains"], "issue": r["gold"]["issue_contains"]}
        from triage.eval.ontology_eval import matches
        hits = [c for c in kb.search(f"{gold['issue']} {r['opening']}", top_k=12) if matches(c, gold)]
        section = "\n".join(c.text for c in hits[:2])[:1500]
        out.append({"id": r["id"], "question": r["opening"][:600], "gold_page": gold["path"], "gold_section": gold["issue"], "section_text": section, "reference": ""})
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "question", "gold_page", "gold_section", "section_text", "reference"])
        w.writeheader()
        w.writerows(out)
    return len(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sheet = sub.add_parser("sheet", help="write the CSV a person fills with reference answers")
    sheet.add_argument("out", type=Path)
    sc = sub.add_parser("score", help="score sent fixes against filled-in references")
    sc.add_argument("references", type=Path)
    sc.add_argument("rows", type=Path, help="an agent_metrics rows JSON (the *_rows.json file)")
    sc.add_argument("--semantic", action="store_true", help="also report embedding cosine similarity (loads the bge model)")
    sc.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    if args.cmd == "sheet":
        print(f"wrote {make_sheet(args.out)} questions to {args.out}; fill the `reference` column, then run `score`")
        return
    data = json.loads(args.rows.read_text(encoding="utf-8"))
    rows = data["rows"] if isinstance(data, dict) else data
    encode = None
    if args.semantic:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("BAAI/bge-base-en-v1.5", local_files_only=True)
        encode = lambda texts: model.encode(texts, normalize_embeddings=True).tolist()      # noqa: E731
    report = score(load_references(args.references), rows, encode)
    text = json.dumps(report, indent=1)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    sys.exit(main())
