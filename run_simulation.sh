#!/usr/bin/env bash
set -e

CASES=${1:-50}
SEED=${2:-42}
TIMESTAMP=$(date +%s)
RUN_ID=${3:-"run_${TIMESTAMP}"}

echo "=================================================="
echo "🎲 Running RecoverAI Batch Simulation Engine"
echo "  - Cases: $CASES"
echo "  - Random Seed: $SEED"
echo "  - Run ID: $RUN_ID"
echo "=================================================="

PYTHONPATH=. python3 simulation/runner.py --cases="$CASES" --seed="$SEED" --run-id="$RUN_ID"

echo ""
echo "=================================================="
echo "✅ Batch simulation completed!"
echo "=================================================="
