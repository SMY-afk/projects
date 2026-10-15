from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from erp_api.services.sample_application_repository import (
    build_group_item_supersede_statement,
)
from erp_api.services.sample_application_upsert import (
    build_sample_application_upsert,
    changed_sample_fields,
    sample_event_transition,
)


def test_pending_refresh_cannot_erase_previously_verified_deadline():
    deadline = datetime(2026, 10, 13, tzinfo=UTC)
    existing = SimpleNamespace(
        platform_status="PENDING", approve_expiration_at=deadline, raw_payload={}
    )
    normalized = {
        "platform_status": "PENDING",
        "approve_expiration_at": None,
        "raw_payload": {},
    }
    changed = changed_sample_fields(existing, normalized)
    assert normalized["approve_expiration_at"] == deadline
    assert "approve_expiration_at" not in changed


def test_confirmed_terminal_refresh_can_clear_approval_deadline():
    existing = SimpleNamespace(
        platform_status="PENDING",
        approve_expiration_at=datetime(2026, 10, 13, tzinfo=UTC),
        raw_payload={},
    )
    normalized = {
        "platform_status": "CANCELLED",
        "approve_expiration_at": None,
        "raw_payload": {},
    }
    assert "approve_expiration_at" in changed_sample_fields(existing, normalized)


def test_upsert_targets_exact_tenant_shop_platform_identity_constraint() -> None:
    observed_at = datetime(2026, 9, 10, tzinfo=UTC)
    statement = build_sample_application_upsert(
        tenant_id=uuid4(),
        shop_id=uuid4(),
        normalized={
            "platform_application_id": "sample-1",
            "source_type": "official_api",
            "source_capture_id": uuid4(),
            "platform_status": "PENDING",
            "raw_payload": {},
            "source_observed_at": datetime(2026, 9, 10, tzinfo=UTC),
        },
        observed_at=observed_at,
        changed_fields={"platform_status", "source_observed_at"},
    )

    sql = str(statement.compile(dialect=postgresql.dialect()))

    assert (
        "ON CONFLICT ON CONSTRAINT "
        "uq_sample_applications_tenant_shop_platform_id DO UPDATE" in sql
    )
    assert "RETURNING sample_applications.id" in sql
    assert "first_seen_at" in sql
    assert "last_seen_at" in sql
    assert "source_type" in sql
    assert "source_capture_id" in sql
    assert "source_observed_at" in sql


def test_conflict_update_keeps_first_seen_and_only_updates_last_seen_and_changes() -> (
    None
):
    observed_at = datetime(2026, 9, 10, tzinfo=UTC)
    statement = build_sample_application_upsert(
        tenant_id=uuid4(),
        shop_id=uuid4(),
        normalized={
            "platform_application_id": "sample-1",
            "source_type": "official_api",
            "platform_status": "SHIPPED",
            "creator_nickname": "Creator",
            "raw_payload": {},
            "source_observed_at": observed_at,
        },
        observed_at=observed_at,
        changed_fields={"platform_status", "source_observed_at"},
    )

    sql = str(statement.compile(dialect=postgresql.dialect())).split("DO UPDATE SET ")[
        1
    ]

    assert "last_seen_at" in sql
    assert "platform_status" in sql
    assert "source_observed_at" in sql
    assert "first_seen_at" not in sql
    assert "creator_nickname" not in sql


def test_changed_fields_and_status_event_are_explicit() -> None:
    observed_at = datetime(2026, 9, 10, tzinfo=UTC)

    existing = SimpleNamespace(
        source_type="official_api",
        platform_status="PENDING",
        creator_nickname="Creator",
        raw_payload={"id": "sample-1", "status": "PENDING"},
    )

    normalized = {
        "platform_application_id": "sample-1",
        "source_type": "official_api",
        "platform_status": "SHIPPED",
        "creator_nickname": "Creator",
        "raw_payload": {"id": "sample-1", "status": "SHIPPED"},
        "source_observed_at": observed_at,
    }

    changed = changed_sample_fields(existing, normalized)
    event_type, before, after = sample_event_transition(existing, normalized)

    assert changed == {"platform_status", "raw_payload", "source_observed_at"}
    assert event_type == "platform_status_changed"
    assert before == {"platform_status": "PENDING"}
    assert after == {"platform_status": "SHIPPED"}


