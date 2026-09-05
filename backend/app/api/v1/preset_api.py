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


class PresetRunRequest(BaseModel):
    preset_name: Optional[str] = None
    seed: int = 42


@router.get("", response_model=List[Dict[str, Any]])
def get_presets_list():
    """Returns the list of 7 available deterministic demo presets."""
    return list_presets()


@router.post("/run")
def run_preset_endpoint(payload: PresetRunRequest, db: Session = Depends(get_db)):
    """
    Executes a single preset (if `preset_name` is provided) or all 7 presets,
    returning execution metrics and expected vs actual validation.
    """
    if payload.preset_name:
        if payload.preset_name not in PRESETS:
            raise HTTPException(
                status_code=404,
                detail=f"Preset '{payload.preset_name}' not found. Available: {list(PRESETS.keys())}"
            )
        result = run_preset(payload.preset_name, seed=payload.seed, db_session=db)
        return {"status": "completed", "preset": payload.preset_name, "result": result}
    else:
        results = run_all_presets(seed=payload.seed, db_session=db)
        passed = sum(1 for r in results if r.get("preset_validation", {}).get("passed"))
        return {
            "status": "completed",
            "total_presets": len(results),
            "passed": passed,
            "failed": len(results) - passed,
            "results": results
        }
