from types import SimpleNamespace
from uuid import uuid4

import pytest

from erp_api.services.sample_shop_pipeline_service import SampleShopPipelineService


@pytest.mark.asyncio
async def test_hubstudio_pipeline_skips_external_work_when_local_gate_is_empty() -> None:
    tenant_id, shop_id = uuid4(), uuid4()
    events = []

    class WorkGate:
        async def has_work(self, **kwargs):
            events.append(("gate", kwargs["shop_id"]))
            return False

    class UnexpectedFeishu:
        async def sync(self, **_kwargs):
            raise AssertionError("empty local gate must not call Feishu")

    async def unexpected_profile_capture():
        raise AssertionError("empty local gate must not capture profiles")

    result = await SampleShopPipelineService(
        object(),
        UnexpectedFeishu(),
        work_gate=WorkGate(),
    ).complete_after_source(
        tenant_id=tenant_id,
        shop_id=shop_id,
        source_type="hubstudio_cdp",
        source_results=(
            SimpleNamespace(
                application_ids=(uuid4(),),
                changed_application_ids=(),
                obsolete_platform_application_ids=frozenset(),
            ),
        ),
        profile_capture=unexpected_profile_capture,
    )

    assert result.status == "skipped"
    assert result.feishu_result is None
    assert events == [("gate", shop_id)]


@pytest.mark.asyncio
async def test_pipeline_runs_source_feishu_and_shop_notifications_in_order() -> None:
    tenant_id, shop_id, event_id = uuid4(), uuid4(), uuid4()
    source_application_id = uuid4()
    assigned_application_id = uuid4()
    events = []
    assignment_record_scopes = []
    auto_assignment_scopes = []

    class Source:
        async def sync(self, *args, **kwargs):
            events.append(("source", kwargs["status"]))
            return SimpleNamespace(
                status="succeeded",
                application_ids=(source_application_id,),
            )

    class Feishu:
        async def sync(self, **kwargs):
            events.append(("feishu", kwargs["shop_id"]))
            return "feishu-result"

    class AutoAssignments:
        async def run_for_shop(self, **kwargs):
            events.append(("auto-assignment", kwargs["shop_id"]))
            auto_assignment_scopes.append(kwargs.get("application_ids"))
            return SimpleNamespace(
                status="succeeded",
                items=(
                    SimpleNamespace(
                        status="assigned",
                        application_id=assigned_application_id,
                    ),
                ),
            )

    class AutoAssignmentProjection:
        async def sync(self, **kwargs):
            events.append(
                ("auto-assignment-projection", kwargs["shop_id"], kwargs.get("verify_current"))
            )
            return SimpleNamespace(updated_count=1)

    class AssignmentRecords:
        calls = 0

        async def sync(self, **kwargs):
            self.calls += 1
            events.append(("assignment-records", kwargs["shop_id"]))
            assignment_record_scopes.append(
                (kwargs.get("application_ids"), kwargs.get("outbox_ids"))
            )
            return SimpleNamespace(
                created_count=int(self.calls == 1),
                updated_count=int(self.calls >= 2),
            )

    class ProfileEnrichment:
        async def enrich(self, **kwargs):
            events.append(("profile-enrichment", kwargs["shop_id"]))
            return SimpleNamespace(enriched_count=1)

    class Notifications:
        async def list_due(self, **kwargs):
            events.append(("notification-query", kwargs["shop_id"]))
            return [(tenant_id, event_id, 0)]

        async def deliver(self, actual_tenant_id, actual_event_id):
            events.append(("notification", actual_event_id))
            assert actual_tenant_id == tenant_id
            return "sent"

    class CooperationPrecheck:
        async def evaluate(self, _tenant_id, **kwargs):
            events.append(("cooperation-evaluate", kwargs["shop_id"]))

        async def complete_due(self, _tenant_id, shop_id):
            events.append(("cooperation-complete", shop_id))

    result = await SampleShopPipelineService(
        Source(),
        Feishu(),
        Notifications(),
        AutoAssignments(),
        AutoAssignmentProjection(),
        AssignmentRecords(),
        ProfileEnrichment(),
        cooperation_precheck=CooperationPrecheck(),
    ).run(
        tenant_id,
        shop_id,
        mode="active",
        statuses=["PENDING", "SHIPPED"],
    )

    assert result.feishu_result == "feishu-result"
    assert result.status == "succeeded"
    assert result.source_type == "official_api"
    assert result.auto_assignment_result.status == "succeeded"
    assert result.auto_assignment_projection_result.updated_count == 1
    assert result.profile_enrichment_result.enriched_count == 1
    assert result.assignment_record_result.updated_count == 1
    assert result.notification_results == ("sent",)
    assert auto_assignment_scopes == [frozenset({source_application_id})]
    assert assignment_record_scopes == [
        (frozenset({assigned_application_id}), None),
        (None, frozenset({event_id})),
        (None, frozenset({event_id})),
    ]
    assert events == [
        ("source", "PENDING"),
        ("source", "SHIPPED"),
        ("cooperation-evaluate", shop_id),
        ("feishu", shop_id),
        ("cooperation-complete", shop_id),
        ("auto-assignment", shop_id),
        ("auto-assignment-projection", shop_id, None),
        ("assignment-records", shop_id),
        ("profile-enrichment", shop_id),
        ("feishu", shop_id),
        ("auto-assignment-projection", shop_id, True),
        ("notification-query", shop_id),
        ("assignment-records", shop_id),
        ("notification", event_id),
        ("assignment-records", shop_id),
    ]


