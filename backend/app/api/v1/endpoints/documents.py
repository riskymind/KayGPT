from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Query,
    Response,
    UploadFile,
    status,
)

from app.api.deps import ContainerDep, CurrentUser, get_document_service, user_rate_limit
from app.schemas import DocumentOut
from app.services.document_service import DocumentService

router = APIRouter(prefix="/documents", tags=["documents"])

Service = Annotated[DocumentService, Depends(get_document_service)]


@router.post(
    "/upload",
    response_model=DocumentOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(user_rate_limit("upload", "rate_limit_upload_per_minute"))],
)
async def upload_document(
    user: CurrentUser,
    service: Service,
    container: ContainerDep,
    background: BackgroundTasks,
    file: Annotated[UploadFile, File()],
    conversation_id: Annotated[uuid.UUID | None, Form()] = None,
) -> DocumentOut:
    """Store the file and queue ingestion. Poll GET /documents/{id} for `status`."""
    document = await service.upload(user.id, file, conversation_id)
    background.add_task(container.ingestor.ingest, document.id)
    return DocumentOut.model_validate(document)


@router.get("", response_model=list[DocumentOut])
async def list_documents(
    user: CurrentUser,
    service: Service,
    conversation_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[DocumentOut]:
    """All of the user's documents, or (with conversation_id) those searchable in that chat."""
    return [
        DocumentOut.model_validate(d) for d in await service.list_for_user(user.id, conversation_id)
    ]


@router.get("/{document_id}", response_model=DocumentOut)
async def get_document(document_id: uuid.UUID, user: CurrentUser, service: Service) -> DocumentOut:
    return DocumentOut.model_validate(await service.get(user.id, document_id))


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: uuid.UUID, user: CurrentUser, service: Service) -> Response:
    await service.delete(user.id, document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
