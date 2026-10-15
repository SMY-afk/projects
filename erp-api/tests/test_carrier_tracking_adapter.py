import hashlib
import hmac
import json
from datetime import UTC, datetime

import pytest

from erp_api.services.carrier_tracking_adapter import GenericCarrierTrackingAdapter


def test_generic_webhook_verifies_signature_and_parses_batch() -> None:
    adapter = GenericCarrierTrackingAdapter()
    timestamp = str(int(datetime.now(UTC).timestamp()))
    body = json.dumps(
        {
            "events": [
                {
                    "eventId": "evt-1",
                    "externalWaybillId": "carrier-waybill-1",
                    "status": "IN_TRANSIT",
                    "occurredAt": "2026-08-24T08:00:00Z",
                    "sequence": 3,
                }
            ]
        }
    ).encode()
    signature = hmac.new(
        b"secret", timestamp.encode() + b"." + body, hashlib.sha256
    ).hexdigest()

    adapter.verify_webhook(
        body, signature=f"sha256={signature}", timestamp=timestamp, secret="secret"
    )
    updates = adapter.parse_webhook(json.loads(body), received_at=datetime.now(UTC))

    assert updates[0].external_event_id == "evt-1"
    assert updates[0].sequence_no == 3
    assert updates[0].occurred_at == datetime(2026, 8, 24, 8, tzinfo=UTC)


def test_generic_webhook_rejects_invalid_signature() -> None:
    with pytest.raises(ValueError, match="signature"):
        GenericCarrierTrackingAdapter().verify_webhook(
            b"{}",
            signature="bad",
            timestamp=str(int(datetime.now(UTC).timestamp())),
            secret="secret",
        )
