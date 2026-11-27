from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import ContainerDep, CurrentUser, get_conversation_service
from app.schemas import (
    ConversationCreate,
    ConversationOut,
    ConversationUpdate,
    MessageOut,
    MessagePage,
    Page,
)
from app.services.conversation_service import ConversationService

router = APIRouter(prefix="/conversations", tags=["conversations"])

Service = Annotated[ConversationService, Depends(get_conversation_service)]


@router.get("", response_model=Page[ConversationOut])
async def list_conversations(
    user: CurrentUser,
    service: Service,
    q: Annotated[str | None, Query(max_length=200, description="Search titles")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ConversationOut]:
    items, total = await service.list_for_user(user.id, query=q, limit=limit, offset=offset)
    return Page[ConversationOut](
        items=[ConversationOut.model_validate(c) for c in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    body: ConversationCreate, user: CurrentUser, service: Service, container: ContainerDep
) -> ConversationOut:
    model_id = container.models.resolve(body.model_id) if body.model_id else None
    conversation = await service.create(user.id, title=body.title, model_id=model_id)
    return ConversationOut.model_validate(conversation)


@router.get("/{conversation_id}", response_model=ConversationOut)
async def get_conversation(
    conversation_id: uuid.UUID, user: CurrentUser, service: Service
) -> ConversationOut:
    return ConversationOut.model_validate(await service.get(user.id, conversation_id))


@router.patch("/{conversation_id}", response_model=ConversationOut)
async def rename_conversation(
    conversation_id: uuid.UUID, body: ConversationUpdate, user: CurrentUser, service: Service
) -> ConversationOut:
    return ConversationOut.model_validate(
        await service.rename(user.id, conversation_id, body.title)
    )


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: uuid.UUID, user: CurrentUser, service: Service
) -> Response:
    await service.delete(user.id, conversation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{conversation_id}/messages", response_model=MessagePage)
async def list_messages(
    conversation_id: uuid.UUID,
    user: CurrentUser,
    service: Service,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before: Annotated[uuid.UUID | None, Query(description="Message id cursor")] = None,
) -> MessagePage:
    items, has_more = await service.list_messages(
        user.id, conversation_id, limit=limit, before=before
    )
    return MessagePage(items=[MessageOut.model_validate(m) for m in items], has_more=has_more)
