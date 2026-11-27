"""Models, preferences and health endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text

from app.api.deps import ContainerDep, CurrentUser, get_preference_service
from app.schemas import HealthOut, ModelOut, ModelsResponse, PreferencesOut, PreferencesUpdate
from app.services.preference_service import PreferenceService

router = APIRouter(tags=["system"])

APP_VERSION = "2.0.0"


@router.get("/models", response_model=ModelsResponse)
async def list_models(container: ContainerDep) -> ModelsResponse:
    models = container.models
    return ModelsResponse(
        models=[
            ModelOut(
                id=m.id,
                label=m.label,
                provider=m.provider,
                description=m.description,
                is_default=m.id == models.default_model,
            )
            for m in models.list_models()
        ],
        default_model=models.default_model,
    )


@router.get("/preferences", response_model=PreferencesOut)
async def get_preferences(
    user: CurrentUser, service: Annotated[PreferenceService, Depends(get_preference_service)]
) -> PreferencesOut:
    return PreferencesOut.model_validate(await service.get(user.id))


@router.put("/preferences", response_model=PreferencesOut)
async def update_preferences(
    body: PreferencesUpdate,
    user: CurrentUser,
    service: Annotated[PreferenceService, Depends(get_preference_service)],
) -> PreferencesOut:
    return PreferencesOut.model_validate(await service.update(user.id, body))


@router.get("/health", response_model=HealthOut)
async def health() -> HealthOut:
    """Liveness: the process is up. Used by Render/Docker health checks."""
    return HealthOut(status="ok", version=APP_VERSION, checks={})


@router.get("/health/ready", response_model=HealthOut)
async def readiness(container: ContainerDep, response: Response) -> HealthOut:
    """Readiness: dependencies reachable. Returns 503 if the database is down."""
    checks: dict[str, str] = {}
    try:
        async with container.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "error"
    checks["vector_store"] = "ok" if await container.vector_store.healthcheck() else "error"
    healthy = all(v == "ok" for v in checks.values())
    if checks["database"] != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthOut(status="ok" if healthy else "degraded", version=APP_VERSION, checks=checks)
