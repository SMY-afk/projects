from datetime import UTC, datetime
from uuid import uuid4

from erp_api.models.sample_application import SampleApplication
from erp_api.models.sample_application_workflow import SampleApplicationWorkflow
from erp_api.models.sample_notification_outbox import SampleNotificationOutbox
from erp_api.services.sample_group_assignment_migration import (
    GroupAssignmentBlocked,
    GroupAssignmentCandidate,
    apply_group_assignment_migration,
)


def _application(*, current: bool) -> SampleApplication:
    return SampleApplication(
        id=uuid4(),
        tenant_id=uuid4(),
        shop_id=uuid4(),
        platform_application_id=str(uuid4()),
        source_type="hubstudio_cdp",
        platform_status="PENDING",
        raw_payload={},
        source_observed_at=datetime(2026, 9, 20, tzinfo=UTC),
        is_current_projection=current,
    )


def _workflow(application: SampleApplication, *, bd: str | None, version: int):
    return SampleApplicationWorkflow(
        id=uuid4(),
        tenant_id=application.tenant_id,
        shop_id=application.shop_id,
        sample_application_id=application.id,
        assigned_bd_name=bd,
        assignment_version=version,
        assigned_at=datetime(2026, 9, 20, 1, tzinfo=UTC) if bd else None,
        processing_status="待处理" if bd else None,
    )


def _outbox(
    application: SampleApplication,
    *,
    version: int,
    record_id: str,
    status: str = "sent",
):
    return SampleNotificationOutbox(
        id=uuid4(),
        tenant_id=application.tenant_id,
        shop_id=application.shop_id,
        sample_application_id=application.id,
        assignment_version=version,
        recipient_open_id="ou_test",
        payload={
            "assigned_bd_name": "example-24ffed966710",
            "assignment_record_id": record_id,
            "source_event_id": "bd-auto:test:event",
        },
        status=status,
        sent_at=(
            datetime(2026, 9, 20, 1, 5, tzinfo=UTC)
            if status == "sent"
            else None
        ),
    )


def test_moves_sent_child_assignment_to_unassigned_group_parent() -> None:
    parent = _application(current=True)
    child = _application(current=False)
    parent_workflow = _workflow(parent, bd=None, version=0)
    child_workflow = _workflow(child, bd="example-24ffed966710", version=1)
    child_outbox = _outbox(child, version=1, record_id="rec_assignment")

    result = apply_group_assignment_migration(
        parent,
        parent_workflow,
        parent_outbox=None,
        child_candidates=(
            GroupAssignmentCandidate(child, child_workflow, child_outbox),
        ),
    )

    assert result is not None
    assert result.canonical_outbox is child_outbox
    assert parent_workflow.assigned_bd_name == "example-24ffed966710"
    assert parent_workflow.assignment_version == 1
    assert child_outbox.sample_application_id == parent.id
    assert child_outbox.assignment_version == 1
    assert child_outbox.status == "sent"
    assert child_outbox.payload["assignment_record_id"] == "rec_assignment"
    assert child_outbox.payload["group_migrated_from_application_id"] == str(child.id)


def test_keeps_existing_parent_outbox_and_cancels_same_bd_child() -> None:
    parent = _application(current=True)
    child = _application(current=False)
    parent_workflow = _workflow(parent, bd="example-24ffed966710", version=2)
    child_workflow = _workflow(child, bd="example-24ffed966710", version=1)
    parent_outbox = _outbox(parent, version=2, record_id="rec_assignment")
    child_outbox = _outbox(child, version=1, record_id="rec_assignment")

    result = apply_group_assignment_migration(
        parent,
        parent_workflow,
        parent_outbox=parent_outbox,
        child_candidates=(
            GroupAssignmentCandidate(child, child_workflow, child_outbox),
        ),
    )

    assert result is not None
    assert result.canonical_outbox is parent_outbox
    assert child_outbox.status == "cancelled"
    assert child_outbox.last_error_code == "superseded_group_assignment"
    assert parent_outbox.payload["assignment_record_id"] == "rec_assignment"


def test_aligns_existing_parent_outbox_to_current_assignment_version() -> None:
    parent = _application(current=True)
    child = _application(current=False)
    parent_workflow = _workflow(parent, bd="bd-a", version=4)
    child_workflow = _workflow(child, bd="bd-a", version=3)
    parent_outbox = _outbox(parent, version=2, record_id="rec_assignment")
    child_outbox = _outbox(child, version=3, record_id="rec_assignment")

    result = apply_group_assignment_migration(
        parent,
        parent_workflow,
        parent_outbox=parent_outbox,
        child_candidates=(
            GroupAssignmentCandidate(child, child_workflow, child_outbox),
        ),
    )

    assert result is not None
    assert parent_outbox.assignment_version == 4
    assert child_outbox.status == "cancelled"


