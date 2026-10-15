from sqlalchemy import select

from erp_api.models.logistics_carrier import LogisticsCarrierService
from erp_api.models.logistics_waybill import LogisticsWaybill
from erp_api.services.logistics_shipping_errors import LogisticsShippingNotFoundError


async def find_tracking_waybill(session, carrier_id, update, tracking_cipher):
    filters = [LogisticsWaybill.carrier_id == carrier_id]
    if update.external_waybill_id:
        filters.append(
            LogisticsWaybill.external_waybill_id == update.external_waybill_id
        )
    elif update.tracking_number and tracking_cipher:
        filters.append(
            LogisticsWaybill.tracking_number_hash
            == tracking_cipher.fingerprint("tracking", update.tracking_number)
        )
    else:
        raise LogisticsShippingNotFoundError("Tracking identity is unavailable.")
    row = (await session.execute(_lookup_query(*filters))).one_or_none()
    if (
        row is None
        and update.tracking_number
        and tracking_cipher
        and not update.external_waybill_id
    ):
        candidates = await session.execute(
            _lookup_query(
                LogisticsWaybill.carrier_id == carrier_id,
                LogisticsWaybill.tracking_number_ciphertext.is_not(None),
            )
        )
        for candidate in candidates:
            waybill = candidate[0]
            stored = tracking_cipher.decrypt(waybill.tracking_number_ciphertext)
            if stored.strip().upper() == update.tracking_number.strip().upper():
                waybill.tracking_number_hash = tracking_cipher.fingerprint(
                    "tracking", update.tracking_number
                )
                row = candidate
                break
    if row is None:
        raise LogisticsShippingNotFoundError("Waybill was not found.")
    return row[0], row[1] or {}


def _lookup_query(*filters):
    return (
        select(LogisticsWaybill, LogisticsCarrierService.configuration)
        .outerjoin(
            LogisticsCarrierService,
            LogisticsCarrierService.id == LogisticsWaybill.service_id,
        )
        .where(*filters)
        .with_for_update(of=LogisticsWaybill)
    )
