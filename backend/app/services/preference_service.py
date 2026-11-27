from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import PreferenceRepository
from app.models import UserPreference
from app.schemas import PreferencesUpdate
from app.services.model_service import ModelService


class PreferenceService:
    def __init__(self, session: AsyncSession, models: ModelService) -> None:
        self.session = session
        self.repo = PreferenceRepository(session)
        self.models = models

    async def get(self, user_id: uuid.UUID) -> UserPreference:
        pref = await self.repo.get_or_create(user_id)
        await self.session.commit()
        return pref

    async def update(self, user_id: uuid.UUID, update: PreferencesUpdate) -> UserPreference:
        pref = await self.repo.get_or_create(user_id)
        fields = update.model_fields_set
        if "default_model" in fields:
            pref.default_model = (
                self.models.resolve(update.default_model) if update.default_model else None
            )
        if "theme" in fields and update.theme:
            pref.theme = update.theme
        if "settings" in fields and update.settings is not None:
            pref.settings = update.settings
        await self.session.commit()
        await self.session.refresh(pref)
        return pref
