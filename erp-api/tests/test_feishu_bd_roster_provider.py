from uuid import uuid4

import pytest

from erp_api.services.feishu_bd_roster_provider import (
    REQUIRED_ROSTER_FIELDS,
    FeishuBdRosterProvider,
)
from erp_api.services.feishu_sample_fields import FeishuFieldMetadata
from erp_api.services.feishu_sample_record_snapshot import (
    FeishuListedRecord,
    FeishuRecordSnapshot,
)


class Client:
    def __init__(self, records, *, person_type=11) -> None:
        self.records = records
        self.person_type = person_type

    async def validate_required_fields(self, required):
        assert required == REQUIRED_ROSTER_FIELDS
        return {
            name: FeishuFieldMetadata(
                f"field-{index}",
                name,
                self.person_type if name == "飞书人员" else 1,
                name == "BD姓名",
            )
            for index, name in enumerate(required)
        }

    async def list_record_snapshots(self):
        return self.records


def _record(record_id, name, person_id, *, pending="0", status="在岗"):
    return FeishuListedRecord(
        record_id,
        FeishuRecordSnapshot(
            {
                "BD姓名": name,
                "飞书人员": [{"id": person_id, "name": name}],
                "负责品类": "测试，遥控车",
                "在岗状态": status,
                "当前待处理量": pending,
            }
        ),
    )


@pytest.mark.asyncio
async def test_reads_only_configured_real_bd_members() -> None:
    client = Client(
        (
            _record("rec-1", "李鸿程", "ou-1"),
            _record("rec-2", "吴洵涛", "ou-2", pending=2),
            _record("rec-other", "Other", "ou-other"),
            FeishuListedRecord("rec-empty", FeishuRecordSnapshot({})),
        )
    )
    provider = FeishuBdRosterProvider(
        client,
        allowed_bd_names={"李鸿程", "吴洵涛"},
        default_capacity=10,
    )

    members = await provider.list_members(uuid4(), uuid4())

    assert [member.name for member in members] == ["李鸿程", "吴洵涛"]
    assert members[0].recipient_open_id == "ou-1"
    assert members[0].categories == {"测试", "遥控车"}
    assert members[1].current_pending == 2

    assert await provider.list_recipient_open_ids() == {
        "李鸿程": "ou-1",
        "吴洵涛": "ou-2",
    }


@pytest.mark.asyncio
async def test_rejects_text_person_field_before_reading_members() -> None:
    provider = FeishuBdRosterProvider(
        Client((), person_type=1),
        allowed_bd_names={"李鸿程"},
        default_capacity=10,
    )

    with pytest.raises(ValueError, match="person field type"):
        await provider.list_members(uuid4(), uuid4())


@pytest.mark.asyncio
async def test_rejects_missing_configured_member() -> None:
    provider = FeishuBdRosterProvider(
        Client((_record("rec-1", "李鸿程", "ou-1"),)),
        allowed_bd_names={"李鸿程", "吴洵涛"},
        default_capacity=10,
    )

    with pytest.raises(ValueError, match="missing configured members"):
        await provider.list_members(uuid4(), uuid4())


@pytest.mark.asyncio
async def test_rejects_fractional_pending_count() -> None:
    provider = FeishuBdRosterProvider(
        Client((_record("rec-1", "李鸿程", "ou-1", pending="1.5"),)),
        allowed_bd_names={"李鸿程"},
        default_capacity=10,
    )

    with pytest.raises(ValueError, match="pending count"):
        await provider.list_members(uuid4(), uuid4())


@pytest.mark.asyncio
async def test_uses_roster_name_when_feishu_person_has_a_nickname() -> None:
    record = _record("rec-1", "吴洵涛", "ou-wuxuntao")
    record.snapshot.fields["飞书人员"][0]["name"] = "十四"
    provider = FeishuBdRosterProvider(
        Client((record,)),
        allowed_bd_names={"吴洵涛"},
        default_capacity=10,
    )

    members = await provider.list_members(uuid4(), uuid4())

    assert members[0].name == "吴洵涛"
    assert members[0].recipient_open_id == "ou-wuxuntao"
