from datetime import UTC, datetime
from uuid import uuid4

import pytest

from erp_api.services.feishu_assignment_workload_provider import (
    AssignmentWorkloadDetail,
    FeishuAssignmentWorkloadProvider,
)
from erp_api.services.feishu_sample_record_snapshot import (
    FeishuListedRecord,
    FeishuRecordSnapshot,
)
from erp_api.services.sample_assignment_summary_service import (
    AssignmentSummaryDetail,
    SampleAssignmentSummaryService,
)
from erp_api.services.sample_bd_assignment import BdWorkload


def _record(assignment_id, *, status: str):
    fields = {
        "分配编号": str(assignment_id),
        "分配BD": "BD A",
        "店铺名称": "Shop A",
        "分配时间": int(datetime(2026, 9, 20, tzinfo=UTC).timestamp() * 1000),
        "通知状态": status,
    }
    return FeishuListedRecord(
        f"rec-{assignment_id}", FeishuRecordSnapshot(fields)
    )


class _Client:
    def __init__(self, records):
        self.records = records

    async def list_record_snapshots(self):
        return self.records


class _Repository:
    def __init__(self, workload_details, summary_details):
        self.workload_details = workload_details
        self.summary_details = summary_details

    async def assignment_workload_details(self, assignment_ids):
        return {item: self.workload_details[item] for item in assignment_ids}

    async def assignment_details(self, assignment_ids):
        return {item: self.summary_details[item] for item in assignment_ids}

    async def list_shop_names(self, _shop_ids):
        return ("Shop A",)


class _SummaryClient:
    def __init__(self):
        self.creates = []

    async def list_record_snapshots(self):
        return ()

    async def batch_create_summary_records(self, records):
        self.creates.extend(records)


@pytest.mark.asyncio
async def test_cancelled_record_is_excluded_from_assignment_workload() -> None:
    shop_id = uuid4()
    active_id, cancelled_id = uuid4(), uuid4()
    repository = _Repository(
        {
            active_id: AssignmentWorkloadDetail(shop_id, "L2", 100_000),
            cancelled_id: AssignmentWorkloadDetail(shop_id, "L2", 900_000),
        },
        {},
    )
    provider = FeishuAssignmentWorkloadProvider(
        _Client((_record(active_id, status="已通知"), _record(cancelled_id, status="已取消"))),
        repository,
    )

    result = await provider.enrich(shop_id, (BdWorkload("BD A"),))

    assert result[0].total_assigned == 1
    assert result[0].level_counts == {"L2": 1}
    assert result[0].level_gmv_minor_totals == {"L2": 100_000}


@pytest.mark.asyncio
async def test_cancelled_record_is_excluded_from_assignment_summary() -> None:
    shop_id = uuid4()
    active_id, cancelled_id = uuid4(), uuid4()
    repository = _Repository(
        {},
        {
            active_id: AssignmentSummaryDetail("L2", "Shop A", 100_000),
            cancelled_id: AssignmentSummaryDetail("L2", "Shop A", 900_000),
        },
    )
    summary = _SummaryClient()
    service = SampleAssignmentSummaryService(
        repository,
        _Client((_record(active_id, status="已通知"), _record(cancelled_id, status="已取消"))),
        summary,
        allowed_shop_ids={shop_id},
        bd_names=("BD A",),
    )

    result = await service.sync()

    assert result.source_count == 1
    assert summary.creates[0]["L2"] == 1
