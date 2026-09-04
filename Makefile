.PHONY: dev train test sim help

help:
	@echo "RecoverAI Command Center:"
	@echo "  make dev      - Train ML model and start FastAPI server on http://localhost:8000"
	@echo "  make train    - Train ML XGBoost + Isotonic calibration model"
	@echo "  make test     - Run full 60-test automated suite across all milestones"
	@echo "  make sim      - Run batch simulation (50 cases)"

dev:
	./run_dev.sh

train:
	PYTHONPATH=. python3 ml/training/train.py

test:
	./run_tests.sh

sim:
	./run_simulation.sh 50 42
