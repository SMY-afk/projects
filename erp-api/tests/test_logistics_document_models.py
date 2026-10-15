from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint

import erp_api.models
from erp_api.db.base import Base


def test_logistics_documents_are_tenant_scoped_and_link_labels_to_waybills() -> None:
    table = Base.metadata.tables["logistics_documents"]
    foreign_keys = {
        (
            tuple(constraint.column_keys),
            tuple(item.target_fullname for item in constraint.elements),
        )
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }
    unique = {
        (constraint.name, tuple(constraint.columns.keys()))
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert erp_api.models.LogisticsDocument is not None
    assert (
        ("waybill_id", "tenant_id"),
        ("logistics_waybills.id", "logistics_waybills.tenant_id"),
    ) in foreign_keys
    assert (
        "uq_logistics_documents_tenant_object",
        ("tenant_id", "object_key"),
    ) in unique


def test_document_constraints_cover_types_owner_size_and_current_version() -> None:
    table = Base.metadata.tables["logistics_documents"]
    checks = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    indexes = {index.name: index for index in table.indexes if isinstance(index, Index)}

    assert {
        "ck_logistics_documents_type",
        "ck_logistics_documents_owner_type",
        "ck_logistics_documents_owner_match",
        "ck_logistics_documents_size",
    } <= checks
    assert indexes["uq_logistics_documents_current_owner"].unique is True
    assert table.columns["version_id"].nullable is False
