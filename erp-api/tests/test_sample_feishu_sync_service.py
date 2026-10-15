from __future__ import annotations

import inspect
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from erp_api.services.feishu_sample_errors import FeishuSampleError
from erp_api.services.feishu_sample_fields import BUSINESS_FIELDS, SYSTEM_FIELDS
from erp_api.services.feishu_sample_record_index import SYNC_KEY_FIELD
from erp_api.services.feishu_sample_record_snapshot import (
    FeishuListedRecord,
    FeishuRecordSnapshot,
)
from erp_api.services.sample_feishu_client_router import SampleFeishuClientRouter
from erp_api.services.sample_feishu_incremental import system_fields_hash
from erp_api.services.sample_feishu_mapper import build_feishu_system_fields
from erp_api.services.sample_feishu_source_repository import SampleFeishuSourceRecord
from erp_api.services.sample_feishu_sync_service import SampleFeishuSyncService


def _record(
    index: int,
    *,
    platform_application_id: str | None = None,
    feishu_record_id: str | None = None,
    sync_hash: str | None = None,
    last_sync_at: datetime | None = None,
    sync_status: str = "pending",
):
    return SampleFeishuSourceRecord(
        application_id=UUID(int=index),
        tenant_id=UUID(int=10_000),
        shop_id=UUID(int=20_000),
        shop_name="Akeleo Toys",
        platform_application_id=platform_application_id or f"sample-{index}",
        source_type="official_api",
        source_capture_id=UUID(int=30_000),
        source_observed_at=datetime(2026, 9, 10, tzinfo=UTC),
        first_seen_at=datetime(2026, 9, 10, tzinfo=UTC),
        creator_open_id=f"creator-{index}",
        creator_username=f"creator_{index}",
        creator_nickname=f"Creator {index}",
        follower_count=1200,
        creator_gmv_minor=5_000_00,
        creator_gmv_currency="USD",
        creator_level="L2",
        platform_status="PENDING",
        product_id=f"product-{index}",
        product_title="Product",
        sku_id=f"sku-{index}",
        sku_name="Blue",
        commission_rate=Decimal("0.12"),
        available_quantity=1,
        feishu_record_id=feishu_record_id,
        assignment_version=0,
        sync_hash=sync_hash,
        last_sync_at=last_sync_at,
        sync_status=sync_status,
    )


class FakeSourceRepository:
    def __init__(self, records: list[SampleFeishuSourceRecord]) -> None:
        self.records = records
        self.calls: list[UUID | None] = []
        self.scopes: list[frozenset[UUID] | None] = []

    async def list_committed(
        self,
        *,
        tenant_id: UUID,
        shop_id: UUID,
        after_application_id: UUID | None,
        limit: int,
        application_ids: frozenset[UUID] | None = None,
    ) -> tuple[SampleFeishuSourceRecord, ...]:
        self.calls.append(after_application_id)
        self.scopes.append(application_ids)
        assert tenant_id == UUID(int=10_000)
        assert shop_id == UUID(int=20_000)
        rows = [
            record
            for record in self.records
            if (
                (application_ids is None or record.application_id in application_ids)
                and (
                    after_application_id is None
                    or record.application_id > after_application_id
                )
            )
        ]
        return tuple(rows[:limit])


