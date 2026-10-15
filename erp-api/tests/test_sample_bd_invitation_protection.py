from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from erp_api.services.feishu_sample_record_snapshot import (
    FeishuListedRecord,
    FeishuRecordSnapshot,
)
from erp_api.services.sample_bd_invitation_parsing import split_creator_ids
from erp_api.services.sample_bd_invitation_protection import (
    BD_INVITATION_CREATOR_FIELD,
    BD_INVITATION_ORIGINAL_SUBMITTER_FIELD,
    BD_INVITATION_OWNER_FIELD,
    BD_INVITATION_REMARK_FIELD,
    BdInvitationLookupSource,
    SampleBdInvitationProtectionService,
)
from erp_api.services.sample_bd_invitation_submission import (
    BD_INVITATION_FORM_ENTRY_CREATOR,
)
from erp_api.services.sample_cooperation_parsing import normalize_account_name
from erp_api.workers.sample_feishu_maintenance_jobs import (
    cleanup_bd_invitation_protection_job,
)


def _record(
    record_id: str,
    creator_id: object,
    bd_name: object,
    created_at: datetime | None,
    remark: object | None = None,
    original_submitter: object | None = None,
    creator_name: str | None = "Original User",
) -> FeishuListedRecord:
    fields = {
        BD_INVITATION_CREATOR_FIELD: creator_id,
        BD_INVITATION_OWNER_FIELD: bd_name,
    }
    if remark is not None:
        fields[BD_INVITATION_REMARK_FIELD] = remark
    if original_submitter is not None:
        fields[BD_INVITATION_ORIGINAL_SUBMITTER_FIELD] = original_submitter
    return FeishuListedRecord(
        record_id,
        FeishuRecordSnapshot(
            fields,
            created_at=created_at,
            creator_name=creator_name,
        ),
    )


class _Client:
    def __init__(self, records) -> None:
        self.records = records
        self.list_calls = []
        self.deleted = []
        self.remark_updates = []
        self.split_updates = []
        self.invitation_creates = []

    async def list_record_snapshots(self, **kwargs):
        self.list_calls.append(kwargs)
        return self.records

    async def batch_delete_records(self, record_ids):
        self.deleted.append(tuple(record_ids))
        return tuple(record_ids)

    async def batch_update_remarks(self, records):
        self.remark_updates.append(tuple(records))
        return tuple(record_id for record_id, _remark in records)

    async def batch_update_split_records(self, records):
        self.split_updates.append(tuple(records))
        return tuple(record_id for record_id, _creator_id, _submitter in records)

    async def batch_create_invitations(self, records):
        self.invitation_creates.append(tuple(records))
        return tuple(f"new-{index}" for index, _record in enumerate(records))


class _LookupClient:
    def __init__(self, records) -> None:
        self.records = records
        self.match_calls = []

    async def list_invitation_rows(self):
        return tuple(
            (record.snapshot.fields.get("达人ID"), "2026/09/20 10:00")
            for record in self.records
        )

    async def match_creator_ids(self, creator_ids, *, field_name):
        self.match_calls.append((creator_ids, field_name))
        return frozenset(
            creator_id
            for record in self.records
            if (
                creator_id := normalize_account_name(
                    record.snapshot.fields.get(field_name)
                )
            )
            and creator_id in creator_ids
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "creator_id",
    (
        BD_INVITATION_FORM_ENTRY_CREATOR,
        "👉请点击“bd填写入口”链接填写",
    ),
)
async def test_refresh_keeps_fixed_form_entry_outside_business_rules(
    creator_id: str,
) -> None:
    now = datetime(2026, 9, 22, 6, tzinfo=UTC)
    client = _Client(
        (
            _record(
                "rec-form-entry",
                creator_id,
                None,
                now - timedelta(days=30),
            ),
        )
    )

    result = await SampleBdInvitationProtectionService(
        client, clock=lambda: now
    ).refresh()

    assert result.active == {}
    assert result.deleted_count == 0
    assert result.updated_count == 0
    assert client.deleted == []
    assert client.remark_updates == []


