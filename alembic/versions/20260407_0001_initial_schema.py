"""initial schema

Revision ID: 20260407_0001
Revises: 
Create Date: 2026-04-07 18:10:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260407_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents",
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
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_documents_business_key"), "documents", ["business_key"], unique=False)
    op.create_index(op.f("ix_documents_doc_type"), "documents", ["doc_type"], unique=False)
    op.create_index(op.f("ix_documents_flow_group"), "documents", ["flow_group"], unique=False)
    op.create_index(op.f("ix_documents_occurred_at"), "documents", ["occurred_at"], unique=False)
    op.create_index(op.f("ix_documents_status"), "documents", ["status"], unique=False)

    op.create_table(
        "users",
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)

    op.create_table(
        "audit_logs",
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=True),
        sa.Column("details_json", sa.JSON(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_logs_user_id"), "audit_logs", ["user_id"], unique=False)

    op.create_table(
        "document_events",
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("step_code", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("meta_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_document_events_document_id"), "document_events", ["document_id"], unique=False)

    op.create_table(
        "document_links",
        sa.Column("from_document_id", sa.String(length=36), nullable=False),
        sa.Column("to_document_id", sa.String(length=36), nullable=False),
        sa.Column("link_type", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.String(length=32), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["from_document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["to_document_id"], ["documents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_document_links_from_document_id"), "document_links", ["from_document_id"], unique=False)
    op.create_index(op.f("ix_document_links_to_document_id"), "document_links", ["to_document_id"], unique=False)

    op.create_table(
        "document_payloads",
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
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id"),
    )
    op.create_index(op.f("ix_document_payloads_client_name"), "document_payloads", ["client_name"], unique=False)
    op.create_index(op.f("ix_document_payloads_document_date"), "document_payloads", ["document_date"], unique=False)
    op.create_index(op.f("ix_document_payloads_exchange_ticket_number"), "document_payloads", ["exchange_ticket_number"], unique=False)
    op.create_index(op.f("ix_document_payloads_mom_number"), "document_payloads", ["mom_number"], unique=False)
    op.create_index(op.f("ix_document_payloads_passenger_name"), "document_payloads", ["passenger_name"], unique=False)
    op.create_index(op.f("ix_document_payloads_payment_number"), "document_payloads", ["payment_number"], unique=False)
    op.create_index(op.f("ix_document_payloads_pnr"), "document_payloads", ["pnr"], unique=False)
    op.create_index(op.f("ix_document_payloads_ticket_number"), "document_payloads", ["ticket_number"], unique=False)

    op.create_table(
        "document_user_states",
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("is_viewed", sa.Boolean(), nullable=False),
        sa.Column("is_hidden", sa.Boolean(), nullable=False),
        sa.Column("hidden_reason", sa.String(length=255), nullable=True),
        sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "user_id", name="uq_document_user_state"),
    )
    op.create_index(op.f("ix_document_user_states_document_id"), "document_user_states", ["document_id"], unique=False)
    op.create_index(op.f("ix_document_user_states_user_id"), "document_user_states", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_document_user_states_user_id"), table_name="document_user_states")
    op.drop_index(op.f("ix_document_user_states_document_id"), table_name="document_user_states")
    op.drop_table("document_user_states")

    op.drop_index(op.f("ix_document_payloads_ticket_number"), table_name="document_payloads")
    op.drop_index(op.f("ix_document_payloads_pnr"), table_name="document_payloads")
    op.drop_index(op.f("ix_document_payloads_payment_number"), table_name="document_payloads")
    op.drop_index(op.f("ix_document_payloads_passenger_name"), table_name="document_payloads")
    op.drop_index(op.f("ix_document_payloads_mom_number"), table_name="document_payloads")
    op.drop_index(op.f("ix_document_payloads_exchange_ticket_number"), table_name="document_payloads")
    op.drop_index(op.f("ix_document_payloads_document_date"), table_name="document_payloads")
    op.drop_index(op.f("ix_document_payloads_client_name"), table_name="document_payloads")
    op.drop_table("document_payloads")

    op.drop_index(op.f("ix_document_links_to_document_id"), table_name="document_links")
    op.drop_index(op.f("ix_document_links_from_document_id"), table_name="document_links")
    op.drop_table("document_links")

    op.drop_index(op.f("ix_document_events_document_id"), table_name="document_events")
    op.drop_table("document_events")

    op.drop_index(op.f("ix_audit_logs_user_id"), table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_index(op.f("ix_users_username"), table_name="users")
    op.drop_table("users")

    op.drop_index(op.f("ix_documents_status"), table_name="documents")
    op.drop_index(op.f("ix_documents_occurred_at"), table_name="documents")
    op.drop_index(op.f("ix_documents_flow_group"), table_name="documents")
    op.drop_index(op.f("ix_documents_doc_type"), table_name="documents")
    op.drop_index(op.f("ix_documents_business_key"), table_name="documents")
    op.drop_table("documents")
