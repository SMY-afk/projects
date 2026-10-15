from datetime import date
from types import SimpleNamespace
from uuid import UUID

import pytest

from backend.app.services.affiliate_idle_availability import (
    availability_probe_stagger_seconds,
    refresh_idle_availability,
    validate_detected_dates,
)


def test_idle_availability_requires_both_live_resource_dates() -> None:
    with pytest.raises(RuntimeError, match="videos"):
        validate_detected_dates(
            {},
            {"creators": date(2026, 9, 19)},
        )


def test_idle_availability_rejects_date_regression() -> None:
    with pytest.raises(RuntimeError, match="creators"):
        validate_detected_dates(
            {"creators": date(2026, 9, 19), "videos": date(2026, 9, 17)},
            {"creators": date(2026, 9, 18), "videos": date(2026, 9, 17)},
        )


def test_idle_availability_accepts_complete_non_regressing_live_dates() -> None:
    detected = {
        "creators": date(2026, 9, 19),
        "videos": date(2026, 9, 18),
    }

    assert (
        validate_detected_dates(
            {"creators": date(2026, 9, 18), "videos": date(2026, 9, 17)},
            detected,
        )
        == detected
    )


def test_idle_availability_probe_stagger_is_stable_and_bounded() -> None:
    shop_id = UUID("eb7678c2-67d6-5446-85f0-dc8fba9b75d6")

    assert availability_probe_stagger_seconds(shop_id) == 29.0


@pytest.mark.asyncio
async def test_idle_probe_opens_and_closes_only_its_own_resource_pages(
    monkeypatch,
) -> None:
    from backend.app.services import affiliate_idle_availability as module

    expected = "9121478993551097445"
    sample_page = SimpleNamespace(
        url=f"https://affiliate.tiktokshopglobalselling.com/affiliate/sample/sample-request?shop_id={expected}"
    )
    created = [object()]
    context = SimpleNamespace(pages=[sample_page])
    browser = SimpleNamespace(contexts=[context])
    events = []

    class Playwright:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *_):
            return None

    async def connect(*_):
        return browser

    async def ensure(_):
        events.append("open")
        return created

    async def detect(*_, **__):
        events.append("detect")
        return {"creators": date(2026, 10, 4), "videos": date(2026, 10, 2)}

    async def close(pages):
        assert pages is created
        events.append("close")

    class Repository:
        async def get(self, *_):
            return SimpleNamespace(latest_available_dates={})

        async def record(self, *_args, **_kwargs):
            events.append("record")

        async def record_observation(self, *_):
            pass

    monkeypatch.setattr(module, "async_playwright", Playwright)
    monkeypatch.setattr(module.attached_browser, "connect_attached_hubstudio_browser", connect)
    monkeypatch.setattr(
        module,
        "page_hygiene",
        SimpleNamespace(
            ensure_affiliate_resource_pages=ensure,
            close_collector_pages=close,
        ),
        raising=False,
    )
    monkeypatch.setattr(module, "detect_initial_selectable_dates", detect)

    result = await refresh_idle_availability(
        "http://127.0.0.1:12345", UUID(int=1), UUID(int=2), expected, object(), Repository()
    )

    assert result == {"creators": date(2026, 10, 4), "videos": date(2026, 10, 2)}
    assert events == ["open", "detect", "record", "close"]
