from __future__ import annotations

import asyncio
import json
import secrets
import sys
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from uuid import UUID, uuid4

from finance_fixture import (
    PAYMENT_NUMBER,
    STATEMENT_NUMBER,
    finance_parent_rows,
    finance_payment_link,
    finance_transaction_rows,
)
from affiliate_fixture import CREATOR_USERNAME, affiliate_rows
from redis.asyncio import Redis
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

import erp_api.models  # noqa: F401 - register all relationship targets
from erp_api.core.config import get_settings
from erp_api.core.permissions import (
    AFFILIATE_CENTER_VIEW,
    FINANCE_VIEW,
    ORDERS_VIEW,
    SHOP_VIEW,
)
from erp_api.infrastructure.database import Database
from erp_api.models.affiliate_order_item import AffiliateOrderItem
from erp_api.models.associations import role_permissions, user_roles
from erp_api.models.finance_statement import FinanceStatement
from erp_api.models.order import Order
from erp_api.models.order_attribution import OrderAttribution
from erp_api.models.permission import Permission
from erp_api.models.role import Role
from erp_api.models.shop import Shop
from erp_api.models.tenant import Tenant
from erp_api.models.user import User

SESSION_TTL_SECONDS = 900
ORDER_NUMBER = "E2E-ORDER-0001"
FIXED_TIME = datetime(2026, 8, 19, 8, 0, tzinfo=UTC)


async def create_scenario() -> dict[str, str]:
    settings = get_settings()
    if settings.app_env == "production":
        raise RuntimeError("E2E fixtures are forbidden in production.")
    scenario_id = uuid4()
    tenant_id = uuid4()
    user_id = uuid4()
    role_id = uuid4()
    restricted_user_id = uuid4()
    restricted_role_id = uuid4()
    shop_id = uuid4()
    order_id = uuid4()
    statement_id = uuid4()
    payment_id = uuid4()
    platform_order_id = f"e2e-platform-order-{scenario_id.hex}"
    database = Database(settings.database_url)
    try:
        creator_id = await _seed_scenario(
            database,
            scenario_id=scenario_id,
            tenant_id=tenant_id,
            user_id=user_id,
            role_id=role_id,
            restricted_user_id=restricted_user_id,
            restricted_role_id=restricted_role_id,
            shop_id=shop_id,
            order_id=order_id,
            statement_id=statement_id,
            payment_id=payment_id,
            platform_order_id=platform_order_id,
        )
    except Exception:
        await _delete_tenant(database, tenant_id)
        raise
    finally:
        await database.dispose()

    access_tokens = [secrets.token_urlsafe(32) for _ in range(3)]
    redis = Redis.from_url(settings.redis_url)
    try:
        for access_token, session_user_id in zip(
            access_tokens,
            [user_id, user_id, restricted_user_id],
            strict=True,
        ):
            await redis.set(
                f"auth:session:{access_token}",
                json.dumps(
                    {"userId": str(session_user_id), "tenantId": str(tenant_id)},
                    separators=(",", ":"),
                ),
                ex=SESSION_TTL_SECONDS,
            )
    except Exception:
        cleanup_database = Database(settings.database_url)
        try:
            await _delete_tenant(cleanup_database, tenant_id)
        finally:
            await cleanup_database.dispose()
        raise
    finally:
        await redis.aclose()

    database = Database(settings.database_url)
    try:
        async with database.system_session_factory() as session:
            foreign_statement = await session.scalar(
                select(FinanceStatement)
                .where(FinanceStatement.tenant_id != tenant_id)
                .limit(1)
            )
    finally:
        await database.dispose()

    return {
        "accessToken": access_tokens[0],
        "logoutAccessToken": access_tokens[1],
        "restrictedAccessToken": access_tokens[2],
        "tenantId": str(tenant_id),
        "shopId": str(shop_id),
        "orderId": str(order_id),
        "orderNumber": ORDER_NUMBER,
        "statementId": str(statement_id),
        "statementNumber": STATEMENT_NUMBER,
        "paymentNumber": PAYMENT_NUMBER,
        "foreignStatementId": str(foreign_statement.id) if foreign_statement else "",
        "foreignShopId": str(foreign_statement.shop_id) if foreign_statement else "",
        "username": f"e2e_admin_{scenario_id.hex}",
        "affiliateCreatorId": str(creator_id),
        "affiliateCreatorUsername": CREATOR_USERNAME,
    }


