"""
perturb_eval.py -- how much does messy input hurt? The same questions, deliberately made worse in ways real customers do it.

Perturbations (deterministic: the same seed gives the same text, so two runs of the system are comparable):
  typos        about 12% of the longer plain words get two adjacent letters swapped (words with digits or symbols, i.e. errors and
               commands, are left alone: a typo in "docker0" would be a different test)
  shouting     the whole message in capitals
  lowercase    the whole message in lower case
  chatter      a greeting before and a plea after ("hi, ... thanks in advance, been stuck on this for hours"), the shape of the
               "Getting this error in while pulling nginx server" message that triggered the uncovered-word fix
  log_noise    1,200 characters of unrelated terminal log lines pasted after the question
  two_issues   a second, unrelated question appended ("Also: ...")

On every labelled question we measure, per perturbation, issue-level Recall@1/3/8 and MRR of the gold issue (retrieval only) and, on the
answerable gold questions, the Clarifier's first decision: how often it is READY, and READY about the right issue. The original text is the
baseline. Free and offline. The sets are small, so read the "worsened" counts and the examples, not the percentages.

    PYTHONHASHSEED=0 HF_HUB_OFFLINE=1 python -m triage.eval.perturb_eval
"""

from __future__ import annotations

import argparse
import json
import random
import re
import time
import zlib
from pathlib import Path

from triage.eval.ontology_eval import issue_rank, load_items
from triage.eval.rerank_eval import metrics
from triage.sim.customer import load_scenarios

HERE = Path(__file__).resolve().parent
REPORT_DIR = HERE.parents[1] / "reports"
KINDS = ("typos", "shouting", "lowercase", "chatter", "log_noise", "two_issues")
LOG_NOISE = "\n".join(
    f"2026-03-0{1 + i % 8}T1{i % 10}:2{i % 6}:0{i % 9}Z {lvl} [{svc}] {msg}" for i, (lvl, svc, msg) in enumerate([
        ("INFO", "scheduler", "heartbeat ok, 3 workers idle"), ("DEBUG", "cache", "evicted 14 entries (ttl)"), ("INFO", "http", "GET /healthz 200 2ms"),
        ("WARN", "disk", "usage at 71% on /var/lib/data"), ("INFO", "worker-2", "job 8841 finished in 412ms"), ("DEBUG", "pool", "connection returned to pool"),
        ("INFO", "http", "GET /metrics 200 5ms"), ("INFO", "scheduler", "next run in 60s"), ("DEBUG", "cache", "hit ratio 0.93"), ("INFO", "worker-1", "job 8842 queued"),
        ("INFO", "http", "POST /api/v1/events 202 9ms"), ("DEBUG", "gc", "pause 3ms"), ("INFO", "worker-3", "job 8843 started"), ("WARN", "net", "retrying dns lookup (1/3)")]))
OTHER_QUESTIONS = ["Also, how do I change the default shell in my terminal?", "Also, my printer keeps going offline.", "Also, how do I rename a git branch?",
                   "Also, why is my laptop fan so loud?", "Also, how do I schedule a cron job?"]
PLAIN_WORD = re.compile(r"^[A-Za-z]{5,}$")


def rng_for(text: str, kind: str, seed: int) -> random.Random:
    return random.Random(zlib.crc32(f"{kind}|{seed}|{text}".encode()))


def perturb(text: str, kind: str, seed: int = 0) -> str:
    """The text made worse in one way. Pure and deterministic."""
    rng = rng_for(text, kind, seed)
    if kind == "typos":
        out = []
        for token in re.split(r"(\s+)", text):
            if PLAIN_WORD.match(token) and rng.random() < 0.12:
                i = rng.randrange(1, len(token) - 2)
                token = token[:i] + token[i + 1] + token[i] + token[i + 2:]
            out.append(token)
        return "".join(out)
    if kind == "shouting":
        return text.upper()
    if kind == "lowercase":
        return text.lower()
    if kind == "chatter":
        return f"hi, {text.strip()} thanks in advance, been stuck on this for hours"
    if kind == "log_noise":
        noise = ((LOG_NOISE + "\n") * 2)[:1200]                                   # the block is about 800 characters: repeat it to reach 1,200
        return f"{text.strip()}\n\n{noise}"
    if kind == "two_issues":
        return f"{text.strip()} {rng.choice(OTHER_QUESTIONS)}"
    raise ValueError(f"unknown perturbation '{kind}', expected one of {KINDS}")


def answerable_items() -> list[dict]:
    held = load_scenarios(HERE / "heldout_scenarios.jsonl")
    gold = lambda s: [{"path": s.gold["source_path_contains"], "issue": s.gold["issue_contains"]}]       # noqa: E731
    return ([{"id": s.id, "set": "scenario", "query": s.opening, "gold": gold(s)} for s in load_scenarios() if s.gold]
            + [{"id": s.id, "set": "heldout", "query": s.opening, "gold": gold(s)} for s in held if s.gold]
            + [{**i, "set": "paraphrase"} for i in load_items()["paraphrases"]])


