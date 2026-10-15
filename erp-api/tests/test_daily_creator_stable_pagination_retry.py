import pytest

from scripts import daily_valid_creator_io as source


@pytest.mark.asyncio
async def test_changed_pagination_restarts_once_before_any_write(monkeypatch):
    calls = []

    async def read(client):
        calls.append(client)
        if len(calls) == 1:
            raise ValueError("Cooperation account total changed during pagination")
        return {"total": 1, "rows": [{"accountName": "abc"}]}

    monkeypatch.setattr(source, "read_creator_tables", read)
    assert await source._read_stable_accounts("client") == {"total": 1, "rows": [{"accountName": "abc"}]}
    assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("reason,expected", [
    ("Cooperation account total changed during pagination", 2),
    ("Cooperation account pagination is incomplete", 1)])
async def test_unstable_or_other_failure_still_blocks_source(monkeypatch, reason, expected):
    calls = []

    async def read(client):
        calls.append(client)
        raise ValueError(reason)

    monkeypatch.setattr(source, "read_creator_tables", read)
    with pytest.raises(ValueError, match=reason):
        await source._read_stable_accounts("client")
    assert len(calls) == expected
