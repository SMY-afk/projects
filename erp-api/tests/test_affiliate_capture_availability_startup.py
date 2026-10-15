import asyncio
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

from backend.app.services import affiliate_capture_availability_startup as startup


def test_restore_rechecks_all_source_dates_even_when_persisted_dates_exist(
    monkeypatch,
) -> None:
    tenant_id = uuid4()
    shop_id = uuid4()
    calls = []

    class ReadRepository:
        def __init__(self, database) -> None:
            assert database == "database"

        async def latest_available_dates(self, actual_tenant_id, actual_shop_id):
            assert actual_tenant_id == tenant_id
            assert actual_shop_id == shop_id
            return {
                "creators": date(2026, 9, 18),
                "videos": date(2026, 9, 16),
            }

    class HealthRepository:
        def __init__(self):
            self.observations = {}

        async def get(self, actual_tenant_id, actual_shop_id):
            assert actual_tenant_id == tenant_id
            assert actual_shop_id == shop_id
            return SimpleNamespace(
                latest_available_dates={
                    "creators": date(2026, 9, 18),
                    "videos": date(2026, 9, 16),
                }
            )

        async def record_observation(
            self, actual_tenant_id, actual_shop_id, resource, day
        ):
            assert (actual_tenant_id, actual_shop_id) == (tenant_id, shop_id)
            self.observations[resource] = day

    async def detect(_contexts, *, resources):
        calls.append(resources)
        return {
            "creators": date(2026, 9, 18),
            "videos": date(2026, 9, 17),
        }

    monkeypatch.setattr(startup, "AffiliateCenterReadRepository", ReadRepository)
    monkeypatch.setattr(startup, "detect_initial_selectable_dates", detect)

    health = HealthRepository()
    result = asyncio.run(
        startup.restore_capture_available_dates(
            "database",
            health,
            [],
            tenant_id,
            shop_id,
        )
    )

    assert calls == [startup.AVAILABILITY_RESOURCES]
    assert result == {
        "creators": date(2026, 9, 18),
        "videos": date(2026, 9, 17),
    }
    assert health.observations == {
        "creators": date(2026, 9, 18),
        "videos": date(2026, 9, 17),
    }
