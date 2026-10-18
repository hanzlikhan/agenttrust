"""Application settings, loaded from the environment (and an optional local `.env`)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    DATABASE_URL: str = "postgresql+psycopg://agenttrust:agenttrust@localhost:5432/agenttrust"
    AGENTTRUST_ENV: str = "local"
    ADMIN_TOKEN: str = ""
    AGENTTRUST_CORS_ORIGINS: str = "http://localhost:3000"
    AGENTTRUST_EVENT_RETENTION_DAYS: int = 14
    # SSE stream tuning (M08). Heartbeat keeps idle connections alive;
    # max_seconds bounds a single subscription (clients reconnect with
    # Last-Event-ID and lose nothing).
    AGENTTRUST_SSE_HEARTBEAT_SECONDS: float = 20.0
    AGENTTRUST_SSE_POLL_SECONDS: float = 0.5
    AGENTTRUST_SSE_MAX_SECONDS: float = 300.0
    # Human approvals (M10). REVIEW decisions create a PENDING approval that
    # expires after this many seconds unless a reviewer decides it.
    AGENTTRUST_APPROVAL_TTL_SECONDS: int = 900
    # Rate limiting (security hardening). Token-bucket refills per minute, per
    # API key, enforced in-process (single-process limitation, ADR-0xx).
    AGENTTRUST_RATE_LIMIT_PER_MINUTE: int = 60
    # Incident investigation (M11). The analyzer tries the local Ollama
    # model first and falls back to a deterministic template on any failure
    # (ADR-0xx). No model is ever downloaded or required.
    AGENTTRUST_OLLAMA_URL: str = "http://localhost:11434"
    AGENTTRUST_OLLAMA_MODEL: str = "qwen2.5:3b"
    AGENTTRUST_ANALYZE_TIMEOUT_SECONDS: int = 30


settings = Settings()