async def _seed_scenario(
    database: Database,
    *,
    scenario_id: UUID,
    tenant_id: UUID,
    user_id: UUID,
    role_id: UUID,
    restricted_user_id: UUID,
    restricted_role_id: UUID,
    shop_id: UUID,
    order_id: UUID,
    statement_id: UUID,
    payment_id: UUID,
    platform_order_id: str,
) -> UUID:
    async with database.system_session_factory() as session, session.begin():
        await session.execute(
            insert(Permission)
            .values(
                [
                    {"id": uuid4(), "code": ORDERS_VIEW, "name": "查看订单"},
                    {"id": uuid4(), "code": SHOP_VIEW, "name": "查看店铺"},
                    {"id": uuid4(), "code": FINANCE_VIEW, "name": "查看财务"},
                    {
                        "id": uuid4(),
                        "code": AFFILIATE_CENTER_VIEW,
                        "name": "查看联盟中心",
                    },
                ]
            )
            .on_conflict_do_nothing(index_elements=["code"])
        )
        permissions = (
            await session.scalars(
                select(Permission).where(
                    Permission.code.in_(
                        [ORDERS_VIEW, SHOP_VIEW, FINANCE_VIEW, AFFILIATE_CENTER_VIEW]
                    )
                )
            )
        ).all()
        if len(permissions) != 4:
            raise RuntimeError("E2E permissions are incomplete.")

        session.add(
            Tenant(
                id=tenant_id,
                name=f"E2E Playwright {scenario_id.hex}",
                status="active",
            )
        )
        await session.flush()

        session.add_all(
            [
                Role(
                    id=role_id,
                    tenant_id=tenant_id,
                    code="e2e-admin",
                    name="E2E Administrator",
                ),
                Role(
                    id=restricted_role_id,
                    tenant_id=tenant_id,
                    code="e2e-restricted",
                    name="E2E Restricted User",
                ),
                User(
                    id=user_id,
                    tenant_id=tenant_id,
                    username=f"e2e_admin_{scenario_id.hex}",
                    password_hash="disabled-e2e-session",
                    status="active",
                ),
                User(
                    id=restricted_user_id,
                    tenant_id=tenant_id,
                    username=f"e2e_restricted_{scenario_id.hex}",
                    password_hash="disabled-e2e-session",
                    status="active",
                ),
                Shop(
                    id=shop_id,
                    tenant_id=tenant_id,
                    platform="tiktok_shop",
                    platform_shop_id=f"e2e-shop-{scenario_id.hex}",
                    shop_name="E2E Deterministic Shop",
                    shop_code="E2E",
                    region="US",
                    timezone="America/Los_Angeles",
                    currency="USD",
                    status="active",
                ),
            ]
        )
        await session.flush()

        creator_id, affiliate_fixture_groups = affiliate_rows(
            scenario_id=scenario_id,
            tenant_id=tenant_id,
            shop_id=shop_id,
        )
        for affiliate_fixture_rows in affiliate_fixture_groups:
            session.add_all(affiliate_fixture_rows)
            await session.flush()

        session.add_all(
            [
                Order(
                    id=order_id,
                    tenant_id=tenant_id,
                    shop_id=shop_id,
                    platform_order_id=platform_order_id,
                    order_number=ORDER_NUMBER,
                    status="awaiting_shipment",
                    external_status="AWAITING_SHIPMENT",
                    currency="USD",
                    subtotal_amount_minor=6610,
                    shipping_fee_minor=0,
                    discount_amount_minor=0,
                    tax_amount_minor=0,
                    total_amount_minor=6610,
                    buyer_username_masked="e2e***buyer",
                    placed_at=FIXED_TIME,
                    paid_at=FIXED_TIME,
                    platform_updated_at=FIXED_TIME,
                    synced_at=FIXED_TIME,
                ),
                *finance_parent_rows(
                    scenario_id=scenario_id,
                    tenant_id=tenant_id,
                    shop_id=shop_id,
                    statement_id=statement_id,
                    payment_id=payment_id,
                    occurred_at=FIXED_TIME,
                ),
            ]
        )
        await session.flush()

        session.add_all(
            [
                OrderAttribution(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    order_id=order_id,
                    traffic_source="organic",
                    operator_subject="creator",
                    entry_point="video",
                    special_order_type="normal",
                    chain_code="organic.creator.video",
                    classification_status="confirmed",
                    classification_method="e2e_fixture",
                    creator_external_id="e2e-creator-001",
                    video_external_id="e2e-video-001",
                    confidence_score=Decimal("1.0000"),
                    is_multi_touch=False,
                    evidence_json={
                        "source": "affiliate_order_item",
                        "field_path": "affiliate.creator_id",
                        "value": "creator",
                        "strength": "verified",
                        "reason": "e2e_fixture",
                        "creator_handle": "e2e_creator",
                        "creator_alias": "E2E Creator",
                    },
                    source_updated_at=FIXED_TIME,
                    source_hash=sha256(
                        f"{scenario_id}:attribution".encode()
                    ).hexdigest(),
                ),
                *finance_transaction_rows(
                    scenario_id=scenario_id,
                    tenant_id=tenant_id,
                    shop_id=shop_id,
                    statement_id=statement_id,
                    order_id=order_id,
                    platform_order_id=platform_order_id,
                    occurred_at=FIXED_TIME,
                ),
                AffiliateOrderItem(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    shop_id=shop_id,
                    main_order_id=platform_order_id,
                    creator_id="e2e-creator-001",
                    creator_nickname="E2E Creator",
                    campaign_id="e2e-campaign-001",
                    product_id="e2e-product-001",
                    product_name="E2E Deterministic Product",
                    sku_id="e2e-sku-001",
                    sku_name="E2E Deterministic SKU",
                    order_created_at=FIXED_TIME,
                    is_cod=False,
                    is_non_same_shop_order=False,
                    cos_type="affiliate_standard",
                    promotion_id="e2e-video-001",
                    promotion_type=2,
                    content_form="video",
                    commission_base=Decimal("66.1000"),
                    commission_currency="USD",
                    commission_rate=Decimal("0.100000"),
                    estimated_standard_commission=Decimal("6.6100"),
                    raw_data={"fixture": True, "scenarioId": scenario_id.hex},
                    source_record_key=sha256(
                        f"{scenario_id}:affiliate".encode()
                    ).hexdigest(),
                ),
            ]
        )
        await session.flush()
        await session.execute(
            insert(role_permissions)
            .values(
                [
                    {"role_id": role_id, "permission_id": permission.id}
                    for permission in permissions
                ]
            )
            .on_conflict_do_nothing()
        )
        await session.execute(
            insert(role_permissions)
            .values(
                [
                    {"role_id": restricted_role_id, "permission_id": permission.id}
                    for permission in permissions
                    if permission.code != FINANCE_VIEW
                ]
            )
            .on_conflict_do_nothing()
        )
        await session.execute(
            insert(user_roles)
            .values(user_id=user_id, role_id=role_id)
            .on_conflict_do_nothing()
        )
        await session.execute(
            insert(user_roles)
            .values(user_id=restricted_user_id, role_id=restricted_role_id)
            .on_conflict_do_nothing()
        )
        session.add(
            finance_payment_link(
                tenant_id=tenant_id,
                payment_id=payment_id,
                statement_id=statement_id,
            )
        )
        return creator_id


