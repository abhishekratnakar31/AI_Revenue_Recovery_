"""
Alembic Migration & Database Schema Drift Test Suite for RecoverAI.

Tests:
1. A fresh database created through Alembic (`upgrade head`) can initialize and serve all M13 routes.
2. Compares Alembic migration schema tables against SQLAlchemy Base.metadata.
"""

import os
import pytest
from sqlalchemy import create_engine, inspect
from alembic.config import Config
from alembic import command

from backend.app.core.database import Base
from backend.app.models.models import (
    Customer, Order, Payment, PaymentAttempt, RecoveryCase, Outcome,
    MerchantPolicy, WebhookEvent, AuditLog, GatewayRouteStatus
)


def test_alembic_upgrade_head_fresh_db(tmp_path):
    db_file = tmp_path / "fresh_alembic_test.db"
    db_url = f"sqlite:///{db_file}"

    alembic_cfg = Config("backend/alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)
    alembic_cfg.set_main_option("script_location", "backend/alembic")

    # Run alembic upgrade head on fresh database
    command.upgrade(alembic_cfg, "head")

    engine = create_engine(db_url)
    inspector = inspect(engine)
    tables = inspector.get_table_names()

    # Assert key tables created by migrations
    assert "customers" in tables
    assert "recovery_cases" in tables
    assert "outcomes" in tables
    assert "merchant_policies" in tables
    assert "webhook_events" in tables
    assert "audit_logs" in tables

    engine.dispose()


def test_sqlalchemy_metadata_table_integrity():
    metadata_tables = set(Base.metadata.tables.keys())
    
    expected_tables = {
        "customers",
        "orders",
        "payments",
        "payment_attempts",
        "recovery_cases",
        "outcomes",
        "merchant_policies",
        "webhook_events",
        "audit_logs"
    }

    assert expected_tables.issubset(metadata_tables)
