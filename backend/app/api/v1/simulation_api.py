"""
Synthetic Simulation REST Endpoint for RecoverAI API v1 (Demo/Lab Mode).
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.schemas.dashboard_schemas import SimulationRunRequest, SimulationRunResponse
from simulation.runner import run_simulation_batch

router = APIRouter(prefix="/simulation", tags=["Demo & Lab Simulation"])


@router.post("/run", response_model=SimulationRunResponse)
def run_simulation_endpoint(
    payload: SimulationRunRequest,
    db: Session = Depends(get_db)
):
    """
    Triggers a synthetic batch simulation run generating payment failures, evaluating risk/policies,
    and recording recovery outcomes (Demo / Lab Mode).
    """
    summary = run_simulation_batch(
        db=db,
        num_cases=payload.num_cases,
        random_seed=payload.random_seed,
        auto_process=True
    )
    return SimulationRunResponse(
        status="completed",
        cases_processed=payload.num_cases,
        summary=summary,
    )
