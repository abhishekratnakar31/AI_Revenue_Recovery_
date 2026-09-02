"""
RecoverAI Configuration Module

This module defines the central application settings using Pydantic Settings.
It automatically loads environment variables from the `.env` file or system environment,
providing typed configurations for database connections, server parameters, Razorpay API credentials,
Gemini AI settings, and default merchant policy parameters across the application.
"""

import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Central settings class holding all application configuration values.
    Pydantic automatically validates types and provides defaults.
    """
    # General Project Metadata
    PROJECT_NAME: str = "RecoverAI"
    VERSION: str = "0.1.0"
    ENVIRONMENT: str = "development"  # Options: development, testing, production
    LOG_LEVEL: str = "INFO"
    
    # Database Connection Strings
    # Default points to local PostgreSQL database created for RecoverAI
    DATABASE_URL: str = "postgresql://recoverai:recoverai_secret@localhost:5432/recoverai_db"
    TEST_DATABASE_URL: str = "sqlite:///./test.db"
    
    # Razorpay Integration (Test Mode Sandbox Credentials)
    RAZORPAY_KEY_ID: str = "rzp_test_dummy_key_id"
    RAZORPAY_KEY_SECRET: str = "dummy_key_secret"
    RAZORPAY_WEBHOOK_SECRET: str = "dummy_webhook_secret"
    
    # Gemini AI Integration Credentials & Provider Abstraction
    GEMINI_API_KEY: str = "dummy_gemini_api_key"
    LLM_PROVIDER: str = "mock"  # Options: mock (for offline unit tests), gemini
    
    # Default Merchant Policy Rules (Used as fallback if no custom merchant policy is set)
    DEFAULT_MAX_RETRIES: int = 2
    DEFAULT_MIN_RETRY_INTERVAL_MINUTES: int = 30
    DEFAULT_MAX_NOTIFICATIONS_PER_24H: int = 2
    DEFAULT_MANUAL_APPROVAL_THRESHOLD: float = 25000.0  # INR amount above which recovery needs manual review

    # Configures Pydantic to read from .env file
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


# Global singleton instance of Settings
settings = Settings()
