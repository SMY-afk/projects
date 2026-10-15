import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from erp_api.services.logistics_feishu_fields import (
    KEY_FIELD,
    RED,
    RESOLVED,
    STATE_FIELD,
)
from erp_api.services.logistics_feishu_plan import same_value
from erp_api.services.logistics_feishu_source import (
    resolved_snapshot_is_new,
    source_rows,
)
from erp_api.services.logistics_feishu_sync import apply_plan, pending_key, verify_rows


class Redis:
    def __init__(self):
        self.values = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value):
        self.values[key] = value

    async def delete(self, key):
        self.values.pop(key, None)

    async def mget(self, keys):
        return [self.values.get(key) for key in keys]


class Client:
    def __init__(self, *, ambiguous=False):
        self.tokens, self.records, self.ambiguous = [], [], ambiguous

    async def create_idempotent(self, rows, token):
        if token not in self.tokens:
            self.records += [SimpleNamespace(record_id=str(i), fields=dict(row)) for i, row in enumerate(rows)]
        self.tokens.append(token)
        if self.ambiguous:
            self.ambiguous = False
            raise TimeoutError("Response was lost after the remote commit")

    async def list_records(self, **kwargs):
        return self.records


@pytest.mark.asyncio
async def test_lost_response_is_recovered_by_readback_without_recreating_existing_records():
    redis, client = Redis(), Client(ambiguous=True)
    row = {KEY_FIELD: "tenant:shop:order", STATE_FIELD: RED}
    with pytest.raises(TimeoutError):
        await apply_plan(redis, client, "tenant", "table", {"creates": [row], "updates": []})
    pending = json.loads(await redis.get(pending_key("tenant", "table")))
    assert pending["rows"] == [row]
    result = await apply_plan(redis, client, "tenant", "table", {"creates": [], "updates": []})
    assert result["recovered"] == 1 and len(client.records) == 1
    assert client.tokens == [pending["token"]]
    assert await redis.get(pending_key("tenant", "table")) is None


@pytest.mark.asyncio
async def test_missing_remote_records_replay_the_original_payload_and_token():
    redis, client = Redis(), Client()
    row = {KEY_FIELD: "tenant:shop:order", STATE_FIELD: RED}
    await redis.set(pending_key("tenant", "table"), json.dumps({"rows": [row], "token": "same-token"}))
    result = await apply_plan(redis, client, "tenant", "table", {"creates": [], "updates": []})
    assert result["recovered"] == 1 and client.tokens == ["same-token"]
    assert client.records[0].fields == row


def test_incorrect_readback_is_not_reported_as_success():
    with pytest.raises(ValueError, match="differs"):
        verify_rows([{KEY_FIELD: "tenant:shop:order", STATE_FIELD: RED}], [])


def test_resolved_history_receives_later_delivery_evidence_without_rewriting_unchanged_snapshots():
    record = SimpleNamespace(fields={STATE_FIELD: RESOLVED, "官方查询时间（北京时间）": "2026-10-13 17:00:00"})
    assert resolved_snapshot_is_new(record, {"checkedAt": "2026-10-13T09:01:00Z", "deliveredAt": "2026-10-13T09:00:30Z"})
    assert not resolved_snapshot_is_new(record, {"checkedAt": "2026-10-13T09:00:00.456Z"})
    assert not resolved_snapshot_is_new(record, {})


def test_feishu_numeric_strings_match_numeric_durations_but_identifiers_remain_text():
    row = {KEY_FIELD: "tenant:shop:order", "创建至发货（小时）": 13.930833}
    verify_rows([row], [SimpleNamespace(fields={KEY_FIELD: "tenant:shop:order", "创建至发货（小时）": "13.930833"})])
    assert not same_value("订单号", "982740775181726442", 982740775181726442)


@pytest.mark.asyncio
@pytest.mark.parametrize("stale,failed", [(True, False), (False, True)])
async def test_stale_or_failed_source_preserves_target_and_does_not_query_other_data(stale, failed):
    tenant, redis = uuid4(), Redis()
    now = datetime.now(UTC)
    stamp = now - timedelta(minutes=5) if stale else now
    await redis.set(f"logistics:monitor:alerts:{tenant}", json.dumps({"asOf": stamp.isoformat(), "matches": {}}))
    await redis.set("logistics:monitor:orders", json.dumps({"at": stamp.isoformat(),
                    "results": [{"status": "failed" if failed else "succeeded"}]}))
    with pytest.raises(ValueError, match="stale|failed"):
        await source_rows(SimpleNamespace(redis=redis), None, tenant, [], now=now)
