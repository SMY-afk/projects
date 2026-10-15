from types import SimpleNamespace
from uuid import uuid4

import pytest

from erp_api.services.sample_assignment_summary_service import (
    AssignmentSummaryDetail,
    SampleAssignmentSummaryService,
)
from erp_api.services.sample_assignment_type_router import CombinedAssignmentReader
from tests.test_sample_assignment_summary_service import (
    AssignmentClient,
    Repository,
    SummaryClient,
    _assignment_record,
)


def test_paid_counts_are_separate_from_existing_free_levels():
    free_id, paid_id = uuid4(), uuid4()
    assignments = {free_id: ("BD A", "Shop"), paid_id: ("BD A", "Shop")}
    details = {
        free_id: AssignmentSummaryDetail("L2", "Shop", 600000),
        paid_id: AssignmentSummaryDetail("L4", "Shop", 8000000, "refundable"),
    }
    free, paid = SampleAssignmentSummaryService.split_assignment_types(assignments, details)
    assert set(free) == {free_id}
    assert set(paid) == {paid_id}


@pytest.mark.asyncio
async def test_same_event_in_both_tables_cannot_be_double_counted():
    class Client:
        async def list_record_snapshots(self):
            return [SimpleNamespace(snapshot=SimpleNamespace(fields={"分配编号": "same-event"}))]
    with pytest.raises(RuntimeError, match="duplicated"):
        await CombinedAssignmentReader(Client(), Client()).list_record_snapshots()


@pytest.mark.asyncio
async def test_paid_summary_has_one_row_per_shop_bd_and_all_eight_levels():
    details, records = {}, []
    for shop in ("Shop A", "Shop B"):
        for bd in ("BD A", "BD B"):
            for level in range(8):
                assignment_id = uuid4()
                details[assignment_id] = AssignmentSummaryDetail(
                    f"L{level}", shop, 100, "refundable",
                )
                records.append(_assignment_record(assignment_id, bd_name=bd, shop_name=shop))
    free_id = uuid4()
    details[free_id] = AssignmentSummaryDetail("L7", "Shop A", 100, "free")
    records.append(_assignment_record(free_id, bd_name="BD A", shop_name="Shop A"))
    summary = SummaryClient()
    service = SampleAssignmentSummaryService(
        Repository(details, ("Shop A", "Shop B")), AssignmentClient(records), summary,
        allowed_shop_ids={uuid4(), uuid4()}, bd_names=("BD A", "BD B"),
        sample_type="refundable",
    )
    result = await service.sync()
    assert result.source_count == 32
    assert result.created_count == 4
    assert {row["店铺｜BD"] for row in summary.creates} == {
        f"{shop}｜{bd}" for shop in ("Shop A", "Shop B") for bd in ("BD A", "BD B")
    }
    for row in summary.creates:
        assert [row[f"L{i}"] for i in range(8)] == [1] * 8
        assert row["店铺分配总计"] == 8