@pytest.mark.asyncio
async def test_refresh_keeps_seven_day_rows_and_deletes_expired_rows() -> None:
    now = datetime(2026, 9, 22, 6, tzinfo=UTC)
    client = _Client(
        (
            _record(
                "rec-active", " @Creator-One\u200b ", "Alice", now - timedelta(days=6)
            ),
            _record("rec-expired", "creator-two", "Bob", now - timedelta(days=7)),
        )
    )
    service = SampleBdInvitationProtectionService(client, clock=lambda: now)

    result = await service.refresh()

    assert result.deleted_count == 1
    assert result.updated_count == 1
    assert result.active["creator-one"].bd_name == "Alice"
    assert result.active["creator-one"].expires_at == now + timedelta(days=1)
    assert client.deleted == [("rec-expired",)]
    assert client.remark_updates == [
        (("rec-active", "未命中配置的数据源；保护原BD归属；按创建时间保存7天"),)
    ]
    assert client.list_calls == [
        {
            "field_names": (
                BD_INVITATION_CREATOR_FIELD,
                BD_INVITATION_OWNER_FIELD,
                BD_INVITATION_REMARK_FIELD,
                BD_INVITATION_ORIGINAL_SUBMITTER_FIELD,
            )
        }
    ]


@pytest.mark.asyncio
async def test_refresh_keeps_source_hit_visible_without_protecting_owner() -> None:
    now = datetime(2026, 9, 22, 6, tzinfo=UTC)
    client = _Client(
        (_record("rec-hit", "Creator-One", "Alice", now - timedelta(hours=23)),)
    )
    lookup = _LookupClient(
        (
            _record(
                "rec-valid",
                " @creator-one\u200b ",
                None,
                None,
            ),
        )
    )
    service = SampleBdInvitationProtectionService(
        client,
        lookup_sources=(
            BdInvitationLookupSource(
                "（每日更新）有效达人",
                lookup,
                BD_INVITATION_CREATOR_FIELD,
            ),
        ),
        unavailable_sources=("AI邀约表",),
        clock=lambda: now,
    )

    result = await service.refresh()

    assert result.deleted_count == 0
    assert result.updated_count == 1
    assert result.active == {}
    assert client.remark_updates == [
        (
            (
                "rec-hit",
                "命中：（每日更新）有效达人；已有BD合作，不重新自动分配；按创建时间保存24小时",
            ),
        )
    ]
    assert lookup.match_calls == [
        (frozenset({"creator-one"}), BD_INVITATION_CREATOR_FIELD)
    ]


@pytest.mark.parametrize(
    ("matched_sources", "expected"),
    [
        (
            ("AI邀约表",),
            "命中：AI邀约表；按原有前置规则判断是否可分配；按创建时间保存24小时",
        ),
        (
            ("（每日更新）有效达人", "AI邀约表"),
            "命中：（每日更新）有效达人、AI邀约表；已有BD合作，不重新自动分配；按创建时间保存24小时",
        ),
    ],
)
def test_source_hit_remark_describes_assignment_rule(
    matched_sources: tuple[str, ...], expected: str
) -> None:
    from erp_api.services.sample_bd_invitation_protection import _protection_remark

    assert _protection_remark(matched_sources, matched_sources, ()) == expected


@pytest.mark.asyncio
async def test_refresh_deletes_source_hit_after_24_hours() -> None:
    now = datetime(2026, 9, 22, 6, tzinfo=UTC)
    client = _Client(
        (_record("rec-hit", "creator-one", "Alice", now - timedelta(hours=24)),)
    )
    lookup = _LookupClient((_record("rec-valid", "creator-one", None, None),))
    service = SampleBdInvitationProtectionService(
        client,
        lookup_sources=(
            BdInvitationLookupSource(
                "AI邀约表",
                lookup,
                BD_INVITATION_CREATOR_FIELD,
            ),
        ),
        clock=lambda: now,
    )

    result = await service.refresh()

    assert result.active == {}
    assert result.deleted_count == 1
    assert result.updated_count == 0
    assert client.deleted == [("rec-hit",)]


@pytest.mark.asyncio
async def test_refresh_rejects_duplicate_creator_ids() -> None:
    now = datetime(2026, 9, 22, 6, tzinfo=UTC)
    client = _Client(
        (
            _record("rec-a", "Creator-One", "Alice", now),
            _record("rec-b", "creator-one", "Bob", now),
        )
    )

    with pytest.raises(RuntimeError, match="duplicated"):
        await SampleBdInvitationProtectionService(client, clock=lambda: now).refresh()


@pytest.mark.asyncio
async def test_refresh_accepts_duplicate_creator_ids_for_same_bd() -> None:
    now = datetime(2026, 9, 22, 6, tzinfo=UTC)
    client = _Client(
        (
            _record("rec-older", "Creator-One", "Alice", now - timedelta(hours=1)),
            _record("rec-newer", "creator-one", "Alice", now),
        )
    )

    result = await SampleBdInvitationProtectionService(
        client, clock=lambda: now
    ).refresh()

    assert result.active["creator-one"].record_id == "rec-newer"
    assert result.active["creator-one"].bd_name == "Alice"


