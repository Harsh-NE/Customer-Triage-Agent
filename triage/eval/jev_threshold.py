"""jev_threshold.py -- choose the bar Jev must clear to turn a refusal into an answer, from a run's per-query log.

Use it on a shadow run (JEV_MODE=shadow): Jev was asked about every case the rules refused, and nothing changed. For each candidate bar it
shows how many refusals would flip to answers, and how many of those are cases with a documented answer (a flip that could be right) against
cases with none (a flip that is certainly a wrong answer). The log does not say whether the drafted answer would have been right, so
"documented" is an upper bound on the good flips.

    python -m triage.eval.jev_threshold reports/ablation/<run>              # prints the table
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

BARS = (0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 0.98)


def load(run_dir: Path) -> list[dict]:
    """First-ask cases where Jev was consulted and answered (a failed call has no probability)."""
    rows = [json.loads(line) for line in (run_dir / "queries.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    return [r for r in rows if r["phase"] == "first_ask" and r.get("jev_p") is not None]


def table(rows: list[dict], bars=BARS) -> list[dict]:
    out = []
    for bar in bars:
        flipped = [r for r in rows if r["jev_p"] >= bar]
        good = sum(r["has_gold"] for r in flipped)
        out.append({"bar": bar, "flips": len(flipped), "documented": good, "undocumented": len(flipped) - good,
                    "share_documented": round(good / len(flipped), 3) if flipped else None})
    return out


def recommend(rows: list[dict], bars=BARS) -> float | None:
    """The lowest bar at which no undocumented case flips and something still does; None when no bar achieves both."""
    for line in table(rows, bars):
        if line["flips"] and not line["undocumented"]:
            return line["bar"]
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("run_dir", type=Path)
    args = ap.parse_args()
    rows = load(args.run_dir)
    if not rows:
        raise SystemExit(f"{args.run_dir}: no first-ask case has a Jev probability. Run arm C (JEV_MODE=shadow) first.")
    answerable = sum(r["has_gold"] for r in rows)
    print(f"{len(rows)} refusals went to Jev: {answerable} have a documented answer, {len(rows) - answerable} do not.\n")
    print(f"{'bar':>5} {'flips':>6} {'documented':>11} {'undocumented':>13}")
    for line in table(rows):
        print(f"{line['bar']:>5} {line['flips']:>6} {line['documented']:>11} {line['undocumented']:>13}")
    bar = recommend(rows)
    print(f"\nLowest bar with no undocumented flip: {bar if bar is not None else 'none. Jev is not separating the two groups on this run'}")
    print("With few documented cases, treat this as a guide: pick the bar on one run and judge it on another.")


if __name__ == "__main__":
    main()
