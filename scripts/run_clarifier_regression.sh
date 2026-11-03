#!/usr/bin/env bash
# Run the same evaluations before and after a Clarifier change and keep each run's reports apart.
#
#   bash scripts/run_clarifier_regression.sh before      # then change the code
#   bash scripts/run_clarifier_regression.sh after
#
# Fixed PYTHONHASHSEED so the Clarifier's tie-breaking is the same in both runs; the fake drafting model, so it is free and offline.
# Reports land in reports/regression/<tag>_*.{json,md}. The held-out file has draft labels (see the report's unverified_labels).
set -euo pipefail
TAG="${1:?usage: run_clarifier_regression.sh <tag>}"
OUT=reports/regression
mkdir -p "$OUT"
export PYTHONHASHSEED=0 HF_HUB_OFFLINE=1

echo "== Clarifier on its own, 29 scenarios ($TAG)"
python -m triage.eval.clarifier_eval --out-json "$OUT/${TAG}_clarifier.json" --out-md "$OUT/${TAG}_clarifier.md" > "$OUT/${TAG}_clarifier.log" 2>&1

echo "== End to end, 29 scenarios ($TAG)"
python -m triage.eval.agent_metrics --clarifier --out-json "$OUT/${TAG}_scenarios.json" --out-md "$OUT/${TAG}_scenarios.md" > "$OUT/${TAG}_scenarios.log" 2>&1

echo "== End to end, 65 held-out real questions ($TAG)"
python -m triage.eval.agent_metrics --scenarios triage/eval/heldout_scenarios.jsonl --clarifier \
    --out-json "$OUT/${TAG}_heldout.json" --out-md "$OUT/${TAG}_heldout.md" > "$OUT/${TAG}_heldout.log" 2>&1

echo "done: $OUT/${TAG}_*"
