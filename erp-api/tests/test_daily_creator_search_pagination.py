"""Only unfiltered read-only POST search may collect complete master pages."""

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from scripts import daily_valid_creator_accounts as accounts


def row(record_id, account="abc"):
    return {"record_id": record_id, "fields": {"帐号名称": [{"text": account}],
            "BD负责人": [{"text": "BD"}], "同意样品日期": "2026-10-14",
            "合作店铺": ["跨境12店"]}}


class SearchClient:
    def __init__(self, pages):
        self.pages = deepcopy(pages)
        self.calls = []

    async def request_json(self, method, path, **kwargs):
        assert method == "POST" and path.endswith("/records/search")
        assert kwargs["retry_mode"] == "idempotent"
        assert kwargs["headers"] == {"Authorization": "test-header-not-real"}
        assert kwargs["json"] == {"field_names": list(accounts.ACCOUNT_SOURCE_FIELDS)}
        assert set(kwargs["params"]) <= {"page_size", "page_token"}
        assert kwargs["params"]["page_size"] in {accounts.MASTER_SEARCH_PAGE_SIZE, 1}
        self.calls.append((method, path, kwargs))
        return {"data": self.pages.pop(0)}

    async def list_records(self, *_args, **_kwargs):
        pytest.fail("GET list_records must not be mixed with POST search cursors")


@pytest.fixture(autouse=True)
def identity(monkeypatch):
    monkeypatch.setattr(accounts, "_verify_source_identity",
                        AsyncMock(return_value={"Authorization": "test-header-not-real"}))


@pytest.mark.asyncio
async def test_complete_unfiltered_search_and_final_size_one_total_check():
    client = SearchClient([
        {"total": 3, "items": [row("one"), {"record_id": "blank", "fields": {}}],
         "has_more": True, "page_token": "search-cursor"},
        {"total": 3, "items": [row("two", "xyz")], "has_more": False},
        {"total": 3, "items": [row("one")], "has_more": True, "page_token": "unused"},
    ])
    result = await accounts.read_accounts(client)
    assert result["total"] == 2 and result["captured_total"] == result["final_total"] == 3
    assert result["empty_placeholders"] == 1
    assert result["terminal_confirmed"] is result["unique_record_ids"] is True
    assert result["scope"] == "physical_table"
    assert result["rows"][0] == {"accountName": "abc", "bdOwner": "BD",
                                   "sampleApprovedDate": "2026-10-14",
                                   "cooperationShop": "跨境12店"}
    assert client.calls[0][2]["params"] == {"page_size": accounts.MASTER_SEARCH_PAGE_SIZE}
    assert client.calls[1][2]["params"] == {"page_size": accounts.MASTER_SEARCH_PAGE_SIZE,
                                          "page_token": "search-cursor"}
    assert client.calls[2][2]["params"] == {"page_size": 1}


@pytest.mark.asyncio
@pytest.mark.parametrize("failure, expected", [
    ("total", "total changed"), ("final-total", "total changed"),
    ("missing-page", "capture is incomplete"), ("duplicate-id", "duplicated"),
    ("cursor", "pagination is incomplete"), ("repeated-cursor", "pagination is incomplete"),
    ("missing-terminal", "response is invalid"), ("bad-id", "duplicated"),
])
async def test_unfiltered_search_incompleteness_never_returns_partial_accounts(failure, expected):
    first = {"total": 2, "items": [row("one")], "has_more": True, "page_token": "next"}
    second = {"total": 2, "items": [row("two")], "has_more": False}
    final = {"total": 2, "items": [row("one")], "has_more": True, "page_token": "unused"}
    if failure == "total":
        second["total"] = 3
    elif failure == "final-total":
        final["total"] = 3
    elif failure == "missing-page":
        first["has_more"] = False
    elif failure == "duplicate-id":
        second["items"] = [row("one")]
    elif failure == "cursor":
        first.pop("page_token")
    elif failure == "repeated-cursor":
        second.update(has_more=True, page_token="next")
    elif failure == "missing-terminal":
        first.pop("has_more")
    else:
        first["items"][0]["record_id"] = 1
    with pytest.raises(ValueError, match=expected):
        await accounts.read_accounts(SearchClient([first, second, final]))
