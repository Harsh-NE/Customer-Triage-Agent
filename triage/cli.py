"""
cli.py -- drive the Clarifier by hand.

    python -m triage.cli chat                       # you play the customer (free: heuristic extraction)
    python -m triage.cli chat --extractor llm       # LLM extraction from .env (costs API calls -- you run it)
    python -m triage.cli replay --id S02            # replay a labeled scenario with a simulated customer
    python -m triage.cli replay --all               # one line per scenario
    python -m triage.cli replay --id S02 --retriever keyword

Add --verbose to see the ranked hypotheses behind every decision. In `chat`, type /quit to stop,
/state to dump the session fields, /record to print the Triage Record JSON.
"""

from __future__ import annotations

import argparse
import json

from triage.clarifier import Clarifier
from triage.config import ClarifierConfig
from triage.eval.clarifier_eval import build_retriever
from triage.sim.customer import RuleBasedCustomer, load_scenarios
from triage.sim.dialogue import run_dialogue
from triage.state import ClarifierStatus, to_dict


def _print_result(res, verbose: bool) -> None:
    if res.status is ClarifierStatus.ASK:
        print(f"\n[assistant asks about '{res.question.feature}']\n{res.question.text}\n")
    else:
        sig = res.signature
        top = sig.hypotheses[0].label if sig and sig.hypotheses else "(none)"
        print(f"\n[{res.status.value.upper()}: {res.reason}]  signature: {sig.canonical_string}")
        print(f"  most likely cause: {top}")
        if res.meta.get("inferred"):
            print(f"  inferred: {res.meta['inferred']}")
    if verbose:
        conf = res.meta.get("confidence")
        if conf:
            print(f"  confidence: {conf}")
        for h in res.meta.get("hypotheses", []):
            print(f"    ({h['weight']:.2f}) {h['label']}")
        print(f"  extraction={res.meta.get('extraction_source')}  tools={[c['tool'] for c in res.meta.get('tool_calls', [])]}")


def cmd_chat(args) -> None:
    llm = None
    if args.extractor == "llm":
        from triage.llm import ProviderLLM
        llm = ProviderLLM()
    clarifier = Clarifier(llm, build_retriever(args.retriever, None), ClarifierConfig())
    session = clarifier.start()
    print("You are the customer. Describe a Docker problem (/quit to stop, /state, /record).")
    while True:
        try:
            message = input("customer> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not message:
            continue
        if message == "/quit":
            break
        if message == "/state":
            print(json.dumps(to_dict(session.fields), indent=2))
            continue
        if message == "/record":
            print(json.dumps(to_dict(session.to_triage_record(tool_calls=clarifier.registry.log)), indent=2))
            continue
        res = clarifier.turn(session, message)
        _print_result(res, args.verbose)
        if res.status is not ClarifierStatus.ASK:
            print("(conversation handed to the Resolver; /record shows what it would receive, /quit to stop)")


def cmd_replay(args) -> None:
    scenarios = load_scenarios()
    if not args.all:
        scenarios = [s for s in scenarios if s.id == args.id]
        if not scenarios:
            raise SystemExit(f"No scenario '{args.id}'. Known: {[s.id for s in load_scenarios()]}")
    retriever = build_retriever(args.retriever, None)
    for s in scenarios:
        d = run_dialogue(Clarifier(None, retriever), RuleBasedCustomer(s, style=args.style), s)
        top = d.result.signature.hypotheses[0].label if d.result.signature and d.result.signature.hypotheses else "-"
        if args.all:
            print(f"{s.id}  {d.status:10s} q={d.result.questions_asked}  gold_rank={d.gold_rank if s.gold else 'n/a':>4}  {s.opening[:55]!r} -> {top[:50]}")
            continue
        print(f"=== {s.id}: {s.note or s.opening} ===")
        for role, text in d.transcript:
            print(f"{'customer' if role == 'customer' else 'assistant':>9}: {text}")
        print(f"\nresult: {d.status}  gold_rank={d.gold_rank}  questions={d.result.questions_asked}")
        _print_result(d.result, args.verbose)


def main() -> None:
    ap = argparse.ArgumentParser(description="Drive the Clarifier by hand.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    chat = sub.add_parser("chat")
    chat.add_argument("--extractor", choices=["heuristic", "llm"], default="heuristic")
    chat.add_argument("--retriever", choices=["hybrid", "chroma", "keyword"], default="hybrid")
    chat.add_argument("--verbose", "-v", action="store_true")
    chat.set_defaults(fn=cmd_chat)
    rep = sub.add_parser("replay")
    rep.add_argument("--id", default="S02")
    rep.add_argument("--all", action="store_true")
    rep.add_argument("--retriever", choices=["hybrid", "chroma", "keyword"], default="hybrid")
    rep.add_argument("--style", choices=["mixed", "number", "text"], default="mixed")
    rep.add_argument("--verbose", "-v", action="store_true")
    rep.set_defaults(fn=cmd_replay)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
