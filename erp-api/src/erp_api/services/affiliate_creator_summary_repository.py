from __future__ import annotations

from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy import func, or_, select

from erp_api.infrastructure.database import Database
from erp_api.models.affiliate_creator import AffiliateCreator
from erp_api.models.sample_application import SampleApplication
from erp_api.services.affiliate_creator_summary_parser import (
    CreatorSummaryPayload,
    merge_profile_snapshots,
    validate_creator_summary_identity,
)
from erp_api.services.affiliate_metric_parse_support import creator_username_key
from erp_api.services.sample_creator_profile_realtime import (
    apply_latest_creator_profile,
    pending_creator_sample_applications_statement,
)


class CreatorSummaryRepositoryError(ValueError):
    pass


class AffiliateCreatorSummaryRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def persist(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        summary: CreatorSummaryPayload,
        *,
        request_id: str,
        response_path: str,
    ) -> UUID:
        async with self._database.system_session_factory() as session:
            creator_id = await self._persist_in_session(
                session,
                tenant_id,
                shop_id,
                summary,
                request_id=request_id,
                response_path=response_path,
            )
            await session.commit()
            return creator_id

    async def persist_batch(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        items: Sequence[tuple[CreatorSummaryPayload, str, str]],
    ) -> UUID:
        if not items:
            raise CreatorSummaryRepositoryError("Creator summary batch is empty.")
        async with self._database.system_session_factory() as session:
            creator_ids = {
                await self._persist_in_session(
                    session,
                    tenant_id,
                    shop_id,
                    summary,
                    request_id=request_id,
                    response_path=response_path,
                )
                for summary, request_id, response_path in items
            }
            if len(creator_ids) != 1:
                raise CreatorSummaryRepositoryError(
                    "Creator summary batch contains multiple creators."
                )
            await session.commit()
            return next(iter(creator_ids))

    async def _persist_in_session(
        self,
        session,
        tenant_id: UUID,
        shop_id: UUID,
        summary: CreatorSummaryPayload,
        *,
        request_id: str,
        response_path: str,
    ) -> UUID:
        creator = await session.scalar(
            select(AffiliateCreator)
            .where(
                AffiliateCreator.tenant_id == tenant_id,
                AffiliateCreator.shop_id == shop_id,
                or_(
                    AffiliateCreator.source_identifiers[
                        "tiktok_sample_detail_creator_id"
                    ].astext
                    == summary.platform_creator_id,
                    AffiliateCreator.source_identifiers["tiktok_page_creator_id"].astext
                    == summary.platform_creator_id,
                ),
            )
            .with_for_update()
        )
        if creator is None and summary.creator_username:
            creator = await session.scalar(
                select(AffiliateCreator)
                .where(
                    AffiliateCreator.tenant_id == tenant_id,
                    AffiliateCreator.shop_id == shop_id,
                    AffiliateCreator.username_normalized
                    == creator_username_key(summary.creator_username),
                )
                .with_for_update()
            )
        username = (
            creator.username_normalized
            if creator is not None
            else creator_username_key(summary.creator_username or "")
        )
        if not username:
            raise CreatorSummaryRepositoryError(
                "Creator summary page identity is unknown to ERP."
            )
        if summary.creator_username and (
            summary.creator_username.strip().lstrip("@").casefold() != username
        ):
            raise CreatorSummaryRepositoryError(
                "Creator summary username conflicts with ERP."
            )
        open_ids = await self._sample_open_ids(session, tenant_id, shop_id, username)
        if len(open_ids) != 1:
            raise CreatorSummaryRepositoryError(
                "Creator summary sample identity is missing or ambiguous."
            )
        open_id = next(iter(open_ids))
        existing_open_id = creator.creator_open_id if creator is not None else None
        actual_open_id = summary.creator_open_id or existing_open_id or open_id
        validate_creator_summary_identity(
            expected_open_id=open_id,
            expected_username=username,
            expected_shop_id=str(shop_id),
            actual_open_id=actual_open_id,
            actual_username=(
                summary.creator_username
                or (creator.username if creator is not None else username)
            ),
            actual_shop_id=str(shop_id),
        )
        if creator is None:
            creator = AffiliateCreator(
                tenant_id=tenant_id,
                shop_id=shop_id,
                username=(summary.creator_username or username).lstrip("@"),
                username_normalized=username,
                creator_open_id=open_id,
                source_identifiers={
                    "tiktok_sample_detail_creator_id": summary.platform_creator_id
                },
                extensions={},
            )
            session.add(creator)
            await session.flush()
        if creator.creator_open_id not in {None, open_id}:
            raise CreatorSummaryRepositoryError(
                "Creator summary creator_open_id conflicts with ERP."
            )
        conflicting_creator = await session.scalar(
            select(AffiliateCreator.id).where(
                AffiliateCreator.tenant_id == tenant_id,
                AffiliateCreator.shop_id == shop_id,
                AffiliateCreator.id != creator.id,
                AffiliateCreator.source_identifiers[
                    "tiktok_sample_detail_creator_id"
                ].astext
                == summary.platform_creator_id,
            )
        )
        if conflicting_creator is not None:
            raise CreatorSummaryRepositoryError(
                "Creator summary page identity conflicts with another creator."
            )
        creator.creator_open_id = open_id
        creator.source_identifiers = {
            **(creator.source_identifiers or {}),
            "tiktok_sample_detail_creator_id": summary.platform_creator_id,
        }
        creator.extensions = _updated_extensions(
            creator.extensions,
            summary,
            shop_id=shop_id,
            open_id=open_id,
            username=creator.username,
            request_id=request_id,
            response_path=response_path,
        )
        applications = (
            await session.scalars(
                pending_creator_sample_applications_statement(
                    tenant_id=tenant_id,
                    shop_id=shop_id,
                    creator_open_id=open_id,
                    creator_username=username,
                ).with_for_update()
            )
        ).all()
        apply_latest_creator_profile(applications, creator)
        return creator.id

    @staticmethod
    async def _sample_open_ids(session, tenant_id, shop_id, username):
        statement = select(SampleApplication.creator_open_id).where(
            SampleApplication.tenant_id == tenant_id,
            SampleApplication.shop_id == shop_id,
            SampleApplication.creator_open_id.is_not(None),
            func.lower(func.ltrim(SampleApplication.creator_username, "@")) == username,
        )
        values = (await session.scalars(statement)).all()
        return {value for value in values if isinstance(value, str) and value}


