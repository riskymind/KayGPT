from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, UserPreference, UserSession


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, user_id: uuid.UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        result: User | None = await self.session.scalar(select(User).where(User.email == email))
        return result

    async def add(self, user: User) -> User:
        self.session.add(user)
        await self.session.flush()
        return user


class SessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, user_session: UserSession) -> None:
        self.session.add(user_session)
        await self.session.flush()

    async def get_active_with_user(
        self, token_hash: str, now: datetime
    ) -> tuple[UserSession, User] | None:
        row = (
            await self.session.execute(
                select(UserSession, User)
                .join(User, User.id == UserSession.user_id)
                .where(
                    UserSession.token_hash == token_hash,
                    UserSession.expires_at > now,
                    User.is_active.is_(True),
                )
            )
        ).first()
        return (row[0], row[1]) if row else None

    async def delete_by_token_hash(self, token_hash: str) -> None:
        await self.session.execute(delete(UserSession).where(UserSession.token_hash == token_hash))

    async def delete_expired(self, now: datetime) -> int:
        result = await self.session.execute(
            delete(UserSession).where(UserSession.expires_at <= now)
        )
        return int(getattr(result, "rowcount", 0) or 0)


class PreferenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, user_id: uuid.UUID) -> UserPreference | None:
        return await self.session.get(UserPreference, user_id)

    async def get_or_create(self, user_id: uuid.UUID) -> UserPreference:
        pref = await self.get(user_id)
        if pref is None:
            pref = UserPreference(user_id=user_id, theme="system", settings={})
            self.session.add(pref)
            await self.session.flush()
        return pref
