from uuid import uuid4

import pytest

from erp_api.services.sample_feishu_group_cleanup import (
    delete_grouped_duplicate_records,
)


class FakeFeishu:
    def __init__(self, shop_id) -> None:
        self.existing = {
            f"{shop_id}:parent": "rec-parent",
            f"{shop_id}:child-1": "rec-child-1",
            f"{shop_id}:child-2": "rec-child-2",
            f"{shop_id}:unrelated": "rec-unrelated",
        }
        self.deleted = []
        self.updated = []

    async def list_record_sync_key_map(self):
        return self.existing

    async def batch_delete_records(self, record_ids):
        self.deleted.append(list(record_ids))
        return tuple(record_ids)

    async def batch_update_records(self, records):
        self.updated.append(list(records))
        return tuple(record_id for record_id, _fields in records)


class FakeMappings:
    def __init__(self) -> None:
        self.detached = []

    async def detach_records(self, **kwargs):
        self.detached.append(kwargs)
        return len(kwargs["record_ids"])


@pytest.mark.asyncio
async def test_cleanup_requires_explicit_approval_before_deleting_records() -> None:
    tenant_id = uuid4()
    shop_id = uuid4()
    feishu = FakeFeishu(shop_id)
    mappings = FakeMappings()

    result = await delete_grouped_duplicate_records(
        feishu=feishu,
        mappings=mappings,
        tenant_id=tenant_id,
        shop_id=shop_id,
        obsolete_platform_application_ids=frozenset({"child-1", "child-2"}),
        grouped_product_updates=(("parent", ("product-1", "product-2")),),
    )

    assert result.updated_count == 1
    assert result.deleted_count == 0
    assert result.pending_record_ids == ("rec-child-1", "rec-child-2")
    assert feishu.updated == [
        [("rec-parent", {"商品ID": ["product-1", "product-2"]})]
    ]
    assert feishu.deleted == []
    assert mappings.detached == []


@pytest.mark.asyncio
async def test_cleanup_deletes_reviewed_records_when_explicitly_allowed() -> None:
    tenant_id = uuid4()
    shop_id = uuid4()
    feishu = FakeFeishu(shop_id)
    mappings = FakeMappings()

    result = await delete_grouped_duplicate_records(
        feishu=feishu,
        mappings=mappings,
        tenant_id=tenant_id,
        shop_id=shop_id,
        obsolete_platform_application_ids=frozenset({"child-1", "child-2"}),
        allow_delete=True,
    )

    assert result.deleted_count == 2
    assert result.pending_record_ids == ()
    assert feishu.deleted == [["rec-child-1", "rec-child-2"]]
    assert mappings.detached == [
        {
            "tenant_id": tenant_id,
            "shop_id": shop_id,
            "record_ids": ("rec-child-1", "rec-child-2"),
        }
    ]
