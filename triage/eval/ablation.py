"""
ablation.py -- run the ablation arms on the same ordered stream of questions and compare them.

    arm A  baseline: no knowledge graph, no Jev          arm B  + knowledge graph          arm C  + knowledge graph + Jev
    (the cache switch is separate: --cache on|off applies to every arm; the default leaves it on)

The stream is every scenario once ("first_ask") and then a seeded sample of them asked again word for word ("repeat"). Each arm starts with an
empty in-memory cache that lives for the whole stream, so a repeat can be served from it and a different problem can be served by mistake
(a false hit). Quality metrics are computed on the first ask; cache, latency and cost telemetry on the whole stream.
The arms advance together, one query at a time, taking turns to go first, so a slow stretch of the model API is shared between them.
A failed model call is retried after a wait; the run stops when too many still fail (usually an exhausted quota).
Customers are simulated and an oracle answers "that worked" only for a fix that cites the scenario's gold issue (see e2e_eval.py).

    python -m triage.eval.ablation --definitions            # print the 9 metrics and exactly how each is computed, then stop
    python -m triage.eval.ablation                          # arms A B C, the 29 scenarios, 30% repeated, fake model: offline and free
    python -m triage.eval.ablation --arms A B --llm gemini --scenarios triage/eval/scenarios.jsonl triage/eval/heldout_scenarios.jsonl

Writes to reports/ablation/: queries.jsonl (one raw line per query and arm), events_<arm>.jsonl (every logged event), rows_<arm>.json
(full per-case rows; feed them to agent_metrics --from-report), summary.json, comparison.md (for the paper) and comparison.csv (long format).

python -m triage.eval.ablation --recompute reports/ablation/<run>     # re-tabulate an earlier run from its logs: no model calls

Arm C is arm B plus Jev as a second opinion when the confidence gate refuses (triage/resolver/jev_gate.py). It needs OPENROUTER_API_KEY, or
JEV_BACKEND=fake for an offline rehearsal; JEV_MODE=shadow asks and logs without changing any decision.
The run sets PYTHONHASHSEED=0 itself (the Clarifier breaks ties by hash order), so two runs of the same code are comparable.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import subprocess
import sys
import time
from pathlib import Path

from triage.eval import agent_metrics as M
from triage.eval import telemetry as T
from triage.eval.e2e_eval import Recording, run_scenario, usage_of
from triage.features import ARM_NAMES, ARMS, Features
from triage.resolver.contracts import CacheStatus, Evidence

OUT_DIR = Path(__file__).resolve().parents[2] / "reports" / "ablation"
CALLS_PER_CASE = 2.3          # model calls per case in the real Gemini runs of 13 Oct - 3 Nov (209 calls over 93 cases)
RETRIES, RETRY_WAIT_S = 2, 20.0     # a failed model call is retried twice, after 20 s and then 40 s, before it counts as a failure
MAX_FAILURES = 5                    # failed calls (after retries) at which the whole run stops

# (key, label, definition). The 9 core metrics; some have two numbers. All but 7, 9 are over the first ask only.
CORE = [
    ("first_attempt_correct", "1 First-attempt correct", "Of the questions the documentation answers (gold), the share whose first fix cites the gold issue."),
    ("wrong_fix_rate", "2 Wrong-fix rate", "Cases that got a fix that is not the gold one, or a documentation fix where there is no answer, / all cases."),
    ("wrong_first_fix_answerable", "2 Wrong first fix, answerable cases", "Answerable cases whose first fix is not the gold one / answerable cases."),
    ("escalation_recall", "3 Escalation recall", "Of the cases that should reach a person (out of scope, or no documented answer), the share that did."),
    ("escalation_precision", "4 Escalation precision", "Of the cases that ended with a person or a refusal, the share that needed it."),
    ("unnecessary_escalation", "4 Unnecessary escalation", "Answerable cases that ended with a person or a refusal / answerable cases."),
    ("recall_at_3", "5 Recall@3", "Answerable cases whose gold issue is in the top 3 chunks of the first documentation search / answerable cases searched."),
    ("mrr", "5 MRR", "Mean of 1 / (rank of the first gold chunk in the first documentation search), over answerable cases searched."),
    ("questions_per_case", "6 Questions per case (mean)", "Mean number of clarifying questions asked per case."),
    ("first_fix_p50_ms", "7 Time to first fix p50 (ms)", "Milliseconds from the first customer message until the first fix is sent, over cases that sent one."),
    ("first_fix_p95_ms", "7 Time to first fix p95 (ms)", "As above, 95th percentile."),
    ("citation_validity", "8 Citation validity", "Sent fixes whose every cited evidence id was among the evidence shown to the drafter / sent fixes."),
    ("retrieval_p50_ms", "9 Retrieval time p50 (ms)", "Milliseconds spent in one retrieval call, over the first ask."),
    ("retrieval_p95_ms", "9 Retrieval time p95 (ms)", "As above, 95th percentile."),
    ("repeat_speedup", "9 Repeat speed-up (x)", "Median end-to-end time of a first ask that was searched and resolved / median of a repeat answered from the cache."),
]
# Metrics 5 and 8 skip every case that ANY arm served from the cache (no search or draft happened there), so all arms are scored on the same
# questions. Without that, an arm whose cache answered a hard question would look better at retrieval for not having been asked to search.

# (label, getter over one arm's summary). Cache, latency and cost telemetry for the whole stream.
TELEMETRY = [
    ("Cache hit rate", lambda s: s["cache"]["hit_rate"]),
    ("Cache precision", lambda s: s["cache"]["precision"]),
    ("Cache false-hit rate", lambda s: s["cache"]["false_hit_rate"]),
    ("End-to-end latency p50 (ms)", lambda s: s["latency"]["end_to_end_ms"]["p50"]),
    ("End-to-end latency p95 (ms)", lambda s: s["latency"]["end_to_end_ms"]["p95"]),
    ("Model calls", lambda s: s["cost"]["llm_calls"]),
    ("Failed model calls (must be 0)", lambda s: s["cost"]["llm_errors"]),
    ("Retried model calls (their cases ran slower)", lambda s: s["cost"]["llm_retries"]),
    ("Input tokens (model + Jev)", lambda s: s["cost"]["input_tokens"]),
    ("Jev calls", lambda s: s["cost"]["jev_calls"]),
    ("Jev overrides (refusals turned into answers)", lambda s: s["cost"]["jev_overrides"]),
    ("Jev errors (the rules decided)", lambda s: s["cost"]["jev_errors"]),
    ("Cost (USD)", lambda s: s["cost"]["cost_usd"]),
    ("Calls saved vs baseline arm (%)", lambda s: s["vs_baseline"]["llm_calls_saved_vs_baseline"]),
    ("Tokens saved vs baseline arm (%)", lambda s: s["vs_baseline"]["input_tokens_saved_vs_baseline"]),
    ("Cost saved vs baseline arm (%)", lambda s: s["vs_baseline"]["cost_usd_saved_vs_baseline"]),
    ("Calls avoided by the cache (est.)", lambda s: s["cache_savings"]["avoided_llm_calls"]),
    ("Cost avoided by the cache (est., USD)", lambda s: s["cache_savings"]["avoided_cost_usd"]),
]


# ---------------------------------------------------------------- the stream and the arm

def build_stream(scenarios: list, repeat_fraction: float, seed: int) -> list[tuple[str, object]]:
    """Every scenario once, then a seeded sample of them again, word for word."""
    again = random.Random(seed).sample(scenarios, round(len(scenarios) * repeat_fraction))
    return [("first_ask", s) for s in scenarios] + [("repeat", s) for s in again]


class RecordingCache:
    """Shows the oracle the evidence behind a cached fix. The cached case never searched, so Recording has nothing to offer."""

    def __init__(self, inner, rec: Recording) -> None:
        self._inner, self._rec = inner, rec

    def lookup(self, signature):
        res = self._inner.lookup(signature)
        if res.entry is not None and res.status != CacheStatus.MISS:
            evidence = [Evidence.from_dict(e) for e in res.entry.evidence]
            self._rec.calls.append((evidence[0].tier if evidence else "kb", evidence))
        return res

    def __getattr__(self, name):
        return getattr(self._inner, name)


class Pacer:
    """Keeps the model under `max_rpm` requests per minute (None: no limit). It waits BETWEEN cases, never inside a call, so the latency
    measurements do not include the wait. `headroom` is the most calls one case is allowed to add, plus the library's one hidden retry."""

    def __init__(self, max_rpm: int | None, headroom: int = 6, clock=time.monotonic, sleep=time.sleep) -> None:
        self.max_rpm, self.headroom, self._clock, self._sleep, self.calls = max_rpm, headroom, clock, sleep, []

    def note_call(self) -> None:
        self.calls.append(self._clock())

    def wait(self) -> float:
        """Block until one more case fits under the limit. Returns the seconds waited."""
        if not self.max_rpm:
            return 0.0
        room, waited = max(self.max_rpm - self.headroom, 0), 0.0
        while True:
            now = self._clock()
            self.calls = [t for t in self.calls if now - t < 60]
            if len(self.calls) <= room:
                return waited
            pause = 60 - (now - self.calls[len(self.calls) - room - 1]) + 0.1          # until enough of the oldest calls are a minute old
            self._sleep(pause)
            waited += pause


