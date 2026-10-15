"""Run sample worker startup validation without consuming any queue jobs."""

import asyncio

from arq.connections import create_pool

from erp_api.workers.sample_settings import SampleWorkerSettings, shutdown, startup


async def main() -> None:
    redis = await create_pool(SampleWorkerSettings.redis_settings)
    context = {"redis": redis}
    try:
        await startup(context)
        print(
            "SAMPLE_STARTUP_PREFLIGHT_OK "
            f"PIPELINE={context.get('sample_shop_pipeline_service') is not None} "
            f"FEISHU_ROUTER={context.get('feishu_sample_client_router') is not None} "
            f"NOTIFICATIONS={context.get('sample_notification_service') is not None} "
            f"AUTO_ASSIGN={context.get('sample_auto_assignment_service') is not None} "
            f"REVERSE_POLL={context.get('feishu_sample_reverse_poll_service') is not None}"
        )
    except Exception as error:
        print(
            f"SAMPLE_STARTUP_PREFLIGHT_FAILED TYPE={type(error).__name__} "
            f"CODE={getattr(error, 'error_code', '-')}"
        )
        raise SystemExit(1) from None
    finally:
        if "database" in context:
            await shutdown(context)
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
