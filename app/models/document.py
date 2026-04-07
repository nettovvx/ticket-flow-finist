from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Document(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "documents"

    doc_type: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    flow_group: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    source_system: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), index=True, default="in_progress", nullable=False)
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

    payload = relationship("DocumentPayload", back_populates="document", uselist=False, cascade="all, delete-orphan")
    events = relationship("DocumentEvent", back_populates="document", cascade="all, delete-orphan")
    user_states = relationship("DocumentUserState", back_populates="document", cascade="all, delete-orphan")
    outgoing_links = relationship(
        "DocumentLink",
        foreign_keys="DocumentLink.from_document_id",
        back_populates="from_document",
        cascade="all, delete-orphan",
    )
    incoming_links = relationship(
        "DocumentLink",
        foreign_keys="DocumentLink.to_document_id",
        back_populates="to_document",
        cascade="all, delete-orphan",
    )


class DocumentPayload(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_payloads"

    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), unique=True, nullable=False)
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

    document = relationship("Document", back_populates="payload")


class DocumentEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_events"

    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    step_code: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(nullable=True)
    meta_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    document = relationship("Document", back_populates="events")


class DocumentLink(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_links"

    from_document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), nullable=False, index=True)
    to_document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), nullable=False, index=True)
    link_type: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    from_document = relationship("Document", foreign_keys=[from_document_id], back_populates="outgoing_links")
    to_document = relationship("Document", foreign_keys=[to_document_id], back_populates="incoming_links")


class DocumentUserState(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_user_states"
    __table_args__ = (UniqueConstraint("document_id", "user_id", name="uq_document_user_state"),)

    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    is_viewed: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_hidden: Mapped[bool] = mapped_column(default=False, nullable=False)
    hidden_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hidden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    document = relationship("Document", back_populates="user_states")
    user = relationship("User", back_populates="document_states")

