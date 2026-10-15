"""Verify one paid creator's real five-part profile before enabling allocation."""

import asyncio
import json
from datetime import datetime
from pathlib import Path

from backend.app.services.hubstudio_cdp import discover_hubstudio_cdp_url
from backend.app.services.refundable_creator_profile_capture import (
    capture_refundable_profiles,
)
from erp_api.services.hubstudio_sample_response_parser import (
    parse_hubstudio_sample_response,
)
from erp_api.services.refundable_creator_profile import apply_refundable_profile
from erp_api.services.sample_application_mapper import normalize_sample_application
from scripts.run_remote_sample_capture_loop import SHOPS


async def run():
    shop_id, _, platform_id = SHOPS["cross-border-12"]
    path = Path(".runtime/refundable-raw-queue") / f"{shop_id}-refundable-3"
    stored = json.loads(next(path.glob("batch-*/page-*.json")).read_text(encoding="utf-8"))
    observed = datetime.fromisoformat(stored["response_observed_at"])
    page = parse_hubstudio_sample_response(stored["payload"], platform_request_id=stored["request_id"], observed_at=observed)
    item = page.applications[0]
    endpoint = await discover_hubstudio_cdp_url(current_url=None, expected_platform_shop_id=platform_id)
    profiles = await capture_refundable_profiles(endpoint, platform_id, [item], host="affiliate.tiktokshopglobalselling.com")
    apply_refundable_profile(item, profiles[item["creator"]["username"]])
    row = normalize_sample_application(item, observed_at=observed, source_type="hubstudio_cdp")
    print(json.dumps({"profile_sources": len(profiles[item["creator"]["username"]]),
                      "classified": row.get("creator_level") is not None,
                      "level": row.get("creator_level"),
                      "complete": row.get("creator_profile_snapshot", {}).get("creator_details_complete")}, ensure_ascii=True))


if __name__ == "__main__":
    asyncio.run(run())
