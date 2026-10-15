from datetime import date

import pytest

from erp_api.services.affiliate_official_creator_validation import (
    OfficialCreatorExportValidationError,
    validate_official_creator_export,
)
from erp_api.services.tiktok_compass_client import CompassExport


def _export(*, file_name="Creator_List_20260826-20260901.xlsx"):
    return CompassExport("task-1", file_name, b"PK\x03\x04official")


def test_official_creator_export_builds_auditable_totals() -> None:
    audit = validate_official_creator_export(
        _export(),
        window_start=date(2026, 8, 26),
        window_end=date(2026, 9, 1),
        rows=[
            {
                "username": "@one",
                "affiliateGmvMinor": 1234,
                "estimatedCommissionMinor": 125,
                "affiliateOrderCount": 2,
                "affiliateProductItemsSold": 3,
            },
            {
                "username": "@two",
                "affiliateGmvMinor": 500,
                "estimatedCommissionMinor": 50,
                "affiliateOrderCount": 1,
                "affiliateProductItemsSold": 1,
            },
        ],
    )

    assert audit.record_count == 2
    assert audit.gmv_minor == 1734
    assert audit.commission_minor == 175
    assert audit.order_count == 3
    assert audit.items_sold == 4
    assert len(audit.file_sha256) == 64


def test_accepts_seller_center_download_timestamp_suffix() -> None:
    audit = validate_official_creator_export(
        _export(
            file_name="Creator_List_20260826-20260901_20260902102420.xlsx"
        ),
        window_start=date(2026, 8, 26),
        window_end=date(2026, 9, 1),
        rows=[{"username": "@one"}],
    )

    assert audit.record_count == 1


@pytest.mark.parametrize(
    ("file_name", "rows", "message"),
    [
        ("Creator_List_20260825-20260831.xlsx", [{"username": "@one"}], "window"),
        ("Creator_List_20260826-20260901.xlsx", [], "empty"),
        (
            "Creator_List_20260826-20260901.xlsx",
            [{"username": "@one"}, {"username": "one"}],
            "duplicate",
        ),
    ],
)
def test_official_creator_export_rejects_unsafe_snapshot(
    file_name, rows, message
) -> None:
    with pytest.raises(OfficialCreatorExportValidationError, match=message):
        validate_official_creator_export(
            _export(file_name=file_name),
            window_start=date(2026, 8, 26),
            window_end=date(2026, 9, 1),
            rows=rows,
        )