@pytest.mark.asyncio
async def test_cleanup_job_uses_configured_protection_service() -> None:
    service = SimpleNamespace(
        refresh=lambda **kwargs: _async_value(SimpleNamespace(deleted_count=2))
    )

    assert (
        await cleanup_bd_invitation_protection_job(
            {"sample_bd_invitation_protection_service": service}
        )
        == 2
    )


def test_split_creator_ids_accepts_lines_and_common_separators() -> None:
    assert split_creator_ids(
        " @Creator-One\ncreator_two，Creator-Three;creator_two "
    ) == (
        "creator-one",
        "creator_two",
        "creator-three",
    )


def test_split_creator_ids_accepts_numbered_lists_and_ignores_empty_markers() -> None:
    assert split_creator_ids(
        "1. @Creator-One\n2、 creator_two\n3) Creator-Three\n4.\n• Creator-Four"
    ) == (
        "creator-one",
        "creator_two",
        "creator-three",
        "creator-four",
    )


def test_split_creator_ids_accepts_compact_numbered_items_on_one_line() -> None:
    assert split_creator_ids("1.E 2.F 3.G") == ("e", "f", "g")


def test_split_creator_ids_removes_accidental_spaces_inside_each_line() -> None:
    assert split_creator_ids("jay alonso\nDuffman 2.0\nmegafinds kenny") == (
        "jayalonso",
        "duffman2.0",
        "megafindskenny",
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Creator-A\nCreator-B\nCreator-C", ("creator-a", "creator-b", "creator-c")),
        ("1.Creator-A\n2.Creator-B", ("creator-a", "creator-b")),
    ],
)
def test_split_creator_ids_accepts_bd_multiline_formats(
    value: str, expected: tuple[str, ...]
) -> None:
    assert split_creator_ids(value) == expected


@pytest.mark.asyncio
async def test_refresh_splits_batch_submission_into_one_record_per_creator() -> None:
    now = datetime(2026, 9, 22, 6, tzinfo=UTC)
    initial = (
        _record(
            "rec-batch",
            "Creator-One\n@Creator-Two，creator-three",
            "Alice",
            now - timedelta(hours=1),
            creator_name="Original User",
        ),
    )
    expanded = (
        _record(
            "rec-batch",
            "creator-one",
            "Alice",
            now - timedelta(hours=1),
            original_submitter="Original User",
        ),
        _record(
            "rec-two",
            "creator-two",
            "Alice",
            now,
            original_submitter="Original User",
        ),
        _record(
            "rec-three",
            "creator-three",
            "Alice",
            now,
            original_submitter="Original User",
        ),
    )

    class _ExpandingClient(_Client):
        async def list_record_snapshots(self, **kwargs):
            self.list_calls.append(kwargs)
            return initial if len(self.list_calls) == 1 else expanded

    client = _ExpandingClient(initial)
    result = await SampleBdInvitationProtectionService(
        client, clock=lambda: now
    ).refresh()

    assert client.split_updates == [(("rec-batch", "creator-one", "Original User"),)]
    assert client.invitation_creates == [
        (
            ("creator-two", "Alice", "Original User"),
            ("creator-three", "Alice", "Original User"),
        )
    ]
    assert set(result.active) == {"creator-one", "creator-two", "creator-three"}


@pytest.mark.asyncio
async def test_refresh_normalizes_accidental_space_without_creating_extra_rows() -> (
    None
):
    now = datetime(2026, 9, 22, 6, tzinfo=UTC)
    initial = (
        _record(
            "rec-space",
            "megafinds kenny",
            "Alice",
            now - timedelta(hours=1),
            creator_name="Original User",
        ),
    )
    expanded = (
        _record(
            "rec-space",
            "megafindskenny",
            "Alice",
            now - timedelta(hours=1),
            original_submitter="Original User",
        ),
    )

    class _NormalizingClient(_Client):
        async def list_record_snapshots(self, **kwargs):
            self.list_calls.append(kwargs)
            return initial if len(self.list_calls) == 1 else expanded

    client = _NormalizingClient(initial)
    result = await SampleBdInvitationProtectionService(
        client, clock=lambda: now
    ).refresh()

    assert client.split_updates == [(("rec-space", "megafindskenny", "Original User"),)]
    assert client.invitation_creates == []
    assert set(result.active) == {"megafindskenny"}


async def _async_value(value):
    return value
