from sqlalchemy import CheckConstraint, Index, UniqueConstraint

from erp_api.db.base import Base
from erp_api.models.logistics_exception import LogisticsException  # noqa: F401


def test_exception_tables_have_tenant_constraints_and_active_dedupe() -> None:
    exceptions = Base.metadata.tables["logistics_exceptions"]
    actions = Base.metadata.tables["logistics_exception_actions"]
    unique_names = {
        item.name
        for item in exceptions.constraints
        if isinstance(item, UniqueConstraint)
    }
    check_names = {
        item.name
        for item in exceptions.constraints
        if isinstance(item, CheckConstraint)
    }
    index_names = {item.name for item in exceptions.indexes if isinstance(item, Index)}

    assert "uq_logistics_exceptions_id_tenant" in unique_names
    assert "ck_logistics_exceptions_type" in check_names
    assert "ck_logistics_exceptions_status" in check_names
    assert "uq_logistics_exceptions_active_fingerprint" in index_names
    assert any(
        {key.parent.name for key in constraint.elements}
        == {"exception_id", "tenant_id"}
        for constraint in actions.foreign_key_constraints
    )