class FakeFeishuClient:
    def __init__(
        self,
        existing: dict[str, str] | None = None,
        request_ids: list[str] | None = None,
        snapshot_fields: dict[str, dict[str, object]] | None = None,
    ) -> None:
        self.existing = existing or {}
        self.request_ids = request_ids or ["feishu-log-1"]
        self.snapshot_fields = snapshot_fields or {}
        self.create_batches: list[list[dict[str, object]]] = []
        self.update_batches: list[list[tuple[str, dict[str, object]]]] = []
        self.delete_batches: list[list[str]] = []
        self.list_calls = 0
        self.get_calls: list[str] = []

    async def list_record_sync_key_map(self) -> dict[str, str]:
        return self.existing

    async def list_record_snapshots(self) -> tuple[FeishuListedRecord, ...]:
        self.list_calls += 1
        return tuple(
            FeishuListedRecord(
                record_id,
                FeishuRecordSnapshot(
                    {
                        SYNC_KEY_FIELD: sync_key,
                        **self.snapshot_fields.get(record_id, {}),
                    }
                ),
            )
            for sync_key, record_id in self.existing.items()
        )

    async def get_record_snapshot(self, record_id: str) -> FeishuRecordSnapshot:
        self.get_calls.append(record_id)
        sync_key = next(
            (
                key
                for key, existing_id in self.existing.items()
                if existing_id == record_id
            ),
            None,
        )
        if sync_key is None:
            raise FeishuSampleError("Feishu record was not found.")
        return FeishuRecordSnapshot(
            {SYNC_KEY_FIELD: sync_key, **self.snapshot_fields.get(record_id, {})}
        )

    @contextmanager
    def capture_evidence(self):
        yield type("Trace", (), {"request_ids": self.request_ids})()

    async def batch_create_records(
        self, records: list[dict[str, object]]
    ) -> dict[str, str]:
        self.create_batches.append(records)
        return {
            fields["同步键（系统）"]: f"created-{len(self.create_batches)}-{index}"
            for index, fields in enumerate(records)
        }

    async def batch_update_records(
        self, records: list[tuple[str, dict[str, object]]]
    ) -> tuple[str, ...]:
        self.update_batches.append(records)
        return tuple(record_id for record_id, _fields in records)

    async def batch_delete_records(self, record_ids: list[str]) -> tuple[str, ...]:
        self.delete_batches.append(record_ids)
        return tuple(record_ids)


class FailingFeishuClient(FakeFeishuClient):
    async def list_record_snapshots(self) -> tuple[FeishuListedRecord, ...]:
        raise FeishuSampleError(
            "Feishu request was rejected.",
            error_code="99991400",
            request_id="failure-log",
        )


class FailingUpdateFeishuClient(FakeFeishuClient):
    async def batch_update_records(self, records):
        raise FeishuSampleError("Feishu update failed.", error_code="update_failed")


class FakeMappingRepository:
    def __init__(self) -> None:
        self.batches: list[list[tuple[UUID, str]]] = []
        self.detached: list[list[str]] = []
        self.synced: list[list[tuple[UUID, str, str]]] = []
        self.failed: list[list[UUID]] = []

    async def attach_records(
        self,
        *,
        tenant_id: UUID,
        shop_id: UUID,
        mappings: list[tuple[UUID, str]],
    ) -> int:
        assert tenant_id == UUID(int=10_000)
        assert shop_id == UUID(int=20_000)
        self.batches.append(mappings)
        return len(mappings)

    async def detach_records(
        self,
        *,
        tenant_id: UUID,
        shop_id: UUID,
        record_ids: list[str],
    ) -> int:
        assert tenant_id == UUID(int=10_000)
        assert shop_id == UUID(int=20_000)
        self.detached.append(record_ids)
        return len(record_ids)

    async def mark_synced(self, *, tenant_id, shop_id, records, synced_at):
        self.synced.append(list(records))
        return len(records)

    async def mark_failed(self, *, tenant_id, shop_id, application_ids):
        self.failed.append(list(application_ids))
        return len(application_ids)


class FakeAuditRepository:
    def __init__(self) -> None:
        self.started: list[dict] = []
        self.finished: list[dict] = []

    async def start_feishu(self, **kwargs) -> UUID:
        self.started.append(kwargs)
        return UUID(int=40_000)

    async def finish_feishu(self, **kwargs) -> None:
        self.finished.append(kwargs)


def _service(source, mappings, feishu, *, deduplication_started_at=None):
    audits = FakeAuditRepository()
    router = SampleFeishuClientRouter(feishu, {})
    kwargs = (
        {"deduplication_started_at": deduplication_started_at}
        if deduplication_started_at is not None
        else {}
    )
    return (
        SampleFeishuSyncService(source, mappings, audits, router, **kwargs),
        audits,
    )


