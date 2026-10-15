from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from scripts.recheck_daily_valid_bd import require_current


def values():
    application = SimpleNamespace(creator_username="_brandi_0824", sample_type="refundable",
        is_current_projection=True, platform_status="REFUNDABLE_SHIPPED",
        source_observed_at=datetime.now(UTC), raw_payload={"refundable_contract_verified": True})
    workflow = SimpleNamespace(feishu_record_id="rec-existing", assigned_bd_name=None,
        assignment_version=0, assigned_at=None)
    batch = SimpleNamespace(status="complete", expected_total=7, captured_total=7,
        completeness_evidence={"pagination_complete": True})
    return application, workflow, batch


def test_current_complete_unassigned_application_can_be_rechecked():
    require_current(*values(), "@_brandi_0824")


@pytest.mark.parametrize("field,value", [
    ("is_current_projection", False),
    ("platform_status", "REFUNDABLE_CANCELLED"),
    ("source_observed_at", datetime.now(UTC) - timedelta(minutes=16)),
])
def test_stale_cancelled_or_superseded_application_is_not_reprocessed(field, value):
    application, workflow, batch = values()
    setattr(application, field, value)
    with pytest.raises(RuntimeError, match="not currently eligible"):
        require_current(application, workflow, batch, "_brandi_0824")


def test_existing_assignment_cannot_be_recreated():
    application, workflow, batch = values()
    workflow.assigned_bd_name = "Existing BD"
    with pytest.raises(RuntimeError, match="already exists"):
        require_current(application, workflow, batch, "_brandi_0824")


def test_manually_deleted_assignment_cannot_be_rebuilt():
    application, workflow, batch = values()
    application.raw_payload["manual_assignment_deleted"] = True
    with pytest.raises(RuntimeError, match="cannot be rebuilt"):
        require_current(application, workflow, batch, "_brandi_0824")


def test_partial_source_batch_is_not_accepted():
    application, workflow, batch = values()
    batch.captured_total = 6
    with pytest.raises(RuntimeError, match="inconsistent"):
        require_current(application, workflow, batch, "_brandi_0824")