class CountingLLM:
    """Wraps the model for an evaluation: tells the pacer about every call, retries a failed call after a wait (a per-minute limit or a busy
    server usually clears), and counts the calls that still fail. The count matters because some steps swallow a model error and carry on
    (the scope check lets the question through, the reply classifier falls back to the offline one): without it a quota error would change
    the results and leave no sign. `errors` keeps each error's type and message, so the cause can be read afterwards."""

    def __init__(self, inner, pacer: Pacer | None = None, retries: int = RETRIES, wait_s: float = RETRY_WAIT_S, sleep=time.sleep) -> None:
        self._inner, self._pacer, self._retries, self._wait, self._sleep = inner, pacer, retries, wait_s, sleep
        self.failures, self.retried, self.errors = 0, 0, []

    def complete_json(self, *args, **kwargs):
        for attempt in range(self._retries + 1):
            if self._pacer:
                self._pacer.note_call()
            try:
                return self._inner.complete_json(*args, **kwargs)
            except Exception as error:
                self.errors.append(f"{type(error).__name__}: {str(error)[:200]}")
                if attempt == self._retries:
                    self.failures += 1
                    raise
                self.retried += 1
                self._sleep(self._wait * (attempt + 1))

    def __getattr__(self, name):                    # name, model, last_usage ...
        return getattr(self._inner, name)


