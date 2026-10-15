import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from scripts import send_local_sample_capture as sender


@pytest.mark.parametrize("receipt_mode", ["queued", "deferred"])
def test_sender_requires_requested_processing_ack(
    monkeypatch, tmp_path: Path, receipt_mode: str
) -> None:
    batch = SimpleNamespace(path=tmp_path / "batch-1", page_count=1, expected_total=1, captured_total=1)
    page = SimpleNamespace(
        payload={
            "data": {
                "sample_applications": [
                    {
                        "id": "application-1",
                        "status": "PENDING",
                        "creator": {"id": "creator-1"},
                        "product": {"id": "product-1"},
                    }
                ],
                "next_page_token": None,
                "total_count": 1,
            }
        },
        request_id="request-1",
        request_page=1,
        request_cursor='[["cur_page",1]]',
        response_has_more=False,
        response_total_count=1,
        response_observed_at=datetime(2026, 10, 9, tzinfo=UTC),
    )
    acknowledged = []
    headers_seen = []

    class Store:
        def __init__(self, *_args):
            pass

        def recover_completed(self):
            return batch

        def load_pages(self, _batch):
            return [page]

        def acknowledge(self, _batch):
            acknowledged.append(True)

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def post(self, _url, *, headers, **_kwargs):
            headers_seen.append(headers)
            return SimpleNamespace(
                status_code=202,
                json=lambda: {
                    "status": "stored",
                    "batch_id": str(uuid4()),
                    "processing": receipt_mode,
                    "duplicate": False,
                },
            )

    monkeypatch.setattr(sender, "SampleRawBatchStore", Store)
    monkeypatch.setattr(sender.httpx, "AsyncClient", Client)
    token_file = tmp_path / "token.txt"
    token_file.write_text("x" * 40, encoding="utf-8")
    args = SimpleNamespace(
        spool_root=tmp_path,
        shop_id=uuid4(),
        environment_id="1234567890",
        platform_shop_id="shop-1",
        verify_batch_sequence=None,
        capture=False,
        token_file=token_file,
        api_url="https://example.com/api/internal/sample-captures/batches",
        processing_mode="enqueue",
    )
    if receipt_mode == "queued":
        asyncio.run(sender.run(args))
        assert acknowledged == [True]
    else:
        with pytest.raises(RuntimeError, match="requested business processing"):
            asyncio.run(sender.run(args))
        assert not acknowledged
    assert headers_seen[0]["x-erp-capture-process"] == "enqueue"
