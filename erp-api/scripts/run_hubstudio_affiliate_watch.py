from __future__ import annotations

import argparse
import asyncio
import os
import platform
import sys
from uuid import UUID

# Python 3.13 queries WMI while importing SQLAlchemy. A degraded WMI provider
# must not prevent this isolated worker from reaching its own bounded retries.
if os.name == "nt" and sys.version_info >= (3, 13):
    platform._wmi = None  # type: ignore[attr-defined]

from backend.app.services.capture_logging import capture_log
from backend.app.services.tiktok_affiliate_listener import (
    DEFAULT_RETRY_DELAYS,
    run_listener,
)

DEFAULT_RESTART_DELAY_SECONDS = 60.0


async def _run_shop_worker(
    cdp_url: str | None,
    tenant_id: UUID,
    shop_id: UUID,
    retry_delays: tuple[float, ...],
    restart_delay_seconds: float,
) -> None:
    while True:
        try:
            await run_listener(cdp_url, tenant_id, shop_id, retry_delays)
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - isolate one shop from the others
            capture_log(
                "affiliate_shop_worker_paused",
                tenant_id=tenant_id,
                shop_id=shop_id,
                reason="unexpected_error",
                error_type=type(error).__name__,
            )
            return
        capture_log(
            "affiliate_shop_worker_restarting",
            tenant_id=tenant_id,
            shop_id=shop_id,
            reason="retry_exhausted",
            delay_seconds=restart_delay_seconds,
        )
        await asyncio.sleep(restart_delay_seconds)


async def run_watch(
    tenant_id: UUID,
    shop_ids: list[UUID],
    retry_delays: tuple[float, ...],
    cdp_urls: list[str | None] | None = None,
    restart_delay_seconds: float = DEFAULT_RESTART_DELAY_SECONDS,
) -> None:
    if restart_delay_seconds <= 0:
        raise ValueError("restart_delay_seconds must be positive")
    urls = cdp_urls if cdp_urls is not None else [None] * len(shop_ids)
    if len(urls) != len(shop_ids):
        raise ValueError("cdp_urls must match shop_ids")
    await asyncio.gather(
        *(
            _run_shop_worker(
                cdp_url,
                tenant_id,
                shop_id,
                retry_delays,
                restart_delay_seconds,
            )
            for shop_id, cdp_url in zip(shop_ids, urls, strict=True)
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Keep HubStudio affiliate capture daemons running."
    )
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument("--shop-id", type=UUID, action="append", required=True)
    parser.add_argument("--cdp-url", action="append")
    parser.add_argument(
        "--retry-delays",
        type=float,
        nargs="+",
        default=DEFAULT_RETRY_DELAYS,
        metavar="SECONDS",
    )
    parser.add_argument(
        "--restart-delay-seconds",
        type=float,
        default=DEFAULT_RESTART_DELAY_SECONDS,
    )
    args = parser.parse_args()
    retry_delays = tuple(args.retry_delays)
    if len(retry_delays) > 3 or any(delay <= 0 for delay in retry_delays):
        parser.error("--retry-delays accepts at most three positive values")
    if args.restart_delay_seconds <= 0:
        parser.error("--restart-delay-seconds must be positive")
    if args.cdp_url and len(args.cdp_url) != len(args.shop_id):
        parser.error("--cdp-url count must match --shop-id count")
    asyncio.run(
        run_watch(
            args.tenant_id,
            args.shop_id,
            retry_delays,
            args.cdp_url,
            args.restart_delay_seconds,
        )
    )


if __name__ == "__main__":
    main()
