from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = Field(default="development", alias="APP_ENV")
    app_port: int = Field(default=8001, alias="APP_PORT")
    app_api_key: str = Field(default="dev_key_change_me", alias="APP_API_KEY")

    database_url: str = Field(
        default="postgresql+asyncpg://cv_user:password@localhost:5432/cv_intelligence",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    celery_broker_url: str = Field(default="redis://localhost:6379/0", alias="CELERY_BROKER_URL")

    search_api_base_url: str = Field(default="http://localhost:8000", alias="SEARCH_API_BASE_URL")
    search_api_key: str = Field(default="search_api_key", alias="SEARCH_API_KEY")
    search_ingest_api_key: str | None = Field(default=None, alias="SEARCH_INGEST_API_KEY")

    llm_provider: str = Field(default="gemini", alias="LLM_PROVIDER")
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_model: str = Field(default="gemini-2.5-flash", alias="LLM_MODEL")
    llm_base_url: str | None = Field(default=None, alias="LLM_BASE_URL")

    upload_dir: Path = Field(default=Path("/tmp/cv_uploads"), alias="UPLOAD_DIR")
    max_file_size_mb: int = Field(default=20, alias="MAX_FILE_SIZE_MB")
    ocr_dpi: int = Field(default=150, alias="OCR_DPI")
    ocr_confidence_threshold: float = Field(default=0.6, alias="OCR_CONFIDENCE_THRESHOLD")
    fasttext_model_path: Path = Field(default=Path("/models/lid.176.bin"), alias="FASTTEXT_MODEL_PATH")

    ranking_default_recall_size: int = Field(default=10, alias="RANKING_DEFAULT_RECALL_SIZE")
    ranking_llm_concurrency: int = Field(default=20, alias="RANKING_LLM_CONCURRENCY")

    search_webhook_secret: str = Field(default="", alias="SEARCH_WEBHOOK_SECRET")
    app_webhook_secret: str = Field(default="", alias="APP_WEBHOOK_SECRET")
    webhook_timeout_seconds: int = Field(default=10, alias="WEBHOOK_TIMEOUT_SECONDS")


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return cached settings instance."""

    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings_cache() -> None:
    """Clear cached settings (for tests)."""

    global _settings
    _settings = None

