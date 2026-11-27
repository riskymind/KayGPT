"""Application settings loaded from environment variables (and `.env` files in development)."""

from __future__ import annotations

from functools import cached_property
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["development", "test", "production"]


def _split_csv(value: object) -> object:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        # `COOKIE_SECURE=` (empty) means "use the default", not an invalid boolean.
        env_ignore_empty=True,
    )

    # --- Application ---
    app_env: Environment = "development"
    app_name: str = "KayGPT"
    debug: bool = False
    log_level: str = "INFO"
    log_json: bool = True

    # --- Database ---
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/kaygpt"
    db_pool_size: int = 5
    db_max_overflow: int = 5
    checkpoint_pool_size: int = 5

    # --- LLM providers ---
    llm_provider: Literal["gemini", "fake"] = "gemini"
    google_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.8-flash"
    gemini_models: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "gemini-3.8-flash",
            "gemini-3.1-pro-preview",
            "gemini-3.5-flash-lite",
        ]
    )
    llm_temperature: float = 0.3
    fake_llm_token_delay: float = 0.0  # seconds between tokens for LLM_PROVIDER=fake (e2e tests)
    embedding_model: str = "gemini-embedding-001"

    # --- Web search ---
    tavily_api_key: SecretStr | None = None
    web_search_max_results: int = 5

    # --- LangSmith (read directly by the LangChain SDK from the environment) ---
    langsmith_tracing: bool = False
    langsmith_project: str = "KayGPT"

    # --- URLs / CORS ---
    frontend_url: str = "http://localhost:3000"
    backend_url: str = "http://localhost:8000"
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # --- Auth ---
    secret_key: SecretStr = SecretStr("dev-insecure-secret-change-me-dev-insecure-secret")
    session_ttl_days: int = 30
    session_cookie_name: str = "kaygpt_session"
    cookie_secure: bool | None = None
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    cookie_domain: str | None = None

    # --- Rate limits (per client IP, per minute; in-process) ---
    rate_limit_auth_per_minute: int = 10
    rate_limit_chat_per_minute: int = 30
    rate_limit_upload_per_minute: int = 10

    # --- Vector store ---
    chroma_mode: Literal["persistent", "http", "ephemeral"] = "persistent"
    chroma_persist_directory: str = "./data/chroma"
    chroma_host: str = "localhost"
    chroma_port: int = 8001
    chroma_ssl: bool = False
    rag_top_k: int = 4
    rag_chunk_size: int = 900
    rag_chunk_overlap: int = 150
    memory_recall_top_k: int = 5
    memory_recall_max_distance: float = 0.8
    memory_duplicate_max_distance: float = 0.08

    # --- File storage ---
    storage_backend: Literal["local", "s3"] = "local"
    upload_dir: str = "./uploads"
    s3_bucket: str | None = None
    s3_endpoint_url: str | None = None
    s3_region: str | None = None
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None
    s3_prefix: str = "kaygpt/"
    max_upload_size_mb: int = 20

    # --- Streaming ---
    sse_heartbeat_seconds: float = 15.0

    @field_validator("database_url")
    @classmethod
    def _psycopg_driver(cls, value: str) -> str:
        """Managed Postgres URLs (Render, Heroku, Neon) use postgres:// or postgresql://, which
        SQLAlchemy maps to psycopg2. This app uses psycopg 3."""
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                return "postgresql+psycopg://" + value[len(prefix) :]
        return value

    @field_validator("gemini_models", "cors_origins", mode="before")
    @classmethod
    def _csv(cls, value: object) -> object:
        return _split_csv(value)

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def effective_cookie_secure(self) -> bool:
        if self.cookie_secure is not None:
            return self.cookie_secure
        return self.is_production

    @cached_property
    def allowed_origins(self) -> list[str]:
        origins = self.cors_origins or [self.frontend_url]
        return [o.rstrip("/") for o in origins]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def psycopg_conninfo(self) -> str:
        """libpq URL for psycopg (LangGraph checkpointer), without the SQLAlchemy driver tag."""
        url = self.database_url
        for prefix in ("postgresql+psycopg://", "postgresql+psycopg_async://"):
            if url.startswith(prefix):
                return "postgresql://" + url[len(prefix) :]
        return url

    def validate_runtime(self) -> list[str]:
        """Return a list of configuration errors that should stop the app from starting."""
        errors: list[str] = []
        if not self.database_url.startswith("postgresql"):
            errors.append("DATABASE_URL must be a PostgreSQL URL (postgresql+psycopg://...).")
        if self.llm_provider == "gemini" and not self.google_api_key:
            errors.append("GOOGLE_API_KEY is required when LLM_PROVIDER=gemini.")
        if self.gemini_model not in self.gemini_models:
            errors.append("GEMINI_MODEL must be one of GEMINI_MODELS.")
        if self.storage_backend == "s3" and not self.s3_bucket:
            errors.append("S3_BUCKET is required when STORAGE_BACKEND=s3.")
        if self.cookie_samesite == "none" and not self.effective_cookie_secure:
            errors.append("COOKIE_SAMESITE=none requires COOKIE_SECURE=true.")
        if self.is_production:
            secret = self.secret_key.get_secret_value()
            if len(secret) < 32 or secret.startswith("dev-insecure"):
                errors.append("SECRET_KEY must be set to a random value of 32+ characters.")
            if self.llm_provider == "fake":
                errors.append("LLM_PROVIDER=fake is not allowed in production.")
            if not self.tavily_api_key:
                errors.append("TAVILY_API_KEY is required in production.")
            if self.chroma_mode == "ephemeral":
                errors.append("CHROMA_MODE=ephemeral is not allowed in production.")
        return errors


def get_settings() -> Settings:
    return Settings()
