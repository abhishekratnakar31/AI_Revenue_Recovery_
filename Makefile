.PHONY: dev frontend clean-ports train test sim help

help:
	@echo "RecoverAI Command Center:"
	@echo "  make dev         - Start FastAPI backend server on http://localhost:8000"
	@echo "  make frontend    - Start Next.js Merchant Control Center on http://localhost:3000"
	@echo "  make clean-ports - Kill any hung processes on ports 8000 and 3000"
	@echo "  make train       - Train ML XGBoost + Isotonic calibration model"
	@echo "  make test        - Run full automated test suite across all milestones"
	@echo "  make sim         - Run batch simulation (50 cases)"

dev:
	./run_dev.sh

frontend:
	cd frontend && npm run dev

clean-ports:
	@lsof -ti :8000 | xargs kill -9 2>/dev/null || true
	@lsof -ti :3000 | xargs kill -9 2>/dev/null || true
	@echo "Ports 8000 and 3000 cleaned."

train:
	PYTHONPATH=. python3 ml/training/train.py

test:
	./run_tests.sh

sim:
	./run_simulation.sh 50 42
