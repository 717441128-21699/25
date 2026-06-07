from pydantic_settings import BaseSettings
from typing import Optional
from functools import lru_cache


class Settings(BaseSettings):
    app_name: str = "EmployeeEquityManagement"
    app_env: str = "development"
    debug: bool = True

    database_url: str = "sqlite:///./equity_management.db"
    redis_url: str = "redis://localhost:6379/0"
    redis_password: Optional[str] = None

    secret_key: str = "change-me-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440

    hr_system_api_url: str = "https://hr-system.example.com/api"
    hr_system_api_key: str = ""
    hr_system_sync_interval_minutes: int = 60

    stock_price_api_url: str = "https://stock-api.example.com"
    stock_price_api_key: str = ""

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""

    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    report_output_dir: str = "./reports"
    agreement_template_dir: str = "./templates/agreements"
    archive_dir: str = "./archive"

    max_concurrent_exercises: int = 1000
    rate_limit_per_minute: int = 5000

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
