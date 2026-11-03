#!/usr/bin/env bash
# The approved paid run (about $0.10-0.15): the improved code with Gemini on the 29 scenarios and the 65 held-out questions, then the
# faithfulness judge on every fix that was sent. No planted-fault controls (--self-check) because they were not part of the approval.
#
#   bash scripts/run_gemini_after.sh
#
# Reports: reports/regression/gemini_after_{scenarios,heldout}.{json,md}; cost is in each report's "6_cost_and_speed" and "judge" blocks.
set -euo pipefail
OUT=reports/regression
mkdir -p "$OUT"
export PYTHONHASHSEED=0 HF_HUB_OFFLINE=1

echo "== Gemini, 29 scenarios, judged"
python -m triage.eval.agent_metrics --llm gemini --judge gemini \
    --out-json "$OUT/gemini_after_scenarios.json" --out-md "$OUT/gemini_after_scenarios.md" > "$OUT/gemini_after_scenarios.log" 2>&1

echo "== Gemini, 65 held-out questions, judged"
python -m triage.eval.agent_metrics --llm gemini --judge gemini --scenarios triage/eval/heldout_scenarios.jsonl \
    --out-json "$OUT/gemini_after_heldout.json" --out-md "$OUT/gemini_after_heldout.md" > "$OUT/gemini_after_heldout.log" 2>&1

echo "done"
