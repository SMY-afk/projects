import asyncio

import httpx
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from erp_api.services.feishu_client import FeishuClient
from erp_api.services.feishu_rate_limiter import FeishuRateLimiter
from erp_api.services.feishu_sample_errors import FeishuSampleError


@pytest.mark.asyncio
async def test_concurrent_requests_wait_in_one_five_qps_queue() -> None:
    now_ms = [0]
    next_at = [0]

    class FakeRedis:
        async def eval(self, script, key_count, key, interval_ms):
            assert key_count == 1
            assert interval_ms == 220
            if now_ms[0] < next_at[0]:
                return next_at[0] - now_ms[0]
            next_at[0] = now_ms[0] + interval_ms
            return 0

    async def sleep(seconds: float) -> None:
        now_ms[0] += round(seconds * 1000)
        await asyncio.sleep(0)

    limiter = FeishuRateLimiter(
        "redis://example/0", redis_client=FakeRedis(), sleeper=sleep
    )
    completed: list[int] = []

    async def call() -> None:
        await limiter.acquire()
        completed.append(now_ms[0])

    await asyncio.gather(*(call() for _ in range(12)))

    assert completed == [index * 220 for index in range(12)]


@pytest.mark.asyncio
async def test_redis_failure_blocks_feishu_request() -> None:
    attempted = 0

    class BrokenRedis:
        async def eval(self, *args):
            raise RedisConnectionError("unavailable")

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempted
        attempted += 1
        return httpx.Response(200, json={"code": 0})

    limiter = FeishuRateLimiter("redis://example/0", redis_client=BrokenRedis())
    http_client = httpx.AsyncClient(
        base_url="https://example.invalid/configure-resource", transport=httpx.MockTransport(handler)
    )
    feishu = FeishuClient(
        app_id="app", app_secret="secret", client=http_client, rate_limiter=limiter
    )

    with pytest.raises(FeishuSampleError) as error:
        await feishu.tenant_access_token()

    assert error.value.error_code == "rate_limiter_unavailable"
    assert attempted == 0