def test_system_fields_hash_ignores_sync_clock_and_notification() -> None:
    record = _record(1)
    first = build_feishu_system_fields(
        record, synced_at=datetime(2026, 9, 10, tzinfo=UTC)
    )
    later = build_feishu_system_fields(
        record, synced_at=datetime(2026, 9, 11, tzinfo=UTC)
    )
    later["通知状态"] = "已通知"
    assert system_fields_hash(first) == system_fields_hash(later)
    later["TK申请状态"] = "SHIPPED"
    assert system_fields_hash(first) != system_fields_hash(later)


@pytest.mark.asyncio
async def test_full_sync_skips_feishu_when_saved_hash_is_recent_and_equal() -> None:
    record = _record(1, feishu_record_id="rec-1")
    digest = system_fields_hash(
        build_feishu_system_fields(record, synced_at=datetime.now(UTC))
    )
    record = _record(
        1,
        feishu_record_id="rec-1",
        sync_hash=digest,
        last_sync_at=datetime.now(UTC),
        sync_status="succeeded",
    )
    source = FakeSourceRepository([record])
    feishu = FakeFeishuClient()
    mappings = FakeMappingRepository()
    service, _audits = _service(source, mappings, feishu)

    result = await service.sync(tenant_id=UUID(int=10_000), shop_id=UUID(int=20_000))

    assert result.source_count == 1
    assert result.created_count == result.updated_count == 0
    assert feishu.list_calls == 0
    assert feishu.create_batches == feishu.update_batches == []
    assert mappings.synced == []


@pytest.mark.asyncio
async def test_changed_hash_updates_record_and_persists_new_hash() -> None:
    record = _record(
        1,
        feishu_record_id="rec-1",
        sync_hash="0" * 64,
        last_sync_at=datetime.now(UTC),
        sync_status="succeeded",
    )
    sync_key = f"{UUID(int=20_000)}:sample-1"
    feishu = FakeFeishuClient({sync_key: "rec-1"})
    mappings = FakeMappingRepository()
    service, _audits = _service(FakeSourceRepository([record]), mappings, feishu)

    result = await service.sync(tenant_id=UUID(int=10_000), shop_id=UUID(int=20_000))

    assert result.updated_count == 1
    assert mappings.synced[0][0] == (
        record.application_id,
        "rec-1",
        system_fields_hash(
            build_feishu_system_fields(record, synced_at=datetime.now(UTC))
        ),
    )

    assert feishu.get_calls == ["rec-1"]
    assert feishu.list_calls == 0


@pytest.mark.asyncio
async def test_full_sync_reads_only_changed_record_after_baseline() -> None:
    now = datetime.now(UTC)
    unchanged = _record(2, feishu_record_id="rec-2")
    unchanged_hash = system_fields_hash(
        build_feishu_system_fields(unchanged, synced_at=now)
    )
    unchanged = _record(
        2,
        feishu_record_id="rec-2",
        sync_hash=unchanged_hash,
        last_sync_at=now,
        sync_status="succeeded",
    )
    changed = _record(
        1,
        feishu_record_id="rec-1",
        sync_hash="a" * 64,
        last_sync_at=now,
        sync_status="succeeded",
    )
    existing = {
        f"{UUID(int=20_000)}:sample-1": "rec-1",
        f"{UUID(int=20_000)}:sample-2": "rec-2",
    }
    feishu = FakeFeishuClient(existing)
    service, _audits = _service(
        FakeSourceRepository([changed, unchanged]), FakeMappingRepository(), feishu
    )

    result = await service.sync(tenant_id=UUID(int=10_000), shop_id=UUID(int=20_000))

    assert result.source_count == 2
    assert result.updated_count == 1
    assert feishu.get_calls == ["rec-1"]
    assert feishu.list_calls == 0


