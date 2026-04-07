"""archive tables for completed documents

Revision ID: 20260407_0002
Revises: 20260407_0001
Create Date: 2026-04-07 19:45:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260407_0002"
down_revision = "20260407_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents_archive",
        sa.Column("doc_type", sa.String(length=32), nullable=False),
        sa.Column("flow_group", sa.String(length=32), nullable=False),
        sa.Column("source_system", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("current_step", sa.String(length=64), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("file_path", sa.String(length=1024), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.String(length=128), nullable=True),
        sa.Column("business_key", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_documents_archive_archived_at"), "documents_archive", ["archived_at"], unique=False)
    op.create_index(op.f("ix_documents_archive_business_key"), "documents_archive", ["business_key"], unique=False)
    op.create_index(op.f("ix_documents_archive_doc_type"), "documents_archive", ["doc_type"], unique=False)
    op.create_index(op.f("ix_documents_archive_flow_group"), "documents_archive", ["flow_group"], unique=False)
    op.create_index("ix_documents_archive_lookup", "documents_archive", ["doc_type", "flow_group", "source_system", "file_name"], unique=False)
    op.create_index(op.f("ix_documents_archive_occurred_at"), "documents_archive", ["occurred_at"], unique=False)
    op.create_index(op.f("ix_documents_archive_status"), "documents_archive", ["status"], unique=False)

    op.create_table(
        "document_events_archive",
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("step_code", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("meta_json", sa.JSON(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_document_events_archive_archived_at"), "document_events_archive", ["archived_at"], unique=False)
    op.create_index(op.f("ix_document_events_archive_document_id"), "document_events_archive", ["document_id"], unique=False)

    op.create_table(
        "document_links_archive",
        sa.Column("from_document_id", sa.String(length=36), nullable=False),
        sa.Column("to_document_id", sa.String(length=36), nullable=False),
        sa.Column("link_type", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.String(length=32), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_document_links_archive_archived_at"), "document_links_archive", ["archived_at"], unique=False)
    op.create_index(op.f("ix_document_links_archive_from_document_id"), "document_links_archive", ["from_document_id"], unique=False)
    op.create_index(op.f("ix_document_links_archive_to_document_id"), "document_links_archive", ["to_document_id"], unique=False)

    op.create_table(
        "document_payloads_archive",
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("passenger_name", sa.String(length=255), nullable=True),
        sa.Column("ticket_number", sa.String(length=64), nullable=True),
        sa.Column("exchange_ticket_number", sa.String(length=64), nullable=True),
        sa.Column("pnr", sa.String(length=32), nullable=True),
        sa.Column("mom_number", sa.String(length=64), nullable=True),
        sa.Column("payment_number", sa.String(length=64), nullable=True),
        sa.Column("payment_purpose", sa.Text(), nullable=True),
        sa.Column("client_name", sa.String(length=255), nullable=True),
        sa.Column("amount", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(length=16), nullable=True),
        sa.Column("direction", sa.String(length=32), nullable=True),
        sa.Column("document_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("route", sa.String(length=255), nullable=True),
        sa.Column("extra_json", sa.JSON(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", name="uq_document_payload_archive"),
    )
    op.create_index(op.f("ix_document_payloads_archive_archived_at"), "document_payloads_archive", ["archived_at"], unique=False)
    op.create_index(op.f("ix_document_payloads_archive_client_name"), "document_payloads_archive", ["client_name"], unique=False)
    op.create_index(op.f("ix_document_payloads_archive_document_date"), "document_payloads_archive", ["document_date"], unique=False)
    op.create_index(op.f("ix_document_payloads_archive_document_id"), "document_payloads_archive", ["document_id"], unique=False)
    op.create_index(op.f("ix_document_payloads_archive_exchange_ticket_number"), "document_payloads_archive", ["exchange_ticket_number"], unique=False)
    op.create_index(op.f("ix_document_payloads_archive_mom_number"), "document_payloads_archive", ["mom_number"], unique=False)
    op.create_index(op.f("ix_document_payloads_archive_passenger_name"), "document_payloads_archive", ["passenger_name"], unique=False)
    op.create_index(op.f("ix_document_payloads_archive_payment_number"), "document_payloads_archive", ["payment_number"], unique=False)
    op.create_index(op.f("ix_document_payloads_archive_pnr"), "document_payloads_archive", ["pnr"], unique=False)
    op.create_index(op.f("ix_document_payloads_archive_ticket_number"), "document_payloads_archive", ["ticket_number"], unique=False)

    op.create_table(
        "document_user_states_archive",
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("is_viewed", sa.Boolean(), nullable=False),
        sa.Column("is_hidden", sa.Boolean(), nullable=False),
        sa.Column("hidden_reason", sa.String(length=255), nullable=True),
        sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "user_id", name="uq_document_user_state_archive"),
    )
    op.create_index(op.f("ix_document_user_states_archive_archived_at"), "document_user_states_archive", ["archived_at"], unique=False)
    op.create_index(op.f("ix_document_user_states_archive_document_id"), "document_user_states_archive", ["document_id"], unique=False)
    op.create_index(op.f("ix_document_user_states_archive_user_id"), "document_user_states_archive", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_document_user_states_archive_user_id"), table_name="document_user_states_archive")
    op.drop_index(op.f("ix_document_user_states_archive_document_id"), table_name="document_user_states_archive")
    op.drop_index(op.f("ix_document_user_states_archive_archived_at"), table_name="document_user_states_archive")
    op.drop_table("document_user_states_archive")

    op.drop_index(op.f("ix_document_payloads_archive_ticket_number"), table_name="document_payloads_archive")
    op.drop_index(op.f("ix_document_payloads_archive_pnr"), table_name="document_payloads_archive")
    op.drop_index(op.f("ix_document_payloads_archive_payment_number"), table_name="document_payloads_archive")
    op.drop_index(op.f("ix_document_payloads_archive_passenger_name"), table_name="document_payloads_archive")
    op.drop_index(op.f("ix_document_payloads_archive_mom_number"), table_name="document_payloads_archive")
    op.drop_index(op.f("ix_document_payloads_archive_exchange_ticket_number"), table_name="document_payloads_archive")
    op.drop_index(op.f("ix_document_payloads_archive_document_id"), table_name="document_payloads_archive")
    op.drop_index(op.f("ix_document_payloads_archive_document_date"), table_name="document_payloads_archive")
    op.drop_index(op.f("ix_document_payloads_archive_client_name"), table_name="document_payloads_archive")
    op.drop_index(op.f("ix_document_payloads_archive_archived_at"), table_name="document_payloads_archive")
    op.drop_table("document_payloads_archive")

    op.drop_index(op.f("ix_document_links_archive_to_document_id"), table_name="document_links_archive")
    op.drop_index(op.f("ix_document_links_archive_from_document_id"), table_name="document_links_archive")
    op.drop_index(op.f("ix_document_links_archive_archived_at"), table_name="document_links_archive")
    op.drop_table("document_links_archive")

    op.drop_index(op.f("ix_document_events_archive_document_id"), table_name="document_events_archive")
    op.drop_index(op.f("ix_document_events_archive_archived_at"), table_name="document_events_archive")
    op.drop_table("document_events_archive")

    op.drop_index(op.f("ix_documents_archive_status"), table_name="documents_archive")
    op.drop_index(op.f("ix_documents_archive_occurred_at"), table_name="documents_archive")
    op.drop_index("ix_documents_archive_lookup", table_name="documents_archive")
    op.drop_index(op.f("ix_documents_archive_flow_group"), table_name="documents_archive")
    op.drop_index(op.f("ix_documents_archive_doc_type"), table_name="documents_archive")
    op.drop_index(op.f("ix_documents_archive_business_key"), table_name="documents_archive")
    op.drop_index(op.f("ix_documents_archive_archived_at"), table_name="documents_archive")
    op.drop_table("documents_archive")
