from __future__ import annotations

from datetime import datetime
from typing import ClassVar
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import Uuid as SQLAlchemyUUID
from sqlalchemy.orm import Mapped, mapped_column

from erp_api.db.base import Base
from erp_api.db.tenant_scope import TenantScoped


class LogisticsDocument(TenantScoped, Base):
    __tablename__ = "logistics_documents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["waybill_id", "tenant_id"],
            ["logistics_waybills.id", "logistics_waybills.tenant_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "tenant_id", name="uq_logistics_documents_id_tenant"),
        UniqueConstraint(
            "tenant_id", "object_key", name="uq_logistics_documents_tenant_object"
        ),
        CheckConstraint(
            "document_type IN ('shipping_label', 'carrier_invoice', 'return_proof')",
            name="ck_logistics_documents_type",
        ),
        CheckConstraint(
            "owner_type IN ('waybill', 'carrier_invoice', 'return')",
            name="ck_logistics_documents_owner_type",
        ),
        CheckConstraint("size_bytes > 0", name="ck_logistics_documents_size"),
        CheckConstraint(
            "(document_type = 'shipping_label' AND owner_type = 'waybill' "
            "AND waybill_id = owner_reference_id) OR "
            "(document_type = 'carrier_invoice' AND owner_type = 'carrier_invoice' "
            "AND waybill_id IS NULL) OR "
            "(document_type = 'return_proof' AND owner_type = 'return' "
            "AND waybill_id IS NULL)",
            name="ck_logistics_documents_owner_match",
        ),
        Index(
            "uq_logistics_documents_current_owner",
            "tenant_id",
            "document_type",
            "owner_reference_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    document_type: Mapped[str] = mapped_column(String(32), nullable=False)
    owner_type: Mapped[str] = mapped_column(String(32), nullable=False)
    owner_reference_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False, index=True
    )
    waybill_id: Mapped[UUID | None] = mapped_column(SQLAlchemyUUID(as_uuid=True))
    storage_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    bucket: Mapped[str] = mapped_column(String(128), nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256_hex: Mapped[str] = mapped_column(String(64), nullable=False)
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    version_id: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )

    __mapper_args__: ClassVar[dict[str, object]] = {"version_id_col": version_id}
