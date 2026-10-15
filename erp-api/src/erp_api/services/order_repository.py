from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.orm import selectinload

from erp_api.infrastructure.database import Database
from erp_api.models.affiliate_order_item import AffiliateOrderItem
from erp_api.models.finance_transaction import FinanceTransaction
from erp_api.models.order import Order
from erp_api.models.order_attribution import OrderAttribution
from erp_api.models.order_fulfillment import OrderFulfillment
from erp_api.models.order_line import OrderLine
from erp_api.models.order_recipient import OrderRecipient
from erp_api.models.pii_access_audit import PiiAccessAudit
from erp_api.models.tiktok_webhook_event import TikTokWebhookEvent
from erp_api.services.token_cipher import TokenCipher


@dataclass(frozen=True)
class OrderListItem:
    order: Order
    settlement_amount_minor: int | None


@dataclass(frozen=True)
class OrderListPage:
    items: list[OrderListItem]
    total: int


class OrderRepository:
    def __init__(self, database: Database, pii_cipher: TokenCipher) -> None:
        self._database = database
        self._pii_cipher = pii_cipher

    async def list_orders(
        self,
        tenant_id: UUID,
        *,
        page: int,
        page_size: int,
        shop_id: UUID | None = None,
        keyword: str | None = None,
        status: str | None = None,
        updated_from: datetime | None = None,
        updated_to: datetime | None = None,
        traffic_source: str | None = None,
        operator_subject: str | None = None,
        entry_point: str | None = None,
        special_order_type: str | None = None,
        classification_status: str | None = None,
        content_form: str | None = None,
    ) -> OrderListPage:
        filters = self._filters(
            shop_id,
            keyword,
            status,
            updated_from,
            updated_to,
            traffic_source=traffic_source,
            operator_subject=operator_subject,
            entry_point=entry_point,
            special_order_type=special_order_type,
            classification_status=classification_status,
            content_form=content_form,
        )
        async for session in self._database.session(tenant_id):
            settlement_totals = _settlement_totals()
            rows = await session.execute(
                select(Order, settlement_totals.c.settlement_amount_minor)
                .outerjoin(
                    settlement_totals,
                    and_(
                        settlement_totals.c.tenant_id == Order.tenant_id,
                        settlement_totals.c.order_id == Order.id,
                        settlement_totals.c.currency == Order.currency,
                    ),
                )
                .options(
                    selectinload(Order.shop),
                    selectinload(Order.lines),
                    selectinload(Order.fulfillments),
                    selectinload(Order.recipient),
                    selectinload(Order.attribution),
                    selectinload(Order.affiliate_order_items),
                )
                .where(*filters)
                .order_by(Order.platform_updated_at.desc(), Order.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            items = [
                OrderListItem(
                    order=row[0],
                    settlement_amount_minor=(
                        int(row[1]) if row[1] is not None else None
                    ),
                )
                for row in rows
            ]
            total = await session.scalar(
                select(func.count()).select_from(Order).where(*filters)
            )
            return OrderListPage(
                items=items,
                total=total or 0,
            )
        raise RuntimeError("Tenant database session was not created.")

    async def get_order(self, tenant_id: UUID, order_id: UUID) -> Order | None:
        async for session in self._database.session(tenant_id):
            return await session.scalar(
                select(Order)
                .options(
                    selectinload(Order.shop),
                    selectinload(Order.lines),
                    selectinload(Order.fulfillments),
                    selectinload(Order.recipient),
                    selectinload(Order.attribution),
                    selectinload(Order.affiliate_order_items),
                )
                .where(Order.id == order_id)
            )
        return None

    async def reveal_recipient(
        self, tenant_id: UUID, order_id: UUID
    ) -> dict[str, object] | None:
        async for session in self._database.session(tenant_id):
            recipient = await session.scalar(
                select(OrderRecipient).where(OrderRecipient.order_id == order_id)
            )
            if recipient is None:
                return None
            return {
                "name": self._decrypt(recipient.name_ciphertext),
                "phone": self._decrypt(recipient.phone_ciphertext),
                "address": self._decrypt(recipient.address_ciphertext),
                "countryCode": recipient.country_code,
                "purged": recipient.purged_at is not None,
            }
        return None

    async def record_pii_access(
        self,
        tenant_id: UUID,
        *,
        order_id: UUID,
        actor_user_id: UUID,
        request_id: str,
        result: str,
    ) -> None:
        async for session in self._database.session(tenant_id):
            session.add(
                PiiAccessAudit(
                    tenant_id=tenant_id,
                    order_id=order_id,
                    actor_user_id=actor_user_id,
                    action="view_order_recipient",
                    result=result,
                    request_id=request_id,
                )
            )
            await session.commit()
            return

    async def purge_expired_pii(
        self, tenant_id: UUID, now: datetime | None = None
    ) -> int:
        cutoff = now or datetime.now(UTC)
        async for session in self._database.session(tenant_id):
            order_ids = select(OrderRecipient.order_id).where(
                OrderRecipient.purge_after.is_not(None),
                OrderRecipient.purge_after <= cutoff,
                OrderRecipient.purged_at.is_(None),
            )
            recipient_result = await session.execute(
                update(OrderRecipient)
                .where(OrderRecipient.order_id.in_(order_ids))
                .values(
                    name_ciphertext=None,
                    phone_ciphertext=None,
                    address_ciphertext=None,
                    purged_at=cutoff,
                )
            )
            await session.execute(
                update(OrderFulfillment)
                .where(OrderFulfillment.order_id.in_(order_ids))
                .values(tracking_number_ciphertext=None)
            )
            await session.execute(
                update(TikTokWebhookEvent)
                .where(TikTokWebhookEvent.received_at <= cutoff)
                .values(payload_ciphertext=None)
            )
            await session.commit()
            return recipient_result.rowcount or 0
        return 0

    @staticmethod
    def _filters(
        shop_id: UUID | None,
        keyword: str | None,
        status: str | None,
        updated_from: datetime | None,
        updated_to: datetime | None,
        *,
        traffic_source: str | None = None,
        operator_subject: str | None = None,
        entry_point: str | None = None,
        special_order_type: str | None = None,
        classification_status: str | None = None,
        content_form: str | None = None,
    ) -> list[object]:
        filters: list[object] = []
        if shop_id:
            filters.append(Order.shop_id == shop_id)
        if status:
            filters.append(Order.status == status)
        if updated_from:
            filters.append(Order.platform_updated_at >= updated_from)
        if updated_to:
            filters.append(Order.platform_updated_at < updated_to)
        if keyword and (needle := keyword.strip()):
            pattern = f"%{needle}%"
            line_match = exists(
                select(OrderLine.id).where(
                    OrderLine.order_id == Order.id,
                    or_(
                        OrderLine.seller_sku.ilike(pattern),
                        OrderLine.platform_sku_id.ilike(pattern),
                    ),
                )
            )
            filters.append(
                or_(
                    Order.order_number.ilike(pattern),
                    Order.platform_order_id.ilike(pattern),
                    line_match,
                )
            )
        attribution_filters = {
            "traffic_source": traffic_source,
            "operator_subject": operator_subject,
            "entry_point": entry_point,
            "classification_status": classification_status,
        }
        for field, value in attribution_filters.items():
            if value is not None:
                column = getattr(OrderAttribution, field)
                filters.append(
                    Order.attribution.has(column == value)
                    if value != "unknown"
                    else ~Order.attribution.has()
                    | Order.attribution.has(column == "unknown")
                )
        if special_order_type == "sample":
            filters.append(Order.total_amount_minor == 0)
        elif special_order_type is not None:
            filters.append(
                Order.attribution.has(
                    OrderAttribution.special_order_type == special_order_type
                )
                if special_order_type != "unknown"
                else ~Order.attribution.has()
                | Order.attribution.has(
                    OrderAttribution.special_order_type == "unknown"
                )
            )
        if content_form is not None:
            filters.append(
                Order.affiliate_order_items.any(
                    AffiliateOrderItem.content_form == content_form
                )
            )
        return filters

    def _decrypt(self, value: str | None) -> str | None:
        return self._pii_cipher.decrypt(value) if value else None


def _settlement_totals():
    transaction = FinanceTransaction
    return (
        select(
            transaction.tenant_id.label("tenant_id"),
            transaction.order_id.label("order_id"),
            transaction.currency.label("currency"),
            func.sum(transaction.settlement_amount_minor).label(
                "settlement_amount_minor"
            ),
        )
        .where(
            transaction.order_id.is_not(None),
            transaction.is_estimated.is_(False),
        )
        .group_by(transaction.tenant_id, transaction.order_id, transaction.currency)
        .subquery()
    )
