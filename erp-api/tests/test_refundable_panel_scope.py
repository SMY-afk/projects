import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from backend.app.services.refundable_sample_capture import _capture_tab


@pytest.mark.asyncio
@pytest.mark.parametrize("initial", [False, True])
async def test_status_controls_are_scoped_to_the_refundable_panel(initial):
    class Tab:
        def filter(self, **kwargs):
            return self

        async def count(self):
            return 1

        async def wait_for(self, **kwargs):
            pass

        async def get_attribute(self, key):
            return "true" if initial else "false"

        async def click(self, **kwargs):
            assert not initial, "Do not click the already selected source tab twice"

    class Panel:
        def get_by_role(self, role, **kwargs):
            assert role == "tab"
            return Tab()

    async def payload():
        return {"code": 0, "data": {"apply_records": [], "total_count": 0}}

    async def header(key):
        return "request-id"

    response = SimpleNamespace(
        url="https://affiliate.tiktokshopglobalselling.com/api/v1/affiliate/sample/refundable/apply/list",
        status=200, json=payload, header_value=header,
        request=SimpleNamespace(method="POST", post_data=json.dumps({
            "tab_type": 4, "cur_page": 1, "page_size": 50, "search_param": {}})),
    )

    class Page:
        def get_by_role(self, *args, **kwargs):
            raise AssertionError("Global tab lookup can match the free panel")

        @asynccontextmanager
        async def expect_response(self, predicate, **kwargs):
            assert not initial, "The initial source response must be reused"
            assert predicate(response)
            yield SimpleNamespace(value=asyncio.sleep(0, result=response))

    store = SimpleNamespace(
        abandon_capturing=lambda *a: None, start_batch=lambda: 1,
        persist_page=lambda *a, **k: None,
        complete_batch=lambda *a, **k: k,
    )
    result = await _capture_tab(Page(), store, 4, 5, "endpoint", "shop", "host", scope=Panel(),
                                initial_response=response if initial else None)
    assert result["terminal_confirmed"] is True
    assert result["expected_total"] == result["captured_total"] == 0
