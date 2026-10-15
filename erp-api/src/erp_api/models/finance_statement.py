from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy import Uuid as SQLAlchemyUUID
from sqlalchemy.orm import Mapped, mapped_column

from erp_api.db.base import Base
from erp_api.db.tenant_scope import TenantScoped


class FinanceStatement(TenantScoped, Base):
    __tablename__ = "finance_statements"
    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id", "tenant_id"],
            ["shops.id", "shops.tenant_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "tenant_id", name="uq_finance_statements_id_tenant"),
        UniqueConstraint(
            "tenant_id",
            "shop_id",
            "platform_statement_id",
            name="uq_finance_statements_tenant_shop_platform",
        ),
        Index(
            "ix_finance_statements_filter",
            "tenant_id",
            "shop_id",
            "statement_end_at",
            "currency",
            "payment_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    shop_id: Mapped[UUID] = mapped_column(SQLAlchemyUUID(as_uuid=True), nullable=False)
    platform_statement_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    payment_status: Mapped[str] = mapped_column(String(32), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    revenue_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fee_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    adjustment_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    settlement_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    statement_start_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    statement_end_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    platform_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    platform_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