def test_official_refresh_preserves_verified_invitation_source_evidence() -> None:
    existing = SimpleNamespace(
        platform_status="PENDING",
        raw_payload={
            "id": "sample-1",
            "application_source_type": 0,
            "is_proactive_invitation": False,
        },
    )
    normalized = {
        "platform_application_id": "sample-1",
        "platform_status": "PENDING",
        "raw_payload": {"id": "sample-1", "status": "PENDING"},
        "source_observed_at": datetime(2026, 9, 15, tzinfo=UTC),
    }

    changed_sample_fields(existing, normalized)

    assert normalized["raw_payload"]["application_source_type"] == 0
    assert normalized["raw_payload"]["is_proactive_invitation"] is False


def test_new_capture_id_does_not_mark_business_source_as_changed() -> None:
    previous_capture_id = uuid4()
    next_capture_id = uuid4()
    existing = SimpleNamespace(
        source_type="hubstudio_cdp",
        source_capture_id=previous_capture_id,
        platform_status="PENDING",
        raw_payload={"id": "sample-1", "status": "PENDING"},
    )
    normalized = {
        "platform_application_id": "sample-1",
        "source_type": "hubstudio_cdp",
        "source_capture_id": next_capture_id,
        "platform_status": "PENDING",
        "raw_payload": {"id": "sample-1", "status": "PENDING"},
        "source_observed_at": datetime(2026, 9, 15, tzinfo=UTC),
    }

    changed = changed_sample_fields(existing, normalized)

    assert changed == {"source_capture_id"}


def test_official_refresh_preserves_manual_assignment_deletion() -> None:
    existing = SimpleNamespace(
        platform_status="PENDING",
        raw_payload={
            "id": "sample-1",
            "manual_assignment_deleted": True,
        },
    )
    normalized = {
        "platform_application_id": "sample-1",
        "platform_status": "PENDING",
        "raw_payload": {"id": "sample-1", "status": "PENDING"},
        "source_observed_at": datetime(2026, 9, 16, tzinfo=UTC),
    }

    changed_sample_fields(existing, normalized)

    assert normalized["raw_payload"]["manual_assignment_deleted"] is True


def test_official_refresh_preserves_ziniao_creator_group_projection() -> None:
    projection = {
        "parent_application_id": "application-1",
        "source_item_ids": ["application-1", "application-2"],
        "platform_status": "PENDING",
        "product_id": "product-1、product-2",
        "product_title": "Product 1、Product 2",
        "sku_id": "sku-1、sku-2",
        "sku_name": "Black、Pink",
        "product_image_urls": ["https://example.com/one.jpg"],
        "product_ids": ["product-1", "product-2"],
    }
    existing = SimpleNamespace(
        platform_application_id="application-2",
        source_type="official_api",
        platform_status="SHIPPED",
        product_id="product-2",
        product_title="Product 2",
        sku_id="sku-2",
        sku_name="Pink",
        product_image_urls=[],
        is_current_projection=False,
        raw_payload={"ziniao_group_projection": projection},
    )
    normalized = {
        "platform_application_id": "application-2",
        "source_type": "official_api",
        "platform_status": "SHIPPED",
        "product_id": "product-2",
        "product_title": "Product 2",
        "sku_id": "sku-2",
        "sku_name": "Pink",
        "product_image_urls": [],
        "is_current_projection": True,
        "raw_payload": {"id": "application-2"},
        "source_observed_at": datetime(2026, 9, 15, tzinfo=UTC),
    }

    changed_sample_fields(existing, normalized)

    assert normalized["is_current_projection"] is False
    assert normalized["raw_payload"]["ziniao_group_projection"] == projection


def test_official_refresh_cannot_clear_enriched_tiktok_application_time() -> None:
    applied_at = datetime(2026, 9, 15, tzinfo=UTC)
    existing = SimpleNamespace(
        platform_status="PENDING",
        tiktok_applied_at=applied_at,
        raw_payload={"id": "application-1"},
    )
    normalized = {
        "platform_application_id": "application-1",
        "platform_status": "PENDING",
        "tiktok_applied_at": None,
        "raw_payload": {"id": "application-1"},
        "source_observed_at": datetime(2026, 9, 15, 1, tzinfo=UTC),
    }

    changed = changed_sample_fields(existing, normalized)

    assert normalized["tiktok_applied_at"] == applied_at
    assert changed == set()


def test_incomplete_source_snapshot_cannot_downgrade_complete_creator_details() -> None:
    existing = SimpleNamespace(
        creator_profile_snapshot={
            "schema_version": 2,
            "creator_details_complete": True,
        },
        creator_profile_source_type="hubstudio_cdp",
        creator_profile_observed_at=datetime(2026, 9, 10, tzinfo=UTC),
    )
    normalized = {
        "platform_application_id": "sample-1",
        "creator_profile_snapshot": {"schema_version": 2},
        "creator_profile_source_type": "official_api",
        "creator_profile_observed_at": datetime(2026, 9, 11, tzinfo=UTC),
        "source_observed_at": datetime(2026, 9, 11, tzinfo=UTC),
    }

    changed = changed_sample_fields(existing, normalized)

    assert changed == set()


