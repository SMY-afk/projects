from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime
from typing import Protocol

from erp_api.services.affiliate_center_metric_dtos import AffiliateCreatorMetricDTO


class StoredCreatorSyncState(Protocol):
    data_hash: str
    last_sync_at: datetime | None
    sync_status: str


def creator_data_hash(record: AffiliateCreatorMetricDTO) -> str:
    payload = asdict(record)
    for field in ("window_start_utc", "window_end_utc", "shop_timezone", "currency"):
        payload.pop(field, None)
    canonical = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def should_sync_creator(
    state: StoredCreatorSyncState | None,
    data_hash: str,
    *,
    stale_before: datetime,
) -> bool:
    if state is None or state.sync_status != "succeeded":
        return True
    if state.data_hash != data_hash or state.last_sync_at is None:
        return True
    return state.last_sync_at <= stale_before
