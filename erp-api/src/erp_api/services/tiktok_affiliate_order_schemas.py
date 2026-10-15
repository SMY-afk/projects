from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

AffiliateMatchKeyType = Literal["order_id", "order_item_id"]


@dataclass(frozen=True)
class TikTokAffiliateOrderSignal:
    """Allow-listed affiliate evidence after an exact order-level match."""

    external_conversion_id: str
    match_key_type: AffiliateMatchKeyType
    match_key: str
    creator_external_id: str | None = None
    traffic_source: str | None = None
    operator_subject: str | None = None
    entry_point: str | None = None
    source_updated_at: datetime | None = None
    platform_source_code: str | None = None
    evidence: dict[str, str] | None = None

    @property
    def has_exact_match(self) -> bool:
        return bool(
            self.external_conversion_id
            and self.match_key
            and self.match_key_type in {"order_id", "order_item_id"}
        )


@dataclass(frozen=True)
class TikTokAffiliateOrderRecord:
    """Normalized affiliate record; unrelated aggregate rows are not represented."""

    external_conversion_id: str
    platform_order_id: str | None
    platform_order_item_ids: tuple[str, ...]
    creator_external_id: str | None
    traffic_source: str | None
    operator_subject: str | None
    entry_point: str | None
    source_updated_at: datetime | None
    platform_source_code: str | None
    evidence: dict[str, str]
