"""
Preset Simulation Endpoints for RecoverAI API v1.
"""

from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from simulation.presets import list_presets, PRESETS
from simulation.preset_runner import run_preset, run_all_presets

router = APIRouter(prefix="/presets", tags=["Presets"])

# Alias mapping for UI card keys to backend preset keys
KEY_ALIASES = {
    "CONFIRMED_GATEWAY_OUTAGE": "CONFIRMED_HDFC_DEGRADATION",
    "BUDGET_CUSTOMER_INCENTIVE": "BUDGET_DISCOUNT_RECOVERY",
}


class PresetRunRequest(BaseModel):
    preset_name: Optional[str] = None
    preset_key: Optional[str] = None
    seed: int = 42
    random_seed: Optional[int] = None


@router.get("", response_model=List[Dict[str, Any]])
def get_presets_list():
    """Returns the list of 7 available deterministic demo presets."""
    return list_presets()


@router.post("/run")
def run_preset_endpoint(payload: PresetRunRequest, db: Session = Depends(get_db)):
    """
    Executes a single preset (if `preset_name` or `preset_key` is provided) or all 7 presets,
    returning execution metrics and expected vs actual validation.
    """
    name = payload.preset_name or payload.preset_key
    seed = payload.random_seed if payload.random_seed is not None else payload.seed

    if name:
        target_key = KEY_ALIASES.get(name, name)
        if target_key not in PRESETS:
            raise HTTPException(
                status_code=404,
                detail=f"Preset '{name}' not found. Available: {list(PRESETS.keys())}"
            )
        result = run_preset(target_key, seed=seed, db_session=db)
        return {
            "status": "completed",
            "preset": target_key,
            "result": result,
            "preset_validation": result.get("preset_validation"),
        }
    else:
        results = run_all_presets(seed=seed, db_session=db)
        passed = sum(1 for r in results if r.get("preset_validation", {}).get("passed"))
        return {
            "status": "completed",
            "total_presets": len(results),
            "passed": passed,
            "failed": len(results) - passed,
            "results": results,
        }


@router.post("/run_all")
def run_all_presets_endpoint(payload: PresetRunRequest, db: Session = Depends(get_db)):
    """Executes all 7 presets."""
    seed = payload.random_seed if payload.random_seed is not None else payload.seed
    results = run_all_presets(seed=seed, db_session=db)
    passed = sum(1 for r in results if r.get("preset_validation", {}).get("passed"))
    return {
        "status": "completed",
        "total_presets": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "results": results,
    }