class ArmRun:
    """One arm: its own system, caches and event log. `ask` runs one query of the stream on it."""

    def __init__(self, arm: str, features: Features, llm, out_dir: Path, pacer: Pacer | None, warmup) -> None:
        from triage.joint import build_clarifier, build_default_deps, build_joint_graph
        self.arm, self.features, self.out_dir, self.pacer, self.done = arm, features, out_dir, pacer, []
        events = out_dir / f"events_{arm}.jsonl"
        events.unlink(missing_ok=True)
        kb, self.deps = build_default_deps(llm, features=features, log_path=events, cache_path=out_dir / f"cache_{arm}.json")
        self.deps.llm = self.counted = CountingLLM(self.deps.llm, pacer)
        self.rec = Recording(self.deps.retriever)
        self.deps.retriever = self.rec
        self._embedder = self.deps.cache.embedder if self.deps.cache is not None else None
        self._empty_caches()
        self.app = build_joint_graph(build_clarifier(kb), self.deps)
        if pacer:
            pacer.wait()
        run_scenario(self.app, self.rec, warmup, run_tag=f"-{arm}-warmup")      # not recorded: models and indexes load now, not during the first query
        self._empty_caches()

    def _empty_caches(self) -> None:                # in memory: nothing is read from or written to the stored caches
        from triage.resolver.cache import NegativeCache, SemanticCache
        if self._embedder is not None:
            self.deps.cache = RecordingCache(SemanticCache(embedder=self._embedder), self.rec)
            self.deps.negative_cache = NegativeCache(embedder=self._embedder)

    def ask(self, i: int, phase: str, scenario, total: int) -> dict:
        if self.pacer and (waited := self.pacer.wait()) > 1:
            print(f"  (waited {waited:.0f}s to stay under {self.pacer.max_rpm} requests per minute)", flush=True)
        events_before, failed_before, retried_before, errors_before = len(self.deps.logger.events), self.counted.failures, self.counted.retried, len(self.counted.errors)
        row = run_scenario(self.app, self.rec, scenario, run_tag=f"-{self.arm}-{i}")
        new = self.deps.logger.events[events_before:]
        row["usage"] = usage_of(new)
        record = T.case_record(self.arm, phase, row, new, self.features.to_dict()) | {
            "llm_errors": self.counted.failures - failed_before, "llm_retries": self.counted.retried - retried_before,
            "llm_error_details": self.counted.errors[errors_before:]}
        self.done.append((phase, row, record))
        with (self.out_dir / "queries.jsonl").open("a", encoding="utf-8") as f:          # as it happens: a crash later keeps what was measured
            f.write(json.dumps(record, default=str) + "\n")
        flag = f"  ** {record['llm_errors']} MODEL CALL(S) FAILED **" if record["llm_errors"] else (f"  ({record['llm_retries']} retried)" if record["llm_retries"] else "")
        print(f"[arm {self.arm}  {i + 1}/{total}] {phase} {scenario.id}: {row['outcome']}, cache {record['cache_status']}, {row['total_s']}s{flag}", flush=True)
        return record


