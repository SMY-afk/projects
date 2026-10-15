from sqlalchemy import or_, select

from erp_api.models.logistics_carrier import LogisticsCarrier
from erp_api.models.logistics_platform_carrier_mapping import (
    LogisticsPlatformCarrierMapping,
)
from erp_api.services.tiktok_platform_logistics_sync_records import (
    carrier_identity,
    safe_mapping_payload,
)


async def resolve_platform_carrier(session, tenant_id, shop_id, detail):
    mapping = None
    if detail.platform_carrier_id:
        mapping = await session.scalar(
            select(LogisticsPlatformCarrierMapping)
            .where(
                LogisticsPlatformCarrierMapping.store_id == shop_id,
                LogisticsPlatformCarrierMapping.platform == "tiktok",
                LogisticsPlatformCarrierMapping.platform_carrier_id
                == detail.platform_carrier_id,
                LogisticsPlatformCarrierMapping.status == "active",
                or_(
                    LogisticsPlatformCarrierMapping.delivery_option_id
                    == detail.delivery_option_id,
                    LogisticsPlatformCarrierMapping.delivery_option_id.is_(None),
                ),
            )
            .order_by(LogisticsPlatformCarrierMapping.delivery_option_id.nulls_last())
        )
    if mapping is not None:
        return await session.get(LogisticsCarrier, mapping.carrier_id)
    code, name = carrier_identity(detail)
    carrier = await session.scalar(
        select(LogisticsCarrier).where(LogisticsCarrier.code == code)
    )
    if carrier is None:
        carrier = LogisticsCarrier(
            tenant_id=tenant_id,
            code=code,
            name=name,
            adapter_key="manual",
            status="active",
        )
        session.add(carrier)
        await session.flush()
    if detail.platform_carrier_id:
        session.add(
            LogisticsPlatformCarrierMapping(
                tenant_id=tenant_id,
                store_id=shop_id,
                carrier_id=carrier.id,
                platform="tiktok",
                platform_carrier_id=detail.platform_carrier_id,
                platform_carrier_code=code,
                platform_carrier_name=detail.carrier_name,
                delivery_option_id=detail.delivery_option_id,
                raw_payload=safe_mapping_payload(detail),
                status="active",
            )
        )
        await session.flush()
    return carrier
