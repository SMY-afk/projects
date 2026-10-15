from sqlalchemy import ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import configure_mappers

import erp_api.models
from erp_api.db.base import Base


def test_affiliate_sync_states_have_expected_columns() -> None:
    table = Base.metadata.tables["affiliate_sync_states"]

    assert list(table.columns.keys()) == [
        "id",
        "shop_id",
        "next_cursor",
        "has_more",
        "last_synced_at",
        "last_success_at",
        "last_error",
        "created_at",
        "updated_at",
        "tenant_id",
    ]
    assert tuple(table.primary_key.columns.keys()) == ("id",)
    assert table.c.has_more.nullable is False
    assert table.c.next_cursor.nullable is True
    assert table.c.last_error.nullable is True


def test_affiliate_sync_states_are_unique_and_tenant_scoped_per_shop() -> None:
    table = Base.metadata.tables["affiliate_sync_states"]
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

    assert ("uq_affiliate_sync_states_shop", ("shop_id",)) in unique_constraints
    assert (("shop_id", "tenant_id"), ("shops.id", "shops.tenant_id")) in foreign_keys
    assert (("tenant_id",), ("tenants.id",)) in foreign_keys
    assert {index.name for index in table.indexes} == {
        "ix_affiliate_sync_states_shop_id",
        "ix_affiliate_sync_states_tenant_id",
    }


def test_affiliate_sync_state_is_exported_with_one_to_one_shop_relationship() -> None:
    configure_mappers()

    assert erp_api.models.AffiliateSyncState is not None
    assert "AffiliateSyncState" in erp_api.models.__all__
    relationship = erp_api.models.Shop.affiliate_sync_state.property
    assert relationship.uselist is False
    assert relationship.back_populates == "shop"
