from datetime import datetime

from pydantic import BaseModel, Field


class UserResponse(BaseModel):
    id: str
    username: str
    role: str
    is_active: bool
    last_login_at: datetime | None


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=255)


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=255)
    role: str = Field(pattern=r"^(admin|user)$")


class UpdateUserRequest(BaseModel):
    role: str = Field(pattern=r"^(admin|user)$")


class DocumentPayloadResponse(BaseModel):
    passenger_name: str | None
    ticket_number: str | None
    exchange_ticket_number: str | None
    pnr: str | None
    mom_number: str | None
    payment_number: str | None
    payment_purpose: str | None
    client_name: str | None
    amount: float | None
    currency: str | None
    direction: str | None
    document_date: datetime | None
    route: str | None
    extra_json: dict | None


class DocumentEventResponse(BaseModel):
    id: str
    event_type: str
    step_code: str
    status: str
    message: str | None
    occurred_at: datetime | None
    duration_ms: int | None
    meta_json: dict | None


class DocumentResponse(BaseModel):
    id: str
    doc_type: str
    flow_group: str
    source_system: str
    status: str
    current_step: str | None
    title: str | None
    file_name: str
    file_path: str | None
    file_size: int | None
    business_key: str | None
    error_message: str | None
    occurred_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    payload: DocumentPayloadResponse | None = None
    events: list[DocumentEventResponse] | None = None


class DocumentStateResponse(BaseModel):
    is_hidden: bool
    is_viewed: bool
    hidden_reason: str | None
    viewed_at: datetime | None
    hidden_at: datetime | None


class TicketFlowStepResponse(BaseModel):
    code: str
    label: str
    status: str
    occurred_at: datetime | None = None
    delta_seconds: int | None = None
    delta_human: str | None = None


class TicketCaseResponse(BaseModel):
    ticket: DocumentResponse
    ticket_state: DocumentStateResponse | None
    realizations: list[DocumentResponse]
    group_status: str
    steps: list[TicketFlowStepResponse]
    last_activity_at: datetime | None


class OrphanRealizationResponse(BaseModel):
    realization: DocumentResponse
    state: DocumentStateResponse | None


class TicketListingEntryResponse(BaseModel):
    entry_type: str
    entry_id: str
    ticket_case: TicketCaseResponse | None = None
    orphan_realization: OrphanRealizationResponse | None = None


class TicketsListingResponse(BaseModel):
    entries: list[TicketListingEntryResponse]
    ticket_cases: list[TicketCaseResponse]
    orphan_realizations: list[OrphanRealizationResponse]
    counters: dict[str, int]
    total_count: int
    filtered_count: int
    offset: int
    limit: int
    has_more: bool


class DocumentRowResponse(BaseModel):
    document: DocumentResponse
    state: DocumentStateResponse | None


class DocumentsListingResponse(BaseModel):
    rows: list[DocumentRowResponse]
    counters: dict[str, int]
    total_count: int
    filtered_count: int
    offset: int
    limit: int
    has_more: bool


class DocumentDetailResponse(BaseModel):
    document: DocumentResponse
    root_ticket: DocumentResponse
    root_ticket_state: DocumentStateResponse | None = None
    linked_realizations: list[DocumentResponse]
    linked_payments: list[DocumentResponse]
    steps: list[TicketFlowStepResponse]


class HideDocumentRequest(BaseModel):
    reason: str = Field(default="Просмотрено")
