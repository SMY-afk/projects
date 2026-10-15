import os

import pytest

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://erp:test-only@localhost:5432/erp_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("AUTH_CAPTCHA_HMAC_SECRET", "test-only-secret-not-for-production")


@pytest.fixture(autouse=True)
def isolate_feishu_rate_limiter(monkeypatch):
    class ImmediateLimiter:
        async def acquire(self) -> None:
            return None

    monkeypatch.setattr(
        "erp_api.services.feishu_client.shared_feishu_rate_limiter",
        lambda _redis_url: ImmediateLimiter(),
    )
