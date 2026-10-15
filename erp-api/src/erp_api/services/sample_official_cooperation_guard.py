"""Do not create an official sample row before its cooperation check succeeds."""

from sqlalchemy import or_, select

from erp_api.models.sample_application import SampleApplication
from erp_api.models.sample_application_event import SampleApplicationEvent
from erp_api.models.sample_application_workflow import SampleApplicationWorkflow
from erp_api.services.sample_cooperation_rules import (
    COOPERATION_DECISION_EVENTS,
    COOPERATION_EVENT_SOURCE,
    COOPERATION_EXCEPTION_EVENT,
)


def official_sample_cooperation_condition():
    checked = (
        select(SampleApplicationEvent.id)
        .where(
            SampleApplicationEvent.tenant_id == SampleApplication.tenant_id,
            SampleApplicationEvent.shop_id == SampleApplication.shop_id,
            SampleApplicationEvent.sample_application_id == SampleApplication.id,
            SampleApplicationEvent.event_source == COOPERATION_EVENT_SOURCE,
            SampleApplicationEvent.event_type.in_(
                COOPERATION_DECISION_EVENTS - {COOPERATION_EXCEPTION_EVENT}
            ),
        )
        .exists()
    )
    return or_(
        SampleApplication.source_type != "official_api",
        SampleApplication.sample_type != "free",
        SampleApplicationWorkflow.feishu_record_id.is_not(None),
        checked,
    )
