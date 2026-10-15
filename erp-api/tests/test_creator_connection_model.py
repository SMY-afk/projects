from sqlalchemy import CheckConstraint, UniqueConstraint

from erp_api.db.base import Base


def test_creator_connections_are_tenant_scoped_and_creator_only() -> None:
    table = Base.metadata.tables["creator_connections"]
    assert {
        "id",
        "tenant_id",
        "authorized_by_user_id",
        "platform",
        "open_id",
        "user_type",
        "region",
        "auth_status",
        "access_token_ciphertext",
        "refresh_token_ciphertext",
        "expires_at",
        "refresh_expires_at",
        "scopes",
        "last_error",
        "created_at",
        "updated_at",
    } == set(table.columns.keys())
    uniques = {
        (constraint.name, tuple(constraint.columns.keys()))
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    checks = {
        (constraint.name, str(constraint.sqltext))
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert (
        "uq_creator_connections_tenant_platform_open_id",
        ("tenant_id", "platform", "open_id"),
    ) in uniques
    assert ("ck_creator_connections_user_type", "user_type = 1") in checks
