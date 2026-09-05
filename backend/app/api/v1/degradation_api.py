"""
Gateway Route Degradation Status REST Endpoint for RecoverAI API v1.
Exposes 3-tuple route statuses with failure rates, Z-scores, and active policy rules.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.schemas.dashboard_schemas import RouteDegradationResponse, RouteStatusItem, RoutePolicyRule
from backend.app.models.models import GatewayRouteStatus
from backend.app.api.v1.auth import get_current_merchant_id

router = APIRouter(prefix="/degradation", tags=["Gateway Degradation Monitor"])


@router.get("/routes", response_model=RouteDegradationResponse)
def get_degradation_routes(
    status_filter: Optional[str] = Query(None, description="Optional status filter: NORMAL, SUSPECTED, CONFIRMED, RECOVERING"),
    merchant_id: int = Depends(get_current_merchant_id),
    db: Session = Depends(get_db)
):
    """
    Returns live health of 3-tuple gateway routes (gateway x payment_method x bank)
    with failure rates, baseline rates, Z-scores, attempt counts, and active policy enforcement rules.
    """
    query = db.query(GatewayRouteStatus)
    if status_filter:
        query = query.filter(GatewayRouteStatus.status == status_filter.upper())

    routes = query.all()
    route_items: List[RouteStatusItem] = []

    degraded_cnt = 0
    for r in routes:
        if r.status in ["SUSPECTED", "CONFIRMED", "RECOVERING"]:
            degraded_cnt += 1

        # Derive active policy enforcement rules
        policy_rules = []
        if r.status == "CONFIRMED":
            policy_rules = [
                RoutePolicyRule(action_type="RETRY", permission="BLOCKED", reason="DEGRADED_ROUTE_PAUSED"),
                RoutePolicyRule(action_type="PAYMENT_LINK", permission="ALLOWED", reason="ALTERNATIVE_CHANNEL_PRESERVED"),
                RoutePolicyRule(action_type="EMAIL_REMINDER", permission="ALLOWED", reason="NON_GATEWAY_ACTION"),
            ]
        elif r.status in ["SUSPECTED", "RECOVERING"]:
            policy_rules = [
                RoutePolicyRule(action_type="RETRY", permission="PROBE", reason="LIMITED_RATE_PROBE_ONLY"),
                RoutePolicyRule(action_type="PAYMENT_LINK", permission="ALLOWED", reason="ALTERNATIVE_CHANNEL_ACTIVE"),
            ]
        else:
            policy_rules = [
                RoutePolicyRule(action_type="RETRY", permission="ALLOWED", reason="HEALTHY_ROUTE"),
                RoutePolicyRule(action_type="PAYMENT_LINK", permission="ALLOWED", reason="HEALTHY_ROUTE"),
            ]

        item = RouteStatusItem(
            id=r.id,
            gateway=r.gateway,
            payment_method=r.payment_method,
            bank=r.bank or "UNKNOWN",
            status=r.status,
            current_failure_rate_pct=round(r.current_failure_rate * 100.0, 2),
            baseline_failure_rate_pct=round(r.baseline_failure_rate * 100.0, 2),
            current_z_score=round(r.current_z_score, 2),
            total_attempts=r.total_attempts,
            failed_attempts=r.failed_attempts,
            last_evaluated_at=r.last_evaluated_at.isoformat() if r.last_evaluated_at else None,
            last_probe_at=r.last_probe_at.isoformat() if r.last_probe_at else None,
            policy_rules=policy_rules,
        )
        route_items.append(item)

    return RouteDegradationResponse(
        routes=route_items,
        total_routes=len(route_items),
        degraded_count=degraded_cnt,
    )
