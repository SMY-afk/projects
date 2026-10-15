from importlib import import_module

from erp_api import bootstrap
from erp_api.core import permissions

EXPECTED_PERMISSION_NAMES = {
    "logistics:view": "查看物流",
    "logistics:operate": "操作物流任务",
    "logistics:dispatch": "确认发货",
    "logistics:manage": "管理物流配置",
    "logistics:cost:view": "查看物流费用",
    "logistics:cost:reconcile": "物流费用对账",
    "returns:view": "查看退换货",
    "returns:manage": "管理退换货",
    "returns:inspect": "退换货质检",
}


class RecordingOperations:
    def __init__(self) -> None:
        self.statements: list[object] = []

    def execute(self, statement: object) -> None:
        self.statements.append(statement)


def _params(statement: object) -> dict[str, object]:
    return statement.compile().params  # type: ignore[union-attr, no-any-return]


def test_logistics_permissions_are_registered_and_named() -> None:
    assert EXPECTED_PERMISSION_NAMES.keys() <= permissions.MODULE_PERMISSION_CODES
    assert {
        code: bootstrap.PERMISSION_NAMES[code] for code in EXPECTED_PERMISSION_NAMES
    } == EXPECTED_PERMISSION_NAMES


def test_logistics_permission_constants_match_contract() -> None:
    assert permissions.LOGISTICS_VIEW == "logistics:view"
    assert permissions.LOGISTICS_OPERATE == "logistics:operate"
    assert permissions.LOGISTICS_DISPATCH == "logistics:dispatch"
    assert permissions.LOGISTICS_MANAGE == "logistics:manage"
    assert permissions.LOGISTICS_COST_VIEW == "logistics:cost:view"
    assert permissions.LOGISTICS_COST_RECONCILE == "logistics:cost:reconcile"
    assert permissions.RETURNS_VIEW == "returns:view"
    assert permissions.RETURNS_MANAGE == "returns:manage"
    assert permissions.RETURNS_INSPECT == "returns:inspect"


def test_migration_grants_every_permission_to_admin_roles(monkeypatch) -> None:
    migration = import_module(
        "migrations.versions.6a7b8c9d0e1f_add_logistics_permissions"
    )
    operations = RecordingOperations()
    monkeypatch.setattr(migration, "op", operations)

    migration.upgrade()

    assert migration.down_revision == "5f6a7b8c9d0e"
    assert dict(migration.PERMISSION_SPECS) == EXPECTED_PERMISSION_NAMES
    assert len(operations.statements) == len(EXPECTED_PERMISSION_NAMES) * 2
    statement_sql = "\n".join(str(statement) for statement in operations.statements)
    statement_params = [_params(statement) for statement in operations.statements]
    assert "ON CONFLICT (code) DO UPDATE" in statement_sql
    assert "roles.code = 'admin'" in statement_sql
    for code in EXPECTED_PERMISSION_NAMES:
        assert sum(params.get("code") == code for params in statement_params) == 2


def test_migration_downgrade_preserves_existing_logistics_view(monkeypatch) -> None:
    migration = import_module(
        "migrations.versions.6a7b8c9d0e1f_add_logistics_permissions"
    )
    operations = RecordingOperations()
    monkeypatch.setattr(migration, "op", operations)

    migration.downgrade()

    deleted_codes = {_params(statement)["code"] for statement in operations.statements}
    assert deleted_codes == set(EXPECTED_PERMISSION_NAMES) - {"logistics:view"}
