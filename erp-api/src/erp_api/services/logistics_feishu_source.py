"""Read the monitor's complete warning scan and reuse its official snapshots."""
import json
from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select, text

from erp_api.models.order import Order
from erp_api.models.order_fulfillment import OrderFulfillment
from erp_api.models.shop import Shop
from erp_api.services.logistics_feishu_fields import RESOLVED, STATE_FIELD
from erp_api.services.logistics_feishu_plan import index_records, plain
from erp_api.services.logistics_feishu_projection import instant, project_order


def snapshot_key(tenant, order):
    return f"logistics:feishu:official:{tenant}:{order}"


def resolved_snapshot_is_new(record, snapshot):
    if plain(record.fields.get(STATE_FIELD)) != RESOLVED or not snapshot:
        return False
    previous = plain(record.fields.get("官方查询时间（北京时间）"))
    if not previous:
        return True
    previous = datetime.strptime(previous, "%Y-%m-%d %H:%M:%S").replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    return instant(snapshot["checkedAt"]).replace(microsecond=0) > previous


async def save_snapshot(redis, tenant, order, result):
    payload = json.dumps(result, default=lambda value: value.isoformat() if isinstance(value, datetime) else str(value))
    script = """
    local old = redis.call('get',KEYS[1])
    if old then
      local prior = cjson.decode(old); local next = cjson.decode(ARGV[1])
      if prior.checkedAt > next.checkedAt then return 0 end
    end
    return redis.call('set',KEYS[1],ARGV[1],'EX',ARGV[2])
    """
    await redis.eval(script, 1, snapshot_key(tenant, order), payload, 120 * 86400)


async def source_rows(state, service, tenant, records, *, now=None):
    raw_scan, raw_orders = await state.redis.mget([
        f"logistics:monitor:alerts:{tenant}", "logistics:monitor:orders",
    ])
    now = now or datetime.now(UTC)
    if not raw_scan or not raw_orders:
        raise ValueError("Logistics monitor snapshots are unavailable")
    scan, order_health = json.loads(raw_scan), json.loads(raw_orders)
    if "error" in order_health or any(item.get("status") == "failed" for item in order_health.get("results", [])):
        raise ValueError("Order synchronization failed; Feishu data was preserved")
    for value in [scan["asOf"], order_health["at"]]:
        age = (now - instant(value)).total_seconds()
        if not 0 <= age <= 180:
            raise ValueError("Logistics monitor source is stale")
    if "matches" not in scan:
        raise ValueError("The monitor has not published a complete warning scan")
    matches = {UUID(key): flags for key, flags in scan["matches"].items()}
    owned = index_records(records, tenant)
    retained_ids = {UUID(key.split(":")[2]) for key, record in owned.items()
                    if plain(record.fields.get(STATE_FIELD)) != RESOLVED}
    resolved = [(UUID(key.split(":")[2]), record) for key, record in owned.items()
                if plain(record.fields.get(STATE_FIELD)) == RESOLVED]
    saved = await state.redis.mget([snapshot_key(tenant, identifier) for identifier, _ in resolved]) if resolved else []
    retained_ids.update(identifier for (identifier, record), value in zip(resolved, saved, strict=True)
                        if resolved_snapshot_is_new(record, json.loads(value) if value else {}))
    identifiers = set(matches) | retained_ids
    if not identifiers:
        return [], scan
    # No official API call is made here; the existing monitor owns all polling.
    async with state.database.system_session_factory() as session:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        rows = (await session.execute(select(Order, Shop.shop_name, Shop.timezone)
            .join(Shop, Shop.id == Order.shop_id).where(Order.tenant_id == tenant, Shop.tenant_id == tenant,
                Shop.platform == "tiktok", Order.id.in_(identifiers)))).all()
        if {order.id for order, _, _ in rows} != identifiers:
            raise ValueError("The ERP source is incomplete; Feishu records were preserved")
        packages = {identifier: [] for identifier in identifiers}
        for item in await session.scalars(select(OrderFulfillment).where(
                OrderFulfillment.tenant_id == tenant, OrderFulfillment.order_id.in_(identifiers))):
            packages[item.order_id].append({"packageId": item.platform_package_id or "",
                "packageStatus": item.status or "", "carrierName": item.carrier,
                "trackingNumberMasked": item.tracking_number_masked})
    raw_live = await state.redis.mget([snapshot_key(tenant, order.id) for order, _, _ in rows])
    projections = []
    for (order, name, timezone), value in zip(rows, raw_live, strict=True):
        key = f"{tenant}:{order.shop_id}:{order.id}"
        if order.id in retained_ids and key not in owned:
            raise ValueError("The persisted order key does not match its ERP shop")
        item = {"id": order.id, "key": key, "shopId": order.shop_id, "shopName": name,
                "orderNumber": order.order_number, "timezone": timezone, "orderCreatedAt": order.placed_at,
                "platformStatus": order.external_status, "erpSyncedAt": order.synced_at,
                "packages": packages[order.id]}
        live = json.loads(value) if value else {}
        if live and order.platform_updated_at > instant(live["platformUpdatedAt"]):
            live["platformStatus"] = order.external_status
        if service._shipping:
            await service._shipping.enrich(tenant, [item], fetch_missing=False)
        projections.append(project_order(item, live, matches.get(order.id, {}), now))
    return projections, scan
