from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.db.session import get_db
from app.models.audit import AuditLog
from app.models.document import Document, DocumentUserState
from app.models.user import User
from app.schemas.api import (
    ArchiveListingResponse,
    DocumentDetailResponse,
    DocumentsListingResponse,
    HideDocumentRequest,
    OperationsOverviewResponse,
    TicketsListingResponse,
)
from app.services.dashboard import (
    build_archived_document_listing,
    build_document_listing,
    build_operations_overview,
    build_ticket_case_listing,
    load_document_with_context,
)
from app.services.serializers import serialize_archived_documents_listing, serialize_document_detail, serialize_documents_listing, serialize_ticket_listing

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("/tickets", response_model=TicketsListingResponse)
def tickets_listing(
    q: str | None = Query(default=None),
    view: str = Query(default="active"),
    status_filter: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TicketsListingResponse:
    listing = build_ticket_case_listing(
        db,
        user=user,
        search=q,
        view=view,
        status_filter=status_filter,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return TicketsListingResponse.model_validate(serialize_ticket_listing(listing))


@router.get("/payments", response_model=DocumentsListingResponse)
def payments_listing(
    q: str | None = Query(default=None),
    view: str = Query(default="active"),
    status_filter: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DocumentsListingResponse:
    listing = build_document_listing(
        db,
        user=user,
        flow_group="payments",
        search=q,
        view=view,
        status_filter=status_filter,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return DocumentsListingResponse.model_validate(serialize_documents_listing(listing))


@router.get("/archive", response_model=ArchiveListingResponse)
def archive_listing(
    q: str | None = Query(default=None),
    view: str = Query(default="all"),
    status_filter: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    flow_group: str | None = Query(default=None, pattern=r"^(tickets|payments)$"),
    limit: int = Query(default=50, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> ArchiveListingResponse:
    listing = build_archived_document_listing(
        db,
        search=q,
        view=view,
        status_filter=status_filter,
        date_from=date_from,
        date_to=date_to,
        flow_group=flow_group,
        limit=limit,
        offset=offset,
    )
    return ArchiveListingResponse.model_validate(serialize_archived_documents_listing(listing))


@router.get("/overview", response_model=OperationsOverviewResponse)
def operations_overview(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> OperationsOverviewResponse:
    overview = build_operations_overview(db)
    return OperationsOverviewResponse.model_validate(overview)


@router.get("/{document_id}", response_model=DocumentDetailResponse)
def document_detail(document_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> DocumentDetailResponse:
    context = load_document_with_context(db, document_id)
    if not context:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Документ не найден")
    root_ticket = context["root_ticket"]
    context["root_ticket_state"] = db.scalar(
        select(DocumentUserState).where(
            DocumentUserState.document_id == root_ticket.id,
            DocumentUserState.user_id == user.id,
        )
    )
    return DocumentDetailResponse.model_validate(serialize_document_detail(context))


@router.post("/{document_id}/hide", status_code=status.HTTP_204_NO_CONTENT)
def hide_document(
    document_id: str,
    payload: HideDocumentRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> None:
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Документ не найден")

    state = db.scalar(
        select(DocumentUserState).where(
            DocumentUserState.document_id == document_id,
            DocumentUserState.user_id == user.id,
        )
    )
    if not state:
        state = DocumentUserState(document_id=document_id, user_id=user.id)
        db.add(state)

    now = datetime.now(timezone.utc)
    state.is_hidden = True
    state.is_viewed = True
    state.hidden_reason = payload.reason
    state.hidden_at = now
    state.viewed_at = now
    db.add(
        AuditLog(
            user_id=user.id,
            action="document_hidden",
            entity_type="document",
            entity_id=document_id,
            message="Документ скрыт из оперативного списка",
            details_json={"reason": payload.reason},
        )
    )
    db.commit()


@router.post("/{document_id}/unhide", status_code=status.HTTP_204_NO_CONTENT)
def unhide_document(document_id: str, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> None:
    state = db.scalar(
        select(DocumentUserState).where(
            DocumentUserState.document_id == document_id,
            DocumentUserState.user_id == user.id,
        )
    )
    if state:
        state.is_hidden = False
        state.hidden_reason = None
        state.hidden_at = None

    db.add(
        AuditLog(
            user_id=user.id,
            action="document_unhidden",
            entity_type="document",
            entity_id=document_id,
            message="Документ возвращен в оперативный список",
        )
    )
    db.commit()