@pytest.mark.asyncio
async def test_expired_baseline_requires_full_remote_audit() -> None:
    record = _record(1, feishu_record_id="rec-1")
    digest = system_fields_hash(
        build_feishu_system_fields(record, synced_at=datetime.now(UTC))
    )
    record = _record(
        1,
        feishu_record_id="rec-1",
        sync_hash=digest,
        last_sync_at=datetime(2026, 9, 1, tzinfo=UTC),
        sync_status="succeeded",
    )
    key = f"{UUID(int=20_000)}:sample-1"
    feishu = FakeFeishuClient({key: "rec-1"})
    service, _audits = _service(
        FakeSourceRepository([record]), FakeMappingRepository(), feishu
    )

    await service.sync(tenant_id=UUID(int=10_000), shop_id=UUID(int=20_000))

    assert feishu.list_calls == 1
    assert feishu.get_calls == []


@pytest.mark.asyncio
async def test_failed_update_marks_record_for_retry() -> None:
    record = _record(1, feishu_record_id="rec-1", sync_hash="a" * 64)
    key = f"{UUID(int=20_000)}:sample-1"
    feishu = FailingUpdateFeishuClient({key: "rec-1"})
    mappings = FakeMappingRepository()
    service, _audits = _service(FakeSourceRepository([record]), mappings, feishu)

    with pytest.raises(FeishuSampleError, match="update failed"):
        await service.sync(tenant_id=UUID(int=10_000), shop_id=UUID(int=20_000))

    assert mappings.failed == [[record.application_id]]
    assert mappings.synced == []


@pytest.mark.asyncio
async def test_sync_reports_post_cutoff_duplicate_without_deleting() -> None:
    record = _record(1, feishu_record_id="rec-current")
    current_key = f"{UUID(int=20_000)}:sample-1"
    duplicate_key = f"{UUID(int=20_000)}:sample-old"
    history_key = f"{UUID(int=20_000)}:sample-history"
    existing = {
        current_key: "rec-current",
        duplicate_key: "rec-duplicate",
        history_key: "rec-history",
    }
    snapshots = {
        "rec-current": {
            "达人OpenID": "creator-1",
            "达人账号": "creator_1",
            "TikTok申请时间": int(datetime(2026, 9, 10, tzinfo=UTC).timestamp() * 1000),
        },
        "rec-duplicate": {
            "达人OpenID": "creator-1",
            "达人账号": "creator_1",
            "TikTok申请时间": int(datetime(2026, 9, 2, tzinfo=UTC).timestamp() * 1000),
        },
        "rec-history": {
            "达人OpenID": "creator-1",
            "达人账号": "creator_1",
            "TikTok申请时间": int(datetime(2026, 8, 31, tzinfo=UTC).timestamp() * 1000),
        },
    }
    feishu = FakeFeishuClient(existing, snapshot_fields=snapshots)
    mappings = FakeMappingRepository()
    service, _audits = _service(
        FakeSourceRepository([record]),
        mappings,
        feishu,
        deduplication_started_at=datetime(2026, 9, 1, tzinfo=UTC),
    )

    result = await service.sync(tenant_id=UUID(int=10_000), shop_id=UUID(int=20_000))

    assert result.delete_pending_count == 1
    assert feishu.delete_batches == []
    assert mappings.detached == []


@pytest.mark.asyncio
async def test_sync_rejects_two_current_rows_for_same_creator() -> None:
    records = [_record(1), _record(2)]
    records[1] = SampleFeishuSourceRecord(
        **{
            **records[1].__dict__,
            "creator_open_id": records[0].creator_open_id,
            "creator_username": records[0].creator_username,
        }
    )
    feishu = FakeFeishuClient()
    service, _audits = _service(
        FakeSourceRepository(records),
        FakeMappingRepository(),
        feishu,
        deduplication_started_at=datetime(2026, 9, 1, tzinfo=UTC),
    )

    with pytest.raises(RuntimeError, match="creator identity is duplicated"):
        await service.sync(tenant_id=UUID(int=10_000), shop_id=UUID(int=20_000))

    assert feishu.delete_batches == []
    assert feishu.create_batches == []


