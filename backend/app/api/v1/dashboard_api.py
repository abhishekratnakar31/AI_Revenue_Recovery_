"""
Dashboard Summary REST Endpoint for RecoverAI API v1.
"""

from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.schemas.dashboard_schemas import DashboardSummaryResponse
from backend.app.analytics.attribution import AttributionEngine
from backend.app.models.models import RecoveryCase, Outcome, Experiment, RecoveryAction
from backend.app.api.v1.auth import get_current_merchant_id

router = APIRouter(prefix="/dashboard", tags=["Dashboard Summary"])


@router.get("/summary", response_model=DashboardSummaryResponse)
def get_dashboard_summary(
    experiment_id: Optional[int] = Query(None, description="Optional experiment ID filter"),
    merchant_id: int = Depends(get_current_merchant_id),
    db: Session = Depends(get_db)
):
    """
    Returns top-level merchant KPIs (Amount at Risk, Cash Collected, Incremental Net Revenue, NRR %, Recovery Rate %).
    Scopes metrics to the requested experiment or active default experiment.
    """
    if experiment_id is None:
        exp = db.query(Experiment).order_by(Experiment.id.desc()).first()
        experiment_id = exp.id if exp else 1

    exp_obj = db.query(Experiment).filter(Experiment.id == experiment_id).first()
    exp_name = exp_obj.name if exp_obj else f"Experiment #{experiment_id}"

    # Compute Attribution Report for requested experiment
    report = AttributionEngine.compute_incremental_attribution(db, experiment_id)
    trt = report.get("treatment", {})
    ctrl = report.get("control", {})
    fin_fx = report.get("financial_effect", {})
    rec_fx = report.get("recovery_effect", {})

    active_cases = db.query(RecoveryCase).filter(RecoveryCase.status.in_(["RECOVERY_ELIGIBLE", "RECOVERY_ACTIVE"])).count()
    deployed_actions = db.query(RecoveryAction).count()

    total_amt_risk = trt.get("total_amount_at_risk", 0.0) + ctrl.get("total_amount_at_risk", 0.0)
    total_cash_col = trt.get("cash_collected", 0.0) + ctrl.get("cash_collected", 0.0)
    incr_rev = fin_fx.get("incremental_net_revenue", 0.0)

    # Fallback to system-wide metrics if experiment has no assignments yet or cash collected is 0
    if total_amt_risk == 0.0 or total_cash_col == 0.0:
        all_cases = db.query(RecoveryCase).all()
        if total_amt_risk == 0.0:
            total_amt_risk = sum(c.amount_at_risk or 0.0 for c in all_cases)
        all_outcomes = db.query(Outcome).filter((Outcome.payment_success == True) | (Outcome.is_recovered == True)).all()
        cash_col_fallback = sum(o.gross_recovered or o.net_recovered or 0.0 for o in all_outcomes)
        if total_cash_col == 0.0:
            total_cash_col = cash_col_fallback

    return DashboardSummaryResponse(
        merchant_id=merchant_id,
        experiment_id=experiment_id,
        experiment_name=exp_name,
        currency="INR",
        amount_at_risk=f"{total_amt_risk:.2f}",
        cash_collected=f"{total_cash_col:.2f}",
        incremental_net_revenue=f"{incr_rev:.2f}",
        nrr_percent=round(trt.get("net_recovery_rate", 0.0) * 100.0, 2),
        recovery_rate_percent=round(rec_fx.get("treatment_recovery_rate_pct", 0.0), 2),
        active_recovery_cases=active_cases,
        deployed_actions=deployed_actions,
        time_scope="CURRENT_EXPERIMENT",
    )
