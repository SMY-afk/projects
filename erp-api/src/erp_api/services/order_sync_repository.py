from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from erp_api.infrastructure.database import Database
from erp_api.models.order import Order
from erp_api.models.order_fulfillment import OrderFulfillment
from erp_api.models.order_recipient import OrderRecipient
from erp_api.models.order_sync import OrderSyncCursor, OrderSyncRun
from erp_api.models.product import Product
from erp_api.models.product_sku import ProductSku
from erp_api.services.order_attribution_repository import OrderAttributionRepository
from erp_api.services.order_chain_classifier import OrderChainClassifier
from erp_api.services.order_conversion_link_repository import (
    OrderConversionLinkRepository,
)
from erp_api.services.order_sync_lines import sync_order_lines
from erp_api.services.order_sync_metrics import metrics_for_orders
from erp_api.services.tiktok_order_schemas import TikTokOrder, TikTokOrderLine
from erp_api.services.token_cipher import TokenCipher

OrderLogisticsProjector = Callable[[object, UUID, UUID], Awaitable[None]]


@dataclass(frozen=True)
class OrderSyncResult:
    run_id: UUID
    shop_id: UUID
    status: str
    fetched_count: int
    upserted_count: int
    recovery_cursor: str | None = None
    error: str | None = None
    confirmed_count: int = 0
    derived_count: int = 0
    unknown_count: int = 0
    unsupported_field_count: int = 0


@dataclass(frozen=True)
class StoredOrderCursor:
    recovery_cursor: str | None
    committed_cursor: str | None
    last_success_at: datetime | None


