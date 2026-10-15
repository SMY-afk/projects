from __future__ import annotations

from dataclasses import dataclass

PLATFORM_NO_ORDER_LEVEL_EVIDENCE = "platform_no_order_level_evidence"
UNSUPPORTED_ENDPOINT = "unsupported_endpoint"


@dataclass(frozen=True)
class ExternalOrderEvidenceLookup:
    """Result of inspecting one optional external order-evidence endpoint."""

    signal: object | None = None
    absence_reason: str | None = None
