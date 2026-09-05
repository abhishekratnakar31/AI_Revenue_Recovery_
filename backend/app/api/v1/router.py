"""
Main API Router for RecoverAI API v1 (/api/v1).
"""

from fastapi import APIRouter

from backend.app.api.v1.dashboard_api import router as dashboard_router
from backend.app.api.v1.attribution_api import router as attribution_router
from backend.app.api.v1.degradation_api import router as degradation_router
from backend.app.api.v1.cases_api import router as cases_router
from backend.app.api.v1.policy_api import router as policy_router
from backend.app.api.v1.simulation_api import router as simulation_router
from backend.app.api.v1.preset_api import router as preset_router

api_v1_router = APIRouter()

api_v1_router.include_router(dashboard_router)
api_v1_router.include_router(attribution_router)
api_v1_router.include_router(degradation_router)
api_v1_router.include_router(cases_router)
api_v1_router.include_router(policy_router)
api_v1_router.include_router(simulation_router)
api_v1_router.include_router(preset_router)
