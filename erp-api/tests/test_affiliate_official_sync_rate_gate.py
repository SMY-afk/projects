from datetime import date
from uuid import uuid4

import pytest

from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)
from erp_api.services.affiliate_official_sync_service import (
    OfficialAffiliateSyncService,
)
from erp_api.services.compass_export_rate_gate import CompassExportDeferred


class SourceResolver:
    async def source_kind(self, tenant_id, shop_id):
        return "official_api"


class ShopRepository:
    async def get_authorized_tiktok_shop(self, tenant_id, shop_id):
        return {"platform_shop_id": "platform-shop"}

    async def get_access_token(self, tenant_id, shop_id):
        return "token"

    async def get_shop_cipher(self, tenant_id, shop_id):
        return "cipher"

    async def get_app_profile(self, tenant_id, shop_id):
        return "feifei"


class ClosedGate:
    async def acquire(self, app_profile):
        raise CompassExportDeferred(3_600)


class CreatorPersistence:
    def __init__(self) -> None:
        self.started = False

    async def begin_capture(self, *args, **kwargs):
        self.started = True
        raise AssertionError("A report must not start while the rate gate is closed.")


@pytest.mark.asyncio
async def test_rate_gate_defers_before_creating_a_partial_report() -> None:
    persistence = CreatorPersistence()
    service = OfficialAffiliateSyncService(
        object(),
        ShopRepository(),
        SourceResolver(),
        object(),
        object(),
        persistence,
        object(),
        compass_rate_gate=ClosedGate(),
    )
    query = AffiliateCenterQuery(
        resource=AffiliateCenterResource.CREATORS,
        shop_id=uuid4(),
        window_start=date(2026, 8, 26),
        window_end=date(2026, 9, 1),
        shop_timezone="America/Los_Angeles",
        currency="USD",
        filters={},
    )

    with pytest.raises(CompassExportDeferred):
        await service.sync(uuid4(), query, job_id="job-gated")

    assert persistence.started is False
