"""Chat-model and embedding providers.

A provider turns a model id into a LangChain chat model. The agent graph only sees
`BaseChatModel`, so adding a provider (OpenAI, Anthropic, ...) means adding one class here and
registering it in `ModelService`; the graph and tools do not change.
"""

from __future__ import annotations

from typing import Protocol

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel

from app.core.config import Settings
from app.llm.fake import FakeChatModel, HashingEmbeddings


class ChatModelProvider(Protocol):
    name: str

    def create(self, model_id: str) -> BaseChatModel: ...


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, temperature: float) -> None:
        self._api_key = api_key
        self._temperature = temperature

    def create(self, model_id: str) -> BaseChatModel:
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=model_id,
            temperature=self._temperature,
            google_api_key=self._api_key,
            max_retries=2,
        )


class FakeProvider:
    name = "fake"

    def __init__(self, token_delay: float = 0.0) -> None:
        self._token_delay = token_delay

    def create(self, model_id: str) -> BaseChatModel:
        return FakeChatModel(model_id=model_id, token_delay=self._token_delay)


def create_embeddings(settings: Settings) -> Embeddings:
    if settings.llm_provider == "fake":
        return HashingEmbeddings()
    from langchain_google_genai import GoogleGenerativeAIEmbeddings

    assert settings.google_api_key is not None  # enforced by Settings.validate_runtime
    return GoogleGenerativeAIEmbeddings(
        model=settings.embedding_model,
        google_api_key=settings.google_api_key,
    )
