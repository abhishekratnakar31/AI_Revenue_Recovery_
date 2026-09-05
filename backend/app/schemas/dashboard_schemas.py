"""
Pydantic API Request and Response Schemas for RecoverAI Merchant Control Center (/api/v1).

Strictly enforces string-decimal monetary values, typed responses, pagination metadata,
and optimistic concurrency control fields.
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


# --- Dashboard Summary ---
class DashboardSummaryResponse(BaseModel):
    merchant_id: int
    experiment_id: int
    experiment_name: str
    currency: str = "INR"
    amount_at_risk: str
    cash_collected: str
    incremental_net_revenue: str
    nrr_percent: float
    recovery_rate_percent: float
    active_recovery_cases: int
    deployed_actions: int
    time_scope: str = "CURRENT_EXPERIMENT"


# --- Attribution Report ---
class AttributionRecoveryEffect(BaseModel):
    control_recovery_rate_pct: float
    treatment_recovery_rate_pct: float
    incremental_recovery_rate_pp: float
    confidence_interval_95_pp: List[float]
    z_statistic: float
    p_value: float
    statistically_significant: bool


class AttributionFinancialEffect(BaseModel):
    currency: str = "INR"
    control_net_recovery_rate_pct: float
    treatment_net_recovery_rate_pct: float
    incremental_nrr_pp: float
    relative_lift_pct: float
    incremental_net_revenue: str
    confidence_interval_95_pp: List[float]
    confidence_interval_95_revenue: List[str]


class SRMCheck(BaseModel):
    chi_square: float
    p_value: float
    is_pass: bool = Field(..., alias="pass")


class AttributionReportResponse(BaseModel):
    experiment_id: int
    observation_window_days: int = 30
    currency: str = "INR"
    control: Dict[str, Any]
    treatment: Dict[str, Any]
    srm_check: SRMCheck
    overall_balance_pass: bool
    recovery_effect: AttributionRecoveryEffect
    financial_effect: AttributionFinancialEffect


# --- Gateway Route Degradation ---
class RoutePolicyRule(BaseModel):
    action_type: str
    permission: str  # ALLOWED, BLOCKED, PROBE
    reason: Optional[str] = None


class RouteStatusItem(BaseModel):
    id: int
    gateway: str
    payment_method: str
    bank: str
    status: str  # NORMAL, SUSPECTED, CONFIRMED, RECOVERING
    current_failure_rate_pct: float
    baseline_failure_rate_pct: float
    current_z_score: float
    total_attempts: int
    failed_attempts: int
    last_evaluated_at: Optional[str] = None
    last_probe_at: Optional[str] = None
    policy_rules: List[RoutePolicyRule]


class RouteDegradationResponse(BaseModel):
    routes: List[RouteStatusItem]
    total_routes: int
    degraded_count: int


# --- Cases List & Details ---
class CaseItemResponse(BaseModel):
    id: int
    customer_id: Optional[int] = None
    customer_external_id: Optional[str] = None
    order_id: Optional[int] = None
    payment_id: Optional[int] = None
    amount_at_risk: str
    currency: str = "INR"
    case_type: str
    status: str
    payment_method: Optional[str] = "UNKNOWN"
    gateway: Optional[str] = "UNKNOWN"
    bank: Optional[str] = "N/A"
    created_at: str
    closed_at: Optional[str] = None


class CaseListResponse(BaseModel):
    items: List[CaseItemResponse]
    page: int
    page_size: int
    total: int
    has_next: bool


class CaseDetailResponse(BaseModel):
    case_id: int
    status: str
    amount_at_risk: str
    currency: str = "INR"
    case_type: str
    customer: Dict[str, Any]
    order: Dict[str, Any]
    payment: Dict[str, Any]
    assignment_group: Optional[str] = None
    policy_decisions: List[Dict[str, Any]]
    created_at: str
    closed_at: Optional[str] = None


# --- Decision Audit Timeline ---
class TimelineStep(BaseModel):
    step_number: int
    step_type: str  # PAYMENT_ATTEMPT, ML_RISK, M8_AGENT_DECISION, M11_ROUTE_GUARDRAIL, M9_ACTION_EXECUTION, M10_COMMUNICATION, M12_FINANCIAL_OUTCOME
    timestamp: str
    title: str
    details: Dict[str, Any]


class CaseTimelineResponse(BaseModel):
    case_id: int
    current_status: str
    steps: List[TimelineStep]


# --- Merchant Policy ---
class MerchantPolicyResponse(BaseModel):
    id: int
    merchant_id: Optional[int] = None
    max_retries: int
    minimum_retry_interval: int
    max_notifications_per_24h: int
    max_discount_percentage: float
    manual_approval_threshold: str
    currency: str = "INR"
    version: int
    updated_at: str


class MerchantPolicyUpdateRequest(BaseModel):
    expected_version: int
    max_retries: Optional[int] = Field(None, ge=0, le=10)
    minimum_retry_interval: Optional[int] = Field(None, ge=1, le=1440)
    max_notifications_per_24h: Optional[int] = Field(None, ge=0, le=10)
    max_discount_percentage: Optional[float] = Field(None, ge=0.0, le=25.0)
    manual_approval_threshold: Optional[float] = Field(None, ge=0.0)


# --- Simulation Run Request & Response ---
class SimulationRunRequest(BaseModel):
    num_cases: int = Field(20, ge=1, le=500)
    random_seed: int = 42


class SimulationRunResponse(BaseModel):
    status: str
    cases_processed: int
    summary: Dict[str, Any]
