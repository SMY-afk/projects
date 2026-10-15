from sqlalchemy import ForeignKeyConstraint, Index, UniqueConstraint

from erp_api.db.base import Base
from erp_api.models.order import Order  # noqa: F401
from erp_api.models.order_line import OrderLine  # noqa: F401
from erp_api.models.product import Product  # noqa: F401
from erp_api.models.product_sku import ProductSku  # noqa: F401
from erp_api.models.shop import Shop  # noqa: F401


def _unique_columns(table_name: str) -> dict[str | None, tuple[str, ...]]:
    table = Base.metadata.tables[table_name]
    return {
        item.name: tuple(column.name for column in item.columns)
        for item in table.constraints
        if isinstance(item, UniqueConstraint)
    }


def _foreign_key_columns(
    table_name: str,
) -> set[tuple[tuple[str, ...], tuple[str, ...]]]:
    table = Base.metadata.tables[table_name]
    return {
        (
            tuple(element.parent.name for element in item.elements),
            tuple(element.target_fullname for element in item.elements),
        )
        for item in table.constraints
        if isinstance(item, ForeignKeyConstraint)
    }


def _index_columns(table_name: str) -> dict[str | None, tuple[str, ...]]:
    table = Base.metadata.tables[table_name]
    return {
        item.name: tuple(column.name for column in item.columns)
        for item in table.indexes
        if isinstance(item, Index)
    }


def test_domain_uses_shops_and_order_lines_as_store_and_item_tables() -> None:
    assert "shops" in Base.metadata.tables
    assert "order_lines" in Base.metadata.tables
    assert "stores" not in Base.metadata.tables
    assert "order_items" not in Base.metadata.tables


def test_product_and_sku_have_complete_tenant_identity() -> None:
    assert _unique_columns("products")["uq_products_id_tenant"] == (
        "id",
        "tenant_id",
    )
    assert _unique_columns("product_skus")["uq_product_skus_id_tenant"] == (
        "id",
        "tenant_id",
    )
    assert "tenant_id" in Base.metadata.tables["product_skus"].c
    assert (
        ("product_id", "tenant_id"),
        ("products.id", "products.tenant_id"),
    ) in _foreign_key_columns("product_skus")


def test_order_lines_reject_cross_tenant_product_links() -> None:
    foreign_keys = _foreign_key_columns("order_lines")
    assert (
        ("product_id", "tenant_id"),
        ("products.id", "products.tenant_id"),
    ) in foreign_keys
    assert (
        ("product_sku_id", "tenant_id"),
        ("product_skus.id", "product_skus.tenant_id"),
    ) in foreign_keys


def test_tenant_prefixed_composite_indexes_cover_primary_access_paths() -> None:
    assert _index_columns("shops")["ix_shops_tenant_status"] == (
        "tenant_id",
        "status",
    )
    assert _index_columns("products")["ix_products_tenant_shop"] == (
        "tenant_id",
        "shop_id",
    )
    assert _index_columns("product_skus")["ix_product_skus_tenant_product"] == (
        "tenant_id",
        "product_id",
    )
    assert _index_columns("orders")["ix_orders_tenant_shop_platform"] == (
        "tenant_id",
        "shop_id",
        "platform_order_id",
    )
    assert _index_columns("order_lines")["ix_order_lines_tenant_order"] == (
        "tenant_id",
        "order_id",
    )
