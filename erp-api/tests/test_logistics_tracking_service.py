import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from erp_api.services.carrier_tracking_adapter import GenericCarrierTrackingAdapter
from erp_api.services.carrier_tracking_registry import CarrierTrackingAdapterRegistry
from erp_api.services.logistics_tracking_repository import TrackingApplyResult
from erp_api.services.logistics_tracking_service import LogisticsTrackingService


class FakeRepository:
    def __init__(self) -> None:
        self.carrier_id = uuid4()
        self.applied = []
        self.poll_finished = []

    async def resolve_carrier(self, tenant_id, carrier_code):
        return SimpleNamespace(carrier_id=self.carrier_id, adapter_key="manual")

    async def apply_update(self, tenant_id, carrier_id, update, **kwargs):
        self.applied.append((update, kwargs))
        duplicate = len(self.applied) > 1
        return TrackingApplyResult(
            uuid4(), duplicate, not duplicate, "in_transit", None
        )

    async def load_poll_target(self, tenant_id, waybill_id):
        return SimpleNamespace(
            adapter_key="manual", context=SimpleNamespace(carrier_id=self.carrier_id)
        )

    async def finish_poll(self, tenant_id, waybill_id, **kwargs):
        self.poll_finished.append(kwargs)


def _service(repository, exception_service=None):
    return LogisticsTrackingService(
        repository,
        CarrierTrackingAdapterRegistry([GenericCarrierTrackingAdapter()]),
        webhook_secrets={"DHL": "secret"},
        poll_interval=timedelta(minutes=30),
        poll_retry_interval=timedelta(minutes=10),
        exception_service=exception_service,
    )


@pytest.mark.asyncio
async def test_webhook_counts_accepted_and_duplicate_events() -> None:
    repository = FakeRepository()
    service = _service(repository)
    tenant_id = uuid4()
    timestamp = str(int(datetime.now(UTC).timestamp()))
    body = json.dumps(
        {
            "events": [
                {"eventId": "1", "externalWaybillId": "WB1", "status": "TRANSIT"},
                {"eventId": "1", "externalWaybillId": "WB1", "status": "TRANSIT"},
            ]
        }
    ).encode()
    signature = hmac.new(
        b"secret", timestamp.encode() + b"." + body, hashlib.sha256
    ).hexdigest()

    result = await service.receive_webhook(
        tenant_id,
        "DHL",
        body,
        signature=signature,
        timestamp=timestamp,
    )

    assert result.received == 2
    assert result.accepted == 1
    assert result.duplicates == 1


@pytest.mark.asyncio
async def test_poll_marks_next_compensation_window() -> None:
    repository = FakeRepository()
    result = await _service(repository).poll(uuid4(), uuid4())

    assert result == {"received": 0, "accepted": 0, "duplicates": 0}
    assert repository.poll_finished[0]["interval"] == timedelta(minutes=30)


@pytest.mark.asyncio
async def test_accepted_tracking_event_triggers_exception_detection() -> None:
    repository = FakeRepository()
    detected = []

    class Detector:
        async def detect_tracking_event(self, tenant_id, event_id):
            detected.append((tenant_id, event_id))

    tenant_id = uuid4()
    await _service(repository, Detector()).poll(tenant_id, uuid4())

    assert detected == []

    repository.applied.clear()
    timestamp = str(int(datetime.now(UTC).timestamp()))
    body = json.dumps(
        {
            "events": [
                {"eventId": "damage-1", "externalWaybillId": "WB1", "status": "DAMAGED"}
            ]
        }
    ).encode()
    signature = hmac.new(
        b"secret", timestamp.encode() + b"." + body, hashlib.sha256
    ).hexdigest()
    await _service(repository, Detector()).receive_webhook(
        tenant_id, "DHL", body, signature=signature, timestamp=timestamp
    )

    assert len(detected) == 1
    assert detected[0][0] == tenant_id
