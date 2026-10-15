from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import configure_mappers

import erp_api.models
from erp_api.db.base import Base


def test_core_models_are_registered_for_migrations() -> None:
    assert set(Base.metadata.tables) == {
        "affiliate_creator_metrics",
        "affiliate_creator_reports",
        "affiliate_creator_detail_items",
        "affiliate_creator_detail_reports",
        "affiliate_creators",
        "affiliate_order_items",
        "affiliate_sync_states",
        "analytics_snapshots",
        "analytics_sync_cursors",
        "analytics_sync_runs",
        "analytics_raw_payloads",
        "analytics_quality_alerts",
        "bestseller_entries",
        "bestseller_snapshots",
        "creator_connections",
        "creator_sync_states",
        "finance_payment_statements",
        "finance_payments",
        "finance_statements",
        "finance_sync_cursors",
        "finance_sync_runs",
        "finance_transaction_components",
        "finance_transactions",
        "logistics_task_items",
        "logistics_task_operations",
        "logistics_task_reviews",
        "logistics_tasks",
        "logistics_packages",
        "logistics_package_items",
        "logistics_carriers",
        "logistics_carrier_services",
        "logistics_carrier_accounts",
        "logistics_platform_carrier_mappings",
        "logistics_waybills",
        "logistics_documents",
        "logistics_exceptions",
        "logistics_exception_actions",
        "platform_fulfillment_outbox",
        "logistics_tracking_events",
        "permissions",
        "orders",
        "order_attributions",
        "order_conversion_links",
        "order_lines",
        "order_fulfillments",
        "order_recipients",
        "order_sync_runs",
        "order_sync_cursors",
        "tiktok_webhook_events",
        "tiktok_live_sessions",
        "tiktok_video_contents",
        "tiktok_video_performance_snapshots",
        "pii_access_audits",
        "products",
        "product_skus",
        "product_sync_runs",
        "return_request_items",
        "return_requests",
        "return_rmas",
        "role_permissions",
        "roles",
        "sample_application_events",
        "sample_application_workflows",
        "sample_applications",
        "sample_ingest_batches",
        "sample_notification_outbox",
        "sample_sync_runs",
        "scraped_data",
        "shop_connections",
        "shops",
        "tenants",
        "user_roles",
        "users",
    }
    assert erp_api.models.AffiliateOrderItem is not None
    assert erp_api.models.AffiliateSyncState is not None
    assert erp_api.models.OrderAttribution is not None
    assert erp_api.models.OrderConversionLink is not None
    assert erp_api.models.BestsellerEntry is not None
    assert erp_api.models.BestsellerSnapshot is not None
    assert "AffiliateOrderItem" in erp_api.models.__all__
    assert "AffiliateSyncState" in erp_api.models.__all__
    assert "OrderAttribution" in erp_api.models.__all__
    assert "BestsellerEntry" in erp_api.models.__all__
    assert "BestsellerSnapshot" in erp_api.models.__all__


