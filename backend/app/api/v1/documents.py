import uuid
from typing import Annotated

from fastapi import APIRouter, File, Query, Response, UploadFile, status

from app.api.deps import CurrentUserDep, DocumentServiceDep, SettingsDep
from app.schemas.documents import DocumentList, DocumentRead, DocumentStatusRead

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", response_model=DocumentRead, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    file: Annotated[UploadFile, File(description="PDF, DOCX, TXT or Markdown file.")],
    user: CurrentUserDep,
    service: DocumentServiceDep,
    settings: SettingsDep,
) -> DocumentRead:
    """Store the file and queue it for processing. 202: the work happens in the background;
    poll ``GET /documents/{id}/status`` until it is ``ready`` or ``failed``."""
    # Read one byte more than allowed so an oversized file is detected without buffering
    # all of it.
    data = await file.read(settings.max_upload_bytes + 1)
    document = await service.upload(user_id=user.id, filename=file.filename, data=data)
    return DocumentRead.model_validate(document)


@router.get("", response_model=DocumentList)
async def list_documents(
    user: CurrentUserDep,
    service: DocumentServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DocumentList:
    items, total = await service.list(user_id=user.id, limit=limit, offset=offset)
    return DocumentList(
        items=[DocumentRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{document_id}", response_model=DocumentRead)
async def get_document(
    document_id: uuid.UUID, user: CurrentUserDep, service: DocumentServiceDep
) -> DocumentRead:
    return DocumentRead.model_validate(await service.get(user_id=user.id, document_id=document_id))


@router.get("/{document_id}/status", response_model=DocumentStatusRead)
async def get_document_status(
    document_id: uuid.UUID, user: CurrentUserDep, service: DocumentServiceDep
) -> DocumentStatusRead:
    return DocumentStatusRead.model_validate(
        await service.get(user_id=user.id, document_id=document_id)
    )


@router.post(
    "/{document_id}/retry", response_model=DocumentRead, status_code=status.HTTP_202_ACCEPTED
)
async def retry_document(
    document_id: uuid.UUID, user: CurrentUserDep, service: DocumentServiceDep
) -> DocumentRead:
    return DocumentRead.model_validate(
        await service.retry(user_id=user.id, document_id=document_id)
    )


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID, user: CurrentUserDep, service: DocumentServiceDep
) -> Response:
    await service.delete(user_id=user.id, document_id=document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
