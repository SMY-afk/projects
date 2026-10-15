from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from erp_api.services.feishu_assignment_workload_provider import (
    AssignmentWorkloadDetail,
    FeishuAssignmentWorkloadProvider,
)
from erp_api.services.sample_bd_assignment import BdWorkload


class AssignmentClient:
    def __init__(self, records) -> None:
        self.records = tuple(records)

    async def list_record_snapshots(self):
        return self.records


class Details:
    def __init__(self, values) -> None:
        self.values = values

    async def assignment_workload_details(self, assignment_ids):
        return {
            assignment_id: self.values[assignment_id]
            for assignment_id in assignment_ids
        }


def _record(assignment_id, *, bd_name, assigned_at):
    return SimpleNamespace(
        snapshot=SimpleNamespace(
            fields={
                "分配编号": str(assignment_id),
                "分配BD": bd_name,
                "分配时间": int(assigned_at.timestamp() * 1000),
            }
        )
    )


@pytest.mark.asyncio
async def test_existing_assignment_records_are_the_workload_source() -> None:
    shop_id = uuid4()
    other_shop_id = uuid4()
    first, second, third, other = (uuid4() for _ in range(4))
    today = datetime(2026, 9, 16, 8, tzinfo=UTC)
    records = (
        _record(first, bd_name="BD A", assigned_at=today.replace(hour=1)),
        _record(second, bd_name="BD A", assigned_at=today.replace(hour=2)),
        _record(third, bd_name="BD B", assigned_at=today.replace(hour=3)),
        _record(other, bd_name="BD A", assigned_at=today.replace(hour=4)),
    )
    details = Details(
        {
            first: AssignmentWorkloadDetail(shop_id, "L2", 500_000),
            second: AssignmentWorkloadDetail(shop_id, "L1", 100_000),
            third: AssignmentWorkloadDetail(shop_id, "L2", 700_000),
            other: AssignmentWorkloadDetail(other_shop_id, "L2", 900_000),
        }
    )
    provider = FeishuAssignmentWorkloadProvider(
        AssignmentClient(records),
        details,
        clock=lambda: today,
    )
    roster = (
        BdWorkload(
            "BD A",
            bd_id="rec-a",
            recipient_open_id="ou-a",
            current_pending=4,
        ),
        BdWorkload(
            "BD B",
            bd_id="rec-b",
            recipient_open_id="ou-b",
            current_pending=3,
        ),
    )

    result = await provider.enrich(shop_id, roster)

    assert result[0].current_pending == 4
    assert result[0].total_assigned == 2
    assert result[0].level_counts == {"L2": 1, "L1": 1}
    assert result[0].level_gmv_minor_totals == {"L2": 500_000, "L1": 100_000}
    assert result[0].assigned_today == 2
    assert result[0].last_received_levels == frozenset({"L1"})
    assert result[1].current_pending == 3
    assert result[1].total_assigned == 1
    assert result[1].level_counts == {"L2": 1}
    assert result[1].level_gmv_minor_totals == {"L2": 700_000}
    assert result[1].last_received_levels == frozenset({"L2"})


@pytest.mark.asyncio
async def test_historical_assignment_for_removed_bd_is_ignored() -> None:
    shop_id = uuid4()
    current, removed = uuid4(), uuid4()
    assigned_at = datetime(2026, 9, 16, 8, tzinfo=UTC)
    records = (
        _record(current, bd_name="BD A", assigned_at=assigned_at),
        _record(removed, bd_name="Former BD", assigned_at=assigned_at),
    )
    details = Details(
        {
            current: AssignmentWorkloadDetail(shop_id, "L2"),
            removed: AssignmentWorkloadDetail(shop_id, "L2"),
        }
    )
    provider = FeishuAssignmentWorkloadProvider(
        AssignmentClient(records),
        details,
        clock=lambda: assigned_at,
    )
    roster = (
        BdWorkload(
            "BD A",
            bd_id="rec-a",
            recipient_open_id="ou-a",
        ),
    )

    result = await provider.enrich(shop_id, roster)

    assert result[0].total_assigned == 1
    assert result[0].level_counts == {"L2": 1}


@pytest.mark.asyncio
async def test_bd_aliases_are_combined_before_level_balancing() -> None:
    shop_id = uuid4()
    historical, current = uuid4(), uuid4()
    assigned_at = datetime(2026, 9, 18, 2, tzinfo=UTC)
    records = (
        _record(historical, bd_name="example-ed519e732c75", assigned_at=assigned_at),
        _record(current, bd_name="example-44e1fbf547ff", assigned_at=assigned_at),
    )
    details = Details(
        {
            historical: AssignmentWorkloadDetail(shop_id, "L2"),
            current: AssignmentWorkloadDetail(shop_id, "L2"),
        }
    )
    provider = FeishuAssignmentWorkloadProvider(
        AssignmentClient(records),
        details,
        bd_aliases={"example-44e1fbf547ff": "example-ed519e732c75"},
        clock=lambda: assigned_at,
    )
    roster = (
        BdWorkload(
            "example-44e1fbf547ff",
            bd_id="rec-current",
            recipient_open_id="ou-current",
        ),
    )

    result = await provider.enrich(shop_id, roster)

    assert result[0].total_assigned == 2
    assert result[0].level_counts == {"L2": 2}