def test_analytics_tables_are_tenant_scoped_and_deduplicated_by_external_identity() -> (
    None
):
    snapshot = Base.metadata.tables["analytics_snapshots"]
    video = Base.metadata.tables["tiktok_video_contents"]
    live = Base.metadata.tables["tiktok_live_sessions"]

    snapshot_uniques = {
        (constraint.name, tuple(constraint.columns.keys()))
        for constraint in snapshot.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    video_uniques = {
        (constraint.name, tuple(constraint.columns.keys()))
        for constraint in video.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    live_uniques = {
        (constraint.name, tuple(constraint.columns.keys()))
        for constraint in live.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert (
        "uq_analytics_snapshots_shop_metric_window_currency",
        (
            "shop_id",
            "metric_set",
            "granularity",
            "window_start",
            "window_end",
            "currency",
        ),
    ) in snapshot_uniques
    assert (
        "uq_tiktok_video_contents_shop_platform_video",
        ("shop_id", "platform_video_id"),
    ) in video_uniques
    assert (
        "uq_tiktok_live_sessions_shop_platform_live",
        ("shop_id", "platform_live_id"),
    ) in live_uniques


def test_analytics_sync_cursor_and_raw_payloads_are_tenant_scoped() -> None:
    cursor = Base.metadata.tables["analytics_sync_cursors"]
    raw_payload = Base.metadata.tables["analytics_raw_payloads"]
    cursor_uniques = {
        (constraint.name, tuple(constraint.columns.keys()))
        for constraint in cursor.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    raw_foreign_keys = {
        tuple(constraint.column_keys)
        for constraint in raw_payload.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }

    assert (
        "uq_analytics_sync_cursors_shop_resource",
        ("shop_id", "resource_type"),
    ) in cursor_uniques
    assert ("shop_id", "tenant_id") in raw_foreign_keys
    assert ("sync_run_id", "tenant_id") in raw_foreign_keys


def test_analytics_sync_resource_types_cover_affiliate_resources() -> None:
    expected = {"video", "live", "affiliate_creator", "affiliate_video"}
    for table_name in (
        "analytics_sync_runs",
        "analytics_sync_cursors",
        "analytics_quality_alerts",
    ):
        table = Base.metadata.tables[table_name]
        resource_type = table.columns["resource_type"]
        checks = {
            str(constraint.sqltext)
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint)
            and constraint.name == f"ck_{table_name}_resource_type"
        }

        assert resource_type.type.length == 32
        assert len(checks) == 1
        check_sql = checks.pop()
        assert all(f"'{value}'" in check_sql for value in expected)


def test_analytics_quality_alerts_are_append_only_trace_records() -> None:
    alerts = Base.metadata.tables["analytics_quality_alerts"]
    unique_constraints = [
        constraint
        for constraint in alerts.constraints
        if isinstance(constraint, UniqueConstraint)
    ]
    foreign_keys = {
        tuple(constraint.column_keys)
        for constraint in alerts.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }

    assert unique_constraints == []
    assert ("shop_id", "tenant_id") in foreign_keys
    assert ("sync_run_id", "tenant_id") in foreign_keys


def test_video_performance_snapshots_are_windowed_and_batch_scoped() -> None:
    table = Base.metadata.tables["tiktok_video_performance_snapshots"]
    unique_constraints = {
        (constraint.name, tuple(constraint.columns.keys()))
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    foreign_keys = {
        tuple(constraint.column_keys)
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }
    indexes = {index.name: tuple(index.columns.keys()) for index in table.indexes}

    assert (
        "uq_tiktok_video_performance_run_video",
        ("sync_run_id", "platform_video_id"),
    ) in unique_constraints
    assert ("shop_id", "tenant_id") in foreign_keys
    assert ("sync_run_id", "tenant_id") in foreign_keys
    assert ("shop_id", "platform_video_id") in foreign_keys
    assert indexes["ix_tiktok_video_performance_window_lookup"] == (
        "tenant_id",
        "shop_id",
        "window_start",
        "window_end",
        "currency",
        "account_type",
    )


def test_tenant_scoped_entities_have_required_unique_constraints() -> None:
    constraints = {
        table_name: {
            tuple(constraint.columns.keys())
            for constraint in Base.metadata.tables[table_name].constraints
            if isinstance(constraint, UniqueConstraint)
        }
        for table_name in ("users", "roles", "shops")
    }

    assert ("tenant_id", "username") in constraints["users"]
    assert ("tenant_id", "code") in constraints["roles"]
    assert ("tenant_id", "platform", "platform_shop_id") in constraints["shops"]


def test_products_are_unique_per_shop_and_reference_shop_with_tenant_scope() -> None:
    products = Base.metadata.tables["products"]
    unique_constraints = {
        tuple(constraint.columns.keys())
        for constraint in products.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    foreign_keys = {
        tuple(constraint.column_keys)
        for constraint in products.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }

    assert ("shop_id", "platform_product_id") in unique_constraints
    assert ("shop_id", "tenant_id") in foreign_keys


def test_order_attributions_are_unique_and_reference_orders_with_tenant_scope() -> None:
    attributions = Base.metadata.tables["order_attributions"]
    assert list(attributions.columns.keys()) == [
        "id",
        "order_id",
        "winning_evidence_link_id",
        "traffic_source",
        "operator_subject",
        "entry_point",
        "special_order_type",
        "chain_code",
        "classification_status",
        "classification_method",
        "platform_source_code",
        "creator_external_id",
        "video_external_id",
        "live_external_id",
        "product_external_id",
        "sku_external_id",
        "campaign_external_id",
        "promotion_external_id",
        "confidence_score",
        "is_multi_touch",
        "conflict_flags",
        "evidence_summary",
        "resolution_version",
        "evidence_json",
        "source_updated_at",
        "source_hash",
        "classified_at",
        "created_at",
        "updated_at",
        "tenant_id",
    ]
    assert tuple(attributions.primary_key.columns.keys()) == ("id",)

    unique_constraints = {
        (constraint.name, tuple(constraint.columns.keys()))
        for constraint in attributions.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    foreign_keys = {
        (
            tuple(constraint.column_keys),
            tuple(element.target_fullname for element in constraint.elements),
        )
        for constraint in attributions.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }

    assert (
        "uq_order_attributions_tenant_order",
        ("tenant_id", "order_id"),
    ) in unique_constraints
    assert foreign_keys == {
        (("order_id", "tenant_id"), ("orders.id", "orders.tenant_id")),
        (("winning_evidence_link_id",), ("order_conversion_links.id",)),
        (("tenant_id",), ("tenants.id",)),
    }

    indexes = {
        index.name: tuple(index.columns.keys()) for index in attributions.indexes
    }
    assert indexes == {
        "ix_order_attributions_order_id": ("order_id",),
        "ix_order_attributions_winning_evidence_link_id": ("winning_evidence_link_id",),
        "ix_order_attributions_tenant_chain_code": ("tenant_id", "chain_code"),
        "ix_order_attributions_tenant_classification_status": (
            "tenant_id",
            "classification_status",
        ),
        "ix_order_attributions_tenant_id": ("tenant_id",),
    }


def test_order_conversion_links_are_exact_and_tenant_scoped() -> None:
    links = Base.metadata.tables["order_conversion_links"]
    assert list(links.columns.keys()) == [
        "id",
        "order_id",
        "order_line_id",
        "scraped_data_id",
        "source_system",
        "source_record_key",
        "external_conversion_id",
        "match_key_type",
        "match_key_value",
        "creator_external_id",
        "video_external_id",
        "live_external_id",
        "product_external_id",
        "sku_external_id",
        "campaign_external_id",
        "promotion_external_id",
        "traffic_source_candidate",
        "operator_subject_candidate",
        "entry_point_candidate",
        "evidence_strength",
        "confidence_score",
        "evidence_json",
        "evidence_hash",
        "source_created_at",
        "source_updated_at",
        "observed_at",
        "tenant_id",
    ]
    unique_constraints = {
        (constraint.name, tuple(constraint.columns.keys()))
        for constraint in links.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert (
        "uq_order_conversion_links_order_source_conversion_evidence",
        (
            "tenant_id",
            "order_id",
            "source_system",
            "external_conversion_id",
            "evidence_hash",
        ),
    ) in unique_constraints
    foreign_keys = {
        tuple(constraint.column_keys)
        for constraint in links.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }
    assert ("order_id", "tenant_id") in foreign_keys
    assert ("order_line_id",) in foreign_keys
    assert ("scraped_data_id",) in foreign_keys
    assert ("tenant_id",) in foreign_keys


def test_order_attribution_relationship_is_one_to_one() -> None:
    configure_mappers()
    relationship = erp_api.models.Order.attribution.property

    assert relationship.uselist is False
    assert relationship.back_populates == "order"
    assert "delete-orphan" in relationship.cascade


def test_order_sync_runs_record_batch_attribution_metrics() -> None:
    columns = Base.metadata.tables["order_sync_runs"].columns

    assert list(columns.keys())[7:15] == [
        "recovery_cursor",
        "fetched_count",
        "upserted_count",
        "confirmed_count",
        "derived_count",
        "unknown_count",
        "unsupported_field_count",
        "attempt_count",
    ]
    for name in (
        "fetched_count",
        "confirmed_count",
        "derived_count",
        "unknown_count",
        "unsupported_field_count",
    ):
        assert columns[name].nullable is False


def test_connection_model_only_exposes_encrypted_token_columns() -> None:
    columns = Base.metadata.tables["shop_connections"].columns.keys()

    assert "access_token_ciphertext" in columns
    assert "refresh_token_ciphertext" in columns
    assert "shop_ciphertext" in columns
    assert "access_token" not in columns
    assert "refresh_token" not in columns
    assert "shop_cipher" not in columns


def test_shop_uses_stable_external_identity_and_display_fields() -> None:
    columns = Base.metadata.tables["shops"].columns

    assert "shop_name" in columns
    assert "shop_code" in columns
    assert "currency" in columns
    assert "updated_at" in columns
    assert "name" not in columns
    assert columns["platform_shop_id"].type.length == 100


def test_model_relationships_are_configurable() -> None:
    configure_mappers()
