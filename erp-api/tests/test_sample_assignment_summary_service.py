from datetime import UTC, datetime
from uuid import uuid4

import pytest

from erp_api.services.feishu_sample_record_snapshot import (
    FeishuListedRecord,
    FeishuRecordSnapshot,
)
from erp_api.services.sample_assignment_summary_service import (
    AssignmentSummaryDetail,
    SampleAssignmentSummaryService,
)


class AssignmentClient:
    def __init__(self, records) -> None:
        self.records = records

    async def list_record_snapshots(self):
        return self.records


class SummaryClient:
    def __init__(self, records=()) -> None:
        self.records = records
        self.updates = []
        self.creates = []

    async def list_record_snapshots(self):
        return self.records

    async def batch_update_summary_records(self, records):
        self.updates.extend(records)

    async def batch_create_summary_records(self, records):
        self.creates.extend(records)


class Repository:
    def __init__(self, details, shop_names=("Shop A",)) -> None:
        self.details = details
        self.shop_names = shop_names

    async def assignment_details(self, assignment_ids):
        assert set(assignment_ids) == set(self.details)
        return self.details

    async def list_shop_names(self, shop_ids):
        assert shop_ids
        return self.shop_names


def _assignment_record(assignment_id, *, bd_name, shop_name):
    return FeishuListedRecord(
        f"rec-source-{assignment_id}",
        FeishuRecordSnapshot(
            {
                "分配编号": str(assignment_id),
                "分配BD": bd_name,
                "店铺名称": shop_name,
            }
        ),
    )


def _summary_record(record_id, *, key, locked, **fields):
    return FeishuListedRecord(
        record_id,
        FeishuRecordSnapshot(
            {"店铺｜BD": key, "人工锁定": locked, **fields}
        ),
    )


@pytest.mark.asyncio
async def test_sync_updates_system_counts_even_when_row_is_locked() -> None:
    first_id = uuid4()
    second_id = uuid4()
    assignments = AssignmentClient(
        (
            _assignment_record(first_id, bd_name="BD A", shop_name="Shop A"),
            _assignment_record(second_id, bd_name="BD B", shop_name="Shop A"),
        )
    )
    summary = SummaryClient(
        (
            _summary_record("rec-a", key="Shop A｜BD A", locked=False),
            _summary_record(
                "rec-b",
                key="Shop A｜BD B",
                locked=True,
                L0=99,
                备注="人工值",
            ),
        )
    )
    repository = Repository(
        {
            first_id: AssignmentSummaryDetail("L0", "Shop A", 12_345),
            second_id: AssignmentSummaryDetail("L1", "Shop A", 67_890),
        }
    )
    now = datetime(2026, 9, 16, 4, 30, tzinfo=UTC)
    service = SampleAssignmentSummaryService(
        repository,
        assignments,
        summary,
        allowed_shop_ids=frozenset({uuid4()}),
        bd_names=("BD A", "BD B"),
        clock=lambda: now,
    )

    result = await service.sync()

    assert result.source_count == 2
    assert result.updated_count == 2
    assert result.created_count == 0
    assert result.locked_count == 1
    updates = dict(summary.updates)
    assert updates["rec-a"]["L0"] == 1
    assert updates["rec-a"]["L0 GMV（USD）"] == 123.45
    assert updates["rec-a"]["GMV总计（USD）"] == 123.45
    assert updates["rec-b"]["L1"] == 1
    assert updates["rec-b"]["L1 GMV（USD）"] == 678.9
    assert updates["rec-b"]["GMV总计（USD）"] == 678.9
    assert updates["rec-b"]["店铺分配总计"] == 1
    assert "备注" not in updates["rec-b"]


@pytest.mark.asyncio
async def test_sync_updates_global_level_count_gmv_and_average_rows() -> None:
    first_id = uuid4()
    second_id = uuid4()
    missing_gmv_id = uuid4()
    summary = SummaryClient(
        (
            _summary_record("rec-count", key="等级数量总计", locked=False),
            _summary_record("rec-total", key="GMV总计", locked=False),
            _summary_record("rec-average", key="GMV平均值", locked=False),
        )
    )
    service = SampleAssignmentSummaryService(
        Repository(
            {
                first_id: AssignmentSummaryDetail("L5", "Shop A", 1_000_000),
                second_id: AssignmentSummaryDetail("L5", "Shop A", 3_000_001),
                missing_gmv_id: AssignmentSummaryDetail("L5", "Shop A", None),
            }
        ),
        AssignmentClient(
            (
                _assignment_record(first_id, bd_name="BD A", shop_name="Shop A"),
                _assignment_record(second_id, bd_name="BD B", shop_name="Shop A"),
                _assignment_record(
                    missing_gmv_id, bd_name="BD A", shop_name="Shop A"
                ),
            )
        ),
        summary,
        allowed_shop_ids=frozenset({uuid4()}),
        bd_names=("BD A", "BD B"),
        clock=lambda: datetime(2026, 9, 18, tzinfo=UTC),
    )

    result = await service.sync()

    assert result.updated_count == 3
    updates = dict(summary.updates)
    assert updates["rec-count"]["L5"] == 3
    assert updates["rec-total"]["L5"] == 40_000.01
    assert updates["rec-average"]["L5"] == 20_000.01
    assert updates["rec-count"]["L0"] == 0


