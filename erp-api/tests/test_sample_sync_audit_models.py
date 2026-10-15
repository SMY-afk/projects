from sqlalchemy import CheckConstraint, ForeignKeyConstraint

from erp_api.models.sample_ingest_batch import SampleIngestBatch
from erp_api.models.sample_sync_run import SampleSyncRun


def _constraint_names(model: type) -> set[str | None]:
    return {constraint.name for constraint in model.__table__.constraints}


def _foreign_key_columns(model: type) -> set[tuple[str, ...]]:
    return {
        tuple(element.parent.name for element in constraint.elements)
        for constraint in model.__table__.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }


def test_sample_sync_audit_tables_are_registered() -> None:
    assert SampleIngestBatch.__table__.name == "sample_ingest_batches"
    assert SampleSyncRun.__table__.name == "sample_sync_runs"


def test_sample_ingest_batch_preserves_completeness_evidence() -> None:
    columns = SampleIngestBatch.__table__.columns

    assert "expected_total" in columns
    assert "captured_total" in columns
    assert "page_count" in columns
    assert "payload_hash" in columns
    assert "completeness_evidence" in columns
    assert "ck_sample_ingest_batches_source_type" in _constraint_names(
        SampleIngestBatch
    )
    assert "ck_sample_ingest_batches_status" in _constraint_names(SampleIngestBatch)
    assert "uq_sample_ingest_batches_id_tenant_shop" in _constraint_names(
        SampleIngestBatch
    )


def test_sample_sync_run_preserves_stage_counts_and_provenance() -> None:
    columns = SampleSyncRun.__table__.columns

    assert "records_read" in columns
    assert "records_created" in columns
    assert "records_updated" in columns
    assert "feishu_created" in columns
    assert "feishu_updated" in columns
    assert "platform_request_ids" in columns
    assert "source_batch_ids" in columns
    assert "ck_sample_sync_runs_sync_type" in _constraint_names(SampleSyncRun)
    assert "ck_sample_sync_runs_counts" in _constraint_names(SampleSyncRun)


def test_sample_sync_audit_tables_are_tenant_and_shop_scoped() -> None:
    for model in (SampleIngestBatch, SampleSyncRun):
        assert ("tenant_id",) in _foreign_key_columns(model)
        assert ("shop_id", "tenant_id") in _foreign_key_columns(model)
        assert any(
            isinstance(constraint, CheckConstraint)
            for constraint in model.__table__.constraints
        )
