"""
Incremental Net Revenue Attribution Report REST Endpoint for RecoverAI API v1.
Implements mandatory experiment_id scoping and 30-second TTL caching.
"""

import time
from typing import Dict, Any, Tuple
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.schemas.dashboard_schemas import (
    AttributionReportResponse,
    AttributionRecoveryEffect,
    AttributionFinancialEffect,
    SRMCheck,
)
from backend.app.analytics.attribution import AttributionEngine
from backend.app.models.models import Experiment
from backend.app.api.v1.auth import get_current_merchant_id

router = APIRouter(prefix="/attribution", tags=["Attribution Analytics"])

# 30-second in-memory TTL cache: {experiment_id: (timestamp, report_dict)}
_ATTRIBUTION_CACHE: Dict[int, Tuple[float, Dict[str, Any]]] = {}
_CACHE_TTL_SECONDS = 30.0


def clear_attribution_cache():
    """Utility to clear cache during testing."""
    _ATTRIBUTION_CACHE.clear()


@router.get("/report", response_model=AttributionReportResponse)
def get_attribution_report(
    experiment_id: int = Query(..., description="Mandatory experiment ID for attribution scoping"),
    merchant_id: int = Depends(get_current_merchant_id),
    db: Session = Depends(get_db)
):
    """
    Returns full Milestone 12 Attribution Report:
    - Metric A: Recovery Effect (Binary Two-Proportion Z-Test)
    - Metric B: Financial Effect (Net Revenue NRR lift, sample variance 95% CIs)
    - SRM Chi-Square & p-value (p = 1.0000)
    - Zero Natural Recovery Overcounting

    Requires mandatory experiment_id query parameter. Caches report for 30s.
    """
    exp = db.query(Experiment).filter(Experiment.id == experiment_id).first()
    if not exp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Experiment #{experiment_id} not found."
        )

    now = time.time()
    if experiment_id in _ATTRIBUTION_CACHE:
        cached_time, cached_report = _ATTRIBUTION_CACHE[experiment_id]
        if now - cached_time < _CACHE_TTL_SECONDS:
            report = cached_report
        else:
            report = AttributionEngine.compute_incremental_attribution(db, experiment_id)
            _ATTRIBUTION_CACHE[experiment_id] = (now, report)
    else:
        report = AttributionEngine.compute_incremental_attribution(db, experiment_id)
        _ATTRIBUTION_CACHE[experiment_id] = (now, report)

    bal = AttributionEngine.verify_experiment_balance(db, experiment_id)

    rec_fx = report["recovery_effect"]
    fin_fx = report["financial_effect"]
    srm = bal["srm_check"]

    rec_response = AttributionRecoveryEffect(
        control_recovery_rate_pct=rec_fx["control_recovery_rate_pct"],
        treatment_recovery_rate_pct=rec_fx["treatment_recovery_rate_pct"],
        incremental_recovery_rate_pp=rec_fx["incremental_recovery_rate_pp"],
        confidence_interval_95_pp=rec_fx["confidence_interval_95_pp"],
        z_statistic=rec_fx["z_statistic"],
        p_value=rec_fx["p_value"],
        statistically_significant=rec_fx["statistically_significant"],
    )

    fin_response = AttributionFinancialEffect(
        currency="INR",
        control_net_recovery_rate_pct=fin_fx["control_net_recovery_rate_pct"],
        treatment_net_recovery_rate_pct=fin_fx["treatment_net_recovery_rate_pct"],
        incremental_nrr_pp=fin_fx["incremental_nrr_pp"],
        relative_lift_pct=fin_fx["relative_lift_pct"],
        incremental_net_revenue=f"{fin_fx['incremental_net_revenue']:.2f}",
        confidence_interval_95_pp=fin_fx["confidence_interval_95_pp"],
        confidence_interval_95_revenue=[
            f"{fin_fx['confidence_interval_95_revenue'][0]:.2f}",
            f"{fin_fx['confidence_interval_95_revenue'][1]:.2f}",
        ],
    )

    srm_response = SRMCheck(
        chi_square=srm["chi_square"],
        p_value=srm["p_value"],
        **{"pass": srm["pass"]}
    )

    return AttributionReportResponse(
        experiment_id=experiment_id,
        observation_window_days=30,
        currency="INR",
        control=report["control"],
        treatment=report["treatment"],
        srm_check=srm_response,
        overall_balance_pass=bal["overall_balance_pass"],
        recovery_effect=rec_response,
        financial_effect=fin_response,
    )
