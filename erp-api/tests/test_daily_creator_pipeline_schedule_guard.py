"""Do not start an old-cycle Feishu write when a read crosses 01:30."""

import pytest
from test_daily_creator_full_pipeline import full_pipeline as full_pipeline_fixture
from test_daily_creator_full_pipeline import reconcile

from scripts import daily_valid_creator_pipeline as pipeline

full_pipeline = full_pipeline_fixture


@pytest.mark.asyncio
async def test_superseded_cycle_rejected_before_online_and_source_reads(full_pipeline, monkeypatch):
    def guard(*_):
        raise ValueError("Daily valid creator schedule changed")

    monkeypatch.setattr(pipeline, "validate_daily_valid_creator_source_batch", guard)
    with pytest.raises(ValueError, match="schedule changed"):
        await reconcile(full_pipeline, apply=True, scheduled_update=True)
    assert full_pipeline["online_checks"] == full_pipeline["target_reads"] == 0
    assert full_pipeline["writes"] == []


@pytest.mark.asyncio
async def test_cycle_change_after_full_read_makes_no_feishu_write(full_pipeline, monkeypatch):
    checks = []

    def guard(*_):
        checks.append(True)
        if len(checks) == 2:
            raise ValueError("Daily valid creator schedule changed")

    monkeypatch.setattr(pipeline, "validate_daily_valid_creator_source_batch", guard)
    with pytest.raises(ValueError, match="schedule changed"):
        await reconcile(full_pipeline, apply=True, scheduled_update=True)
    assert len(checks) == 2
    assert full_pipeline["target_reads"] == 2
    assert full_pipeline["writes"] == []
    assert full_pipeline["records"] == full_pipeline["baseline"]


@pytest.mark.asyncio
async def test_same_cycle_retains_all_existing_write_and_readback_gates(full_pipeline, monkeypatch):
    checks = []
    monkeypatch.setattr(pipeline, "validate_daily_valid_creator_source_batch",
                        lambda *_: checks.append(True))
    result = await reconcile(full_pipeline, apply=True, scheduled_update=True)
    assert len(checks) == 2
    assert result["apply"]["second_preview"] == [0, 0, 0]
    assert full_pipeline["online_checks"] == full_pipeline["batch_checks"] == 2
