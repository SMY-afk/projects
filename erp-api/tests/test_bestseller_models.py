from sqlalchemy import ForeignKeyConstraint, UniqueConstraint

from erp_api.models.bestseller_snapshot import (
    BestsellerEntry,
    BestsellerSnapshot,
)


def _unique_names(model: type) -> set[str]:
    return {
        constraint.name
        for constraint in model.__table__.constraints
        if isinstance(constraint, UniqueConstraint) and constraint.name
    }


def _foreign_key_columns(model: type) -> set[tuple[tuple[str, ...], tuple[str, ...]]]:
    result = set()
    for constraint in model.__table__.constraints:
        if not isinstance(constraint, ForeignKeyConstraint):
            continue
        local = tuple(element.parent.name for element in constraint.elements)
        remote = tuple(element.target_fullname for element in constraint.elements)
        result.add((local, remote))
    return result


def test_snapshot_has_query_identity_composite_fk_and_read_index() -> None:
    assert {
        "uq_bestseller_snapshots_id_tenant",
        "uq_bestseller_snapshots_query",
    }.issubset(_unique_names(BestsellerSnapshot))
    assert (
        ("shop_id", "tenant_id"),
        ("shops.id", "shops.tenant_id"),
    ) in _foreign_key_columns(BestsellerSnapshot)
    assert "ix_bestseller_snapshots_shop_entity_date" in {
        index.name for index in BestsellerSnapshot.__table__.indexes
    }


def test_entry_has_tenant_safe_snapshot_fk_uniques_and_rank_index() -> None:
    assert {
        "uq_bestseller_entries_snapshot_external",
        "uq_bestseller_entries_snapshot_rank",
    }.issubset(_unique_names(BestsellerEntry))
    assert (
        ("snapshot_id", "tenant_id"),
        ("bestseller_snapshots.id", "bestseller_snapshots.tenant_id"),
    ) in _foreign_key_columns(BestsellerEntry)
    assert "ix_bestseller_entries_tenant_snapshot_rank" in {
        index.name for index in BestsellerEntry.__table__.indexes
    }
    assert "ix_bestseller_entries_raw_payload_expires_at" in {
        index.name for index in BestsellerEntry.__table__.indexes
    }
    assert BestsellerEntry.__table__.c.raw_payload.nullable is True
    assert BestsellerEntry.__table__.c.raw_payload_expires_at.nullable is True
