"""add logistics object documents

Revision ID: e25d6e7f8091
Revises: d14c5d6e7f80
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e25d6e7f8091"
down_revision: str | Sequence[str] | None = "d14c5d6e7f80"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "logistics_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_type", sa.String(32), nullable=False),
        sa.Column("owner_type", sa.String(32), nullable=False),
        sa.Column("owner_reference_id", sa.Uuid(), nullable=False),
        sa.Column("waybill_id", sa.Uuid()),
        sa.Column("storage_provider", sa.String(32), nullable=False),
        sa.Column("bucket", sa.String(128), nullable=False),
        sa.Column("object_key", sa.String(512), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256_hex", sa.String(64), nullable=False),
        sa.Column("is_current", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("version_id", sa.Integer(), server_default="1", nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["waybill_id", "tenant_id"],
            ["logistics_waybills.id", "logistics_waybills.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "document_type IN ('shipping_label', 'carrier_invoice', 'return_proof')",
            name="ck_logistics_documents_type",
        ),
        sa.CheckConstraint(
            "owner_type IN ('waybill', 'carrier_invoice', 'return')",
            name="ck_logistics_documents_owner_type",
        ),
        sa.CheckConstraint("size_bytes > 0", name="ck_logistics_documents_size"),
        sa.CheckConstraint(
            "(document_type = 'shipping_label' AND owner_type = 'waybill' AND waybill_id = owner_reference_id) OR "
            "(document_type = 'carrier_invoice' AND owner_type = 'carrier_invoice' AND waybill_id IS NULL) OR "
            "(document_type = 'return_proof' AND owner_type = 'return' AND waybill_id IS NULL)",
            name="ck_logistics_documents_owner_match",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_logistics_documents_id_tenant"),
        sa.UniqueConstraint(
            "tenant_id", "object_key", name="uq_logistics_documents_tenant_object"
        ),
    )
    op.create_index(
        "ix_logistics_documents_tenant_id", "logistics_documents", ["tenant_id"]
    )
    op.create_index(
        "ix_logistics_documents_owner_reference_id",
        "logistics_documents",
        ["owner_reference_id"],
    )
    op.create_index(
        "uq_logistics_documents_current_owner",
        "logistics_documents",
        ["tenant_id", "document_type", "owner_reference_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )


def downgrade() -> None:
    op.drop_table("logistics_documents")
