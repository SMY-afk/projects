from decimal import Decimal

from sqlalchemy import ForeignKeyConstraint

from erp_api.models.sample_application import SampleApplication
from erp_api.models.sample_application_event import SampleApplicationEvent
from erp_api.models.sample_application_workflow import SampleApplicationWorkflow


def test_sample_application_tables_are_registered() -> None:
    assert SampleApplication.__table__.name == "sample_applications"
    assert SampleApplicationWorkflow.__table__.name == "sample_application_workflows"
    assert SampleApplicationEvent.__table__.name == "sample_application_events"


def test_sample_application_unique_key_is_shop_scoped() -> None:
    constraint = next(
        constraint
        for constraint in SampleApplication.__table__.constraints
        if constraint.name == "uq_sample_applications_tenant_shop_platform_id"
    )
    assert tuple(column.name for column in constraint.columns) == (
        "tenant_id",
        "shop_id",
        "platform_application_id",
    )


def test_sample_application_stores_creator_gmv_and_level() -> None:
    assert SampleApplication.creator_gmv_minor.type.python_type is int
    assert SampleApplication.creator_gmv_currency.type.length == 3
    assert SampleApplication.creator_level.type.length == 2


def test_sample_application_stores_visible_creator_performance() -> None:
    assert SampleApplication.creator_content_count.type.python_type is int
    assert SampleApplication.creator_ec_video_view.type.python_type is int
    assert SampleApplication.creator_units_sold.type.python_type is int
    assert SampleApplication.creator_fulfillment_percentage.type.python_type is Decimal
    assert SampleApplication.creator_pps.type.python_type is Decimal
    assert SampleApplication.creator_rating.type.python_type is Decimal


def test_sample_application_stores_safe_creator_profile_references() -> None:
    columns = SampleApplication.__table__.columns

    assert columns["creator_avatar_object_key"].type.python_type is str
    assert columns["creator_avatar_source_hash"].type.length == 64
    assert columns["creator_avatar_observed_at"].type.timezone is True
    assert columns["creator_profile_snapshot"].type.python_type is dict
    assert columns["creator_profile_observed_at"].type.timezone is True
    assert "creator_avatar_url" not in columns


def test_sample_application_preserves_first_and_last_seen_timestamps() -> None:
    columns = SampleApplication.__table__.columns

    assert columns["first_seen_at"].nullable is False
    assert columns["first_seen_at"].type.timezone is True
    assert columns["last_seen_at"].nullable is False
    assert columns["last_seen_at"].type.timezone is True


def test_sample_application_stores_nullable_tiktok_application_time() -> None:
    column = SampleApplication.__table__.columns["tiktok_applied_at"]

    assert column.nullable is True
    assert column.type.timezone is True


def test_sample_application_stores_grouped_product_projection() -> None:
    columns = SampleApplication.__table__.columns

    assert columns["product_id"].type.python_type is str
    assert columns["product_id"].type.length is None
    assert columns["sku_id"].type.length is None
    assert columns["product_image_urls"].type.python_type is dict
    assert columns["product_image_urls"].nullable is False
    assert columns["is_current_projection"].type.python_type is bool
    assert columns["is_current_projection"].nullable is False


def test_sample_application_source_capture_is_shop_scoped() -> None:
    columns = SampleApplication.__table__.columns
    constraint = next(
        constraint
        for constraint in SampleApplication.__table__.constraints
        if constraint.name == "fk_sample_applications_source_capture_scope"
    )

    assert columns["source_capture_id"].nullable is True
    assert isinstance(constraint, ForeignKeyConstraint)
    assert tuple(element.parent.name for element in constraint.elements) == (
        "source_capture_id",
        "tenant_id",
        "shop_id",
    )
