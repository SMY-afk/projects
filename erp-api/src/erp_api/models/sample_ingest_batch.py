from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import Uuid as SQLAlchemyUUID
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from erp_api.db.base import Base
from erp_api.db.tenant_scope import TenantScoped


class SampleIngestBatch(TenantScoped, Base):
    __tablename__ = "sample_ingest_batches"
    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id", "tenant_id"],
            ["shops.id", "shops.tenant_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "tenant_id", name="uq_sample_ingest_batches_id_tenant"),
        UniqueConstraint(
            "id",
            "tenant_id",
            "shop_id",
            name="uq_sample_ingest_batches_id_tenant_shop",
        ),
        CheckConstraint(
            "sample_type IN ('free', 'refundable')",
            name="ck_sample_ingest_batches_sample_type",
        ),
        CheckConstraint(
            "source_type IN ('official_api', 'hubstudio_cdp')",
            name="ck_sample_ingest_batches_source_type",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'complete', 'partial', 'failed')",
            name="ck_sample_ingest_batches_status",
        ),
        CheckConstraint(
            "expected_total IS NULL OR expected_total >= 0",
            name="ck_sample_ingest_batches_expected_total",
        ),
        CheckConstraint(
            "captured_total >= 0 AND page_count >= 0",
            name="ck_sample_ingest_batches_counts",
        ),
        CheckConstraint(
            "status <> 'complete' OR finished_at IS NOT NULL",
            name="ck_sample_ingest_batches_complete_finished",
        ),
        Index(
            "ix_sample_ingest_batches_shop_source_started",
            "tenant_id",
            "shop_id",
            "source_type",
            "started_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    shop_id: Mapped[UUID] = mapped_column(SQLAlchemyUUID(as_uuid=True), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    sample_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="free", server_default="free"
    )
    source_identity: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    expected_total: Mapped[int | None] = mapped_column(Integer)
    captured_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload_hash: Mapped[str | None] = mapped_column(String(64))
    completeness_evidence: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_summary: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