class OrderSyncRepository:
    def __init__(
        self,
        database: Database,
        pii_cipher: TokenCipher,
        retention_days: int = 90,
        logistics_projector: OrderLogisticsProjector | None = None,
    ) -> None:
        self._database = database
        self._pii_cipher = pii_cipher
        self._retention_days = retention_days
        self._logistics_projector = logistics_projector
        self._attribution_repository = OrderAttributionRepository()
        self._conversion_link_repository = OrderConversionLinkRepository()

    async def get_cursor(self, tenant_id: UUID, shop_id: UUID) -> StoredOrderCursor:
        async for session in self._database.session(tenant_id):
            row = await session.scalar(
                select(OrderSyncCursor).where(OrderSyncCursor.shop_id == shop_id)
            )
            if row is None:
                return StoredOrderCursor(None, None, None)
            return StoredOrderCursor(
                row.recovery_cursor, row.committed_cursor, row.last_success_at
            )
        raise RuntimeError("Tenant database session was not created.")

    async def create_run(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        *,
        trigger: str,
        mode: str,
        window_from: datetime,
        window_to: datetime,
    ) -> UUID:
        async for session in self._database.session(tenant_id):
            run = OrderSyncRun(
                tenant_id=tenant_id,
                shop_id=shop_id,
                trigger=trigger,
                mode=mode,
                status="running",
                window_from=window_from,
                window_to=window_to,
                attempt_count=1,
            )
            session.add(run)
            try:
                await session.commit()
            except IntegrityError as error:
                await session.rollback()
                raise RuntimeError(
                    "An order sync is already active for this shop."
                ) from error
            return run.id
        raise RuntimeError("Tenant database session was not created.")

    async def upsert_page(
        self,
        tenant_id: UUID,
        run_id: UUID,
        shop_id: UUID,
        orders: list[TikTokOrder],
        next_cursor: str,
    ) -> int:
        applied = 0
        metrics = metrics_for_orders(orders)
        async for session in self._database.session(tenant_id):
            for incoming in orders:
                stored = await session.scalar(
                    select(Order).where(
                        Order.shop_id == shop_id,
                        Order.platform_order_id == incoming.platform_order_id,
                    )
                )
                if stored and stored.platform_updated_at > incoming.platform_updated_at:
                    continue
                if stored is None:
                    stored = Order(tenant_id=tenant_id, shop_id=shop_id)
                    session.add(stored)
                self._assign_order(stored, incoming)
                await session.flush()
                await self._replace_children(
                    session, tenant_id, shop_id, stored, incoming
                )
                # Keep the order facts persisted before attribution validation;
                # both remain in the caller-owned transaction until commit.
                await session.flush()
                affiliate_signal = getattr(incoming, "affiliate_signal", None)
                ads_signal = getattr(incoming, "ads_signal", None)
                decision = OrderChainClassifier.classify(
                    getattr(incoming, "attribution_signal", None),
                    affiliate_signal,
                    ads_signal,
                    getattr(incoming, "external_evidence_absence_reason", None),
                )
                await self._attribution_repository.upsert(
                    session, tenant_id, stored.id, decision
                )
                if affiliate_signal is not None and affiliate_signal.has_exact_match:
                    await self._conversion_link_repository.upsert_affiliate(
                        session, tenant_id, stored.id, affiliate_signal
                    )
                if ads_signal is not None and ads_signal.has_exact_match:
                    await self._conversion_link_repository.upsert_ads(
                        session, tenant_id, stored.id, ads_signal
                    )
                if self._logistics_projector is not None:
                    await self._logistics_projector(session, tenant_id, stored.id)
                applied += 1

            cursor = await session.scalar(
                select(OrderSyncCursor).where(OrderSyncCursor.shop_id == shop_id)
            )
            if cursor is None:
                cursor = OrderSyncCursor(tenant_id=tenant_id, shop_id=shop_id)
                session.add(cursor)
            cursor.recovery_cursor = next_cursor or None
            await session.execute(
                update(OrderSyncRun)
                .where(OrderSyncRun.id == run_id)
                .values(
                    recovery_cursor=next_cursor or None,
                    fetched_count=OrderSyncRun.fetched_count + len(orders),
                    upserted_count=OrderSyncRun.upserted_count + applied,
                    confirmed_count=OrderSyncRun.confirmed_count
                    + metrics.confirmed_count,
                    derived_count=OrderSyncRun.derived_count + metrics.derived_count,
                    unknown_count=OrderSyncRun.unknown_count + metrics.unknown_count,
                    unsupported_field_count=(
                        OrderSyncRun.unsupported_field_count
                        + metrics.unsupported_field_count
                    ),
                )
            )
            await session.commit()
            return applied
        raise RuntimeError("Tenant database session was not created.")

    async def complete_run(
        self, tenant_id: UUID, run_id: UUID, *, committed_at: datetime
    ) -> OrderSyncResult:
        async for session in self._database.session(tenant_id):
            run = await session.get(OrderSyncRun, run_id)
            if run is None:
                raise RuntimeError("Order sync run was not found.")
            cursor = await session.scalar(
                select(OrderSyncCursor).where(OrderSyncCursor.shop_id == run.shop_id)
            )
            if cursor is None:
                cursor = OrderSyncCursor(tenant_id=tenant_id, shop_id=run.shop_id)
                session.add(cursor)
            cursor.recovery_cursor = None
            if cursor.last_success_at is None or committed_at > cursor.last_success_at:
                cursor.committed_cursor = committed_at.isoformat()
                cursor.last_success_at = committed_at
            run.status = "succeeded"
            run.recovery_cursor = None
            run.finished_at = datetime.now(UTC)
            await session.commit()
            return self._result(run)
        raise RuntimeError("Tenant database session was not created.")

    async def fail_run(
        self, tenant_id: UUID, run_id: UUID, error: str
    ) -> OrderSyncResult:
        async for session in self._database.session(tenant_id):
            run = await session.get(OrderSyncRun, run_id)
            if run is None:
                raise RuntimeError("Order sync run was not found.")
            run.status = "failed"
            run.error_summary = error
            run.finished_at = datetime.now(UTC)
            await session.commit()
            return self._result(run)
        raise RuntimeError("Tenant database session was not created.")

    async def _replace_children(
        self,
        session,
        tenant_id: UUID,
        shop_id: UUID,
        stored: Order,
        incoming: TikTokOrder,
    ) -> None:
        await sync_order_lines(
            session,
            tenant_id=tenant_id,
            shop_id=shop_id,
            order_id=stored.id,
            incoming_lines=incoming.lines,
            resolve_sku=self._resolve_sku,
        )
        await session.execute(
            delete(OrderFulfillment).where(OrderFulfillment.order_id == stored.id)
        )
        await session.execute(
            delete(OrderRecipient).where(OrderRecipient.order_id == stored.id)
        )
        for package in incoming.fulfillments:
            tracking = package.tracking_number
            session.add(
                OrderFulfillment(
                    tenant_id=tenant_id,
                    order_id=stored.id,
                    platform_package_id=_bounded(package.platform_package_id, 128),
                    delivery_option_id=_bounded_optional(
                        package.delivery_option_id, 128
                    ),
                    status=_bounded(package.status, 64),
                    carrier=_bounded_optional(package.carrier, 128),
                    tracking_number_masked=_mask(tracking, 4),
                    tracking_number_ciphertext=self._encrypt(tracking),
                    shipped_at=package.shipped_at,
                    delivered_at=package.delivered_at,
                )
            )
        if incoming.recipient:
            address = json.dumps(
                incoming.recipient.address, ensure_ascii=False, sort_keys=True
            )
            terminal = incoming.status in {"completed", "cancelled"}
            session.add(
                OrderRecipient(
                    tenant_id=tenant_id,
                    order_id=stored.id,
                    name_masked=_mask_name(incoming.recipient.name),
                    phone_masked=_mask(incoming.recipient.phone, 4),
                    address_masked=_mask_address(incoming.recipient.address),
                    name_ciphertext=self._encrypt(incoming.recipient.name),
                    phone_ciphertext=self._encrypt(incoming.recipient.phone),
                    address_ciphertext=self._encrypt(address),
                    country_code=_bounded_optional(incoming.recipient.country_code, 2),
                    purge_after=(
                        incoming.platform_updated_at
                        + timedelta(days=self._retention_days)
                        if terminal
                        else None
                    ),
                )
            )

    @staticmethod
    async def _resolve_sku(
        session, shop_id: UUID, line: TikTokOrderLine
    ) -> tuple[UUID | None, UUID | None]:
        if not line.platform_sku_id:
            return None, None
        row = (
            await session.execute(
                select(Product.id, ProductSku.id)
                .join(ProductSku, ProductSku.product_id == Product.id)
                .where(
                    Product.shop_id == shop_id,
                    ProductSku.platform_sku_id == line.platform_sku_id,
                )
                .limit(1)
            )
        ).one_or_none()
        return (row[0], row[1]) if row else (None, None)

    @staticmethod
    def _assign_order(stored: Order, incoming: TikTokOrder) -> None:
        for field in (
            "subtotal_amount_minor",
            "shipping_fee_minor",
            "discount_amount_minor",
            "tax_amount_minor",
            "total_amount_minor",
            "placed_at",
            "paid_at",
            "platform_updated_at",
        ):
            setattr(stored, field, getattr(incoming, field))
        stored.platform_order_id = _bounded(incoming.platform_order_id, 128)
        stored.order_number = _bounded(incoming.order_number, 128)
        stored.status = _bounded(incoming.status, 32)
        stored.external_status = _bounded(incoming.external_status, 64)
        stored.currency = _bounded(incoming.currency.upper(), 3)
        stored.buyer_username_masked = _mask_name(incoming.buyer_username)
        stored.synced_at = datetime.now(UTC)

    def _encrypt(self, value: str | None) -> str | None:
        return self._pii_cipher.encrypt(value) if value else None

    @staticmethod
    def _result(run: OrderSyncRun) -> OrderSyncResult:
        return OrderSyncResult(
            run_id=run.id,
            shop_id=run.shop_id,
            status=run.status,
            fetched_count=run.fetched_count,
            upserted_count=run.upserted_count,
            recovery_cursor=run.recovery_cursor,
            error=run.error_summary,
            confirmed_count=run.confirmed_count,
            derived_count=run.derived_count,
            unknown_count=run.unknown_count,
            unsupported_field_count=run.unsupported_field_count,
        )


def _mask(value: str | None, visible: int) -> str | None:
    if not value:
        return None
    return "*" * max(3, len(value) - visible) + value[-visible:]


def _mask_name(value: str | None) -> str | None:
    return None if not value else value[:1] + "***"


def _mask_address(address: dict[str, str]) -> str | None:
    country = address.get("region_code") or address.get("country_code") or ""
    city = address.get("city") or address.get("district_info") or ""
    return _bounded(" ".join(part for part in (country, city, "***") if part), 300)


def _bounded(value: str, limit: int) -> str:
    return value[:limit]


def _bounded_optional(value: str | None, limit: int) -> str | None:
    return _bounded(value, limit) if value else None
