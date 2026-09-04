#!/usr/bin/env bash
set -e

echo "=================================================="
echo "🧪 Running RecoverAI Automated Test Suite"
echo "=================================================="

# Check if specific test file or flag is passed
if [ -n "$1" ]; then
    echo "Running specific test target: $1"
    PYTHONPATH=. pytest "$1" -v
else
    echo "Running complete test suite across all 7 Milestones (60 Tests)..."
    PYTHONPATH=. pytest backend/tests/ -v
fi

echo ""
echo "=================================================="
echo "✅ All automated tests passed successfully!"
echo "=================================================="
