from sqlalchemy import CheckConstraint, UniqueConstraint

from erp_api.db.base import Base
from erp_api.models.logistics_tracking_event import LogisticsTrackingEvent  # noqa: F401


def test_tracking_event_has_tenant_dedupe_and_status_constraints() -> None:
    table = Base.metadata.tables["logistics_tracking_events"]
    unique_names = {
        item.name for item in table.constraints if isinstance(item, UniqueConstraint)
    }
    check_names = {
        item.name for item in table.constraints if isinstance(item, CheckConstraint)
    }

    assert "uq_logistics_tracking_events_dedupe" in unique_names
    assert "uq_logistics_tracking_events_id_tenant" in unique_names
    assert "ck_logistics_tracking_events_status" in check_names
    assert "ck_logistics_tracking_events_source" in check_names