@pytest.mark.asyncio
async def test_each_notification_immediately_refreshes_its_assignment_record() -> None:
    tenant_id, shop_id = uuid4(), uuid4()
    first_event_id, second_event_id = uuid4(), uuid4()
    events = []

    class Feishu:
        async def sync(self, **_kwargs):
            return "feishu-result"

    class AutoAssignments:
        async def run_for_shop(self, **_kwargs):
            return SimpleNamespace(status="succeeded", items=())

    class Projection:
        async def sync(self, **_kwargs):
            return SimpleNamespace(updated_count=0)

    class AssignmentRecords:
        async def sync(self, **kwargs):
            outbox_ids = kwargs.get("outbox_ids")
            if outbox_ids:
                events.append(("assignment-record", tuple(outbox_ids)))
            return SimpleNamespace(created_count=0, updated_count=1)

    class ProfileEnrichment:
        async def enrich(self, **_kwargs):
            return SimpleNamespace(enriched_count=0)

    class Notifications:
        async def list_due(self, **_kwargs):
            return [
                (tenant_id, first_event_id, 0),
                (tenant_id, second_event_id, 0),
            ]

        async def deliver(self, _tenant_id, event_id):
            events.append(("notification", event_id))
            return SimpleNamespace(status="sent")

    await SampleShopPipelineService(
        object(),
        Feishu(),
        Notifications(),
        AutoAssignments(),
        Projection(),
        AssignmentRecords(),
        ProfileEnrichment(),
    ).complete_after_source(
        tenant_id=tenant_id,
        shop_id=shop_id,
        source_type="hubstudio_cdp",
    )

    assert events == [
        ("assignment-record", (first_event_id,)),
        ("notification", first_event_id),
        ("assignment-record", (first_event_id,)),
        ("assignment-record", (second_event_id,)),
        ("notification", second_event_id),
        ("assignment-record", (second_event_id,)),
    ]


@pytest.mark.asyncio
async def test_profile_capture_runs_before_assignment_and_enrichment_failure() -> None:
    tenant_id, shop_id = uuid4(), uuid4()
    events = []

    class Feishu:
        async def sync(self, **_kwargs):
            events.append("feishu")

    class AutoAssignments:
        async def run_for_shop(self, **_kwargs):
            events.append("auto-assignment")
            return SimpleNamespace(status="succeeded")

    class Projection:
        async def sync(self, **_kwargs):
            events.append("projection")

    class AssignmentRecords:
        async def sync(self, **_kwargs):
            events.append("assignment-records")

    class ProfileEnrichment:
        async def enrich(self, **_kwargs):
            events.append("profile-enrichment")
            raise RuntimeError("profile unavailable")

    service = SampleShopPipelineService(
        object(),
        Feishu(),
        auto_assignments=AutoAssignments(),
        auto_assignment_projection=Projection(),
        assignment_records=AssignmentRecords(),
        profile_enrichment=ProfileEnrichment(),
    )

    async def profile_capture():
        events.append("profile-capture")

    with pytest.raises(RuntimeError, match="profile unavailable"):
        await service.complete_after_source(
            tenant_id=tenant_id,
            shop_id=shop_id,
            source_type="hubstudio_cdp",
            profile_capture=profile_capture,
        )

    assert events == [
        "feishu",
        "profile-capture",
        "auto-assignment",
        "projection",
        "assignment-records",
        "profile-enrichment",
    ]


