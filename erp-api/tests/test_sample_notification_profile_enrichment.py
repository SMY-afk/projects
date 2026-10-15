from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from erp_api.services.sample_notification_profile_enrichment import (
    SampleNotificationProfileEnrichmentService,
    _requeue_profile_event,
    build_notification_profile_snapshot,
)


class _Result:
    def scalars(self):
        return self

    def unique(self):
        return ()


class _Session:
    statement = None

    async def execute(self, statement):
        self.statement = statement
        return _Result()


class _Database:
    def __init__(self):
        self.session = _Session()

    @asynccontextmanager
    async def system_session_factory(self):
        yield self.session


def _application(**values):
    defaults = {
        "creator_gmv_minor": None,
        "creator_units_sold": None,
        "creator_fulfillment_percentage": None,
        "creator_content_count": None,
        "creator_ec_video_view": None,
        "follower_count": None,
        "creator_profile_snapshot": None,
    }
    return SimpleNamespace(**{**defaults, **values})


def test_builds_real_profile_from_sample_summary_without_inventing_window() -> None:
    snapshot = build_notification_profile_snapshot(
        _application(
            creator_gmv_minor=850_000,
            creator_units_sold=167,
            creator_fulfillment_percentage=Decimal("97.35"),
            creator_content_count=86,
            creator_ec_video_view=7_200,
            follower_count=72_000,
        )
    )

    assert snapshot == {
        "schema_version": 2,
        "sales": {"gmv_minor": 850_000, "units_sold": 167},
        "cooperation": {"estimated_post_rate_bps": 9_735},
        "video": {"count": 86, "average_view_count": 7_200},
        "trends": {
            "gmv_minor": 850_000,
            "units_sold": 167,
            "followers": 72_000,
        },
    }


def test_ignores_affiliate_report_outside_sample_request_scope() -> None:
    observed_at = datetime(2026, 9, 10, 3, tzinfo=UTC)
    metric = SimpleNamespace(
        affiliate_gmv_minor=1_000_000,
        items_sold=240,
        affiliate_order_count=180,
        average_order_amount_minor=5_556,
        showcase_product_count=18,
        affiliate_video_gmv_minor=600_000,
        affiliate_video_count=40,
        affiliate_live_gmv_minor=300_000,
        affiliate_live_count=6,
        affiliate_showcase_gmv_minor=100_000,
        affiliate_follower_count=90_000,
    )
    report = SimpleNamespace(
        window_start_utc=datetime(2026, 8, 11, tzinfo=UTC),
        window_end_utc=observed_at,
        shop_timezone="America/Los_Angeles",
        captured_at=observed_at,
        source_kind="page_capture",
    )

    assert build_notification_profile_snapshot(
        _application(),
        SimpleNamespace(metric=metric, report=report),
    ) is None


def test_sample_summary_takes_precedence_over_older_affiliate_metric() -> None:
    metric = SimpleNamespace(
        affiliate_gmv_minor=100,
        items_sold=2,
        affiliate_order_count=None,
        average_order_amount_minor=None,
        showcase_product_count=None,
        affiliate_video_gmv_minor=None,
        affiliate_video_count=3,
        affiliate_live_gmv_minor=None,
        affiliate_live_count=None,
        affiliate_showcase_gmv_minor=None,
        affiliate_follower_count=4,
    )
    report = SimpleNamespace(
        window_start_utc=datetime(2026, 8, 1, tzinfo=UTC),
        window_end_utc=datetime(2026, 9, 1, tzinfo=UTC),
        shop_timezone="UTC",
    )

    snapshot = build_notification_profile_snapshot(
        _application(
            creator_gmv_minor=900,
            creator_units_sold=20,
            creator_content_count=30,
            follower_count=40,
        ),
        SimpleNamespace(metric=metric, report=report),
    )

    assert snapshot["sales"]["gmv_minor"] == 900
    assert snapshot["sales"]["units_sold"] == 20
    assert snapshot["video"]["count"] == 30
    assert snapshot["trends"]["followers"] == 40


def test_returns_none_when_no_real_profile_metric_exists() -> None:
    assert build_notification_profile_snapshot(_application()) is None


def test_does_not_reuse_a_previously_mixed_profile_snapshot() -> None:
    application = _application(
        creator_profile_snapshot={
            "schema_version": 2,
            "sales": {"order_count": 999},
            "video": {"count": 999},
        }
    )

    assert build_notification_profile_snapshot(application) is None


