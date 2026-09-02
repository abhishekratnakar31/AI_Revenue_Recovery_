"""
Database Core Module

This module manages the SQLAlchemy database engine, session factory (`SessionLocal`),
and declarative base (`Base`) for the RecoverAI platform.

It includes:
1. Dynamic environment resolution (switching between PostgreSQL for production/dev and SQLite for fast unit testing).
2. Connection pooling configuration with pre-ping validation.
3. The `get_db` FastAPI dependency generator for managing database session lifecycles per request.
"""

import os
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from backend.app.core.config import settings

# Determine active database connection URL.
# If USE_TEST_DB environment variable is set (during pytest runs), use TEST_DATABASE_URL (SQLite).
# Otherwise, default to settings.DATABASE_URL (PostgreSQL).
db_url = os.getenv("TEST_DATABASE_URL") if os.getenv("USE_TEST_DB") else settings.DATABASE_URL

# SQLite specific connect arguments (prevent single-thread check errors in tests)
connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}

# Create global SQLAlchemy Engine
engine = create_engine(
    db_url,
    connect_args=connect_args,
    pool_pre_ping=True  # Automatically verifies connection health before issuing queries
)

# Session factory for generating database sessions
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Declarative Base class for all SQLAlchemy ORM models
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that provides a transactional database session for an HTTP request.
    
    Yields:
        Session: Active SQLAlchemy database session.
        
    Clean Up:
        Ensures the session is safely closed after the request completes,
        even if an unhandled exception occurred during route execution.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
