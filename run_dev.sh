#!/usr/bin/env bash
set -e

echo "=================================================="
echo "⚡ Starting RecoverAI ML Pipeline & Backend Server"
echo "=================================================="

# 1. Train ML Model and serialize artifacts
echo "🧠 Training Calibrated ML Model..."
PYTHONPATH=. python3 ml/training/train.py

echo ""
echo "🚀 Starting FastAPI Backend Server on http://localhost:8000..."
echo "  - Swagger UI: http://localhost:8000/docs"
echo "  - Health Check: http://localhost:8000/health"
echo "=================================================="

# 2. Start Uvicorn Server
PYTHONPATH=. uvicorn backend.app.main:app --reload --port 8000
