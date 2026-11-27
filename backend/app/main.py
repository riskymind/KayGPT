"""FastAPI application factory.

Run: `uvicorn app.main:create_app --factory`.
Importing this module has no side effects; settings are validated in the lifespan (startup).
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import certifi
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.container import ContainerOverrides, build_container
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.middleware import RequestContextMiddleware

logger = logging.getLogger(__name__)


class ConfigurationError(RuntimeError):
    pass


def create_app(
    settings: Settings | None = None, overrides: ContainerOverrides | None = None
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(settings.log_level, settings.log_json)
        errors = settings.validate_runtime()
        if errors:
            for error in errors:
                logger.error("config_error", extra={"error": error})
            raise ConfigurationError("Invalid configuration: " + " ".join(errors))
        # Some environments (notably macOS python.org builds) lack a CA bundle.
        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
        os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

        async with build_container(settings, overrides) as container:
            app.state.container = container
            stale = await container.ingestor.fail_stale()
            logger.info(
                "startup_complete",
                extra={"env": settings.app_env, "stale_documents_failed": stale},
            )
            yield
        logger.info("shutdown_complete")

    app = FastAPI(
        title=f"{settings.app_name} API",
        version="2.0.0",
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/api/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/api/openapi.json",
    )
    register_exception_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-CSRF-Token", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
        max_age=600,
    )
    app.add_middleware(RequestContextMiddleware)
    app.include_router(api_router)
    return app
