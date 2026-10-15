from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from erp_api.services.hubstudio_sample_application_source import (
    HubStudioSampleTarget,
)
from erp_api.services.tiktok_sample_application_payload import (
    TikTokSampleApplicationPage,
)


@dataclass(frozen=True)
class HubStudioSampleCapture:
    target: HubStudioSampleTarget
    page: TikTokSampleApplicationPage
    observed_at: datetime
    source_type: str = "hubstudio_cdp"
