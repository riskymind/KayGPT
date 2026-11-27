from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from app.api.deps import (
    ContainerDep,
    CurrentUser,
    check_origin,
    client_ip,
    get_auth_service,
    rate_limit,
)
from app.core.container import Container
from app.core.security import csrf_token_for
from app.schemas import AuthResponse, LoginRequest, RegisterRequest, UserOut
from app.services.auth_service import AuthService, IssuedSession

router = APIRouter(prefix="/auth", tags=["auth"])

AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
auth_rate_limit = Depends(rate_limit("auth", "rate_limit_auth_per_minute"))


def _set_session_cookie(response: Response, container: Container, issued: IssuedSession) -> None:
    settings = container.settings
    response.set_cookie(
        key=settings.session_cookie_name,
        value=issued.token,
        max_age=int(container.session_ttl.total_seconds()),
        expires=issued.expires_at,
        path="/",
        domain=settings.cookie_domain,
        secure=settings.effective_cookie_secure,
        httponly=True,
        samesite=settings.cookie_samesite,
    )


def _auth_response(container: Container, issued: IssuedSession) -> AuthResponse:
    return AuthResponse(
        user=UserOut.model_validate(issued.user),
        csrf_token=csrf_token_for(issued.token, container.settings.secret_key.get_secret_value()),
    )


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[auth_rate_limit],
)
async def register(
    body: RegisterRequest,
    request: Request,
    response: Response,
    service: AuthServiceDep,
    container: ContainerDep,
) -> AuthResponse:
    check_origin(request, container)
    issued = await service.register(
        email=body.email,
        password=body.password,
        display_name=body.display_name,
        user_agent=request.headers.get("user-agent"),
        ip_address=client_ip(request),
    )
    _set_session_cookie(response, container, issued)
    return _auth_response(container, issued)


@router.post("/login", response_model=AuthResponse, dependencies=[auth_rate_limit])
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    service: AuthServiceDep,
    container: ContainerDep,
) -> AuthResponse:
    check_origin(request, container)
    issued = await service.login(
        email=body.email,
        password=body.password,
        user_agent=request.headers.get("user-agent"),
        ip_address=client_ip(request),
    )
    _set_session_cookie(response, container, issued)
    return _auth_response(container, issued)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    _: CurrentUser,
    request: Request,
    service: AuthServiceDep,
    container: ContainerDep,
) -> Response:
    settings = container.settings
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        await service.logout(token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        domain=settings.cookie_domain,
        secure=settings.effective_cookie_secure,
        httponly=True,
        samesite=settings.cookie_samesite,
    )
    return response


@router.get("/me", response_model=AuthResponse)
async def me(user: CurrentUser, request: Request, container: ContainerDep) -> AuthResponse:
    token = request.cookies[container.settings.session_cookie_name]
    return AuthResponse(
        user=UserOut.model_validate(user),
        csrf_token=csrf_token_for(token, container.settings.secret_key.get_secret_value()),
    )