def _updated_extensions(
    extensions: Mapping[str, object] | None,
    summary: CreatorSummaryPayload,
    *,
    shop_id: UUID,
    open_id: str,
    username: str,
    request_id: str,
    response_path: str,
) -> dict[str, object]:
    result = dict(extensions or {})
    current = result.get("creator_details_summary")
    details = dict(current) if isinstance(current, Mapping) else {}
    profile = merge_profile_snapshots(
        _mapping(details.get("profile_snapshot")), summary.profile_snapshot
    )
    sections = dict(_mapping(details.get("sections")))
    sections.update(_profile_sections(summary.profile_snapshot))
    payloads = dict(_mapping(details.get("source_payloads")))
    payloads[summary.resource_kind] = summary.raw_data
    sources = dict(_mapping(details.get("sources")))
    sources[summary.resource_kind] = {
        "request_id": request_id,
        "path": response_path,
        "observed_at": summary.observed_at.isoformat(),
    }
    result["creator_details_summary"] = {
        "schema_version": 1,
        "identity": {
            "creator_open_id": open_id,
            "username": username,
            "shop_id": str(shop_id),
        },
        "observed_at": summary.observed_at.isoformat(),
        "sections": sections,
        "profile_snapshot": profile,
        "source_payloads": payloads,
        "sources": sources,
    }
    return result


def _profile_sections(snapshot: Mapping[str, object]) -> dict[str, object]:
    aliases = {
        "sales": "sales",
        "cooperation": "collaboration",
        "video": "video",
        "live": "live",
        "audience": "followers",
        "trends": "trends",
    }
    return {
        target: snapshot[source]
        for source, target in aliases.items()
        if snapshot.get(source) not in (None, {}, [])
    }


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}