def clarifier_first_turn(kb, query: str, gold: list[dict]) -> dict:
    from triage.clarifier import Clarifier
    c = Clarifier(None, kb)
    result = c.turn(c.start("T-perturb"), query)
    labels = [h["label"] for h in (result.meta.get("hypotheses") or [])]
    if result.signature and result.signature.hypotheses:
        labels = [h.label for h in result.signature.hypotheses]
    right = any(g["issue"].lower().strip("`") in label.lower() for g in gold for label in labels[:1])
    return {"ready": result.status.value == "ready", "top1_right": right, "gold_in_top3": any(g["issue"].lower().strip("`") in label.lower() for g in gold for label in labels[:3])}


def evaluate(kb, items: list[dict], kinds: tuple[str, ...], seed: int, with_clarifier: bool) -> dict:
    out: dict = {}
    for kind in ("original", *kinds):
        ranks, clar = {}, []
        for item in items:
            text = item["query"] if kind == "original" else perturb(item["query"], kind, seed)
            ranks[item["id"]] = issue_rank(kb.search(text, top_k=8), item["gold"])
            if with_clarifier and item["set"] != "paraphrase":
                clar.append(clarifier_first_turn(kb, text, item["gold"]))
        out[kind] = {"ranks": ranks, "clarifier": clar}
    return out


def summarize(results: dict) -> dict:
    base = results["original"]["ranks"]
    report = {}
    for kind, res in results.items():
        row = {"retrieval": metrics(res["ranks"])}
        if kind != "original":
            row["retrieval"]["improved"] = sum((res["ranks"][i] or 99) < (base[i] or 99) for i in base)
            row["retrieval"]["worsened"] = sum((res["ranks"][i] or 99) > (base[i] or 99) for i in base)
        if res["clarifier"]:
            n = len(res["clarifier"])
            row["clarifier"] = {"n": n, "ready": sum(c["ready"] for c in res["clarifier"]), "ready_and_top1_right": sum(c["ready"] and c["top1_right"] for c in res["clarifier"]),
                                "top1_right": sum(c["top1_right"] for c in res["clarifier"]), "gold_in_top3": sum(c["gold_in_top3"] for c in res["clarifier"])}
        report[kind] = row
    return report


def write_markdown(path: Path, report: dict, n_items: int) -> None:
    lines = ["# Robustness to messy input", "", f"_Generated {time.strftime('%Y-%m-%d %H:%M')} by `python -m triage.eval.perturb_eval`; {n_items} answerable questions (42 paraphrases, 20 scenario openings, 19 held-out gold) before perturbation. "
             "Retrieval only plus the Clarifier's first turn; see the module docstring._", "",
             "## Retrieval of the gold issue", "", "| input | recall@1 | recall@3 | recall@8 | MRR | improved / worsened vs original |", "|---|---|---|---|---|---|"]
    for kind, row in report.items():
        m = row["retrieval"]
        lines.append(f"| {kind} | {m['recall@1']} | {m['recall@3']} | {m['recall@8']} | {m['mrr']} | {'-' if kind == 'original' else str(m['improved']) + ' / ' + str(m['worsened'])} |")
    if any("clarifier" in r for r in report.values()):
        lines += ["", "## The Clarifier's first decision (scenario openings and held-out gold only)", "", "| input | n | READY | READY about the right issue | leading issue right | gold in top 3 |", "|---|---|---|---|---|---|"]
        for kind, row in report.items():
            c = row.get("clarifier")
            if c:
                lines.append(f"| {kind} | {c['n']} | {c['ready']} | {c['ready_and_top1_right']} | {c['top1_right']} | {c['gold_in_top3']} |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Measure the effect of messy input on retrieval and on the Clarifier's first decision.")
    ap.add_argument("--kinds", nargs="*", default=list(KINDS))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--no-clarifier", action="store_true")
    ap.add_argument("--out-json", type=Path, default=REPORT_DIR / "regression" / "perturb_eval.json")
    ap.add_argument("--out-md", type=Path, default=REPORT_DIR / "regression" / "perturb_eval.md")
    args = ap.parse_args()

    from triage.hybrid import HybridKBRetriever
    kb = HybridKBRetriever(rerank_mode="off", kb_filters="")
    kb._ensure()
    items = answerable_items()[:args.limit]
    started = time.time()
    results = evaluate(kb, items, tuple(args.kinds), args.seed, not args.no_clarifier)
    report = summarize(results)
    write_markdown(args.out_md, report, len(items))
    examples = []
    for kind in args.kinds:
        for item in items:
            b, r = results["original"]["ranks"][item["id"]], results[kind]["ranks"][item["id"]]
            if (r or 99) > (b or 99):
                examples.append({"kind": kind, "id": item["id"], "was": b, "now": r, "text": perturb(item["query"], kind, args.seed)[:160]})
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps({"report": report, "worsened_examples": examples[:40], "seed": args.seed, "seconds": round(time.time() - started)}, indent=1), encoding="utf-8")
    print(args.out_md.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