@pytest.mark.asyncio
async def test_pipeline_completes_hubstudio_capture_without_running_source() -> None:
    tenant_id, shop_id = uuid4(), uuid4()
    events = []

    class Source:
        async def sync(self, *_args, **_kwargs):
            raise AssertionError("HubStudio source was already committed")

    class Feishu:
        async def sync(self, **kwargs):
            events.append(("feishu", kwargs["shop_id"]))
            return "feishu-result"

    result = await SampleShopPipelineService(Source(), Feishu()).complete_after_source(
        tenant_id=tenant_id,
        shop_id=shop_id,
        source_type="hubstudio_cdp",
    )

    assert result.status == "succeeded"
    assert result.source_type == "hubstudio_cdp"
    assert result.source_results == ()
    assert result.feishu_result == "feishu-result"
    assert events == [("feishu", shop_id)]


@pytest.mark.asyncio
async def test_hubstudio_pipeline_deletes_confirmed_group_children() -> None:
    tenant_id, shop_id = uuid4(), uuid4()
    events = []

    class Feishu:
        async def sync(self, **_kwargs):
            events.append("feishu")
            return "feishu-result"

    async def group_cleanup(**kwargs):
        events.append(("group-cleanup", kwargs))

    await SampleShopPipelineService(
        object(),
        Feishu(),
        group_cleanup=group_cleanup,
    ).complete_after_source(
        tenant_id=tenant_id,
        shop_id=shop_id,
        source_type="hubstudio_cdp",
        source_results=(
            SimpleNamespace(
                application_ids=(),
                obsolete_platform_application_ids=frozenset({"child-1"}),
            ),
        ),
    )

    assert events == [
        "feishu",
        (
            "group-cleanup",
            {
                "tenant_id": tenant_id,
                "shop_id": shop_id,
                "obsolete_platform_application_ids": frozenset({"child-1"}),
            },
        ),
    ]


@pytest.mark.asyncio
async def test_group_assignment_is_migrated_before_feishu_and_notified_again() -> None:
    tenant_id, shop_id = uuid4(), uuid4()
    parent_id = uuid4()
    events = []
    assignment_scopes = []

    class GroupAssignments:
        async def migrate(self, **kwargs):
            events.append(("group-assignment", kwargs["obsolete_platform_application_ids"]))
            return frozenset({parent_id})

    class Feishu:
        async def sync(self, **_kwargs):
            events.append("feishu")
            return "feishu-result"

    class AutoAssignments:
        async def run_for_shop(self, **_kwargs):
            events.append("auto-assignment")
            return SimpleNamespace(status="succeeded", items=())

    class Projection:
        async def sync(self, **_kwargs):
            events.append("projection")
            return SimpleNamespace(updated_count=1)

    class AssignmentRecords:
        async def sync(self, **kwargs):
            events.append("assignment-records")
            assignment_scopes.append(kwargs.get("application_ids"))
            return SimpleNamespace(created_count=0, updated_count=1)

    class ProfileEnrichment:
        async def enrich(self, **_kwargs):
            return SimpleNamespace(enriched_count=0)

    class Notifications:
        async def list_due(self, **_kwargs):
            return []

    await SampleShopPipelineService(
        object(),
        Feishu(),
        Notifications(),
        AutoAssignments(),
        Projection(),
        AssignmentRecords(),
        ProfileEnrichment(),
        group_assignment_migration=GroupAssignments(),
    ).complete_after_source(
        tenant_id=tenant_id,
        shop_id=shop_id,
        source_type="hubstudio_cdp",
        source_results=(
            SimpleNamespace(
                application_ids=(parent_id,),
                obsolete_platform_application_ids=frozenset({"child-1"}),
            ),
        ),
    )

    assert events[:4] == [
        ("group-assignment", frozenset({"child-1"})),
        "feishu",
        "auto-assignment",
        "projection",
    ]
    assert assignment_scopes == [frozenset({parent_id})]


