import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "RecoverAI"
    VERSION: str = "0.1.0"
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    
    # Database
    DATABASE_URL: str = "postgresql://recoverai:recoverai_secret@localhost:5432/recoverai_db"
    TEST_DATABASE_URL: str = "sqlite:///./test.db"
    
    # Razorpay Integration
    RAZORPAY_KEY_ID: str = "rzp_test_dummy_key_id"
    RAZORPAY_KEY_SECRET: str = "dummy_key_secret"
    RAZORPAY_WEBHOOK_SECRET: str = "dummy_webhook_secret"
    
    # Gemini AI
    GEMINI_API_KEY: str = "dummy_gemini_api_key"
    LLM_PROVIDER: str = "mock"
    
    # Default Merchant Policies
    DEFAULT_MAX_RETRIES: int = 2
    DEFAULT_MIN_RETRY_INTERVAL_MINUTES: int = 30
    DEFAULT_MAX_NOTIFICATIONS_PER_24H: int = 2
    DEFAULT_MANUAL_APPROVAL_THRESHOLD: float = 25000.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
