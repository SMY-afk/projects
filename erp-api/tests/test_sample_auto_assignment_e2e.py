import asyncio
from collections import Counter
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4, uuid5

import pytest

from erp_api.services.sample_application_mapper import normalize_sample_application
from erp_api.services.sample_auto_assignment_service import (
    PendingSampleAssignment,
    SampleAutoAssignmentService,
)
from erp_api.services.sample_bd_assignment import BdWorkload
from erp_api.services.sample_shop_pipeline_service import SampleShopPipelineService


class MemoryAssignmentState:
    def __init__(self) -> None:
        self.pending: list[PendingSampleAssignment] = []
        self.assignments: dict[UUID, object] = {}
        self.audits: list[dict[str, object]] = []
        self.outbox: list[dict[str, object]] = []
        self.delivered: set[UUID] = set()
        self.workloads: dict[str, dict[str, object]] = {}
        self.locks: dict[tuple[UUID, UUID], asyncio.Lock] = {}
        self.clock = datetime(2026, 9, 10, tzinfo=UTC)
class MemoryTransaction:
    def __init__(
        self,
        state: MemoryAssignmentState,
        request: PendingSampleAssignment,
    ) -> None:
        self.state = state
        self.request = request

    async def is_assigned(self) -> bool:
        return self.request.application_id in self.state.assignments

    async def load_workloads(self, roster):
        workloads = []
        for member in roster:
            values = self.state.workloads.setdefault(
                member.bd_id,
                {
                    "current_pending": member.current_pending,
                    "assigned_today": member.assigned_today,
                    "total_assigned": member.total_assigned,
                    "level_counts": Counter(member.level_counts),
                    "last_assigned_level": member.last_assigned_level,
                    "last_received_levels": member.last_received_levels,
                    "last_assigned_at": member.last_assigned_at,
                },
            )
            workloads.append(replace(member, **values))
        return workloads

    async def load_creator_bd_name(self):
        return None

    async def load_compensation_bd_name(self):
        return None

    async def record_decision(self, decision, *, rule_version: str) -> None:
        audit = {
            "application_id": self.request.application_id,
            "rule_version": rule_version,
            "status": "assigned" if decision.assigned else "blocked",
            "reason": decision.decision_reason or decision.blocked_reason,
            "bd_id": decision.assigned_bd_id,
        }
        self.state.audits.append(audit)
        if not decision.assigned:
            return
        self.state.assignments[self.request.application_id] = decision
        values = self.state.workloads[decision.assigned_bd_id]
        values["current_pending"] += 1
        values["assigned_today"] += 1
        values["total_assigned"] += 1
        values["level_counts"][decision.creator_level] += 1
        values["last_assigned_level"] = decision.creator_level
        for workload in self.state.workloads.values():
            levels = set(workload["last_received_levels"])
            levels.discard(decision.creator_level)
            workload["last_received_levels"] = frozenset(levels)
        values["last_received_levels"] |= {decision.creator_level}
        values["last_assigned_at"] = self.state.clock
        self.state.clock += timedelta(seconds=1)
        self.state.outbox.append(
            {
                "application_id": self.request.application_id,
                "bd_id": decision.assigned_bd_id,
                "recipient_open_id": decision.recipient_open_id,
                "rule_version": rule_version,
            }
        )
class MemoryAssignmentRepository:
    def __init__(self, state: MemoryAssignmentState) -> None:
        self.state = state

    async def list_pending(
        self,
        tenant_id,
        shop_id,
        *,
        application_ids=None,
    ):
        return [
            item
            for item in self.state.pending
            if item.tenant_id == tenant_id and item.shop_id == shop_id
            and (
                application_ids is None
                or item.application_id in application_ids
            )
            and item.application_id not in self.state.assignments
        ]

    @asynccontextmanager
    async def transaction(self, request):
        key = (request.tenant_id, request.shop_id)
        lock = self.state.locks.setdefault(key, asyncio.Lock())
        async with lock:
            yield MemoryTransaction(self.state, request)


class MemoryRoster:
    def __init__(self, members) -> None:
        self.members = tuple(members)

    async def list_members(self, _tenant_id, _shop_id, *, sample_type="free"):
        return self.members


class SourceSync:
    def __init__(self, state, tenant_id, shop_id, count=12) -> None:
        self.state = state
        self.tenant_id = tenant_id
        self.shop_id = shop_id
        self.count = count
        self.loaded = False

    async def sync(self, *_args, **_kwargs):
        if not self.loaded:
            namespace = uuid4()
            for index in range(self.count):
                platform_id = f"smoke-like-{index}"
                normalized = normalize_sample_application(
                    {
                        "id": platform_id,
                        "status": "PENDING",
                        "creator": {
                            "nickname": f"Creator {index}",
                            "gmv": {"amount": "25000", "currency": "USD"},
                        },
                        "product": {"id": "rc-1", "title": "RC Car"},
                    },
                    observed_at=datetime(2026, 9, 10, tzinfo=UTC),
                )
                self.state.pending.append(
                    PendingSampleAssignment(
                        tenant_id=self.tenant_id,
                        shop_id=self.shop_id,
                        application_id=uuid5(namespace, platform_id),
                        creator_level=normalized["creator_level"],
                        category="rc-car",
                        assignment_key=platform_id,
                    )
                )
            self.loaded = True
        application_ids = tuple(
            item.application_id
            for item in self.state.pending
            if item.tenant_id == self.tenant_id and item.shop_id == self.shop_id
        )
        return SimpleNamespace(
            status="succeeded",
            application_ids=application_ids,
        )


