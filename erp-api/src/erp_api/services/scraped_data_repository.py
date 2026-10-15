from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert

from erp_api.infrastructure.database import Database
from erp_api.models.scraped_data import ScrapedData


class ScrapedDataUpsertError(ValueError):
    """Raised when raw records cannot be safely persisted."""


class ScrapedDataOwnershipConflict(ScrapedDataUpsertError):
    """Raised when a global platform ID already belongs to another tenant."""


@dataclass(frozen=True)
class ScrapedDataUpsertResult:
    received_count: int
    unique_count: int
    upserted_count: int


class ScrapedDataRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def bulk_upsert(
        self,
        tenant_id: UUID,
        records: Sequence[Mapping[str, object]],
    ) -> ScrapedDataUpsertResult:
        values = self._normalize_records(tenant_id, records)
        if not values:
            return ScrapedDataUpsertResult(
                received_count=len(records),
                unique_count=0,
                upserted_count=0,
            )

        statement = self._build_upsert_statement(values)
        async for session in self._database.session(tenant_id):
            result = await session.execute(statement)
            platform_ids = result.scalars().all()
            if len(platform_ids) != len(values):
                raise ScrapedDataOwnershipConflict(
                    "One or more platform IDs already belong to another tenant."
                )
            await session.commit()
            return ScrapedDataUpsertResult(
                received_count=len(records),
                unique_count=len(values),
                upserted_count=len(platform_ids),
            )
        raise RuntimeError("Tenant database session was not created.")

    @staticmethod
    def _build_upsert_statement(values: list[dict[str, object]]):
        statement = insert(ScrapedData).values(values)
        excluded = statement.excluded
        return statement.on_conflict_do_update(
            constraint="uq_scraped_data_platform_id",
            set_={
                "data_type": excluded.data_type,
                "creator_id": excluded.creator_id,
                "creator_name": excluded.creator_name,
                "title": excluded.title,
                "raw_data": excluded.raw_data,
                "updated_at": func.now(),
            },
            where=ScrapedData.tenant_id == excluded.tenant_id,
        ).returning(ScrapedData.platform_id)

    @classmethod
    def _normalize_records(
        cls,
        tenant_id: UUID,
        records: Sequence[Mapping[str, object]],
    ) -> list[dict[str, object]]:
        unique_records: dict[str, dict[str, object]] = {}
        for index, record in enumerate(records):
            platform_id = cls._required_text(
                record, "platform_id", index, max_length=100
            )
            data_type = cls._required_text(record, "data_type", index, max_length=50)
            raw_data = record.get("raw_data")
            if not isinstance(raw_data, Mapping):
                raise ScrapedDataUpsertError(
                    f"records[{index}].raw_data must be an object"
                )
            unique_records[platform_id] = {
                "tenant_id": tenant_id,
                "platform_id": platform_id,
                "data_type": data_type,
                "creator_id": cls._optional_text(record, "creator_id", max_length=100),
                "creator_name": cls._optional_text(
                    record,
                    "creator_name",
                    max_length=255,
                ),
                "title": cls._optional_text(record, "title"),
                "raw_data": dict(raw_data),
            }
        return list(unique_records.values())

    @classmethod
    def _required_text(
        cls,
        record: Mapping[str, object],
        key: str,
        index: int,
        *,
        max_length: int,
    ) -> str:
        value = cls._optional_text(record, key, max_length=max_length)
        if value is None:
            raise ScrapedDataUpsertError(f"records[{index}].{key} is required")
        return value

    @staticmethod
    def _optional_text(
        record: Mapping[str, object],
        key: str,
        *,
        max_length: int | None = None,
    ) -> str | None:
        raw = record.get(key)
        if raw is None:
            return None
        if isinstance(raw, (dict, list)):
            raise ScrapedDataUpsertError(f"{key} must be text")
        value = str(raw).strip()
        if not value:
            return None
        if max_length is not None and len(value) > max_length:
            raise ScrapedDataUpsertError(f"{key} exceeds {max_length} characters")
        return value