def check_failures(runs, limit: int) -> None:
    """Stop an evaluation whose model calls keep failing after their retries: it is almost always an exhausted quota, and going on only wastes time."""
    failed = sum(run.counted.failures for run in runs)
    if failed >= limit:
        last = {run.arm: run.counted.errors[-1] for run in runs if run.counted.errors}
        raise SystemExit(f"STOPPED: {failed} model calls failed even after retries. Last error per arm: {last}. The usual cause is the daily request "
                         "quota. Nothing more was run; queries.jsonl keeps what was measured. Run again after the quota resets.")


def run_arms(arms: dict[str, Features], stream: list, llm, out_dir: Path, pacer: Pacer | None = None, max_failures: int = MAX_FAILURES) -> dict:
    """{arm: [(phase, row, record)]}. The arms advance together, one query at a time, and take turns going first: the API's speed drifts over
    a run, and running one arm after the other would charge that drift to whichever arm ran in the slow stretch."""
    runs = [ArmRun(arm, features, llm, out_dir, pacer, stream[0][1]) for arm, features in arms.items()]
    for i, (phase, scenario) in enumerate(stream):
        for run in (runs if i % 2 == 0 else runs[::-1]):
            run.ask(i, phase, scenario, len(stream))
        check_failures(runs, max_failures)
    return {run.arm: run.done for run in runs}


def run_arm(arm: str, features: Features, stream: list, llm, out_dir: Path, pacer: Pacer | None = None) -> list[tuple[str, dict, dict]]:
    """(phase, row, record) for every query of the stream on one arm."""
    return run_arms({arm: features}, stream, llm, out_dir, pacer)[arm]


# ---------------------------------------------------------------- measuring

