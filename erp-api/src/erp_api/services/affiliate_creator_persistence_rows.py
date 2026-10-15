from __future__ import annotations

from hashlib import sha256
from uuid import UUID

from erp_api.models.affiliate_creator import (
    AffiliateCreatorMetric,
    AffiliateCreatorReport,
)
from erp_api.services.affiliate_center_metric_dtos import AffiliateCreatorMetricDTO

METRIC_FIELDS = tuple(
    column.name
    for column in AffiliateCreatorMetric.__table__.columns
    if column.name not in {"id", "tenant_id", "shop_id", "report_id", "creator_id"}
)


def creator_row(
    tenant_id: UUID, shop_id: UUID, record: AffiliateCreatorMetricDTO
) -> dict[str, object]:
    return {
        "tenant_id": tenant_id,
        "shop_id": shop_id,
        "username": record.username,
        "username_normalized": record.username_normalized,
        "creator_open_id": record.creator_open_id,
        "avatar_url": record.avatar_url,
        "source_identifiers": {
            key: value
            for key, value in record.source_identifiers.items()
            if key not in {"creatorOpenId", "creator_open_id", "avatar", "avatar_url"}
        },
        "extensions": {},
    }


def metric_row(
    tenant_id: UUID,
    shop_id: UUID,
    report_id: UUID,
    creator_id: UUID,
    record: AffiliateCreatorMetricDTO,
) -> dict[str, object]:
    row = {
        "tenant_id": tenant_id,
        "shop_id": shop_id,
        "report_id": report_id,
        "creator_id": creator_id,
    }
    row.update({field: getattr(record, field) for field in METRIC_FIELDS})
    return row


def capture_lock_key(tenant_id: UUID, shop_id: UUID, fingerprint: str) -> int:
    identity = f"affiliate_creator:{tenant_id}:{shop_id}:{fingerprint}"
    return int.from_bytes(
        sha256(identity.encode("utf-8")).digest()[:8],
        byteorder="big",
        signed=True,
    )


def running_report_run_id(report: AffiliateCreatorReport) -> UUID:
    value = report.source_metadata.get("syncRunId")
    if value is None and report.source_fingerprint:
        for prefix in ("page-capture:", "browser-export:"):
            if report.source_fingerprint.startswith(prefix):
                value = report.source_fingerprint[len(prefix) :]
                break
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as error:
        raise RuntimeError(
            "Running creator report has no synchronization run ID."
        ) from error


def _batches(rows: list[dict[str, object]]) -> list[list[dict[str, object]]]:
    return [
        rows[index : index + 500]
        for index in range(0, len(rows), 500)
    ]
