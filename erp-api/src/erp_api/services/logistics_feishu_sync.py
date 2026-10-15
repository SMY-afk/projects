"""Durable, idempotent Feishu delivery with a full readback after every write."""
import json
from uuid import uuid4

from erp_api.services.logistics_feishu_fields import KEY_FIELD, OWNED_FIELDS
from erp_api.services.logistics_feishu_plan import build_plan, plain, same_value
from erp_api.services.logistics_feishu_projection import display_time


def pending_key(tenant, table):
    return f"logistics:feishu:pending:{tenant}:{table}"


def verify_rows(expected, records):
    indexed = {}
    for record in records:
        key = plain(record.fields.get(KEY_FIELD))
        if key:
            if key in indexed:
                raise ValueError("Feishu readback contains duplicate order keys")
            indexed[key] = record.fields
    for row in expected:
        prior = indexed.get(row[KEY_FIELD])
        if prior is None or any(not same_value(name, prior.get(name), value) for name, value in row.items()):
            raise ValueError("Feishu readback differs from the logistics sync plan")


async def apply_plan(redis, client, tenant, table, plan):
    pending = pending_key(tenant, table)
    raw = await redis.get(pending)
    if raw:
        operation = json.loads(raw)
        records = await client.list_records(field_names=OWNED_FIELDS)
        present = {plain(record.fields.get(KEY_FIELD)) for record in records}
        if all(row[KEY_FIELD] in present for row in operation["rows"]):
            # Some Feishu deployments reject an already accepted client_token.
            # Confirm ownership/uniqueness, then reconcile a fresh complete plan.
            verify_rows([{KEY_FIELD: row[KEY_FIELD]} for row in operation["rows"]], records)
            await redis.delete(pending)
            return {"recovered": len(operation["rows"]), "retryFreshPlan": True}
        # Replay exactly the saved payload/token after a timeout or process restart.
        await client.create_idempotent(operation["rows"], operation["token"])
        records = await client.list_records(field_names=OWNED_FIELDS)
        verify_rows(operation["rows"], records)
        await redis.delete(pending)
        return {"recovered": len(operation["rows"]), "retryFreshPlan": True}
    written = []
    for offset in range(0, len(plan["updates"]), 500):
        batch = plan["updates"][offset:offset + 500]
        await client.batch_update(batch)
        written.extend(row for _, row in batch)
    for offset in range(0, len(plan["creates"]), 500):
        batch = plan["creates"][offset:offset + 500]
        operation = {"token": str(uuid4()), "rows": batch}
        await redis.set(pending, json.dumps(operation, ensure_ascii=False))
        await client.create_idempotent(batch, operation["token"])
        records = await client.list_records(field_names=OWNED_FIELDS)
        verify_rows(batch, records)
        await redis.delete(pending)
        written.extend(batch)
    if written:
        records = await client.list_records(field_names=OWNED_FIELDS)
        verify_rows(written, records)
    return {"created": len(plan["creates"]), "updated": len(plan["updates"]), "readbackVerified": True}


async def sync_once(state, service, client, config, *, apply=False, now=None):
    from datetime import UTC, datetime
    from uuid import UUID

    from erp_api.services.logistics_feishu_source import source_rows

    tenant, table = UUID(config["tenantId"]), config["tableId"]
    requested_now = now
    fields = await client.validate_schema()
    # Include user fields when detecting empty placeholders; never adopt a row with notes.
    records = await client.list_records(field_names=list(fields))
    now = now or datetime.now(UTC)
    desired, scan = await source_rows(state, service, tenant, records, now=requested_now)
    plan = build_plan(desired, records, tenant, display_time(now))
    if not apply:
        return {"created": len(plan["creates"]), "updated": len(plan["updates"]),
                "sourceOrders": len(desired), "cards": scan["cards"], "asOf": scan["asOf"], "plan": plan}
    receipt = await apply_plan(state.redis, client, tenant, table, plan)
    if receipt.get("retryFreshPlan"):
        return {**await sync_once(state, service, client, config, apply=True, now=requested_now), "recovered": receipt["recovered"]}
    return {**receipt, "sourceOrders": len(desired), "asOf": scan["asOf"], "activeOrders": scan["uniqueOrderCount"]}
