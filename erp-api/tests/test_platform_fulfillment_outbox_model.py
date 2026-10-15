from sqlalchemy import CheckConstraint, UniqueConstraint

from erp_api.models.platform_fulfillment_outbox import PlatformFulfillmentOutbox


def test_outbox_has_tenant_idempotency_and_status_constraints() -> None:
    table = PlatformFulfillmentOutbox.__table__
    unique_names = {
        item.name for item in table.constraints if isinstance(item, UniqueConstraint)
    }
    check_names = {
        item.name for item in table.constraints if isinstance(item, CheckConstraint)
    }

    assert "uq_platform_fulfillment_outbox_tenant_key" in unique_names
    assert "ck_platform_fulfillment_outbox_status" in check_names
    assert "ck_platform_fulfillment_outbox_attempts" in check_names
    assert table.c.version_id.nullable is False
