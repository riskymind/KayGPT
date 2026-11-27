"""Central registry of selectable chat models."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool

from app.core.config import Settings
from app.core.exceptions import ValidationFailedError
from app.llm.providers import ChatModelProvider, FakeProvider, GeminiProvider

_GEMINI_DESCRIPTIONS = {
    "gemini-3.8-flash": "Fast, balanced default",
    "gemini-3.1-pro-preview": "Most capable, slower",
    "gemini-3.5-flash-lite": "Lowest latency and cost",
}


@dataclass(frozen=True)
class ModelInfo:
    id: str
    label: str
    provider: str
    description: str


class ModelService:
    def __init__(
        self,
        models: Sequence[ModelInfo],
        providers: dict[str, ChatModelProvider],
        default_model: str,
    ) -> None:
        self._models = {m.id: m for m in models}
        if default_model not in self._models:
            raise ValueError(f"Default model {default_model!r} is not registered.")
        self._providers = providers
        self.default_model = default_model
        self._bound: dict[str, Runnable[LanguageModelInput, AIMessage]] = {}

    @classmethod
    def from_settings(cls, settings: Settings) -> ModelService:
        if settings.llm_provider == "fake":
            provider: ChatModelProvider = FakeProvider(settings.fake_llm_token_delay)
        else:
            assert settings.google_api_key is not None
            provider = GeminiProvider(
                settings.google_api_key.get_secret_value(), settings.llm_temperature
            )
        models = [
            ModelInfo(
                id=model_id,
                label=model_id,
                provider=provider.name,
                description=_GEMINI_DESCRIPTIONS.get(model_id, "Gemini model"),
            )
            for model_id in settings.gemini_models
        ]
        return cls(models, {provider.name: provider}, settings.gemini_model)

    def list_models(self) -> list[ModelInfo]:
        return list(self._models.values())

    def resolve(self, model_id: str | None) -> str:
        """Return a valid model id. Unknown ids are rejected instead of silently replaced."""
        if not model_id:
            return self.default_model
        model_id = model_id.strip()
        if model_id not in self._models:
            raise ValidationFailedError(
                f"Unknown model {model_id!r}.",
                details={"allowed": list(self._models)},
                code="unknown_model",
            )
        return model_id

    def is_known(self, model_id: str | None) -> bool:
        return bool(model_id) and model_id in self._models

    def create_chat_model(self, model_id: str) -> BaseChatModel:
        info = self._models[model_id]
        return self._providers[info.provider].create(model_id)

    def get_bound_model(
        self, model_id: str, tools: Sequence[BaseTool]
    ) -> Runnable[LanguageModelInput, AIMessage]:
        """Chat model with tools bound, built once per model id and reused across requests."""
        bound = self._bound.get(model_id)
        if bound is None:
            bound = self.create_chat_model(model_id).bind_tools(list(tools))
            self._bound[model_id] = bound
        return bound
