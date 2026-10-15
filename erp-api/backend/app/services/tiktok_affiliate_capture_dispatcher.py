from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from backend.app.services.tiktok_affiliate_analytics_context import (
    AffiliateAnalyticsResponseContext,
)


class AffiliateCaptureSession(Protocol):
    async def persist_page(
        self,
        resource: str,
        payload: Mapping[str, object],
        observation: Mapping[str, object],
        response_context: AffiliateAnalyticsResponseContext,
        page_number: int,
        next_page_number: int | None,
    ) -> None: ...

    async def finalize_resource(
        self, resource: str, snapshot: Mapping[str, object]
    ) -> None: ...


class TikTokAffiliateCaptureDispatcher:
    def __init__(
        self,
        creator_session: AffiliateCaptureSession,
        video_session: AffiliateCaptureSession,
    ) -> None:
        self._sessions = {
            "creators": creator_session,
            "videos": video_session,
        }

    async def persist_page(
        self,
        resource: str,
        payload: Mapping[str, object],
        observation: Mapping[str, object],
        response_context: AffiliateAnalyticsResponseContext,
        page_number: int,
        next_page_number: int | None,
    ) -> None:
        session = self._session(resource)
        await session.persist_page(
            resource,
            payload,
            observation,
            response_context,
            page_number,
            next_page_number,
        )

    async def finalize_resource(
        self, resource: str, snapshot: Mapping[str, object]
    ) -> None:
        await self._session(resource).finalize_resource(resource, snapshot)

    def _session(self, resource: str) -> AffiliateCaptureSession:
        try:
            return self._sessions[resource]
        except KeyError as error:
            raise ValueError("Unknown affiliate capture resource.") from error
