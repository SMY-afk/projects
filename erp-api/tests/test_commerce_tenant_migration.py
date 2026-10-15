from pathlib import Path


def test_migration_backfills_before_enforcing_tenant_constraints() -> None:
    migration = Path(
        "migrations/versions/d7ab9c1234e6_harden_commerce_tenant_links.py"
    ).read_text(encoding="utf-8")

    assert 'down_revision: str | Sequence[str] | None = "c69a8b0123d5"' in migration
    assert "UPDATE product_skus AS sku" in migration
    assert "SET tenant_id = product.tenant_id" in migration
    assert migration.index("UPDATE product_skus AS sku") < migration.index(
        'op.alter_column("product_skus", "tenant_id", nullable=False)'
    )
    assert "Cannot resolve tenant_id for every product_sku" in migration
    assert "Cross-tenant order line product link detected" in migration
    assert "Cross-tenant order line SKU link detected" in migration


def test_migration_adds_and_reverses_composite_contract() -> None:
    migration = Path(
        "migrations/versions/d7ab9c1234e6_harden_commerce_tenant_links.py"
    ).read_text(encoding="utf-8")

    for name in (
        "uq_products_id_tenant",
        "uq_product_skus_id_tenant",
        "fk_product_skus_product_tenant",
        "fk_order_lines_product_tenant",
        "fk_order_lines_product_sku_tenant",
        "ix_orders_tenant_shop_platform",
        "ix_order_lines_tenant_order",
    ):
        assert name in migration
    assert "def downgrade() -> None:" in migration
    assert 'op.drop_column("product_skus", "tenant_id")' in migration


def test_followup_migration_indexes_tenant_scope_column() -> None:
    migration = Path(
        "migrations/versions/e8bc0d2345f7_index_product_sku_tenant.py"
    ).read_text(encoding="utf-8")

    assert 'down_revision: str | Sequence[str] | None = "d7ab9c1234e6"' in migration
    assert "ix_product_skus_tenant_id" in migration
