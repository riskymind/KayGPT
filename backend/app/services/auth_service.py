"""Registration, login and server-side session management."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthenticationError, ConflictError
from app.core.security import (
    hash_password,
    hash_session_token,
    new_session_token,
    password_needs_rehash,
    verify_password,
)
from app.db.repositories import SessionRepository, UserRepository
from app.models import User, UserSession


@dataclass(frozen=True)
class IssuedSession:
    user: User
    token: str
    expires_at: datetime


def normalize_email(email: str) -> str:
    return email.strip().lower()


class AuthService:
    def __init__(self, session: AsyncSession, session_ttl: timedelta) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.sessions = SessionRepository(session)
        self.session_ttl = session_ttl

    async def register(
        self,
        *,
        email: str,
        password: str,
        display_name: str | None,
        user_agent: str | None,
        ip_address: str | None,
    ) -> IssuedSession:
        email = normalize_email(email)
        if await self.users.get_by_email(email):
            raise ConflictError("An account with this email already exists.", code="email_taken")
        password_hash = await asyncio.to_thread(hash_password, password)
        user = User(email=email, password_hash=password_hash, display_name=display_name)
        try:
            await self.users.add(user)
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(
                "An account with this email already exists.", code="email_taken"
            ) from exc
        issued = await self._issue(user, user_agent, ip_address)
        await self.session.commit()
        return issued

    async def login(
        self, *, email: str, password: str, user_agent: str | None, ip_address: str | None
    ) -> IssuedSession:
        user = await self.users.get_by_email(normalize_email(email))
        stored_hash = user.password_hash if user and user.is_active else None
        valid = await asyncio.to_thread(verify_password, stored_hash, password)
        if not valid or user is None:
            raise AuthenticationError("Invalid email or password.", code="invalid_credentials")
        if password_needs_rehash(user.password_hash):
            user.password_hash = await asyncio.to_thread(hash_password, password)
        issued = await self._issue(user, user_agent, ip_address)
        await self.session.commit()
        return issued

    async def logout(self, token: str) -> None:
        await self.sessions.delete_by_token_hash(hash_session_token(token))
        await self.session.commit()

    async def resolve(self, token: str) -> User | None:
        found = await self.sessions.get_active_with_user(
            hash_session_token(token), datetime.now(UTC)
        )
        return found[1] if found else None

    async def _issue(
        self, user: User, user_agent: str | None, ip_address: str | None
    ) -> IssuedSession:
        token = new_session_token()
        expires_at = datetime.now(UTC) + self.session_ttl
        await self.sessions.add(
            UserSession(
                user_id=user.id,
                token_hash=hash_session_token(token),
                expires_at=expires_at,
                user_agent=(user_agent or "")[:512] or None,
                ip_address=ip_address,
            )
        )
        await self.sessions.delete_expired(datetime.now(UTC))
        return IssuedSession(user=user, token=token, expires_at=expires_at)
