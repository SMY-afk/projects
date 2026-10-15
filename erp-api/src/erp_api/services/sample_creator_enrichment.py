from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from erp_api.services.affiliate_center_capture_policy import sanitize_capture_payload
from erp_api.services.sample_creator_avatar_storage import (
    SampleCreatorAvatarError,
    SampleCreatorAvatarStorage,
    extract_creator_avatar_source,
)
from erp_api.services.tiktok_transport import TikTokClientError, TikTokRateLimitError


@dataclass(frozen=True)
class CreatorEnrichmentResult:
    performance_enriched_count: int
    performance_error_count: int
    avatar_stored_count: int
    avatar_error_count: int
    request_ids: tuple[str, ...]


class SampleCreatorEnrichmentService:
    def __init__(
        self,
        client,
        avatar_storage: SampleCreatorAvatarStorage | None,
        *,
        concurrency: int = 8,
        min_interval_seconds: float = 0.75,
    ) -> None:
        if concurrency <= 0 or min_interval_seconds < 0:
            raise ValueError("Creator enrichment limits are invalid.")
        self._client = client
        self._avatar_storage = avatar_storage
        self._concurrency = concurrency
        self._min_interval_seconds = min_interval_seconds

    async def enrich(
        self,
        payloads: list[dict[str, object]],
        *,
        source_payloads: Sequence[Mapping[str, object]],
        access_token: str,
        shop_cipher: str,
        tenant_id: UUID,
        shop_id: UUID,
        observed_at: datetime,
    ) -> CreatorEnrichmentResult:
        if len(payloads) != len(source_payloads):
            raise ValueError("Creator enrichment source count is invalid.")
        semaphore = asyncio.Semaphore(self._concurrency)
        request_lock = asyncio.Lock()
        last_request_started = 0.0
        rate_limited = False
        groups: dict[str, list[int]] = defaultdict(list)
        results: list[tuple[bool, bool | None, str | None]] = [
            (False, None, None) for _ in payloads
        ]
        for index, payload in enumerate(payloads):
            creator = payload.get("creator")
            creator_id = (
                creator.get("creator_open_id") if isinstance(creator, dict) else None
            )
            if isinstance(creator_id, str) and creator_id:
                groups[creator_id].append(index)

        async def enrich_group(
            creator_id: str, indices: list[int]
        ) -> tuple[list[int], bool, bool | None, str | None]:
            nonlocal last_request_started, rate_limited
            creators = [payloads[index]["creator"] for index in indices]
            avatar_source = next(
                (
                    source
                    for index in indices
                    if (source := extract_creator_avatar_source(source_payloads[index]))
                ),
                None,
            )
            performance_ok = False
            request_id = None
            try:
                async with request_lock:
                    if rate_limited:
                        return indices, False, None, None
                    remaining = self._min_interval_seconds - (
                        time.monotonic() - last_request_started
                    )
                    if remaining > 0:
                        await asyncio.sleep(remaining)
                    last_request_started = time.monotonic()
                    performance = await self._client.get_creator_performance(
                        access_token,
                        creator_open_id=creator_id,
                        shop_cipher=shop_cipher,
                        tenant_id=str(tenant_id),
                        shop_id=str(shop_id),
                    )
            except TikTokRateLimitError:
                rate_limited = True
            except TikTokClientError:
                pass
            else:
                performance_ok = True
                request_id = performance.platform_request_id
                avatar_source = avatar_source or extract_creator_avatar_source(
                    performance.fields
                )
                fields = sanitize_capture_payload(performance.fields)
                if not isinstance(fields, dict):
                    raise TypeError("TikTok creator performance payload is invalid.")
                for creator in creators:
                    creator["performance"] = dict(fields)
            avatar_ok = await self._store_avatar(
                creators[0],
                avatar_source,
                tenant_id=tenant_id,
                shop_id=shop_id,
                creator_open_id=creator_id,
                observed_at=observed_at,
                semaphore=semaphore,
            )
            if avatar_ok:
                for creator in creators[1:]:
                    for key in (
                        "avatar_object_key",
                        "avatar_source_hash",
                        "avatar_observed_at",
                    ):
                        creator[key] = creators[0][key]
            return indices, performance_ok, avatar_ok, request_id

        grouped_results = await asyncio.gather(
            *(
                enrich_group(creator_id, indices)
                for creator_id, indices in groups.items()
            )
        )
        for indices, performance_ok, avatar_ok, request_id in grouped_results:
            for index in indices:
                results[index] = (performance_ok, avatar_ok, request_id)
        return CreatorEnrichmentResult(
            performance_enriched_count=sum(item[0] for item in results),
            performance_error_count=sum(not item[0] for item in results),
            avatar_stored_count=sum(item[1] is True for item in results),
            avatar_error_count=sum(item[1] is False for item in results),
            request_ids=tuple(
                dict.fromkeys(
                    item[2] for item in results if isinstance(item[2], str) and item[2]
                )
            ),
        )

    async def _store_avatar(
        self,
        creator: dict[str, object],
        source_url: str | None,
        *,
        tenant_id: UUID,
        shop_id: UUID,
        creator_open_id: str,
        observed_at: datetime,
        semaphore: asyncio.Semaphore,
    ) -> bool | None:
        if source_url is None or self._avatar_storage is None:
            return None
        try:
            async with semaphore:
                stored = await self._avatar_storage.store(
                    source_url,
                    tenant_id=tenant_id,
                    shop_id=shop_id,
                    creator_open_id=creator_open_id,
                )
        except SampleCreatorAvatarError:
            return False
        creator["avatar_object_key"] = stored.object_key
        creator["avatar_source_hash"] = stored.source_hash
        creator["avatar_observed_at"] = observed_at.isoformat()
        return True
