from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.rate_limit import RateLimiter
from app.core.security import (
    csrf_token_for,
    csrf_token_matches,
    hash_password,
    hash_session_token,
    verify_password,
)


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("a-long-password")
    assert hashed.startswith("$argon2id$")
    assert verify_password(hashed, "a-long-password")
    assert not verify_password(hashed, "wrong-password")
    assert not verify_password(None, "kaygpt-timing-equalizer")  # dummy hash never authenticates
    assert not verify_password("not-a-hash", "x")


def test_session_token_hash_is_deterministic_and_not_plaintext() -> None:
    assert hash_session_token("abc") == hash_session_token("abc")
    assert hash_session_token("abc") != "abc"


def test_csrf_token_is_bound_to_session_and_secret() -> None:
    token = csrf_token_for("session-1", "secret")
    assert csrf_token_matches("session-1", token, "secret")
    assert not csrf_token_matches("session-2", token, "secret")
    assert not csrf_token_matches("session-1", token, "other-secret")
    assert not csrf_token_matches("session-1", None, "secret")


def test_rate_limiter_blocks_after_limit() -> None:
    limiter = RateLimiter()
    assert limiter.hit("k", 2) is None
    assert limiter.hit("k", 2) is None
    retry = limiter.hit("k", 2)
    assert retry is not None and retry >= 1
    assert limiter.hit("other", 2) is None


def _settings(**values: object) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def test_production_config_validation(tmp_path: Path) -> None:
    errors = _settings(app_env="production", llm_provider="fake").validate_runtime()
    joined = " ".join(errors)
    assert "SECRET_KEY" in joined
    assert "LLM_PROVIDER=fake" in joined
    assert "TAVILY_API_KEY" in joined

    ok = _settings(
        app_env="production",
        google_api_key="k",
        tavily_api_key="t",
        secret_key="x" * 40,
    )
    assert ok.validate_runtime() == []
    assert ok.effective_cookie_secure is True


def test_config_parses_csv_lists_and_conninfo() -> None:
    settings = _settings(
        gemini_models="a, b",
        gemini_model="a",
        cors_origins="https://x.example/, https://y.example",
        database_url="postgresql+psycopg://u:p@h:5432/db",
        llm_provider="fake",
    )
    assert settings.gemini_models == ["a", "b"]
    assert settings.allowed_origins == ["https://x.example", "https://y.example"]
    assert settings.psycopg_conninfo == "postgresql://u:p@h:5432/db"
    assert settings.validate_runtime() == []


def test_sqlite_database_is_rejected() -> None:
    errors = _settings(database_url="sqlite:///x.db", llm_provider="fake").validate_runtime()
    assert any("PostgreSQL" in e for e in errors)


def test_managed_postgres_urls_use_psycopg3() -> None:
    for raw in ("postgres://u:p@h/db", "postgresql://u:p@h/db"):
        settings = _settings(database_url=raw, llm_provider="fake")
        assert settings.database_url == "postgresql+psycopg://u:p@h/db"
        assert settings.psycopg_conninfo == "postgresql://u:p@h/db"


def test_empty_env_values_fall_back_to_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("COOKIE_SECURE", "SECRET_KEY", "CORS_ORIGINS", "COOKIE_DOMAIN"):
        monkeypatch.setenv(name, "")
    settings = Settings(_env_file=None)
    assert settings.cookie_secure is None
    assert settings.cors_origins == []
    assert settings.cookie_domain is None