@pytest.mark.asyncio
async def test_sync_creates_missing_and_updates_existing_with_system_fields() -> None:
    source = FakeSourceRepository([_record(1), _record(2)])
    first_key = f"{UUID(int=20_000)}:sample-1"
    feishu = FakeFeishuClient({first_key: "rec-1"})
    mappings = FakeMappingRepository()
    service, audits = _service(source, mappings, feishu)

    result = await service.sync(tenant_id=UUID(int=10_000), shop_id=UUID(int=20_000))

    assert result.source_count == 2
    assert result.created_count == 1
    assert result.updated_count == 1
    assert len(feishu.create_batches) == 1
    assert len(feishu.update_batches) == 1
    assert feishu.update_batches[0][0][0] == "rec-1"
    assert mappings.batches == [
        [(UUID(int=1), "rec-1")],
        [(UUID(int=2), "created-1-0")],
    ]
    assert audits.finished[0]["status"] == "succeeded"
    assert audits.finished[0]["request_ids"] == ["feishu-log-1"]
    assert audits.finished[0]["error_code"] is None
    assert feishu.create_batches[0][0]["通知状态"] == "待通知"
    assert "首次同步时间" in feishu.create_batches[0][0]
    updated_fields = feishu.update_batches[0][0][1]
    assert "通知状态" not in updated_fields
    assert "通知时间" not in updated_fields
    assert "首次同步时间" not in updated_fields
    for fields in [
        *feishu.create_batches[0],
        *(fields for _record_id, fields in feishu.update_batches[0]),
    ]:
        assert set(fields) <= SYSTEM_FIELDS
        assert set(fields).isdisjoint(BUSINESS_FIELDS)


@pytest.mark.asyncio
async def test_sync_splits_501_creates_into_safe_batches() -> None:
    source = FakeSourceRepository([_record(index) for index in range(1, 502)])
    feishu = FakeFeishuClient()
    mappings = FakeMappingRepository()
    service, _audits = _service(source, mappings, feishu)

    result = await service.sync(tenant_id=UUID(int=10_000), shop_id=UUID(int=20_000))

    assert result.created_count == 501
    assert [len(batch) for batch in feishu.create_batches] == [500, 1]
    assert [len(batch) for batch in mappings.batches] == [500, 1]
    assert feishu.update_batches == []
    assert source.calls == [None, UUID(int=500)]


@pytest.mark.asyncio
async def test_sync_updates_only_requested_application_scope() -> None:
    records = [_record(1), _record(2)]
    existing = {
        f"{UUID(int=20_000)}:sample-1": "rec-1",
        f"{UUID(int=20_000)}:sample-2": "rec-2",
    }
    source = FakeSourceRepository(records)
    feishu = FakeFeishuClient(existing)
    service, _audits = _service(source, FakeMappingRepository(), feishu)

    result = await service.sync(
        tenant_id=UUID(int=10_000),
        shop_id=UUID(int=20_000),
        application_ids=frozenset({UUID(int=2)}),
    )

    assert result.source_count == 1
    assert result.updated_count == 1
    assert [record_id for batch in feishu.update_batches for record_id, _ in batch] == [
        "rec-2"
    ]


