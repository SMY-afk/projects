from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from hashlib import sha256

from erp_api.services.tiktok_compass_client import CompassExport


class OfficialCreatorExportValidationError(ValueError):
    pass


@dataclass(frozen=True)
class OfficialCreatorExportAudit:
    record_count: int
    gmv_minor: int
    commission_minor: int
    order_count: int
    items_sold: int
    file_sha256: str


def validate_official_creator_export(
    export: CompassExport,
    *,
    window_start: date,
    window_end: date,
    rows: Sequence[Mapping[str, object]],
) -> OfficialCreatorExportAudit:
    if not _matches_window(export.file_name, window_start, window_end):
        raise OfficialCreatorExportValidationError(
            "Official Creator export window does not match the requested window."
        )
    if not rows:
        raise OfficialCreatorExportValidationError(
            "Official Creator export is empty; the existing complete snapshot is retained."
        )
    usernames: set[str] = set()
    for row in rows:
        username = str(row.get("username") or "").strip().lstrip("@").casefold()
        if not username:
            raise OfficialCreatorExportValidationError(
                "Official Creator export contains a missing username."
            )
        if username in usernames:
            raise OfficialCreatorExportValidationError(
                "Official Creator export contains a duplicate username."
            )
        usernames.add(username)
    return OfficialCreatorExportAudit(
        record_count=len(rows),
        gmv_minor=_total(rows, "affiliateGmvMinor"),
        commission_minor=_total(rows, "estimatedCommissionMinor"),
        order_count=_total(rows, "affiliateOrderCount"),
        items_sold=_total(rows, "affiliateProductItemsSold"),
        file_sha256=sha256(export.content).hexdigest(),
    )


def _matches_window(file_name: str | None, start: date, end: date) -> bool:
    if not file_name:
        return False
    suffix = f"{start:%Y%m%d}-{end:%Y%m%d}"
    pattern = rf"(?:^|_){suffix}(?:_\d{{14}})?(?:\.xlsx)?$"
    return re.search(pattern, file_name, re.IGNORECASE) is not None


def _total(rows: Sequence[Mapping[str, object]], field: str) -> int:
    total = 0
    for row in rows:
        value = row.get(field)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise OfficialCreatorExportValidationError(
                f"Official Creator export contains an invalid {field}."
            )
        total += value
    return total
