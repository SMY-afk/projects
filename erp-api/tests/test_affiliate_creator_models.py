from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import JSONB

from erp_api.models.affiliate_creator import (
    AffiliateCreator,
    AffiliateCreatorMetric,
    AffiliateCreatorReport,
)


def _constraint_names(table) -> set[str | None]:
    return {constraint.name for constraint in table.constraints}


def test_latest_creator_master_prefers_open_id_and_preserves_source_fields() -> None:
    table = AffiliateCreator.__table__
    targets = {
        tuple(element.target_fullname for element in constraint.elements)
        for constraint in table.foreign_key_constraints
    }

    assert "shop_id" in table.c
    assert ("shops.id", "shops.tenant_id") in targets
    assert "uq_affiliate_creators_shop_open_id" in _constraint_names(table)
    assert "uq_affiliate_creators_shop_username" in _constraint_names(table)
    assert "uq_affiliate_creators_id_tenant_shop" in _constraint_names(table)
    assert isinstance(table.c.source_identifiers.type, JSONB)
    assert isinstance(table.c.extensions.type, JSONB)
    assert "avatar_url" in table.c
    assert table.c.last_seen_at.type.timezone is True


def test_report_batch_owns_one_shop_and_keeps_utc_window_and_shop_timezone() -> None:
    table = AffiliateCreatorReport.__table__
    targets = {
        tuple(element.target_fullname for element in constraint.elements)
        for constraint in table.foreign_key_constraints
    }

    assert ("shops.id", "shops.tenant_id") in targets
    assert "uq_affiliate_creator_reports_id_tenant_shop" in _constraint_names(table)
    assert "uq_affiliate_creator_reports_shop_query_revision" in _constraint_names(
        table
    )
    assert "uq_affiliate_creator_reports_shop_source_query" in _constraint_names(table)
    assert isinstance(table.c.window_start_utc.type, DateTime)
    assert table.c.window_start_utc.type.timezone is True
    assert table.c.window_end_utc.type.timezone is True
    assert "shop_timezone" in table.c
    assert "query_fingerprint" in table.c
    assert "expected_total" in table.c
    assert "records_unique" in table.c
    assert "completeness_reason" in table.c
    assert table.c.source_fingerprint.nullable is True
    assert isinstance(table.c.source_metadata.type, JSONB)
    assert table.c.status.default.arg == "running"


def test_report_fact_is_batch_scoped_source_nullable_and_extension_safe() -> None:
    table = AffiliateCreatorMetric.__table__
    targets = {
        tuple(element.target_fullname for element in constraint.elements)
        for constraint in table.foreign_key_constraints
    }

    assert "shop_id" in table.c
    assert ("shops.id", "shops.tenant_id") in targets
    assert (
        "affiliate_creator_reports.id",
        "affiliate_creator_reports.tenant_id",
        "affiliate_creator_reports.shop_id",
    ) in targets
    assert (
        "affiliate_creators.id",
        "affiliate_creators.tenant_id",
        "affiliate_creators.shop_id",
    ) in targets
    assert "uq_affiliate_creator_metrics_shop_report_creator" in _constraint_names(
        table
    )
    assert "source_row_number" not in table.c
    assert isinstance(table.c.click_through_rate.type, String)
    assert table.c.click_through_rate.type.length == 32
    assert isinstance(table.c.extensions.type, JSONB)
    assert all(
        table.c[name].nullable
        for name in (
            "affiliate_gmv_minor",
            "items_sold",
            "estimated_commission_minor",
            "affiliate_order_count",
            "product_impressions",
        )
    )