async def cleanup_scenario(scenario: dict[str, str]) -> None:
    settings = get_settings()
    if settings.app_env == "production":
        raise RuntimeError("E2E fixture cleanup is forbidden in production.")
    tenant_id = UUID(scenario["tenantId"])
    redis = Redis.from_url(settings.redis_url)
    try:
        for key in ("accessToken", "logoutAccessToken", "restrictedAccessToken"):
            if access_token := scenario.get(key, ""):
                await redis.delete(f"auth:session:{access_token}")
    finally:
        await redis.aclose()

    database = Database(settings.database_url)
    try:
        deleted = await _delete_tenant(database, tenant_id)
    finally:
        await database.dispose()
    if deleted != 1:
        raise RuntimeError("Expected to delete exactly one E2E tenant.")


async def _delete_tenant(database: Database, tenant_id: UUID) -> int:
    async with database.system_session_factory() as session, session.begin():
        result = await session.execute(delete(Tenant).where(Tenant.id == tenant_id))
    return result.rowcount or 0


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action == "create":
        print(json.dumps(asyncio.run(create_scenario()), separators=(",", ":")))
    elif action == "cleanup":
        asyncio.run(cleanup_scenario(json.loads(sys.stdin.read())))
    else:
        raise SystemExit("Expected create or cleanup")
