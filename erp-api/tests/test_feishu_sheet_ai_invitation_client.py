import pytest

from erp_api.services.feishu_sample_errors import FeishuSampleError
from erp_api.services.feishu_sheet_ai_invitation_client import (
    FeishuSheetAiInvitationClient,
)


class _Client(FeishuSheetAiInvitationClient):
    def __init__(self, rows, *, revision=1) -> None:
        super().__init__(
            spreadsheet_token="spreadsheet",
            sheet_id="worksheet",
            app_id="app",
            app_secret="secret",
        )
        self.rows = rows
        self.revision = revision

    async def tenant_access_token(self):
        return "token"

    async def _request(self, method, path, **kwargs):
        assert method == "GET"
        if path.endswith("/sheets/query"):
            return {
                "sheets": [
                    {
                        "sheet_id": "worksheet",
                        "grid_properties": {"row_count": len(self.rows)},
                    }
                ]
            }
        requested = path.rsplit("!A", 1)[1]
        start, end = requested.split(":")
        end = end[1:]
        return {
            "revision": self.revision,
            "valueRange": {"values": self.rows[int(start) - 1 : int(end)]},
        }


@pytest.mark.asyncio
async def test_sheet_matches_creator_ids_without_reading_invitation_times() -> None:
    client = _Client(
        [
            ["达人ID", "最近邀约时间"],
            ["@Creator-One", "2026/09/24 10:24"],
            ["Creator-Two", "2026/09/23 09:30"],
        ]
    )

    fields = await client.list_field_metadata()
    matches = await client.match_creator_ids(
        ["creator-one", "creator-missing"], field_name="达人ID"
    )

    assert fields["达人ID"].field_type == 1
    assert matches == frozenset({"creator-one"})


@pytest.mark.asyncio
async def test_sheet_rejects_duplicate_creator_ids() -> None:
    client = _Client(
        [
            ["达人ID", "最近邀约时间"],
            ["Creator-One", "2026/09/24 10:24"],
            ["@creator-one", "2026/09/24 10:24"],
        ]
    )

    with pytest.raises(FeishuSampleError, match="duplicated"):
        await client.match_creator_ids(["creator-one"], field_name="达人ID")


@pytest.mark.asyncio
async def test_sheet_ignores_blank_row_left_by_deleted_creator() -> None:
    client = _Client(
        [
            ["达人ID", "最近邀约时间"],
            ["Creator-One", "2026/09/24 10:24"],
            [None, None],
            ["Creator-Two", "2026/09/24 10:25"],
        ]
    )

    assert await client.match_creator_ids(
        ["creator-one", "creator-two"], field_name="达人ID"
    ) == frozenset({"creator-one", "creator-two"})


@pytest.mark.asyncio
async def test_sheet_ignores_invitation_time_format() -> None:
    client = _Client([["达人ID", "最近邀约时间"], ["Creator-One", "bad date"]])

    assert await client.match_creator_ids(
        ["creator-one"], field_name="达人ID"
    ) == frozenset({"creator-one"})


@pytest.mark.asyncio
async def test_bd_invitation_source_reads_both_columns_without_changing_membership():
    client = _Client([["达人ID", "最近邀约时间"], ["@Creator-One", "bad date"]])
    assert await client.list_invitation_rows() == (("@Creator-One", "bad date"),)
    assert await client.list_creator_ids() == frozenset({"creator-one"})


@pytest.mark.asyncio
async def test_bd_invitation_source_rejects_unverified_time_column():
    client = _Client([["达人ID", "采集时间"], ["@Creator-One", "2026/09/20 11:32"]])
    with pytest.raises(FeishuSampleError, match="time header"):
        await client.list_invitation_rows()
