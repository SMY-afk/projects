import base64
from datetime import date

import pytest

from erp_api.services.tiktok_compass_client import (
    CompassExportFailed,
    HttpTikTokCompassClient,
)


class StubTransport:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    async def request(self, request, *, access_token=None):
        self.requests.append((request, access_token))
        return next(self.responses)


@pytest.mark.asyncio
async def test_creator_export_creates_polls_and_downloads_xlsx() -> None:
    content = b"PK\x03\x04xlsx"
    transport = StubTransport(
        [
            {"data": {"task": {"id": "task-1"}}},
            {"data": {"tasks": [{"id": "task-1", "status": "RUNNING"}]}},
            {
                "data": {
                    "tasks": [
                        {
                            "id": "task-1",
                            "status": "SUCCEEDED",
                            "file_name": "Creator_List_20260826-20260826.xlsx",
                        }
                    ]
                }
            },
            {"data": {"file": {"base64": base64.b64encode(content).decode()}}},
        ]
    )
    sleeps = []
    client = HttpTikTokCompassClient(
        transport, sleep=lambda seconds: _record_sleep(sleeps, seconds)
    )

    result = await client.export_creators(
        "token",
        shop_cipher="cipher",
        window_start=date(2026, 8, 26),
        window_end=date(2026, 8, 26),
    )

    assert result.content == content
    assert result.task_id == "task-1"
    assert result.file_name == "Creator_List_20260826-20260826.xlsx"
    assert sleeps == [2.0]
    create = transport.requests[0][0]
    assert create.path == "/affiliate_seller/202603/compass/offline_task"
    assert create.json_body == {
        "module_type": "CREATOR",
        "window_type": "PAST_24H",
        "end_day": 20260826,
        "plan_type": "ALL",
    }
    assert transport.requests[1][0].query["doc_type"] == "CREATOR"
    assert transport.requests[-1][0].path.endswith("/task-1/file")


@pytest.mark.asyncio
async def test_creator_export_rejects_unsupported_window() -> None:
    client = HttpTikTokCompassClient(StubTransport([]))

    with pytest.raises(ValueError, match="1, 7, or 30"):
        await client.export_creators(
            "token",
            shop_cipher="cipher",
            window_start=date(2026, 8, 25),
            window_end=date(2026, 8, 26),
        )


@pytest.mark.asyncio
async def test_creator_export_surfaces_failed_task() -> None:
    client = HttpTikTokCompassClient(
        StubTransport(
            [
                {"data": {"task": {"id": "task-1"}}},
                {"data": {"tasks": [{"id": "task-1", "status": "FAILED"}]}},
            ]
        )
    )

    with pytest.raises(CompassExportFailed):
        await client.export_creators(
            "token",
            shop_cipher="cipher",
            window_start=date(2026, 8, 26),
            window_end=date(2026, 8, 26),
        )


@pytest.mark.asyncio
async def test_creator_export_reuses_completed_window() -> None:
    content = b"PK\x03\x04xlsx"
    encoded = base64.b64encode(content).decode()
    transport = StubTransport(
        [
            {
                "data": {
                    "tasks": [
                        {
                            "id": "existing",
                            "status": "SUCCEEDED",
                            "file_name": "Transaction_Analysis_Creator_List_20260826-20260826",
                        }
                    ]
                }
            },
            {"data": {"file": {"base64": encoded}}},
        ]
    )
    client = HttpTikTokCompassClient(transport, reuse_existing=True)

    result = await client.export_creators(
        "token",
        shop_cipher="cipher",
        window_start=date(2026, 8, 26),
        window_end=date(2026, 8, 26),
    )

    assert result.task_id == "existing"
    assert result.content == content
    assert all(request.method == "GET" for request, _token in transport.requests)


@pytest.mark.asyncio
async def test_creator_export_rejects_task_for_another_window() -> None:
    client = HttpTikTokCompassClient(
        StubTransport(
            [
                {"data": {"task": {"id": "task-1"}}},
                {
                    "data": {
                        "tasks": [
                            {
                                "id": "task-1",
                                "status": "SUCCEEDED",
                                "file_name": "Creator_List_20260825-20260831.xlsx",
                            }
                        ]
                    }
                },
                {"data": {"file": {"base64": "UEsDBA=="}}},
            ]
        )
    )

    with pytest.raises(Exception, match="window"):
        await client.export_creators(
            "token",
            shop_cipher="cipher",
            window_start=date(2026, 8, 26),
            window_end=date(2026, 9, 1),
        )


async def _record_sleep(values, seconds):
    values.append(seconds)
