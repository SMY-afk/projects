from __future__ import annotations

from collections.abc import Collection

from erp_api.services.feishu_sample_batch_client import (
    FEISHU_BATCH_RECORD_LIMIT,
    FeishuSampleBatchClient,
)
from erp_api.services.feishu_sample_errors import FeishuSampleError
from erp_api.services.sample_cooperation_parsing import normalize_account_name

FEISHU_SEARCH_CONDITION_LIMIT = 50
CREATOR_IDS_PER_SEARCH = FEISHU_SEARCH_CONDITION_LIMIT // 2


class FeishuCreatorLookupClient(FeishuSampleBatchClient):
    async def match_creator_ids(
        self,
        creator_ids: Collection[str],
        *,
        field_name: str,
    ) -> frozenset[str]:
        requested = tuple(
            dict.fromkeys(
                creator_id
                for value in creator_ids
                if (creator_id := normalize_account_name(value))
            )
        )
        if not requested:
            return frozenset()
        token = await self.tenant_access_token()
        matches: set[str] = set()
        for offset in range(0, len(requested), CREATOR_IDS_PER_SEARCH):
            chunk = requested[offset : offset + CREATOR_IDS_PER_SEARCH]
            query_values = tuple(
                dict.fromkeys(
                    candidate
                    for creator_id in chunk
                    for candidate in (creator_id, f"@{creator_id}")
                )
            )
            matches.update(
                await self._search_chunk(
                    token,
                    field_name=field_name,
                    query_values=query_values,
                    requested=frozenset(chunk),
                )
            )
        return frozenset(matches)

    async def _search_chunk(
        self,
        token: str,
        *,
        field_name: str,
        query_values: tuple[str, ...],
        requested: frozenset[str],
    ) -> frozenset[str]:
        page_token: str | None = None
        seen_page_tokens: set[str] = set()
        matches: set[str] = set()
        while True:
            params: dict[str, object] = {"page_size": FEISHU_BATCH_RECORD_LIMIT}
            if page_token:
                params["page_token"] = page_token
            data = await self._request(
                "POST",
                f"{self._record_path()}/search",
                token=token,
                retry_mode="rate_limit",
                params=params,
                json={
                    "field_names": [field_name],
                    "filter": {
                        "conjunction": "or",
                        "conditions": [
                            {
                                "field_name": field_name,
                                "operator": "is",
                                "value": [value],
                            }
                            for value in query_values
                        ],
                    },
                },
            )
            total = data.get("total")
            items = data.get("items")
            if items is None and total == 0:
                items = []
            if not isinstance(items, list):
                raise FeishuSampleError("Feishu creator search result is invalid.")
            for item in items:
                fields = item.get("fields") if isinstance(item, dict) else None
                creator_id = normalize_account_name(
                    fields.get(field_name) if isinstance(fields, dict) else None
                )
                if creator_id in requested:
                    matches.add(creator_id)
            has_more = data.get("has_more")
            if not isinstance(has_more, bool):
                raise FeishuSampleError("Feishu creator search pagination is invalid.")
            if not has_more:
                break
            next_token = data.get("page_token")
            if (
                not isinstance(next_token, str)
                or not next_token
                or next_token in seen_page_tokens
            ):
                raise FeishuSampleError(
                    "Feishu creator search pagination is incomplete."
                )
            seen_page_tokens.add(next_token)
            page_token = next_token
        return frozenset(matches)
