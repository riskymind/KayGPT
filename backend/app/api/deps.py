"""FastAPI dependencies: resources, auth, CSRF, rate limits and service construction."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.container import Container
from app.core.exceptions import AuthenticationError, PermissionDeniedError, RateLimitedError
from app.core.security import csrf_token_matches
from app.models import User
from app.services.auth_service import AuthService
from app.services.chat_service import ChatService
from app.services.conversation_service import ConversationService
from app.services.document_service import DocumentService
from app.services.memory_service import MemoryService
from app.services.preference_service import PreferenceService

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CSRF_HEADER = "X-CSRF-Token"


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


ContainerDep = Annotated[Container, Depends(get_container)]


async def get_db(container: ContainerDep) -> AsyncIterator[AsyncSession]:
    async with container.session_factory() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(get_db)]


def client_ip(request: Request) -> str:
    # Behind a proxy, uvicorn --proxy-headers sets request.client from X-Forwarded-For.
    return request.client.host if request.client else "unknown"


def check_origin(request: Request, container: Container) -> None:
    """Reject cross-site state-changing requests from origins we do not serve."""
    if request.method in SAFE_METHODS:
        return
    origin = request.headers.get("origin")
    if origin is None:
        return  # non-browser client; CSRF token still required for cookie-authenticated calls
    allowed = {*container.settings.allowed_origins, container.settings.backend_url.rstrip("/")}
    if origin.rstrip("/") not in allowed:
        raise PermissionDeniedError("Origin not allowed.", code="origin_not_allowed")


async def get_current_user(request: Request, db: DbSession, container: ContainerDep) -> User:
    token = request.cookies.get(container.settings.session_cookie_name)
    if not token:
        raise AuthenticationError("Authentication required.")
    user = await AuthService(db, container.session_ttl).resolve(token)
    if user is None:
        raise AuthenticationError("Session expired. Please sign in again.", code="session_expired")
    if request.method not in SAFE_METHODS:
        check_origin(request, container)
        if not csrf_token_matches(
            token,
            request.headers.get(CSRF_HEADER),
            container.settings.secret_key.get_secret_value(),
        ):
            raise PermissionDeniedError("Missing or invalid CSRF token.", code="csrf_failed")
    request.state.user_id = user.id
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def rate_limit(
    bucket: str, setting: str
) -> Callable[[Request, Container], Coroutine[Any, Any, None]]:
    """Per-IP sliding-window limit for unauthenticated endpoints (login/register).

    `setting` names the Settings attribute holding the per-minute limit. Client IPs come from
    X-Forwarded-For, which a client could spoof when calling the API directly, so expensive
    authenticated endpoints use `user_rate_limit` instead.
    """

    async def dependency(request: Request, container: ContainerDep) -> None:
        limit = int(getattr(container.settings, setting))
        retry_after = container.rate_limiter.hit(f"{bucket}:ip:{client_ip(request)}", limit)
        if retry_after is not None:
            raise RateLimitedError(retry_after)

    return dependency


def user_rate_limit(
    bucket: str, setting: str
) -> Callable[[User, Container], Coroutine[Any, Any, None]]:
    """Per-user sliding-window limit (cannot be bypassed by changing IP or headers)."""

    async def dependency(user: CurrentUser, container: ContainerDep) -> None:
        limit = int(getattr(container.settings, setting))
        retry_after = container.rate_limiter.hit(f"{bucket}:user:{user.id}", limit)
        if retry_after is not None:
            raise RateLimitedError(retry_after)

    return dependency


# ---- Service constructors ----


def get_auth_service(db: DbSession, container: ContainerDep) -> AuthService:
    return AuthService(db, container.session_ttl)


def get_conversation_service(db: DbSession, container: ContainerDep) -> ConversationService:
    return ConversationService(
        db, container.checkpointer, container.vector_store, container.storage
    )


def get_chat_service(db: DbSession, container: ContainerDep) -> ChatService:
    return ChatService(db, container.models)


def get_document_service(db: DbSession, container: ContainerDep) -> DocumentService:
    return DocumentService(
        db, container.storage, container.vector_store, container.settings.max_upload_bytes
    )


def get_memory_service(db: DbSession, container: ContainerDep) -> MemoryService:
    return MemoryService(db, container.vector_store, container.memory_config)


def get_preference_service(db: DbSession, container: ContainerDep) -> PreferenceService:
    return PreferenceService(db, container.models)
