import importlib

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

import erp_api.models
from erp_api.db.base import Base


def test_creator_sync_state_is_tenant_shop_creator_scoped() -> None:
    table = Base.metadata.tables["creator_sync_states"]
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
        "uq_creator_sync_states_creator",
        ("tenant_id", "shop_id", "creator_id"),
    ) in unique_constraints
    assert (
        ("affiliate_creator_id", "tenant_id", "shop_id"),
        (
            "affiliate_creators.id",
            "affiliate_creators.tenant_id",
            "affiliate_creators.shop_id",
        ),
    ) in foreign_keys
    assert {column.name for column in table.columns} >= {
        "creator_id",
        "affiliate_creator_id",
        "last_sync_at",
        "last_video_sync_at",
        "data_hash",
        "sync_status",
    }
    status_check = next(
        constraint
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    )
    assert "pending" in str(status_check.sqltext)
    assert "succeeded" in str(status_check.sqltext)


def test_creator_sync_state_model_and_migration_are_registered() -> None:
    migration = importlib.import_module(
        "migrations.versions.24e5f6a7b8c9_create_creator_sync_states"
    )

    assert erp_api.models.CreatorSyncState is not None
    assert migration.down_revision == "13d4e5f6a7b8"
