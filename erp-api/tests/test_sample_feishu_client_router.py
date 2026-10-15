from uuid import UUID

import pytest

from erp_api.services.sample_feishu_client_router import SampleFeishuClientRouter


class FakeClient:
    def __init__(self, table_name: str) -> None:
        self.table_name = table_name
        self.validated = 0

    async def validate_required_fields(self) -> None:
        self.validated += 1


def test_router_selects_exact_shop_before_default() -> None:
    shop_id = UUID("e4408786-af60-545e-8f8c-5ef22a71e675")
    default = FakeClient("default")
    target = FakeClient("cross-border-3")
    router = SampleFeishuClientRouter(default, {shop_id: target})

    assert router.for_shop(shop_id) is target
    assert router.for_shop(UUID(int=2)) is default


def test_router_without_mapping_fails_closed() -> None:
    router = SampleFeishuClientRouter(None, {})

    with pytest.raises(LookupError, match="not configured"):
        router.for_shop(UUID(int=1))


@pytest.mark.asyncio
async def test_router_validates_each_unique_target_once() -> None:
    first = FakeClient("first")
    second = FakeClient("second")
    router = SampleFeishuClientRouter(
        first,
        {
            UUID(int=1): first,
            UUID(int=2): second,
        },
    )

    await router.validate_required_fields()

    assert first.validated == 1
    assert second.validated == 1
