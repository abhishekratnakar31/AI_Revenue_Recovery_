"""
Preset Runner Module for RecoverAI.

Executes deterministic presets through the simulation runner and compares actual
decisions and outcomes against expected preset definitions.
"""

import argparse
import json
import logging
from typing import Dict, Any, List

from backend.app.core.database import SessionLocal
from simulation.presets import PRESETS, get_preset, list_presets
from simulation.runner import process_simulation_case

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


import time

def run_preset(preset_key: str, seed: int = 42, db_session=None, run_tag: Optional[str] = None) -> Dict[str, Any]:
    """Execute a single preset by key and return the full case metrics."""
    preset = get_preset(preset_key)
    
    if not run_tag:
        run_tag = f"run_{time.time_ns()}"

    close_db = False
    if db_session is None:
        db_session = SessionLocal()
        close_db = True

    try:
        case_dict = process_simulation_case(
            case_index=1,
            seed=seed,
            db=db_session,
            preset=preset,
            run_tag=run_tag
        )

        actual_action = case_dict.get("chosen_action", "NO_ACTION")
        actual_outcome = case_dict.get("recovery_status", "UNKNOWN")
        actual_notif = case_dict.get("notification_status")
        actual_group = case_dict.get("experiment_group")

        match_action = (actual_action == preset.expected_action)
        match_outcome = (actual_outcome == preset.expected_outcome)
        match_group = (actual_group == preset.experiment_group)
        match_notif = True
        if preset.expected_notification_status is not None:
            match_notif = (actual_notif == preset.expected_notification_status)

        passed = match_action and match_outcome and match_group and match_notif

        case_dict["preset_validation"] = {
            "preset_key": preset_key,
            "expected_action": preset.expected_action,
            "actual_action": actual_action,
            "match_action": match_action,
            "expected_outcome": preset.expected_outcome,
            "actual_outcome": actual_outcome,
            "match_outcome": match_outcome,
            "expected_group": preset.experiment_group,
            "actual_group": actual_group,
            "match_group": match_group,
            "expected_notification_status": preset.expected_notification_status,
            "actual_notification_status": actual_notif,
            "match_notification": match_notif,
            "passed": passed,
        }

        return case_dict

    finally:
        if close_db:
            db_session.close()


def run_all_presets(seed: int = 42, db_session=None, run_tag: Optional[str] = None) -> List[Dict[str, Any]]:
    """Execute all 7 presets and return detailed validation results."""
    results = []
    base_tag = run_tag or f"batch_{time.time_ns()}"
    for preset_key in PRESETS.keys():
        logger.info(f"Running preset: {preset_key}")
        p_tag = f"{base_tag}_{preset_key.lower()}"
        res = run_preset(preset_key, seed=seed, db_session=db_session if db_session else None, run_tag=p_tag)
        results.append(res)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RecoverAI Preset Runner CLI")
    parser.add_argument("--preset", type=str, default=None, help="Name of preset to run (runs all if not specified)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for simulation")
    args = parser.parse_args()

    if args.preset:
        res = run_preset(args.preset, seed=args.seed)
        print(json.dumps(res, indent=2, default=str))
    else:
        results = run_all_presets(seed=args.seed)
        summary = {
            "total_presets": len(results),
            "passed": sum(1 for r in results if r["preset_validation"]["passed"]),
            "failed": sum(1 for r in results if not r["preset_validation"]["passed"]),
            "results": [r["preset_validation"] for r in results]
        }
        print(json.dumps(summary, indent=2, default=str))