@pytest.mark.asyncio
async def test_official_pipeline_limits_feishu_sync_to_observed_applications() -> None:
    tenant_id, shop_id = uuid4(), uuid4()
    application_ids = (uuid4(), uuid4())
    feishu_scopes = []

    class Source:
        async def sync(self, *_args, **_kwargs):
            return SimpleNamespace(
                status="succeeded",
                application_ids=application_ids,
            )

    class Feishu:
        async def sync(self, **kwargs):
            feishu_scopes.append(kwargs.get("application_ids"))
            return "feishu-result"

    result = await SampleShopPipelineService(Source(), Feishu()).run(
        tenant_id,
        shop_id,
        mode="active",
        statuses=["PENDING"],
    )

    assert result.status == "succeeded"
    assert feishu_scopes == [frozenset(application_ids)]


@pytest.mark.asyncio
async def test_pipeline_stops_before_feishu_when_source_is_incomplete() -> None:
    calls = []

    class Source:
        async def sync(self, *_args, **_kwargs):
            return SimpleNamespace(status="partial")

    class Feishu:
        async def sync(self, **_kwargs):
            calls.append("feishu")

    with pytest.raises(RuntimeError, match="incomplete"):
        await SampleShopPipelineService(Source(), Feishu()).run(
            uuid4(),
            uuid4(),
            mode="full",
            statuses=[None],
        )

    assert calls == []


@pytest.mark.asyncio
async def test_pipeline_stops_after_initial_feishu_when_assignment_is_not_ready() -> (
    None
):
    calls = []

    class Source:
        async def sync(self, *_args, **_kwargs):
            return SimpleNamespace(status="succeeded")

    class AutoAssignments:
        async def run_for_shop(self, **_kwargs):
            return SimpleNamespace(status="blocked")

    class Feishu:
        async def sync(self, **_kwargs):
            calls.append("feishu")

    class Projection:
        async def sync(self, **_kwargs):
            calls.append("projection")

    with pytest.raises(RuntimeError, match="not ready"):
        await SampleShopPipelineService(
            Source(),
            Feishu(),
            auto_assignments=AutoAssignments(),
            auto_assignment_projection=Projection(),
            assignment_records=Projection(),
            profile_enrichment=Projection(),
        ).run(
            uuid4(),
            uuid4(),
            mode="full",
            statuses=[None],
        )

    assert calls == ["feishu"]


def test_pipeline_requires_assignment_and_projection_to_be_paired() -> None:
    with pytest.raises(ValueError, match="must be paired"):
        SampleShopPipelineService(object(), object(), auto_assignments=object())


@pytest.mark.asyncio
async def test_pipeline_dry_run_has_no_side_effects_for_either_source() -> None:
    class Unexpected:
        async def sync(self, *_args, **_kwargs):
            raise AssertionError("dry-run must not call external services")

    service = SampleShopPipelineService(Unexpected(), Unexpected())
    for source_type in ("official_api", "hubstudio_cdp"):
        result = await service.run(
            uuid4(),
            uuid4(),
            mode="full",
            statuses=[None],
            source_type=source_type,
            dry_run=True,
        )
        assert result.status == "dry_run"
        assert result.source_type == source_type


@pytest.mark.asyncio
async def test_pipeline_rejects_direct_hubstudio_execution() -> None:
    service = SampleShopPipelineService(object(), object())

    with pytest.raises(RuntimeError, match="explicitly bound listener"):
        await service.run(
            uuid4(),
            uuid4(),
            mode="full",
            statuses=[None],
            source_type="hubstudio_cdp",
            dry_run=False,
        )
