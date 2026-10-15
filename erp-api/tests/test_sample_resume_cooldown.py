import argparse
import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import run_remote_sample_capture_loop as loop


@pytest.mark.asyncio
@pytest.mark.parametrize("shop", list(loop.SHOPS))
async def test_resume_honors_recent_free_success_before_browser_work(shop):
    args = argparse.Namespace(
        shop_label=shop, once=False, interval_seconds=300, status_dir=Path("unused")
    )
    with (
        patch.object(loop, "_write_status"),
        patch.object(loop, "initial_free_delay", return_value=240) as delay,
        patch.object(loop.asyncio, "sleep", side_effect=asyncio.CancelledError),
        patch.object(loop, "cycle") as capture,
        pytest.raises(asyncio.CancelledError),
    ):
        await loop.run(args)
    delay.assert_called_once_with(shop, 300)
    capture.assert_not_called()
