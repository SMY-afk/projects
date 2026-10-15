from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select

from erp_api.infrastructure.database import Database
from erp_api.models.scraped_data import ScrapedData
from erp_api.models.shop import Shop
from erp_api.services.order_evidence_repository import (
    EvidenceIngestResult,
    OrderEvidenceRepository,
)


class SellerEvidenceSyncRepository:
    def __init__(self, database: Database) -> None:
        self._database = database
        self._evidence_repository = OrderEvidenceRepository()

    async def resolve_shop_id(
        self,
        tenant_id: UUID,
        platform_shop_id: str,
    ) -> UUID | None:
        async for session in self._database.session(tenant_id):
            return await session.scalar(
                select(Shop.id).where(
                    Shop.platform == "tiktok",
                    Shop.platform_shop_id == platform_shop_id,
                )
            )
        raise RuntimeError("Tenant database session was not created.")

    async def ingest_orders(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        records: Sequence[Mapping[str, object]],
    ) -> EvidenceIngestResult:
        async for session in self._database.session(tenant_id):
            result = await self._evidence_repository.ingest_seller_records(
                session,
                tenant_id,
                shop_id,
                records,
            )
            await session.commit()
            return result
        raise RuntimeError("Tenant database session was not created.")

    async def ingest_export(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        records: Sequence[Mapping[str, object]],
    ) -> EvidenceIngestResult:
        async for session in self._database.session(tenant_id):
            payloads = (
                await session.scalars(
                    select(ScrapedData.raw_data).where(
                        ScrapedData.data_type.in_(
                            ("seller_video_analytics", "seller_live_analytics")
                        )
                    )
                )
            ).all()
            accounts = _extract_creator_accounts(
                [payload for payload in payloads if isinstance(payload, Mapping)]
            )
            result = await self._evidence_repository.ingest_seller_records(
                session,
                tenant_id,
                shop_id,
                _enrich_export_records(records, accounts),
            )
            await session.commit()
            return result
        raise RuntimeError("Tenant database session was not created.")


@dataclass(frozen=True)
class SellerCreatorAccount:
    external_id: str
    handle: str
    alias: str | None
    account_type: str | None


def _extract_creator_accounts(
    payloads: Sequence[Mapping[str, object]],
) -> dict[str, SellerCreatorAccount]:
    accounts: dict[str, SellerCreatorAccount] = {}

    def visit(value: object, parent_key: str | None = None) -> None:
        if isinstance(value, Mapping):
            if parent_key in {"creator_meta", "account_meta"}:
                external_id = _text(value.get("id") or value.get("creator_id"))
                handle = _text(value.get("handle") or value.get("unique_id"))
                if external_id and handle:
                    accounts[handle.casefold()] = SellerCreatorAccount(
                        external_id=external_id,
                        handle=handle,
                        alias=_text(value.get("alias") or value.get("nickname")),
                        account_type=_account_type(value.get("type")),
                    )
            for key, child in value.items():
                visit(child, str(key))
        elif isinstance(value, list):
            for child in value:
                visit(child, parent_key)

    for payload in payloads:
        visit(payload)
    return accounts


def _enrich_export_records(
    records: Sequence[Mapping[str, object]],
    accounts: Mapping[str, SellerCreatorAccount],
) -> list[dict[str, object]]:
    enriched: list[dict[str, object]] = []
    for source in records:
        record = dict(source)
        evidence = dict(source.get("evidence_json") or {})
        handle = _text(evidence.get("creator_handle"))
        account = accounts.get(handle.casefold()) if handle else None
        direct_id = _text(record.get("creator_external_id"))
        if (
            account is None
            or account.account_type not in {"official", "marketing"}
            or (direct_id is not None and direct_id != account.external_id)
        ):
            continue
        record["source_system"] = "seller_managed_creator_export"
        record["creator_external_id"] = account.external_id
        record["operator_subject_candidate"] = "self_operated"
        record["confidence_score"] = 0.98
        evidence.update(
            {
                "source": "seller_managed_creator_export",
                "reason": "verified_seller_managed_creator",
                "creator_identity_verified": True,
                "creator_account_type": account.account_type,
                **({"creator_alias": account.alias} if account.alias else {}),
            }
        )
        record["evidence_json"] = evidence
        enriched.append(record)
    return enriched


def _account_type(value: object) -> str | None:
    normalized = _text(value)
    return {"1": "official", "2": "marketing"}.get(
        normalized or "",
        normalized,
    )


def _text(value: object) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    parsed = str(value).strip()
    return parsed or None
