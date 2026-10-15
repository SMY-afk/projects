from datetime import UTC, datetime
from types import SimpleNamespace

from erp_api.services.sample_application_upsert import changed_sample_fields


def test_source_refresh_preserves_manual_creator_level_override() -> None:
    existing = SimpleNamespace(
        creator_level="L0",
        raw_payload={"manual_creator_level_override": "L0"},
    )
    normalized = {
        "platform_application_id": "sample-1",
        "creator_level": None,
        "raw_payload": {"id": "sample-1"},
        "source_observed_at": datetime(2026, 9, 15, tzinfo=UTC),
    }

    changed = changed_sample_fields(existing, normalized)

    assert normalized["creator_level"] == "L0"
    assert normalized["raw_payload"]["manual_creator_level_override"] == "L0"
    assert changed == {"raw_payload", "source_observed_at"}
