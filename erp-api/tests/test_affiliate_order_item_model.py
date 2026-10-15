from sqlalchemy import ForeignKeyConstraint, Numeric, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import configure_mappers

import erp_api.models
from erp_api.db.base import Base


def test_affiliate_order_items_are_registered_with_expected_columns() -> None:
    table = Base.metadata.tables["affiliate_order_items"]

    assert list(table.columns.keys()) == [
        "id",
        "shop_id",
        "main_order_id",
        "creator_id",
        "creator_nickname",
        "campaign_id",
        "product_id",
        "product_name",
        "image_uri",
        "sku_id",
        "sku_name",
        "order_created_at",
        "is_cod",
        "is_non_same_shop_order",
        "cos_type",
        "promotion_id",
        "promotion_type",
        "content_form",
        "commission_base",
        "commission_currency",
        "commission_rate",
        "estimated_standard_commission",
        "raw_data",
        "source_record_key",
        "created_at",
        "updated_at",
        "tenant_id",
    ]
    assert tuple(table.primary_key.columns.keys()) == ("id",)
    assert isinstance(table.c.raw_data.type, JSONB)
    assert table.c.raw_data.nullable is False
    assert table.c.source_record_key.nullable is False
    assert table.c.main_order_id.nullable is False
    assert table.c.product_id.nullable is False
    assert table.c.sku_id.nullable is False
    assert table.c.order_created_at.nullable is False


def test_affiliate_order_item_money_columns_use_exact_numeric_types() -> None:
    table = Base.metadata.tables["affiliate_order_items"]

    for name in (
        "commission_base",
        "estimated_standard_commission",
    ):
        column_type = table.c[name].type
        assert isinstance(column_type, Numeric)
        assert (column_type.precision, column_type.scale) == (20, 4)

    rate_type = table.c.commission_rate.type
    assert isinstance(rate_type, Numeric)
    assert (rate_type.precision, rate_type.scale) == (10, 6)


def test_affiliate_order_items_are_tenant_scoped_and_idempotent_per_shop() -> None:
    table = Base.metadata.tables["affiliate_order_items"]
    unique_constraints = {
        (constraint.name, tuple(constraint.columns.keys()))
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    foreign_keys = {
        (
            tuple(constraint.column_keys),
            tuple(element.target_fullname for element in constraint.elements),
        )
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }

    assert (
        "uq_affiliate_order_items_shop_source_record",
        ("shop_id", "source_record_key"),
    ) in unique_constraints
    assert (("shop_id", "tenant_id"), ("shops.id", "shops.tenant_id")) in foreign_keys
    assert (("tenant_id",), ("tenants.id",)) in foreign_keys

    indexes = {index.name: tuple(index.columns.keys()) for index in table.indexes}
    assert indexes == {
        "ix_affiliate_order_items_shop_id": ("shop_id",),
        "ix_affiliate_order_items_tenant_id": ("tenant_id",),
        "ix_affiliate_order_items_shop_main_order": ("shop_id", "main_order_id"),
        "ix_affiliate_order_items_shop_order_created_at": (
            "shop_id",
            "order_created_at",
        ),
        "ix_affiliate_order_items_shop_creator": ("shop_id", "creator_id"),
        "ix_affiliate_order_items_shop_campaign": ("shop_id", "campaign_id"),
    }


def test_affiliate_order_item_model_is_exported() -> None:
    assert erp_api.models.AffiliateOrderItem is not None
    assert "AffiliateOrderItem" in erp_api.models.__all__


def test_orders_have_a_shop_scoped_read_only_affiliate_item_relationship() -> None:
    configure_mappers()

    relationship = erp_api.models.Order.affiliate_order_items.property
    column_pairs = {
        (local.key, remote.key) for local, remote in relationship.local_remote_pairs
    }

    assert relationship.uselist is True
    assert relationship.viewonly is True
    assert column_pairs == {
        ("tenant_id", "tenant_id"),
        ("shop_id", "shop_id"),
        ("platform_order_id", "main_order_id"),
    }
