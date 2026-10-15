from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKeyConstraint, String, Text, UniqueConstraint
from sqlalchemy import Uuid as SQLAlchemyUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from erp_api.db.base import Base
from erp_api.db.tenant_scope import TenantScoped

if TYPE_CHECKING:
    from erp_api.models.order import Order


class OrderRecipient(TenantScoped, Base):
    __tablename__ = "order_recipients"
    __table_args__ = (
        UniqueConstraint("order_id", name="uq_order_recipients_order"),
        ForeignKeyConstraint(
            ["order_id", "tenant_id"],
            ["orders.id", "orders.tenant_id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    order_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False, index=True
    )
    name_masked: Mapped[str | None] = mapped_column(String(128))
    phone_masked: Mapped[str | None] = mapped_column(String(64))
    address_masked: Mapped[str | None] = mapped_column(String(300))
    name_ciphertext: Mapped[str | None] = mapped_column(Text)
    phone_ciphertext: Mapped[str | None] = mapped_column(Text)
    address_ciphertext: Mapped[str | None] = mapped_column(Text)
    country_code: Mapped[str | None] = mapped_column(String(2))
    purge_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    order: Mapped[Order] = relationship(back_populates="recipient")
