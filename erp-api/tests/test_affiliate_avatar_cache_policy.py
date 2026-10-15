import sqlite3

import pytest
from sqlalchemy import literal, select
from sqlalchemy.dialects.sqlite import dialect

from erp_api.services.affiliate_avatar_cache_policy import (
    cached_avatar_expression,
    retained_avatar,
)

CACHED = "https://example.invalid/configure-resource" + "a" * 64 + ".jpg"
REMOTE = "https://p16-sign.tiktokcdn-us.com/creator.jpg?x-expires=1"


@pytest.mark.parametrize("current,incoming,expected", [
    (CACHED, REMOTE, CACHED),
    (CACHED, None, CACHED),
    (REMOTE, None, REMOTE),
    (None, REMOTE, REMOTE),
    (REMOTE, CACHED, CACHED),
    (None, None, None),
])
def test_automatic_sync_keeps_a_working_cached_avatar(current, incoming, expected):
    assert retained_avatar(current, incoming) == expected
    statement = select(cached_avatar_expression(literal(current), literal(incoming)))
    compiled = str(statement.compile(dialect=dialect(), compile_kwargs={"literal_binds": True}))
    with sqlite3.connect(":memory:") as connection:
        assert connection.execute(compiled).fetchone()[0] == expected


def test_unrelated_asset_host_does_not_block_a_new_official_avatar():
    external = CACHED.replace("wanju-erp.hxwkedu.com", "unrelated.example")
    assert retained_avatar(external, REMOTE) == REMOTE
