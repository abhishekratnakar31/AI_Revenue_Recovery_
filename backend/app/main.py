"""
RecoverAI FastAPI Main Entrypoint Module

This is the primary application entrypoint for the RecoverAI backend server.

Responsibilities:
1. Initializes the FastAPI instance with project metadata and configuration settings.
2. Registers API routers (/webhooks, /simulation, /cases, /experiments).
3. Exposes operational health check and interactive testing routes.
"""

from typing import Optional
from pydantic import BaseModel
from fastapi import FastAPI, Depends, HTTPException, Query, Body, status
from sqlalchemy.orm import Session
from sqlalchemy import text

from backend.app.core.config import settings
from backend.app.core.database import get_db, engine, Base
from backend.app.models.models import RecoveryCase, Customer, Order, Payment, Outcome, PolicyDecision, AuditLog
from backend.app.webhooks.receiver import router as webhook_router
from backend.app.recovery.eligibility import evaluate_eligibility
from backend.app.risk.gate import evaluate_risk
from backend.app.policies.engine import evaluate_policy
from backend.app.experiments.registry import get_or_create_experiment, get_experiment_metrics
from simulation.runner import run_simulation_batch

from fastapi.middleware.cors import CORSMiddleware
from backend.app.api.v1.router import api_v1_router

# Create database tables if they do not exist
Base.metadata.create_all(bind=engine)

# Initialize FastAPI Application
app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="AI-powered revenue recovery and payment intelligence platform"
)

# Configure CORS Middleware for Next.js Dashboard Frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register Webhook Router & Canonical API v1 Router
app.include_router(webhook_router)
app.include_router(api_v1_router, prefix="/api/v1")


@app.get("/", tags=["Operational"])
def read_root():
    """
    Root API endpoint returning application metadata and environment status.
    """
    return {
        "project": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "status": "running"
    }


@app.get("/health", tags=["Operational"])
def health_check(db: Session = Depends(get_db)):
    """
    Health check endpoint for monitoring system readiness and database connectivity.
    """
    db_status = "disconnected"
    try:
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {str(e)}"

    return {
        "status": "ok" if db_status == "connected" else "degraded",
        "project": settings.PROJECT_NAME,
        "environment": settings.ENVIRONMENT,
        "database": db_status
    }


class SimulationRunRequest(BaseModel):
    num_cases: Optional[int] = 20
    random_seed: Optional[int] = 42


from fastapi.concurrency import run_in_threadpool
from backend.app.core.database import get_db, engine, Base, SessionLocal

@app.post("/simulation/run", tags=["Simulation & Testing"])
async def run_simulation(
    req: Optional[SimulationRunRequest] = Body(None),
    num_cases: Optional[int] = Query(None),
    random_seed: Optional[int] = Query(None),
):
    """
    Triggers a synthetic batch simulation run generating payment failures, evaluating risk/policies,
    and recording recovery outcomes asynchronously offloaded to a threadpool.
    """
    cases = (req.num_cases if req and req.num_cases is not None else (num_cases or 20))
    seed = (req.random_seed if req and req.random_seed is not None else (random_seed or 42))

    def _worker():
        session = SessionLocal()
        try:
            return run_simulation_batch(session, num_cases=cases, random_seed=seed, auto_process=True)
        finally:
            session.close()

    summary = await run_in_threadpool(_worker)
    return summary


@app.get("/cases/{case_id}", tags=["Recovery Cases"])
def get_case_details(case_id: int, db: Session = Depends(get_db)):
    """
    Retrieves full details for a RecoveryCase including customer, order, payment attempts,
    state machine status, policy decisions, and outcome metrics.
    """
    case = db.query(RecoveryCase).filter(RecoveryCase.id == case_id).first()
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Case #{case_id} not found")

    customer = db.query(Customer).filter(Customer.id == case.customer_id).first()
    order = db.query(Order).filter(Order.id == case.order_id).first() if case.order_id else None
    payment = db.query(Payment).filter(Payment.id == case.payment_id).first() if case.payment_id else None
    policy_decisions = db.query(PolicyDecision).filter(PolicyDecision.recovery_case_id == case.id).all()
    audit_logs = db.query(AuditLog).filter(AuditLog.case_id == case.id).all()

    return {
        "case_id": case.id,
        "status": case.status,
        "amount_at_risk": case.amount_at_risk,
        "case_type": case.case_type,
        "customer": {
            "id": customer.id if customer else None,
            "external_id": customer.external_customer_id if customer else None,
            "segment": customer.customer_segment if customer else None,
            "opt_out": customer.opt_out if customer else None
        },
        "order": {
            "id": order.id if order else None,
            "razorpay_order_id": order.razorpay_order_id if order else None,
            "status": order.status if order else None
        },
        "payment": {
            "id": payment.id if payment else None,
            "razorpay_payment_id": payment.razorpay_payment_id if payment else None,
            "status": payment.status if payment else None,
            "method": payment.payment_method if payment else None
        },
        "policy_decisions": [
            {"action": p.action_type, "decision": p.decision, "reason": p.reason} for p in policy_decisions
        ],
        "audit_trail_count": len(audit_logs),
        "created_at": case.created_at,
        "closed_at": case.closed_at
    }


@app.get("/experiments/metrics", tags=["Experiments & Baselines"])
def get_ab_metrics(
    experiment_name: str = Query("default_recovery_ab", description="Experiment identifier name"),
    db: Session = Depends(get_db)
):
    """
    Returns live performance metrics and recovery rates across A/B experiment groups
    (TREATMENT vs CONTROL vs NO_INTERVENTION).
    """
    exp = get_or_create_experiment(db, name=experiment_name)
    metrics = get_experiment_metrics(db, exp.id)
    return metrics
