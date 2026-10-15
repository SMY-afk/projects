from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Protocol

from erp_api.services.external_order_evidence import (
    PLATFORM_NO_ORDER_LEVEL_EVIDENCE,
    ExternalOrderEvidenceLookup,
)
from erp_api.services.tiktok_affiliate_order_schemas import (
    TikTokAffiliateOrderRecord,
    TikTokAffiliateOrderSignal,
)
from erp_api.services.tiktok_transport import TikTokRequest, TikTokTransport


class TikTokAffiliateOrderClient(Protocol):
    async def get_order_signal(
        self,
        access_token: str,
        *,
        shop_cipher: str,
        platform_order_id: str,
        platform_order_item_ids: tuple[str, ...],
    ) -> TikTokAffiliateOrderSignal | None: ...


class HttpTikTokAffiliateOrderClient:
    """Connector for the approved affiliate-order endpoint.

    The endpoint path and allow-listed field names are configurable because
    TikTok scope/API approval determines the concrete version. No aggregate
    report row can become an order signal: a record is emitted only when an
    order ID or order-item ID is present.
    """

    def __init__(
        self,
        transport: TikTokTransport,
        *,
        path: str = "/affiliate/202309/orders",
    ) -> None:
        self._transport = transport
        self._path = path

    async def get_order_signal(
        self,
        access_token: str,
        *,
        shop_cipher: str,
        platform_order_id: str,
        platform_order_item_ids: tuple[str, ...],
    ) -> TikTokAffiliateOrderSignal | None:
        return (
            await self.lookup_order_evidence(
                access_token,
                shop_cipher=shop_cipher,
                platform_order_id=platform_order_id,
                platform_order_item_ids=platform_order_item_ids,
            )
        ).signal

    async def lookup_order_evidence(
        self,
        access_token: str,
        *,
        shop_cipher: str,
        platform_order_id: str,
        platform_order_item_ids: tuple[str, ...],
    ) -> ExternalOrderEvidenceLookup:
        query = {
            "shop_cipher": shop_cipher,
            "order_id": platform_order_id,
            **(
                {"order_item_ids": ",".join(platform_order_item_ids)}
                if platform_order_item_ids
                else {}
            ),
        }
        payload = await self._transport.request(
            TikTokRequest("GET", self._path, query=query),
            access_token=access_token,
        )
        records = parse_affiliate_order_response(payload)
        for record in records:
            if record.platform_order_id == platform_order_id:
                return ExternalOrderEvidenceLookup(
                    _signal(record, "order_id", platform_order_id)
                )
        requested_items = set(platform_order_item_ids)
        for record in records:
            if record.platform_order_id:
                continue
            matched_items = set(record.platform_order_item_ids) & requested_items
            if matched_items:
                return ExternalOrderEvidenceLookup(
                    _signal(record, "order_item_id", min(matched_items))
                )
        # An empty response is still a successful order-level lookup with no
        # matching evidence. It must not fall back to the Shop-detail reason.
        return ExternalOrderEvidenceLookup(
            absence_reason=PLATFORM_NO_ORDER_LEVEL_EVIDENCE
        )


def _signal(
    record: TikTokAffiliateOrderRecord,
    match_key_type: str,
    match_key: str,
) -> TikTokAffiliateOrderSignal:
    return TikTokAffiliateOrderSignal(
        external_conversion_id=record.external_conversion_id,
        match_key_type=match_key_type,
        match_key=match_key,
        creator_external_id=record.creator_external_id,
        traffic_source=record.traffic_source,
        operator_subject=record.operator_subject,
        entry_point=record.entry_point,
        source_updated_at=record.source_updated_at,
        platform_source_code=record.platform_source_code,
        evidence=record.evidence,
    )


def parse_affiliate_order_response(
    payload: Mapping[str, object],
) -> list[TikTokAffiliateOrderRecord]:
    data = payload.get("data", payload)
    if not isinstance(data, Mapping):
        return []
    raw_records = data.get("orders", data.get("items", []))
    if not isinstance(raw_records, list):
        return []
    records = [_parse_record(item) for item in raw_records]
    return [record for record in records if record is not None]


def _has_external_rows(payload: Mapping[str, object]) -> bool:
    data = payload.get("data", payload)
    if not isinstance(data, Mapping):
        return False
    rows = data.get("orders", data.get("items", []))
    return isinstance(rows, list) and bool(rows)


def _parse_record(value: object) -> TikTokAffiliateOrderRecord | None:
    if not isinstance(value, Mapping):
        return None
    order_id = _text(value, "order_id", "platform_order_id", "orderId")
    raw_item_ids = value.get(
        "order_item_ids",
        value.get(
            "orderItemIds", value.get("order_item_id", value.get("orderItemId", []))
        ),
    )
    if isinstance(raw_item_ids, str):
        item_ids = (raw_item_ids,) if raw_item_ids else ()
    elif isinstance(raw_item_ids, list):
        item_ids = tuple(
            item for item in raw_item_ids if isinstance(item, str) and item
        )
    else:
        item_ids = ()
    if not order_id and not item_ids:
        return None
    conversion_id = _text(
        value, "conversion_id", "affiliate_order_id", "conversionId", "id"
    )
    if not conversion_id:
        return None
    evidence = {
        "source": "affiliate_order",
        "match_key_type": "order_id" if order_id else "order_item_id",
        "match_key": order_id or item_ids[0],
    }
    return TikTokAffiliateOrderRecord(
        external_conversion_id=conversion_id,
        platform_order_id=order_id,
        platform_order_item_ids=item_ids,
        creator_external_id=_text(
            value, "creator_id", "creatorId", "affiliate_creator_id"
        ),
        traffic_source=_text(value, "traffic_source", "trafficSource"),
        operator_subject=_text(value, "operator_subject", "operatorSubject")
        or "creator",
        entry_point=_text(value, "entry_point", "entryPoint"),
        source_updated_at=_datetime(value.get("update_time", value.get("updatedAt"))),
        platform_source_code=_text(value, "source_code", "sourceCode"),
        evidence=evidence,
    )


def _text(value: Mapping[str, object], *keys: str) -> str | None:
    for key in keys:
        item = value.get(key)
        if isinstance(item, str) and item:
            return item
    return None


def _datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=UTC)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None
