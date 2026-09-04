#!/usr/bin/env bash
set -e

CASES=${1:-50}
SEED=${2:-42}

echo "=================================================="
echo "🎲 Running RecoverAI Batch Simulation Engine"
echo "  - Cases: $CASES"
echo "  - Random Seed: $SEED"
echo "=================================================="

PYTHONPATH=. python3 simulation/runner.py --cases="$CASES" --seed="$SEED"

echo ""
echo "=================================================="
echo "✅ Batch simulation completed!"
echo "=================================================="
