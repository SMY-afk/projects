from importlib import import_module

from sqlalchemy import CheckConstraint

from erp_api.db.base import Base
from erp_api.models import LogisticsTask

MIGRATION_MODULE = "migrations.versions.ae1f2a3b4c5d_align_logistics_task_statuses"
WORKFLOW_STATUSES = {
    "pending_review",
    "pending_pack",
    "pending_waybill",
    "pending_dispatch",
    "shipped",
    "in_transit",
    "delivered",
    "exception",
    "cancelled",
}


class RecordingOperations:
    def __init__(self) -> None:
        self.executed: list[str] = []
        self.created_checks: list[tuple[str, str, str]] = []
        self.dropped_constraints: list[tuple[str, str]] = []

    def execute(self, statement) -> None:
        self.executed.append(str(statement))

    def create_check_constraint(self, name: str, table: str, condition: str) -> None:
        self.created_checks.append((name, table, condition))

    def drop_constraint(self, name: str, table: str, **kwargs) -> None:
        del kwargs
        self.dropped_constraints.append((name, table))


def test_task_model_exposes_canonical_page_workflow_statuses() -> None:
    table = Base.metadata.tables["logistics_tasks"]
    assert LogisticsTask.__table__ is table
    status_check = next(
        constraint
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
        and constraint.name == "ck_logistics_tasks_status"
    )
    sql = str(status_check.sqltext)

    assert all(f"'{status}'" in sql for status in WORKFLOW_STATUSES)
    assert "'reviewed'" not in sql
    assert "'review_exception'" not in sql
    assert "'ready_to_ship'" not in sql


def test_status_migration_maps_existing_rows_and_replaces_check(monkeypatch) -> None:
    migration = import_module(MIGRATION_MODULE)
    operations = RecordingOperations()
    monkeypatch.setattr(migration, "op", operations)

    migration.upgrade()

    assert migration.down_revision == "9d0e1f2a3b4c"
    assert operations.dropped_constraints == [
        ("ck_logistics_tasks_status", "logistics_tasks")
    ]
    migration_sql = " ".join(operations.executed)
    assert "pending_pack" in migration_sql
    assert "pending_waybill" in migration_sql
    assert "pending_dispatch" in migration_sql
    assert "exception" in migration_sql
    assert operations.created_checks[0][0] == "ck_logistics_tasks_status"
    assert all(
        status in operations.created_checks[0][2] for status in WORKFLOW_STATUSES
    )


def test_status_migration_has_a_bounded_downgrade(monkeypatch) -> None:
    migration = import_module(MIGRATION_MODULE)
    operations = RecordingOperations()
    monkeypatch.setattr(migration, "op", operations)

    migration.downgrade()

    downgrade_sql = " ".join(operations.executed)
    assert "reviewed" in downgrade_sql
    assert "review_exception" in downgrade_sql
    assert "ready_to_ship" in downgrade_sql
