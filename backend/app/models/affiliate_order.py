from datetime import UTC, datetime
from decimal import Decimal

from app.db.base import Base
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column


class AffiliateOrderItem(Base):
    __tablename__ = "affiliate_order_items"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    shop_id: Mapped[str | None] = mapped_column(String(64), index=True)
    main_order_id: Mapped[str] = mapped_column(String(64), index=True)
    creator_id: Mapped[str | None] = mapped_column(String(64), index=True)
    creator_nickname: Mapped[str | None] = mapped_column(String(255))
    campaign_id: Mapped[str | None] = mapped_column(String(64))
    product_id: Mapped[str | None] = mapped_column(String(64), index=True)
    product_name: Mapped[str | None] = mapped_column(String(500))
    image_uri: Mapped[str | None] = mapped_column(Text)
    sku_id: Mapped[str | None] = mapped_column(String(64), index=True)
    sku_name: Mapped[str | None] = mapped_column(String(500))
    order_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_cod: Mapped[bool | None] = mapped_column(Boolean)
    is_non_same_shop_order: Mapped[bool | None] = mapped_column(Boolean)
    cos_type: Mapped[int | None] = mapped_column(Integer)
    commission_base: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    commission_currency: Mapped[str | None] = mapped_column(String(16))
    commission_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    estimated_standard_commission: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    source_record_key: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        index=True,
    )
    raw_data: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


Index(
    "ix_affiliate_main_order_creator",
    AffiliateOrderItem.main_order_id,
    AffiliateOrderItem.creator_id,
)
