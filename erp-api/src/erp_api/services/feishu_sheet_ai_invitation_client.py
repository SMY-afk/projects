from __future__ import annotations

from collections.abc import Collection

from erp_api.services.feishu_sample_client import FeishuSampleClient
from erp_api.services.feishu_sample_errors import FeishuSampleError
from erp_api.services.feishu_sample_fields import FeishuFieldMetadata
from erp_api.services.sample_ai_invitation_mirror import (
    AI_INVITATION_CREATOR_FIELD,
    AI_INVITATION_TIME_FIELD,
)
from erp_api.services.sample_cooperation_parsing import normalize_account_name

SHEET_READ_BATCH_ROWS = 5000


class FeishuSheetAiInvitationClient(FeishuSampleClient):
    def __init__(
        self, *, spreadsheet_token: str, sheet_id: str, app_id: str, app_secret: str
    ) -> None:
        if not spreadsheet_token or not sheet_id:
            raise ValueError("AI invitation sheet token and sheet ID are required.")
        super().__init__(
            app_id=app_id,
            app_secret=app_secret,
            base_token="unused",
            table_id="unused",
        )
        self._spreadsheet_token = spreadsheet_token
        self._sheet_id = sheet_id

    async def list_field_metadata(self) -> dict[str, FeishuFieldMetadata]:
        token = await self.tenant_access_token()
        await self._read_values(token, 1, 1)
        return {
            AI_INVITATION_CREATOR_FIELD: FeishuFieldMetadata(
                "A", AI_INVITATION_CREATOR_FIELD, 1, True
            ),
        }

    async def match_creator_ids(
        self, creator_ids: Collection[str], *, field_name: str
    ) -> frozenset[str]:
        if field_name != AI_INVITATION_CREATOR_FIELD:
            raise ValueError("AI invitation sheet creator field is invalid.")
        requested = {normalize_account_name(value) for value in creator_ids}
        requested.discard("")
        if not requested:
            return frozenset()
        listed = await self.list_creator_ids()
        return frozenset(requested & listed)

    async def list_creator_ids(self) -> frozenset[str]:
        rows = await self._read_all_rows()
        listed: set[str] = set()
        for number, row in enumerate(rows[1:], start=2):
            creator_id = normalize_account_name(row[0] if row else None)
            if not creator_id:
                continue
            if creator_id in listed:
                raise FeishuSampleError(
                    f"AI invitation sheet creator ID is duplicated at row {number}."
                )
            listed.add(creator_id)
        return frozenset(listed)

    async def list_invitation_rows(self) -> tuple[tuple[object, object], ...]:
        """BD-collection-only time source; general cooperation membership is unchanged."""
        rows = await self._read_all_rows(end_column="B")
        return tuple(
            (row[0] if row else None, row[1] if len(row) > 1 else None)
            for row in rows[1:]
        )

    async def _read_all_rows(self, *, end_column: str = "A") -> list[list[object]]:
        token = await self.tenant_access_token()
        row_count = await self._row_count(token)
        if row_count < 1:
            raise FeishuSampleError("AI invitation sheet has no header row.")
        rows: list[list[object]] = []
        revision: int | None = None
        for start in range(1, row_count + 1, SHEET_READ_BATCH_ROWS):
            end = min(start + SHEET_READ_BATCH_ROWS - 1, row_count)
            data = await self._read_values(token, start, end, end_column=end_column)
            current_revision = data.get("revision")
            if isinstance(current_revision, bool) or not isinstance(
                current_revision, int
            ):
                raise FeishuSampleError("AI invitation sheet revision is invalid.")
            if revision is not None and revision != current_revision:
                raise FeishuSampleError("AI invitation sheet changed during reading.")
            revision = current_revision
            values = data.get("valueRange", {}).get("values")
            if not isinstance(values, list) or len(values) != end - start + 1:
                raise FeishuSampleError("AI invitation sheet range is incomplete.")
            if any(not isinstance(row, list) for row in values):
                raise FeishuSampleError("AI invitation sheet row is invalid.")
            rows.extend(values)
        if await self._row_count(token) != row_count:
            raise FeishuSampleError(
                "AI invitation sheet row count changed during reading."
            )
        while len(rows) > 1 and not any(rows[-1][:1]):
            rows.pop()
        return rows

    async def _row_count(self, token: str) -> int:
        data = await self._request(
            "GET",
            f"/open-apis/sheets/v3/spreadsheets/{self._spreadsheet_token}/sheets/query",
            token=token,
        )
        sheets = data.get("sheets")
        if not isinstance(sheets, list):
            raise FeishuSampleError("AI invitation workbook sheet list is invalid.")
        sheet = next(
            (item for item in sheets if item.get("sheet_id") == self._sheet_id),
            None,
        )
        if sheet is None:
            raise FeishuSampleError("AI invitation worksheet was not found.")
        count = sheet.get("grid_properties", {}).get("row_count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise FeishuSampleError("AI invitation worksheet row count is invalid.")
        return count

    async def _read_values(
        self, token: str, start: int, end: int, *, end_column: str = "A"
    ) -> dict[str, object]:
        data = await self._request(
            "GET",
            f"/open-apis/sheets/v2/spreadsheets/{self._spreadsheet_token}/values/"
            f"{self._sheet_id}!A{start}:{end_column}{end}",
            token=token,
        )
        if start == 1:
            values = data.get("valueRange", {}).get("values")
            if (
                not isinstance(values, list)
                or not values
                or not isinstance(values[0], list)
                or values[0][:1] != [AI_INVITATION_CREATOR_FIELD]
            ):
                raise FeishuSampleError("AI invitation sheet headers are invalid.")
            if end_column == "B" and values[0][:2] != [
                AI_INVITATION_CREATOR_FIELD,
                AI_INVITATION_TIME_FIELD,
            ]:
                raise FeishuSampleError("AI invitation sheet time header is invalid.")
        return data
