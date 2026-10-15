from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from erp_api.services.sample_feishu_mapper import format_sample_time_left
from erp_api.services.sample_time_left_refresh import (
    build_desired_time_left,
    refresh_time_left_records,
)


def test_remaining_time_decreases_without_new_source_capture():
    today = datetime(2026, 10, 10, tzinfo=UTC)
    deadline = today + timedelta(days=6)
    assert format_sample_time_left(deadline, now=today) == "剩余 6 天"
    assert (
        format_sample_time_left(deadline, now=today + timedelta(days=1)) == "剩余 5 天"
    )
    assert format_sample_time_left(deadline, now=deadline) == "已过期"


class Client:
    def __init__(self, sync_key, previous):
        self.sync_key = sync_key
        self.previous = previous
        self.status = "PENDING"
        self.updates = []

    async def tenant_access_token(self):
        return "test-token"

    def _record_path(self):
        return "/test/records"

    async def _request(self, method, path, **kwargs):
        return {
            "records": [
                {
                    "record_id": record_id,
                    "fields": {
                        "同步键（系统）": self.sync_key,
                        "样品申请剩余时间": [{"text": self.previous, "type": "text"}],
                        "TK申请状态": self.status,
                    },
                }
                for record_id in kwargs["json"]["record_ids"]
            ]
        }

    async def batch_update_records(self, records):
        self.updates.extend(records)
        self.previous = records[0][1].get("样品申请剩余时间", self.previous)
        self.status = records[0][1].get("TK申请状态", self.status)
        return tuple(record_id for record_id, _fields in records)


@pytest.mark.asyncio
async def test_refresh_changes_only_countdown_and_verifies_readback():
    shop_id = uuid4()
    client = Client(f"{shop_id}:application", "剩余 6 天")
    desired = {"rec-1": (f"{shop_id}:application", {"样品申请剩余时间": "剩余 5 天"})}
    assert await refresh_time_left_records(client, desired) == 1
    assert client.updates == [("rec-1", {"样品申请剩余时间": "剩余 5 天"})]
    assert await refresh_time_left_records(client, desired) == 0


@pytest.mark.asyncio
async def test_refresh_rejects_conflicting_saved_record_mapping():
    client = Client("another-shop:application", "剩余 6 天")
    with pytest.raises(RuntimeError, match="identity mismatch"):
        await refresh_time_left_records(
            client, {"rec-1": ("shop:application", {"样品申请剩余时间": "剩余 5 天"})}
        )
    assert client.updates == []


@pytest.mark.asyncio
async def test_refresh_repairs_verified_terminal_status_without_business_fields():
    shop_id = uuid4()
    client = Client(f"{shop_id}:application", "")
    desired = {
        "rec-1": (
            f"{shop_id}:application",
            {"TK申请状态": "CANCELLED", "样品申请剩余时间": "已取消"},
        )
    }
    assert await refresh_time_left_records(client, desired) == 1
    assert client.updates == [
        ("rec-1", {"TK申请状态": "CANCELLED", "样品申请剩余时间": "已取消"})
    ]


def test_missing_deadline_does_not_infer_cancelled_status():
    tenant_id, shop_id = uuid4(), uuid4()
    desired = build_desired_time_left(
        [
            (
                tenant_id,
                shop_id,
                "application",
                None,
                "rec-1",
                "PENDING",
                True,
                {"status": "PENDING"},
            )
        ]
    )
    fields = desired[tenant_id, shop_id]["rec-1"][1]
    assert fields["TK申请状态"] == "PENDING"
    assert fields["样品申请剩余时间"] == "待核验（缺少截止时间）"


def test_conflicting_raw_status_is_not_projected_to_feishu():
    tenant_id, shop_id = uuid4(), uuid4()
    desired = build_desired_time_left(
        [
            (
                tenant_id,
                shop_id,
                "application",
                None,
                "rec-1",
                "PENDING",
                True,
                {"status": "CANCELLED"},
            )
        ]
    )
    assert "TK申请状态" not in desired[tenant_id, shop_id]["rec-1"][1]


@pytest.mark.asyncio
async def test_deleted_history_rows_are_skipped_without_recreation():
    client = Client("shop:application", "")

    async def empty_response(*_args, **_kwargs):
        return {"records": []}

    client._request = empty_response
    assert (
        await refresh_time_left_records(
            client,
            {"deleted-record": ("shop:application", {"样品申请剩余时间": "已取消"})},
        )
        == 0
    )
    assert client.updates == []
