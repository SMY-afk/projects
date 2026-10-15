import importlib
from typing import get_args

from erp_api.models.analytics_sync import AnalyticsSyncRun
from erp_api.services.analytics_sync_types import AnalyticsSyncStatus


def test_partial_status_is_supported_by_model_type_and_migration() -> None:
    constraint = next(
        item
        for item in AnalyticsSyncRun.__table__.constraints
        if item.name == "ck_analytics_sync_runs_status"
    )
    migration = importlib.import_module(
        "migrations.versions.12c3d4e5f6a7_add_analytics_partial_status"
    )

    assert "partial" in str(constraint.sqltext)
    assert "partial" in get_args(AnalyticsSyncStatus)
    assert "'partial'" in migration._STATUS_CHECK
