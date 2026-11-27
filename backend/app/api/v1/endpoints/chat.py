from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import ContainerDep, CurrentUser, get_chat_service, user_rate_limit
from app.schemas import ChatRequest
from app.services.chat_service import ChatService

router = APIRouter(prefix="/chat", tags=["chat"])

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # disable nginx/Render proxy buffering
}


@router.post(
    "/stream",
    response_class=StreamingResponse,
    dependencies=[Depends(user_rate_limit("chat", "rate_limit_chat_per_minute"))],
    responses={200: {"content": {"text/event-stream": {}}, "description": "SSE event stream"}},
)
async def chat_stream(
    body: ChatRequest,
    user: CurrentUser,
    service: Annotated[ChatService, Depends(get_chat_service)],
    container: ContainerDep,
) -> StreamingResponse:
    # Validation/persistence errors surface as normal JSON errors before the stream starts.
    turn = await service.prepare(user.id, body)
    return StreamingResponse(
        container.streamer.stream(turn),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