def measure(pairs: list[tuple[dict, dict]], repeat_speedup, skip: frozenset | set = frozenset()) -> dict:
    """The 9 core metrics for one arm from its first-ask (row, record) pairs. `skip`: ids of questions not to score for 5 and 8."""
    rows = [row for row, _ in pairs]
    searched = [row for row, record in pairs if not record["cache_served"] and row["id"] not in skip]
    safe, search = M.safe_decisions(rows), M.retrieval(searched)
    first_fix = M.dist([record["first_fix_s"] * 1000 for _, record in pairs if record["first_fix_s"] is not None])
    retrieval = M.dist([ms for _, record in pairs for ms in record["retrieval_ms"]])
    return {"first_attempt_correct": M.resolution([rows])["gold_first_attempt_correct"],
            "wrong_fix_rate": safe["wrong_fix_rate"], "wrong_first_fix_answerable": safe["wrong_first_fix_on_gold"],
            "escalation_recall": safe["escalation_recall"], "escalation_precision": safe["escalation_precision"],
            "unnecessary_escalation": safe["unnecessary_escalation_rate"],
            "recall_at_3": search["recall@3"], "mrr": search["mrr"],
            "questions_per_case": M.effort(rows)["questions_per_case"]["mean"],
            "first_fix_p50_ms": first_fix["p50"], "first_fix_p95_ms": first_fix["p95"],
            "citation_validity": M.drafting(searched)["citation_valid"],
            "retrieval_p50_ms": retrieval["p50"], "retrieval_p95_ms": retrieval["p95"], "repeat_speedup": repeat_speedup}


def summarize(done: list[tuple[str, dict, dict]], skip: frozenset | set = frozenset()) -> dict:
    records = [record for _, _, record in done]
    latency = T.latency_summary(records)
    first = [(row, record) for phase, row, record in done if phase == "first_ask"]
    return {"metrics": measure(first, latency["repeat_speedup"], skip), "cache": T.cache_summary(records), "latency": latency,
            "cost": T.cost_summary(records), "cache_savings": T.cache_savings(records)}


# ---------------------------------------------------------------- tables

def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% interval for a share, in percent. Wilson, because the shares here rest on a few dozen cases."""
    p, d = k / n, 1 + z * z / n
    centre, half = (p + z * z / (2 * n)) / d, z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round(100 * (centre - half), 1), round(100 * (centre + half), 1)


def fmt(v) -> str:
    if M.is_rate(v):
        if not v["n"]:
            return "n/a"
        lo, hi = wilson(v["k"], v["n"])
        return f"{v['value'] * 100:.1f}% [{lo}-{hi}] ({v['k']}/{v['n']})"
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:,.0f}" if abs(v) >= 100 else f"{v:.4g}"
    return f"{v:,}"


def table(arms: dict[str, dict]) -> list[tuple[str, str, str, dict]]:
    """(section, label, definition, {arm: value}) for every row of both tables."""
    core = [("Core metrics (first ask)", label, text, {a: s["metrics"][key] for a, s in arms.items()}) for key, label, text in CORE]
    tele = [("Cache, latency and cost (whole stream)", label, "", {a: get(s) for a, s in arms.items()}) for label, get in TELEMETRY]
    return core + tele


def write_markdown(path: Path, meta: dict, rows: list, arms: dict) -> None:
    names = [f"{a} {ARM_NAMES[a]}" for a in arms]
    lines = ["# Ablation: baseline, + KG, + KG + Jev", "", "```json", json.dumps(meta, indent=2, default=str), "```", ""]
    for section in dict.fromkeys(r[0] for r in rows):
        lines += [f"## {section}", "", "| Metric | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
        lines += [f"| {label} | " + " | ".join(fmt(v[a]) for a in arms) + " |" for sec, label, _, v in rows if sec == section]
        lines.append("")
    lines += ["## Definitions", ""] + [f"* **{label}**: {text}" for _, label, text, _ in rows if text]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["section", "metric", "arm", "value", "k", "n"])
        for section, label, _, values in rows:
            for arm, v in values.items():
                w.writerow([section, label, arm, v["value"] if M.is_rate(v) else v, v["k"] if M.is_rate(v) else "", v["n"] if M.is_rate(v) else ""])


# ---------------------------------------------------------------- run

def ensure_seed() -> int | None:
    """The Clarifier breaks ties by hash order, so without a fixed PYTHONHASHSEED two runs differ and cannot be compared. When it is not set,
    run this same command again with it set to 0. Returns that run's exit code, or None when the seed was already set."""
    if os.environ.get("PYTHONHASHSEED") is not None:
        return None
    return subprocess.call([sys.executable, "-m", "triage.eval.ablation", *sys.argv[1:]], env={**os.environ, "PYTHONHASHSEED": "0"})


