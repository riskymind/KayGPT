from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import CurrentUser, get_memory_service
from app.schemas import MemoryCreate, MemoryCreateResult, MemoryOut, Page
from app.services.memory_service import MemoryService

router = APIRouter(prefix="/memory", tags=["memory"])

Service = Annotated[MemoryService, Depends(get_memory_service)]


@router.get("", response_model=Page[MemoryOut])
async def list_memories(
    user: CurrentUser,
    service: Service,
    q: Annotated[str | None, Query(max_length=500, description="Semantic search query")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[MemoryOut]:
    """Newest first, or ranked by relevance (with `score` = cosine distance) when `q` is given."""
    if q and q.strip():
        found = await service.recall(user.id, q, k=limit)
        items = [
            MemoryOut.model_validate(r.memory).model_copy(update={"score": round(r.distance, 4)})
            for r in found
        ]
        return Page[MemoryOut](items=items, total=len(items), limit=limit, offset=0)
    rows, total = await service.list_for_user(user.id, limit=limit, offset=offset)
    return Page[MemoryOut](
        items=[MemoryOut.model_validate(m) for m in rows], total=total, limit=limit, offset=offset
    )


@router.post("", response_model=MemoryCreateResult)
async def create_memory(
    body: MemoryCreate, user: CurrentUser, service: Service, response: Response
) -> MemoryCreateResult:
    memory, created = await service.remember(user.id, body.content, source="user")
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return MemoryCreateResult(memory=MemoryOut.model_validate(memory), created=created)


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(memory_id: uuid.UUID, user: CurrentUser, service: Service) -> Response:
    await service.delete(user.id, memory_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