class FeishuProjection:
    def __init__(self, state) -> None:
        self.state = state
        self.projected = 0

    async def sync(self, **_kwargs):
        self.projected = len(self.state.assignments)
        return SimpleNamespace(status="succeeded", projected=self.projected)


class CapturedNotifications:
    def __init__(self, state) -> None:
        self.state = state

    async def list_due(self, **_kwargs):
        return [
            (item["tenant_id"], item["application_id"], 0)
            if "tenant_id" in item
            else (_kwargs["tenant_id"], item["application_id"], 0)
            for item in self.state.outbox
            if item["application_id"] not in self.state.delivered
        ]

    async def deliver(self, _tenant_id, event_id):
        self.state.delivered.add(event_id)
        return "captured"


class AssignmentProjection:
    async def sync(self, **_kwargs):
        return SimpleNamespace(updated_count=12)


class AssignmentRecords:
    async def sync(self, **_kwargs):
        return SimpleNamespace(created_count=12, updated_count=0)


class ProfileEnrichment:
    async def enrich(self, **_kwargs):
        return SimpleNamespace(enriched_count=12)


class ReadyImages:
    async def blocked_reason(self, _tenant_id, _shop_id, _application_id):
        return None


def _roster():
    names = ("李鸿程", "吴洵涛", "刘诚")
    return [
        BdWorkload(
            name=name,
            bd_id=f"test-bd-{index}",
            recipient_open_id=f"ou-test-{index}",
            categories=frozenset({"rc-car"}),
            capacity=10,
        )
        for index, name in enumerate(names, start=1)
    ]


@pytest.mark.asyncio
async def test_three_test_bds_complete_automatic_pipeline_without_external_writes():
    tenant_id, shop_id = uuid4(), uuid4()
    state = MemoryAssignmentState()
    assignments = SampleAutoAssignmentService(
        MemoryAssignmentRepository(state),
        MemoryRoster(_roster()),
        ReadyImages(),
        allowed_shop_ids=frozenset({shop_id}),
        rule_version="bd-v1-e2e",
    )
    feishu = FeishuProjection(state)
    notifications = CapturedNotifications(state)
    pipeline = SampleShopPipelineService(
        SourceSync(state, tenant_id, shop_id),
        feishu,
        notifications,
        assignments,
        AssignmentProjection(),
        AssignmentRecords(),
        ProfileEnrichment(),
    )

    first = await pipeline.run(
        tenant_id,
        shop_id,
        mode="active",
        statuses=["PENDING"],
    )

    assert first.auto_assignment_result.assigned_count == 12
    assert first.auto_assignment_result.blocked_count == 0
    assert feishu.projected == 12
    assert len(state.audits) == len(state.outbox) == len(state.delivered) == 12
    assert set(Counter(item["bd_id"] for item in state.outbox).values()) == {4}
    assert all(
        item["reason"]
        in {
            "selected",
            "selected_level_balance",
            "selected_level_rotation",
            "selected_level_balance_over_rotation",
        }
        for item in state.audits
    )
    assert {item["recipient_open_id"] for item in state.outbox} == {
        "ou-test-1",
        "ou-test-2",
        "ou-test-3",
    }

    second = await pipeline.run(
        tenant_id,
        shop_id,
        mode="active",
        statuses=["PENDING"],
    )

    assert second.auto_assignment_result.items == ()
    assert len(state.audits) == len(state.outbox) == len(state.delivered) == 12


@pytest.mark.asyncio
async def test_concurrent_assignment_runs_remain_unique_and_shop_scoped():
    tenant_id, shop_id, other_shop_id = uuid4(), uuid4(), uuid4()
    state = MemoryAssignmentState()
    await SourceSync(state, tenant_id, shop_id, count=6).sync()
    service = SampleAutoAssignmentService(
        MemoryAssignmentRepository(state),
        MemoryRoster(_roster()),
        ReadyImages(),
        allowed_shop_ids=frozenset({shop_id}),
    )

    first, second = await asyncio.gather(
        service.run_for_shop(tenant_id=tenant_id, shop_id=shop_id),
        service.run_for_shop(tenant_id=tenant_id, shop_id=shop_id),
    )
    skipped = await service.run_for_shop(
        tenant_id=tenant_id,
        shop_id=other_shop_id,
    )

    assert first.assigned_count + second.assigned_count == 6
    assert first.duplicate_count + second.duplicate_count == 0
    assert len(state.assignments) == len(state.outbox) == 6
    assert skipped.status == "skipped"
    assert skipped.blocked_reason == "shop_not_allowed"
