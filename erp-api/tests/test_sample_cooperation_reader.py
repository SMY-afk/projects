from types import SimpleNamespace

import pytest

from erp_api.services.feishu_bd_roster_provider import (
    BD_NAME_FIELD,
    BD_PERSON_FIELD,
    BD_STATUS_FIELD,
)
from erp_api.services.feishu_creator_export_service import FEISHU_CREATOR_FIELDS
from erp_api.services.feishu_sample_record_snapshot import (
    FeishuListedRecord,
    FeishuRecordSnapshot,
)
from erp_api.services.sample_cooperation_reader import (
    DAILY_VALID_CREATOR_ACCOUNT_FIELD,
    DAILY_VALID_CREATOR_FIELDS,
    SampleCooperationReader,
)
from erp_api.services.sample_cooperation_rules import (
    BdInvitationProtection,
    CooperationRecipient,
)


def _record(record_id: str, fields: dict) -> FeishuListedRecord:
    return FeishuListedRecord(record_id, FeishuRecordSnapshot(fields))


@pytest.mark.asyncio
async def test_reader_uses_both_views_and_resolves_bd_names_to_open_ids() -> None:
    calls = []

    class Client:
        def __init__(self, records):
            self.records = records

        async def list_record_snapshots(self, **kwargs):
            calls.append(kwargs)
            return self.records

    first = Client(
        (
            _record(
                "rec-a",
                {
                    FEISHU_CREATOR_FIELDS[0]: "creator-one",
                    FEISHU_CREATOR_FIELDS[1]: "Alice",
                    FEISHU_CREATOR_FIELDS[2]: "9.15",
                },
            ),
        )
    )
    second = Client(())
    valid_creators = Client(
        (
            _record(
                "rec-valid",
                {DAILY_VALID_CREATOR_ACCOUNT_FIELD: " @Creator-One\u200b ",
                 "BD负责人": "Alice", "匹配店铺": "跨境3"},
            ),
        )
    )
    roster = Client(
        (
            _record(
                "rec-bd",
                {
                    BD_NAME_FIELD: "Alice",
                    BD_STATUS_FIELD: "在岗",
                    BD_PERSON_FIELD: [{"id": "ou-alice", "name": "Alice"}],
                },
            ),
        )
    )
    reader = SampleCooperationReader(
        (
            SimpleNamespace(label="童车", client=first, view_id="view-a"),
            SimpleNamespace(label="遥控车", client=second, view_id="view-b"),
        ),
        roster,
        valid_creators,
        SimpleNamespace(
            refresh=lambda: _async_value(
                SimpleNamespace(
                    pending_creator_ids=frozenset(),
                    active={
                        "creator-protected": BdInvitationProtection(
                            "rec-protection",
                            "creator-protected",
                            "Alice",
                            None,
                        )
                    }
                )
            )
        ),
    )

    snapshot = await reader.read()

    assert snapshot.rows[0].account_name == "creator-one"
    assert snapshot.recipients["alice"].open_id == "ou-alice"
    assert snapshot.current_bd_names == frozenset({"alice"})
    assert snapshot.valid_creator_ids == frozenset({"creator-one"})
    assert snapshot.protected_creators["creator-protected"].bd_name == "Alice"
    assert calls[:2] == [
        {"view_id": "view-a", "field_names": FEISHU_CREATOR_FIELDS},
        {"view_id": "view-b", "field_names": FEISHU_CREATOR_FIELDS},
    ]
    assert calls[2] == {
        "field_names": DAILY_VALID_CREATOR_FIELDS,
    }
    assert calls[3] == {}

    resolved = await reader.resolve_current_recipient(
        CooperationRecipient("Alice", "ou-old-app")
    )
    assert resolved == CooperationRecipient("Alice", "ou-alice")
    assert calls[4] == {}


@pytest.mark.asyncio
async def test_reader_checks_ai_invitation_membership_for_pending_creators() -> None:
    class Client:
        async def list_record_snapshots(self, **_kwargs):
            return ()

    class AiLookup:
        def __init__(self) -> None:
            self.calls = []

        async def match_creator_ids(self, creator_ids, *, field_name):
            self.calls.append((creator_ids, field_name))
            return frozenset({"creator-one"})

    ai = AiLookup()
    reader = SampleCooperationReader(
        (
            SimpleNamespace(label="童车", client=Client(), view_id="view-a"),
            SimpleNamespace(label="遥控车", client=Client(), view_id="view-b"),
        ),
        Client(),
        Client(),
        ai_invitation_client=ai,
    )

    snapshot = await reader.read(creator_ids=frozenset({"Creator-One"}))

    assert snapshot.ai_invitation_creator_ids == frozenset({"creator-one"})
    assert ai.calls == [(frozenset({"Creator-One"}), "达人ID")]


async def _async_value(value):
    return value