def test_blocks_group_when_different_bds_both_have_delivery_evidence() -> None:
    parent = _application(current=True)
    first = _application(current=False)
    second = _application(current=False)
    parent_workflow = _workflow(parent, bd=None, version=0)
    first_workflow = _workflow(first, bd="example-24ffed966710", version=1)
    second_workflow = _workflow(second, bd="example-2b3220d55335", version=1)
    first_outbox = _outbox(first, version=1, record_id="rec_assignment")
    second_outbox = _outbox(second, version=1, record_id="rec_assignment")
    second_outbox.payload = {**second_outbox.payload, "assigned_bd_name": "example-2b3220d55335"}

    result = apply_group_assignment_migration(
        parent,
        parent_workflow,
        parent_outbox=None,
        child_candidates=(
            GroupAssignmentCandidate(first, first_workflow, first_outbox),
            GroupAssignmentCandidate(second, second_workflow, second_outbox),
        ),
    )

    assert isinstance(result, GroupAssignmentBlocked)
    assert result.reason == "multiple_delivered_bds"
    assert first_outbox.status == "sent"
    assert second_outbox.status == "sent"


def test_keeps_delivered_parent_when_different_child_has_no_evidence() -> None:
    parent = _application(current=True)
    child = _application(current=False)
    parent_workflow = _workflow(parent, bd="example-f1a9c17dfce3", version=2)
    child_workflow = _workflow(child, bd="example-f667fc1c0974", version=1)
    parent_outbox = _outbox(parent, version=2, record_id="rec_assignment")
    child_outbox = _outbox(
        child,
        version=1,
        record_id="rec_assignment",
        status="pending",
    )

    result = apply_group_assignment_migration(
        parent,
        parent_workflow,
        parent_outbox=parent_outbox,
        child_candidates=(
            GroupAssignmentCandidate(child, child_workflow, child_outbox),
        ),
    )

    assert result is not None
    assert not isinstance(result, GroupAssignmentBlocked)
    assert result.canonical_outbox is parent_outbox
    assert parent_workflow.assigned_bd_name == "example-f1a9c17dfce3"
    assert child_outbox.status == "cancelled"


def test_keeps_earliest_delivered_child_when_parent_has_no_evidence() -> None:
    parent = _application(current=True)
    child = _application(current=False)
    parent_workflow = _workflow(parent, bd="example-f1a9c17dfce3", version=2)
    child_workflow = _workflow(child, bd="example-f667fc1c0974", version=1)
    parent_outbox = _outbox(
        parent,
        version=2,
        record_id="rec_assignment",
        status="pending",
    )
    child_outbox = _outbox(child, version=1, record_id="rec_assignment")

    result = apply_group_assignment_migration(
        parent,
        parent_workflow,
        parent_outbox=parent_outbox,
        child_candidates=(
            GroupAssignmentCandidate(child, child_workflow, child_outbox),
        ),
    )

    assert result is not None
    assert not isinstance(result, GroupAssignmentBlocked)
    assert result.canonical_outbox is child_outbox
    assert parent_workflow.assigned_bd_name == "example-f667fc1c0974"
    assert parent_outbox.status == "cancelled"


def test_blocks_different_bds_when_no_record_has_delivery_evidence() -> None:
    parent = _application(current=True)
    child = _application(current=False)
    parent_workflow = _workflow(parent, bd="example-f1a9c17dfce3", version=2)
    child_workflow = _workflow(child, bd="example-f667fc1c0974", version=1)
    parent_outbox = _outbox(
        parent,
        version=2,
        record_id="rec_assignment",
        status="pending",
    )
    child_outbox = _outbox(
        child,
        version=1,
        record_id="rec_assignment",
        status="pending",
    )

    result = apply_group_assignment_migration(
        parent,
        parent_workflow,
        parent_outbox=parent_outbox,
        child_candidates=(
            GroupAssignmentCandidate(child, child_workflow, child_outbox),
        ),
    )

    assert isinstance(result, GroupAssignmentBlocked)
    assert result.reason == "no_delivery_evidence"
    assert parent_outbox.status == "pending"
    assert child_outbox.status == "pending"