@pytest.mark.asyncio
async def test_manual_assignment_deletion_recalculates_locked_summary_row() -> None:
    summary = SummaryClient(
        (
            _summary_record(
                "rec-a",
                key="Shop A｜BD A",
                locked=True,
                L0=1,
                L1=0,
                L2=0,
                L3=0,
                L4=0,
                L5=0,
                L6=0,
                L7=0,
                店铺分配总计=1,
            ),
        )
    )
    service = SampleAssignmentSummaryService(
        Repository({}, shop_names=("Shop A",)),
        AssignmentClient(()),
        summary,
        allowed_shop_ids=frozenset({uuid4()}),
        bd_names=("BD A",),
        clock=lambda: datetime(2026, 9, 17, tzinfo=UTC),
    )

    result = await service.sync()

    assert result.source_count == 0
    assert result.updated_count == 1
    assert result.locked_count == 1
    assert summary.updates[0][0] == "rec-a"
    assert summary.updates[0][1]["L0"] == 0
    assert summary.updates[0][1]["店铺分配总计"] == 0


@pytest.mark.asyncio
async def test_sync_creates_all_shop_bd_combinations_with_zero_rows() -> None:
    assignment_id = uuid4()
    assignments = AssignmentClient(
        (_assignment_record(assignment_id, bd_name="BD A", shop_name="Shop A"),)
    )
    summary = SummaryClient()
    repository = Repository(
        {assignment_id: AssignmentSummaryDetail("L2", "Shop A")},
        shop_names=("Shop A", "Shop B"),
    )
    service = SampleAssignmentSummaryService(
        repository,
        assignments,
        summary,
        allowed_shop_ids=frozenset({uuid4(), uuid4()}),
        bd_names=("BD A", "BD B"),
        clock=lambda: datetime(2026, 9, 16, tzinfo=UTC),
    )

    result = await service.sync()

    assert result.created_count == 4
    rows = {fields["店铺｜BD"]: fields for fields in summary.creates}
    assert set(rows) == {
        "Shop A｜BD A",
        "Shop A｜BD B",
        "Shop B｜BD A",
        "Shop B｜BD B",
    }
    assert rows["Shop A｜BD A"]["L2"] == 1
    assert rows["Shop B｜BD B"]["店铺分配总计"] == 0
    assert all(fields["人工锁定"] is False for fields in rows.values())


@pytest.mark.asyncio
async def test_sync_rejects_duplicate_summary_keys() -> None:
    summary = SummaryClient(
        (
            _summary_record("rec-a", key="Shop A｜BD A", locked=False),
            _summary_record("rec-b", key="Shop A｜BD A", locked=False),
        )
    )
    service = SampleAssignmentSummaryService(
        Repository({}, shop_names=("Shop A",)),
        AssignmentClient(()),
        summary,
        allowed_shop_ids=frozenset({uuid4()}),
        bd_names=("BD A",),
    )

    with pytest.raises(RuntimeError, match="duplicated"):
        await service.sync()


@pytest.mark.asyncio
async def test_sync_normalizes_shop_suffix_and_bd_alias() -> None:
    assignment_id = uuid4()
    summary = SummaryClient(
        (_summary_record("rec-a", key="Shop A｜example-ed519e732c75", locked=False),)
    )
    service = SampleAssignmentSummaryService(
        Repository(
            {assignment_id: AssignmentSummaryDetail("L3", "Shop A")},
            shop_names=("Shop A",),
        ),
        AssignmentClient(
            (
                _assignment_record(
                    assignment_id,
                    bd_name="example-44e1fbf547ff",
                    shop_name="Shop A（跨境3）",
                ),
            )
        ),
        summary,
        allowed_shop_ids=frozenset({uuid4()}),
        bd_names=("example-ed519e732c75",),
        bd_aliases={"example-44e1fbf547ff": "example-ed519e732c75"},
    )

    result = await service.sync()

    assert result.updated_count == 1
    assert summary.updates[0][1]["L3"] == 1


@pytest.mark.asyncio
async def test_sync_skips_unchanged_summary_rows() -> None:
    now = datetime(2026, 9, 18, tzinfo=UTC)
    service = SampleAssignmentSummaryService(
        Repository({}, shop_names=("Shop A",)),
        AssignmentClient(()),
        SummaryClient(),
        allowed_shop_ids=frozenset({uuid4()}),
        bd_names=("BD A",),
        clock=lambda: now,
    )
    initial = await service.sync()
    assert initial.created_count == 1
    fields = service._summary_client.creates[0]
    summary = SummaryClient((_summary_record("rec-a", key="Shop A｜BD A", locked=False, **{key: value for key, value in fields.items() if key not in {"店铺｜BD", "人工锁定"}}),))
    service._summary_client = summary

    result = await service.sync()

    assert result.updated_count == 0
    assert summary.updates == []
