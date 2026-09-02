"""
RecoverAI FastAPI Main Entrypoint Module

This is the primary application entrypoint for the RecoverAI backend server.

Responsibilities:
1. Initializes the FastAPI instance with project metadata and configuration settings.
2. Registers API routers (e.g. `/webhooks` router for Razorpay event ingestion).
3. Exposes the root (`/`) and health check (`/health`) operational endpoints.
"""

from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from backend.app.core.config import settings
from backend.app.core.database import get_db
from backend.app.webhooks.receiver import router as webhook_router

# Initialize FastAPI Application
app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="AI-powered revenue recovery and payment intelligence platform"
)

# Register API Routers
app.include_router(webhook_router)


@app.get("/")
def read_root():
    """
    Root API endpoint returning application metadata and environment status.
    
    Returns:
        dict: Application name, version, current environment, and running status.
    """
    return {
        "project": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "status": "running"
    }


@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    """
    Health check endpoint for monitoring system readiness and database connectivity.
    Executes a `SELECT 1` query against PostgreSQL.
    
    Args:
        db (Session): Database session instance injected by get_db dependency.
        
    Returns:
        dict: Status ('ok' or 'degraded'), project name, environment, and database connection status.
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