@pytest.mark.asyncio
async def test_incremental_sync_skips_unchanged_scoped_records() -> None:
    records = [
        _record(1, feishu_record_id="rec-1"),
        _record(2, feishu_record_id="rec-2"),
        _record(3, feishu_record_id="rec-3"),
    ]
    scope = frozenset({records[0].application_id, records[1].application_id})
    synced_at = datetime(2026, 9, 11, tzinfo=UTC)
    snapshots = {
        "rec-1": build_feishu_system_fields(records[0], synced_at=synced_at),
        "rec-2": build_feishu_system_fields(records[1], synced_at=synced_at),
    }
    snapshots["rec-2"]["TK\u7533\u8bf7\u72b6\u6001"] = "SHIPPED"
    existing = {
        f"{UUID(int=20_000)}:sample-{index}": f"rec-{index}" for index in range(1, 4)
    }
    source = FakeSourceRepository(records)
    feishu = FakeFeishuClient(existing, snapshot_fields=snapshots)
    service, _audits = _service(source, FakeMappingRepository(), feishu)

    result = await service.sync(
        tenant_id=UUID(int=10_000),
        shop_id=UUID(int=20_000),
        application_ids=scope,
    )

    assert result.source_count == 2
    assert result.updated_count == 1
    assert source.scopes == [scope]
    assert [item[0] for batch in feishu.update_batches for item in batch] == ["rec-2"]


@pytest.mark.asyncio
async def test_duplicate_postgres_sync_key_fails_before_feishu_write() -> None:
    source = FakeSourceRepository(
        [
            _record(1, platform_application_id="duplicate"),
            _record(2, platform_application_id="duplicate"),
        ]
    )
    feishu = FakeFeishuClient()
    mappings = FakeMappingRepository()
    service, audits = _service(source, mappings, feishu)

    with pytest.raises(RuntimeError, match="invalid or duplicated"):
        await service.sync(tenant_id=UUID(int=10_000), shop_id=UUID(int=20_000))

    assert feishu.create_batches == []
    assert feishu.update_batches == []
    assert mappings.batches == []
    assert audits.finished[0]["status"] == "failed"
    assert audits.finished[0]["error_code"] == "RuntimeError"


@pytest.mark.asyncio
async def test_conflicting_saved_record_id_fails_before_feishu_write() -> None:
    source = FakeSourceRepository([_record(1, feishu_record_id="rec-old")])
    sync_key = f"{UUID(int=20_000)}:sample-1"
    feishu = FakeFeishuClient({sync_key: "rec-new"})
    mappings = FakeMappingRepository()
    service, _audits = _service(source, mappings, feishu)

    with pytest.raises(RuntimeError, match="mappings conflict"):
        await service.sync(tenant_id=UUID(int=10_000), shop_id=UUID(int=20_000))

    assert mappings.batches == []
    assert feishu.create_batches == []
    assert feishu.update_batches == []


@pytest.mark.asyncio
async def test_saved_record_missing_from_feishu_fails_before_duplicate_create() -> None:
    source = FakeSourceRepository([_record(1, feishu_record_id="rec-missing")])
    feishu = FakeFeishuClient()
    mappings = FakeMappingRepository()
    service, _audits = _service(source, mappings, feishu)

    with pytest.raises(RuntimeError, match="missing from the target table"):
        await service.sync(tenant_id=UUID(int=10_000), shop_id=UUID(int=20_000))

    assert mappings.batches == []
    assert feishu.create_batches == []
    assert feishu.update_batches == []


@pytest.mark.asyncio
async def test_feishu_failure_code_and_request_id_are_audited() -> None:
    source = FakeSourceRepository([_record(1)])
    feishu = FailingFeishuClient(request_ids=["failure-log"])
    mappings = FakeMappingRepository()
    service, audits = _service(source, mappings, feishu)

    with pytest.raises(FeishuSampleError):
        await service.sync(tenant_id=UUID(int=10_000), shop_id=UUID(int=20_000))

    assert audits.finished[0]["status"] == "failed"
    assert audits.finished[0]["request_ids"] == ["failure-log"]
    assert audits.finished[0]["error_code"] == "99991400"


def test_sync_boundary_accepts_no_browser_payload() -> None:
    parameters = inspect.signature(SampleFeishuSyncService.sync).parameters
    source = Path("src/erp_api/services/sample_feishu_sync_service.py").read_text(
        encoding="utf-8"
    )

    assert set(parameters) == {"self", "tenant_id", "shop_id", "application_ids"}
    assert "raw_payload" not in source
    assert "hubstudio" not in source.casefold()
    assert "backend.app" not in source
