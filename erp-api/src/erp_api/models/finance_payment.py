from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKeyConstraint,
    Index,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy import Uuid as SQLAlchemyUUID
from sqlalchemy.orm import Mapped, mapped_column

from erp_api.db.base import Base
from erp_api.db.tenant_scope import TenantScoped


class FinancePayment(TenantScoped, Base):
    __tablename__ = "finance_payments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id", "tenant_id"],
            ["shops.id", "shops.tenant_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "tenant_id", name="uq_finance_payments_id_tenant"),
        UniqueConstraint(
            "tenant_id",
            "shop_id",
            "platform_payment_id",
            name="uq_finance_payments_tenant_shop_platform",
        ),
        Index(
            "ix_finance_payments_filter",
            "tenant_id",
            "shop_id",
            "paid_at",
            "currency",
            "status",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    shop_id: Mapped[UUID] = mapped_column(SQLAlchemyUUID(as_uuid=True), nullable=False)
    platform_payment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    payment_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    initiated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bank_reference_masked: Mapped[str | None] = mapped_column(String(128))
    platform_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class FinancePaymentStatement(TenantScoped, Base):
    __tablename__ = "finance_payment_statements"
    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "payment_id", "statement_id"),
        ForeignKeyConstraint(
            ["payment_id", "tenant_id"],
            ["finance_payments.id", "finance_payments.tenant_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["statement_id", "tenant_id"],
            ["finance_statements.id", "finance_statements.tenant_id"],
            ondelete="CASCADE",
        ),
        Index(
            "ix_finance_payment_statements_statement",
            "tenant_id",
            "statement_id",
        ),
    )

    payment_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False
    )
    statement_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False
    )