def git_dirty() -> bool | None:
    """True when tracked files have uncommitted changes: the commit hash in the metadata then does not describe the code that ran."""
    try:
        status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True, cwd=OUT_DIR.parents[1], timeout=10)
        return bool(status.stdout.strip())
    except Exception:  # noqa: BLE001 -- not a git checkout is fine
        return None


def print_definitions() -> None:
    print("The 9 core metrics (computed on the first ask; for 5 and 8, questions that any arm served from the cache are skipped in every arm):\n")
    for _, label, text in CORE:
        print(f"  {label}\n      {text}")
    print("\nTelemetry over the whole stream: " + "; ".join(label for label, _ in TELEMETRY) + ".\n"
          "  Cache hit rate = served from cache (exact or semantic) / cases that consulted the cache. Precision = served answers whose first fix is the "
          "gold fix / served answers; false-hit rate = 1 - precision.\n  Savings vs baseline arm = 1 - (this arm / baseline arm) for model calls, input "
          "tokens and USD.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the ablation arms on the same question stream and compare them.")
    ap.add_argument("--arms", nargs="+", default=["A", "B", "C"], choices=list(ARMS))
    ap.add_argument("--scenarios", type=Path, nargs="*", default=None, help="scenario file(s) (default: triage/eval/scenarios.jsonl)")
    ap.add_argument("--llm", default="fake", help="Resolver model: fake | gemini | anthropic | openai (default fake: offline, free)")
    ap.add_argument("--repeat-fraction", type=float, default=0.3, help="share of scenarios asked a second time (default 0.3)")
    ap.add_argument("--seed", type=int, default=0, help="chooses which scenarios are repeated")
    ap.add_argument("--cache", choices=["on", "off"], default=None, help="override use_semantic_cache for every arm")
    ap.add_argument("--limit", type=int, default=None, help="only the first N scenarios (a quick look)")
    ap.add_argument("--max-rpm", type=int, default=None, help="model requests per minute to stay under (see your project's limit in AI Studio); default: no limit")
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    ap.add_argument("--definitions", action="store_true", help="print the metric definitions and stop")
    ap.add_argument("--recompute", type=Path, default=None, metavar="RUN_DIR", help="rebuild the tables of an earlier run from its logs: no model calls")
    ap.add_argument("--max-failures", type=int, default=MAX_FAILURES, help="stop the run when this many model calls have failed even after retries")
    args = ap.parse_args()
    if args.definitions:
        return print_definitions()
    if args.recompute:
        return finish(*reload(args.recompute), args.recompute)
    if (code := ensure_seed()) is not None:
        raise SystemExit(code)

    from triage.resolver.llm import get_llm
    from triage.sim.customer import load_scenarios
    os.environ.pop("TICKET_WRITEBACK", None)                      # an evaluation must not feed the historical dataset
    scenarios = [s for path in (args.scenarios or [None]) for s in load_scenarios(path)][:args.limit]
    stream = build_stream(scenarios, args.repeat_fraction, args.seed)
    estimate = round((len(stream) + 1) * len(args.arms) * CALLS_PER_CASE)
    print(f"{len(stream)} queries x {len(args.arms)} arm(s): about {estimate} model calls (estimate from earlier real runs: {CALLS_PER_CASE} per case, "
          f"about $0.001 per case on gemini-3.5-flash-lite)" + (f"; at {args.max_rpm}/min that is at least {estimate / args.max_rpm:.0f} minutes." if args.max_rpm else "."))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    llm, started, notes, pacer = get_llm(args.llm), time.time(), [], Pacer(args.max_rpm)
    (args.out_dir / "queries.jsonl").write_text("", encoding="utf-8")             # the arms append one line per query
    arm_features = {arm: ARMS[arm] if args.cache is None else Features(**{**ARMS[arm].to_dict(), "use_semantic_cache": args.cache == "on"})
                    for arm in args.arms}
    jev = None
    if any(f.use_jev for f in arm_features.values()):
        from triage.jev import MODEL
        from triage.resolver.jev_gate import JevGateConfig
        jev = {"backend": "fake" if os.environ.get("JEV_BACKEND", "").lower() == "fake" else "openrouter", "model": os.environ.get("JEV_MODEL") or MODEL,
               **JevGateConfig.from_env().__dict__}
    done_by_arm = run_arms(arm_features, stream, llm, args.out_dir, pacer, args.max_failures)
    for arm, done in done_by_arm.items():
        rows = [row for phase, row, _ in done if phase == "first_ask"]
        (args.out_dir / f"rows_{arm}.json").write_text(json.dumps({"rows": rows}, indent=1, default=str), encoding="utf-8")
    meta = {"date": time.strftime("%Y-%m-%d %H:%M"), "git_commit": M.git_commit(), "git_dirty": git_dirty(), "pythonhashseed": os.environ.get("PYTHONHASHSEED"),
            "llm": args.llm, "model": getattr(llm, "model", None), "seconds": round(time.time() - started, 1),
            "scenario_files": [str(p) for p in args.scenarios or ["triage/eval/scenarios.jsonl"]], "scenarios": len(scenarios),
            "stream": {"first_ask": len(scenarios), "repeat": len(stream) - len(scenarios), "seed": args.seed},
            "arms": {a: {**ARMS[a].to_dict(), "name": ARM_NAMES[a]} for a in args.arms}, "baseline_arm": args.arms[0], "jev": jev, "notes": sorted(set(notes))}
    finish(done_by_arm, meta, args.out_dir)


