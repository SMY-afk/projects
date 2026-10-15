from __future__ import annotations

import argparse
import asyncio
import os
from uuid import UUID


def main() -> None:
    from backend.app.services.tiktok_affiliate_listener import (
        DEFAULT_RETRY_DELAYS,
        run_listener,
    )

    parser = argparse.ArgumentParser(
        description="Capture Hubstudio TikTok Affiliate responses over CDP."
    )
    parser.add_argument("--cdp-url", default=os.getenv("HUBSTUDIO_CDP_URL"))
    parser.add_argument("--tenant-id", type=UUID, default=os.getenv("ERP_TENANT_ID"))
    parser.add_argument("--shop-id", type=UUID, default=os.getenv("ERP_SHOP_ID"))
    parser.add_argument(
        "--retry-delays",
        type=float,
        nargs="+",
        default=DEFAULT_RETRY_DELAYS,
    )
    arguments = parser.parse_args()
    if not arguments.tenant_id:
        parser.error("--tenant-id or ERP_TENANT_ID is required")
    if not arguments.shop_id:
        parser.error("--shop-id or ERP_SHOP_ID is required")
    if not arguments.cdp_url:
        parser.error("--cdp-url or HUBSTUDIO_CDP_URL is required")
    retry_delays = tuple(arguments.retry_delays)
    if len(retry_delays) > 3 or any(delay <= 0 for delay in retry_delays):
        parser.error("--retry-delays accepts at most three positive values")
    asyncio.run(
        run_listener(
            arguments.cdp_url,
            arguments.tenant_id,
            arguments.shop_id,
            retry_delays,
        )
    )


if __name__ == "__main__":
    main()
