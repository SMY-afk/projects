from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from erp_api.services.sample_creator_profile_realtime import (
    apply_latest_creator_profile,
    pending_creator_sample_applications_statement,
)


def test_pending_application_query_requires_shop_open_id_and_username() -> None:
    statement = pending_creator_sample_applications_statement(
        tenant_id=uuid4(),
        shop_id=uuid4(),
        creator_open_id="creator-open-id",
        creator_username="@Creator_Name",
    )

    sql = str(statement)
    for required in (
        "tenant_id",
        "shop_id",
        "platform_status",
        "creator_open_id",
        "creator_username",
    ):
        assert required in sql


def test_latest_complete_details_are_applied_to_every_pending_sample() -> None:
    observed_at = datetime(2026, 9, 11, 3, tzinfo=UTC)
    creator = SimpleNamespace(
        extensions={
            "creator_details_summary": {
                "observed_at": observed_at.isoformat(),
                "sources": {
                    name: {}
                    for name in (
                        "profile",
                        "performance",
                        "followers",
                        "trends",
                        "examples",
                    )
                },
                "profile_snapshot": {
                    "schema_version": 2,
                    "audience": {"gender": [{"label": "女性", "share_bps": 7000}]},
                },
            }
        }
    )
    applications = [_application(), _application()]

    updated = apply_latest_creator_profile(applications, creator)

    assert updated == 2
    assert all(
        item.creator_profile_snapshot["creator_details_complete"] is True
        for item in applications
    )
    assert all(item.creator_profile_observed_at == observed_at for item in applications)


def test_latest_details_backfill_missing_assignment_gmv_and_level() -> None:
    observed_at = datetime(2026, 9, 21, 2, tzinfo=UTC)
    creator = SimpleNamespace(
        extensions={
            "creator_details_summary": {
                "observed_at": observed_at.isoformat(),
                "sources": {
                    name: {}
                    for name in (
                        "profile",
                        "performance",
                        "followers",
                        "trends",
                        "examples",
                    )
                },
                "profile_snapshot": {
                    "schema_version": 2,
                    "sales": {"gmv_minor": 2_470_000},
                },
            }
        }
    )
    application = _application()
    application.creator_gmv_minor = None
    application.creator_gmv_currency = "USD"
    application.creator_level = None

    updated = apply_latest_creator_profile([application], creator)

    assert updated == 1
    assert application.creator_gmv_minor == 2_470_000
    assert application.creator_gmv_currency == "USD"
    assert application.creator_level == "L2"


def _application():
    return SimpleNamespace(
        creator_gmv_minor=100,
        creator_gmv_currency="USD",
        creator_level="L0",
        creator_units_sold=2,
        creator_fulfillment_percentage=None,
        creator_content_count=3,
        creator_ec_video_view=4,
        follower_count=5,
        creator_profile_snapshot=None,
        creator_profile_source_type=None,
        creator_profile_observed_at=None,
    )
