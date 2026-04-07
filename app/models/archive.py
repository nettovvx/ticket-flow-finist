from datetime import datetime

from sqlalchemy import DateTime, Float, Index, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ArchivedDocument(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "documents_archive"
    __table_args__ = (Index("ix_documents_archive_lookup", "doc_type", "flow_group", "source_system", "file_name"),)

    doc_type: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    flow_group: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    source_system: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    current_step: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    file_size: Mapped[int | None] = mapped_column(nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(128), nullable=True)
    business_key: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)


class ArchivedDocumentPayload(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_payloads_archive"
    __table_args__ = (UniqueConstraint("document_id", name="uq_document_payload_archive"),)

    document_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    passenger_name: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    ticket_number: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    exchange_ticket_number: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    pnr: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    mom_number: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    payment_number: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    payment_purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_name: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    direction: Mapped[str | None] = mapped_column(String(32), nullable=True)
    document_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True, nullable=True)
    route: Mapped[str | None] = mapped_column(String(255), nullable=True)
    extra_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    archived_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)


class ArchivedDocumentEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_events_archive"

    document_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    step_code: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(nullable=True)
    meta_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    archived_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)


class ArchivedDocumentLink(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_links_archive"

    from_document_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    to_document_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    link_type: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    archived_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)


class ArchivedDocumentUserState(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_user_states_archive"
    __table_args__ = (UniqueConstraint("document_id", "user_id", name="uq_document_user_state_archive"),)

    document_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    is_viewed: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_hidden: Mapped[bool] = mapped_column(default=False, nullable=False)
    hidden_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hidden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
