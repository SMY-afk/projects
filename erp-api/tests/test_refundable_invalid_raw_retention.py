import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from backend.app.services.refundable_sample_capture import _capture_tab


@pytest.mark.asyncio
async def test_identity_failure_keeps_raw_page_but_cannot_complete_or_publish():
    persisted = []

    class Tab:
        def filter(self, **kwargs): return self
        async def wait_for(self, **kwargs): pass
        async def count(self): return 1
        async def get_attribute(self, key): return "false"
        async def click(self, **kwargs): pass

    class Panel:
        def get_by_role(self, role, **kwargs): return Tab()

    item = {"apply_id": "100", "creator_id": None, "creator_name": "verified.account"}
    payload = {"code": 0, "data": {"apply_records": [item], "total_count": 1}}

    async def body(): return payload
    async def header(_key): return "request-id"

    response = SimpleNamespace(url="https://affiliate-us.tiktok.com/api/v1/affiliate/sample/refundable/apply/list",
        status=200, json=body, header_value=header,
        request=SimpleNamespace(method="POST", post_data=json.dumps({
            "tab_type": 3, "cur_page": 1, "page_size": 50, "search_param": {},
        })))

    class Page:
        @asynccontextmanager
        async def expect_response(self, predicate, **kwargs):
            assert predicate(response)
            yield SimpleNamespace(value=asyncio.sleep(0, result=response))

    store = SimpleNamespace(
        abandon_capturing=lambda *_: None, start_batch=lambda: 1,
        persist_page=lambda *args, **kwargs: persisted.append((args, kwargs)),
        complete_batch=lambda *_args, **_kwargs: pytest.fail("Invalid identity must not complete the batch"),
    )
    with pytest.raises(ValueError, match="stable identity"):
        await _capture_tab(Page(), store, 3, 5, "endpoint", "shop", "host", scope=Panel())
    assert len(persisted) == 1
    assert persisted[0][0][2]["refundable_response"] == payload