def finish(done_by_arm: dict, meta: dict, out_dir: Path) -> None:
    """Summaries, tables and the end-of-run check, from finished arms (or arms reloaded from their logs)."""
    skip = {record["id"] for done in done_by_arm.values() for phase, _, record in done if phase == "first_ask" and record["cache_served"]}
    summaries = {arm: summarize(done, skip) for arm, done in done_by_arm.items()}
    for s in summaries.values():
        s["vs_baseline"] = T.versus(s["cost"], summaries[meta["baseline_arm"]]["cost"])
    rows = table(summaries)
    (out_dir / "summary.json").write_text(json.dumps({"meta": meta, "arms": summaries}, indent=2, default=str), encoding="utf-8")
    write_markdown(out_dir / "comparison.md", meta, rows, summaries)
    write_csv(out_dir / "comparison.csv", rows)
    print("\n".join(f"{label:<44}" + "  ".join(f"{a}: {fmt(v[a]):<34}" for a in summaries) for sec, label, _, v in rows))
    print("\n".join(meta["notes"]) + f"\nreports: {out_dir}")
    failed = {a: s["cost"]["llm_errors"] for a, s in summaries.items() if s["cost"]["llm_errors"]}
    if failed:
        raise SystemExit(f"RUN INVALID: model calls failed ({failed}). Some steps carry on after a failure, so these numbers are not "
                         "comparable. Fix the cause (quota, network) and run again.")


def reload(out_dir: Path) -> tuple[dict, dict]:
    """The finished arms of an earlier run, rebuilt from its raw logs (queries.jsonl, rows_<arm>.json): no model calls. Use it after a
    metric definition changes, so a paid run never has to be repeated just to re-tabulate."""
    old = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))["meta"]
    records = [json.loads(line) for line in (out_dir / "queries.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    done = {}
    for arm in old["arms"]:
        rows = {r["id"]: r for r in json.loads((out_dir / f"rows_{arm}.json").read_text(encoding="utf-8"))["rows"]}
        done[arm] = [(r["phase"], rows.get(r["id"]) if r["phase"] == "first_ask" else None, r) for r in records if r["arm"] == arm]
    return done, {**old, "recomputed": time.strftime("%Y-%m-%d %H:%M")}


if __name__ == "__main__":
    main()