def test_refresh_without_performance_keeps_last_enriched_creator_metrics() -> None:
    existing = SimpleNamespace(
        platform_status="PENDING",
        creator_content_count=480,
        creator_units_sold=94,
        creator_pps="4.4",
        creator_rating="3.5",
        creator_profile_snapshot={
            "schema_version": 2,
            "sales": {"units_sold": 94},
        },
        creator_profile_source_type="official_api",
        creator_profile_observed_at=datetime(2026, 9, 10, tzinfo=UTC),
    )
    normalized = {
        "platform_application_id": "sample-1",
        "platform_status": "AWAITING_SHIPMENT",
        "creator_content_count": 0,
        "creator_units_sold": None,
        "creator_pps": None,
        "creator_rating": None,
        "creator_profile_snapshot": {"schema_version": 2},
        "creator_profile_source_type": "official_api",
        "creator_profile_observed_at": datetime(2026, 9, 11, tzinfo=UTC),
        "source_observed_at": datetime(2026, 9, 11, tzinfo=UTC),
    }

    changed = changed_sample_fields(
        existing,
        normalized,
        performance_fields=frozenset(),
    )

    assert changed == {"platform_status", "source_observed_at"}


def test_refresh_without_gmv_keeps_profile_enriched_level_and_gmv() -> None:
    existing = SimpleNamespace(
        platform_status="PENDING",
        creator_gmv_minor=493_475,
        creator_gmv_currency="USD",
        creator_level="L1",
        raw_payload={"id": "application-1"},
    )
    normalized = {
        "platform_application_id": "application-1",
        "platform_status": "PENDING",
        "creator_gmv_minor": None,
        "creator_gmv_currency": None,
        "creator_level": None,
        "raw_payload": {"id": "application-1"},
        "source_observed_at": datetime(2026, 9, 21, tzinfo=UTC),
    }

    changed = changed_sample_fields(
        existing,
        normalized,
        performance_fields=frozenset(),
    )

    assert normalized["creator_gmv_minor"] == 493_475
    assert normalized["creator_gmv_currency"] == "USD"
    assert normalized["creator_level"] == "L1"
    assert changed == set()


def test_official_refresh_keeps_existing_dom_sample_score_without_marking_complete():
    existing = SimpleNamespace(
        creator_profile_snapshot={
            "schema_version": 2,
            "sample_score": {"overall": "86"},
        },
        creator_profile_source_type="hubstudio_cdp",
        creator_profile_observed_at=datetime(2026, 9, 10, tzinfo=UTC),
    )
    normalized = {
        "platform_application_id": "sample-1",
        "creator_profile_snapshot": {
            "schema_version": 2,
            "sales": {"units_sold": 94},
            "sample_score": {"overall": None},
        },
        "creator_profile_source_type": "official_api",
        "creator_profile_observed_at": datetime(2026, 9, 11, tzinfo=UTC),
        "source_observed_at": datetime(2026, 9, 11, tzinfo=UTC),
    }

    changed_sample_fields(
        existing,
        normalized,
        performance_fields=frozenset({"units_sold"}),
    )

    snapshot = normalized["creator_profile_snapshot"]
    assert snapshot["sample_score"]["overall"] == "86"
    assert "creator_details_complete" not in snapshot


def test_group_parent_deactivates_only_its_source_item_rows() -> None:
    statement = build_group_item_supersede_statement(
        tenant_id=uuid4(),
        shop_id=uuid4(),
        parent_application_id=uuid4(),
        parent_platform_application_id="parent-application",
        source_item_ids=("sample-1", "sample-2"),
        creator_open_id="creator-1",
    )

    sql = str(statement.compile(dialect=postgresql.dialect()))

    assert sql.startswith("UPDATE sample_applications SET ")
    assert "raw_payload=" in sql
    assert "is_current_projection=" in sql
    assert "parent-application" in str(
        statement.compile(dialect=postgresql.dialect()).params
    )
    assert "sample_applications.tenant_id" in sql
    assert "sample_applications.shop_id" in sql
    assert "sample_applications.platform_application_id IN" in sql
    assert "sample_applications.platform_application_id LIKE" in sql
    assert "sample_applications.creator_open_id" in sql
    assert "sample_applications.id !=" in sql
