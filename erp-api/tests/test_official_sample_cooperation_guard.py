import pytest
from sqlalchemy import create_engine, literal, select

from erp_api.models.sample_application import SampleApplication
from erp_api.models.sample_application_workflow import SampleApplicationWorkflow
from erp_api.services.sample_official_cooperation_guard import (
    official_sample_cooperation_condition,
)


@pytest.mark.parametrize(
    "source,kind,record,event,event_shop,event_application,expected",
    [
        ("official_api", "free", None, None, "shop", "app", False),
        (
            "official_api",
            "free",
            None,
            "sample_cooperation_allowed",
            "shop",
            "app",
            True,
        ),
        (
            "official_api",
            "free",
            None,
            "sample_cooperation_exception",
            "shop",
            "app",
            False,
        ),
        (
            "official_api",
            "free",
            None,
            "sample_cooperation_allowed",
            "other",
            "app",
            False,
        ),
        (
            "official_api",
            "free",
            None,
            "sample_cooperation_allowed",
            "shop",
            "other",
            False,
        ),
        ("official_api", "free", "existing", None, "shop", "app", True),
        ("hubstudio_cdp", "free", None, None, "shop", "app", True),
        ("official_api", "refundable", None, None, "shop", "app", True),
    ],
)
def test_new_official_samples_need_an_exact_precheck(
    source, kind, record, event, event_shop, event_application, expected
):
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as c:
            c.exec_driver_sql(
                "CREATE TABLE sample_applications (id TEXT, tenant_id TEXT, shop_id TEXT, source_type TEXT, sample_type TEXT)"
            )
            c.exec_driver_sql(
                "CREATE TABLE sample_application_workflows (sample_application_id TEXT, feishu_record_id TEXT)"
            )
            c.exec_driver_sql(
                "CREATE TABLE sample_application_events (id TEXT, tenant_id TEXT, shop_id TEXT, sample_application_id TEXT, event_source TEXT, event_type TEXT)"
            )
            c.exec_driver_sql(
                "INSERT INTO sample_applications VALUES ('app','tenant','shop',?,?)",
                (source, kind),
            )
            c.exec_driver_sql(
                "INSERT INTO sample_application_workflows VALUES ('app',?)", (record,)
            )
            if event:
                c.exec_driver_sql(
                    "INSERT INTO sample_application_events VALUES ('event','tenant',?,?,'feishu_cooperation_precheck',?)",
                    (event_shop, event_application, event),
                )
            query = (
                select(literal(1))
                .select_from(SampleApplication)
                .join(
                    SampleApplicationWorkflow,
                    SampleApplicationWorkflow.sample_application_id
                    == SampleApplication.id,
                )
                .where(official_sample_cooperation_condition())
            )
            assert (c.execute(query).first() is not None) is expected
    finally:
        engine.dispose()