def test_creator_details_summary_merges_into_existing_notification_snapshot() -> None:
    application = _application(
        creator_gmv_minor=54_400,
        creator_profile_snapshot={
            "schema_version": 2,
            "sales": {"order_count": 999},
            "video": {"count": 999},
        }
    )
    creator = SimpleNamespace(
        extensions={
            "creator_details_summary": {
                "schema_version": 1,
                "sources": {
                    key: {"request_id": key}
                    for key in (
                        "profile",
                        "performance",
                        "followers",
                        "trends",
                        "examples",
                    )
                },
                "profile_snapshot": {
                    "schema_version": 2,
                    "pps": {"score": "3.9"},
                    "sales": {"units_sold": 23, "gmv_per_mille_minor": 1_220},
                    "video": {"count": 111, "average_view_count": 331},
                    "live": {"count": 12, "average_view_count": 857},
                    "audience": {
                        "gender": [
                            {"code": "Female", "label": "Female", "share_bps": 7500}
                        ]
                    },
                },
            }
        }
    )
    affiliate = SimpleNamespace(creator=creator, metric=None, report=None)

    snapshot = build_notification_profile_snapshot(application, affiliate)

    assert snapshot["sales"] == {
        "gmv_minor": 54_400,
        "units_sold": 23,
        "gmv_per_mille_minor": 1_220,
    }
    assert snapshot["video"]["count"] == 111
    assert snapshot["live"]["average_view_count"] == 857
    assert snapshot["audience"]["gender"][0]["share_bps"] == 7500
    assert snapshot["pps"] == {"score": "3.9"}
    assert snapshot["creator_details_complete"] is True


def test_does_not_import_channel_share_from_affiliate_report() -> None:
    metric = SimpleNamespace(
        affiliate_gmv_minor=100,
        items_sold=None,
        affiliate_order_count=None,
        average_order_amount_minor=None,
        showcase_product_count=None,
        affiliate_video_gmv_minor=120,
        affiliate_video_count=None,
        affiliate_live_gmv_minor=None,
        affiliate_live_count=None,
        affiliate_showcase_gmv_minor=None,
        affiliate_follower_count=None,
    )
    report = SimpleNamespace(
        window_start_utc=datetime(2026, 8, 1, tzinfo=UTC),
        window_end_utc=datetime(2026, 9, 1, tzinfo=UTC),
        shop_timezone="UTC",
    )

    assert build_notification_profile_snapshot(
        _application(),
        SimpleNamespace(metric=metric, report=report),
    ) is None


@pytest.mark.asyncio
async def test_default_target_query_is_shop_scoped_and_only_pre_notification() -> None:
    database = _Database()
    tenant_id, shop_id = uuid4(), uuid4()
    service = SampleNotificationProfileEnrichmentService(database)

    assert await service._list_targets(tenant_id, shop_id, None) == ()

    compiled = database.session.statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    values = compiled.params
    assert "sample_notification_outbox.tenant_id" in sql
    assert "sample_notification_outbox.shop_id" in sql
    assert "sample_notification_outbox.status IN" in sql
    assert "sample_notification_outbox.last_error_code IN" in sql
    parameter_lists = [set(value) for value in values.values() if isinstance(value, list)]
    assert any(
        {"creator_profile_incomplete", "creator_profile_stale"}.issubset(value)
        for value in parameter_lists
    )
    assert tenant_id in values.values()
    assert shop_id in values.values()


@pytest.mark.asyncio
async def test_application_target_query_does_not_require_notification_outbox() -> None:
    database = _Database()
    tenant_id, shop_id = uuid4(), uuid4()
    application_ids = frozenset({uuid4(), uuid4()})
    service = SampleNotificationProfileEnrichmentService(database)

    assert await service._list_targets(
        tenant_id,
        shop_id,
        None,
        application_ids,
    ) == ()

    compiled = database.session.statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    values = compiled.params
    assert "sample_notification_outbox" not in sql
    assert "sample_applications.tenant_id" in sql
    assert "sample_applications.shop_id" in sql
    assert "sample_applications.id IN" in sql
    assert tenant_id in values.values()
    assert shop_id in values.values()
    bound_ids = next(value for value in values.values() if isinstance(value, list))
    assert application_ids == frozenset(bound_ids)


def test_requeues_failed_profile_gate_only_without_delivery_evidence() -> None:
    now = datetime(2026, 9, 15, 4, tzinfo=UTC)
    event = SimpleNamespace(
        status="failed",
        last_error_code="creator_profile_stale",
        payload={"source_event_id": "bd-auto:1"},
        sent_at=None,
        attempt_count=5,
        next_attempt_at=None,
        last_error_summary="Feishu notification request failed.",
    )

    assert _requeue_profile_event(event, now) is True
    assert event.status == "pending"
    assert event.attempt_count == 0
    assert event.next_attempt_at == now
    assert event.last_error_code is None
    assert event.last_error_summary is None

    event.status = "failed"
    event.last_error_code = "creator_profile_stale"
    event.payload = {"message_id": "om-private"}
    assert _requeue_profile_event(event, now) is False
