from pathlib import Path

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from erp_api.models.sample_application_event import SampleApplicationEvent
from erp_api.models.sample_notification_outbox import SampleNotificationOutbox


def _constraint_names(model: type, constraint_type: type) -> set[str | None]:
    return {
        constraint.name
        for constraint in model.__table__.constraints
        if isinstance(constraint, constraint_type)
    }


def test_sample_notification_outbox_has_tenant_safe_idempotency() -> None:
    unique_names = _constraint_names(SampleNotificationOutbox, UniqueConstraint)
    check_names = _constraint_names(SampleNotificationOutbox, CheckConstraint)

    assert "uq_sample_notification_outbox_assignment_recipient" in unique_names
    assert "ck_sample_notification_outbox_status" in check_names
    assert "ck_sample_notification_outbox_assignment_version" in check_names
    assert "ck_sample_notification_outbox_attempt_count" in check_names
    assert isinstance(SampleNotificationOutbox.payload.type, JSONB)


def test_sample_notification_outbox_cannot_cross_shop_or_application_tenant() -> None:
    foreign_keys = {
        tuple(element.parent.name for element in constraint.elements)
        for constraint in SampleNotificationOutbox.__table__.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }

    assert ("tenant_id",) in foreign_keys
    assert ("shop_id", "tenant_id") in foreign_keys
    assert ("sample_application_id", "tenant_id") in foreign_keys


def test_sample_event_idempotency_is_tenant_and_shop_scoped() -> None:
    constraint = next(
        constraint
        for constraint in SampleApplicationEvent.__table__.constraints
        if constraint.name
        == "uq_sample_application_events_tenant_shop_source_external"
    )

    assert tuple(column.name for column in constraint.columns) == (
        "tenant_id",
        "shop_id",
        "event_source",
        "external_event_id",
    )
    assert isinstance(SampleApplicationEvent.before_data.type, JSONB)
    assert isinstance(SampleApplicationEvent.after_data.type, JSONB)


def test_sample_event_migration_enforces_append_only() -> None:
    migration = Path(
        "migrations/versions/9bf2a3b4c5d6_add_sample_notification_outbox.py"
    ).read_text(encoding="utf-8")

    assert "trg_sample_application_events_append_only" in migration
    assert "BEFORE UPDATE OR DELETE" in migration
    assert "DROP TRIGGER IF EXISTS" in migration
