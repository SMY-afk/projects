from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from backend.app.services.hubstudio_cdp import (
    normalize_loopback_cdp_url,
    probe_cdp_endpoint,
    read_cdp_platform_shop_ids,
)
from backend.app.services.hubstudio_cdp_ownership import (
    assert_erp_hubstudio_cdp_url,
)

_ENVIRONMENT_ID = re.compile(r"^\d{6,20}$")
_DENIED_CDP_PORTS = frozenset({6873, 19222})


class HubStudioSamplePreflightError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class HubStudioSampleTarget:
    tenant_id: UUID
    shop_id: UUID
    environment_id: str
    platform_shop_id: str
    cdp_url: str
    official_access_state: str


@dataclass(frozen=True)
class HubStudioEnvironmentSnapshot:
    environment_id: str
    running: bool
    cdp_url: str


@dataclass(frozen=True)
class HubStudioSamplePreflight:
    target: HubStudioSampleTarget
    normalized_cdp_url: str


EnvironmentProbe = Callable[[str], Awaitable[HubStudioEnvironmentSnapshot | None]]
EndpointProbe = Callable[[str], Awaitable[bool]]
PageShopReader = Callable[[str], Awaitable[frozenset[str]]]
OwnershipChecker = Callable[[str], str]


class HubStudioSampleApplicationSource:
    """Fail-closed preflight for an externally owned HubStudio CDP session."""

    def __init__(
        self,
        source_policy,
        environment_probe: EnvironmentProbe,
        *,
        ownership_checker: OwnershipChecker = assert_erp_hubstudio_cdp_url,
        endpoint_probe: EndpointProbe = probe_cdp_endpoint,
        page_shop_reader: PageShopReader = read_cdp_platform_shop_ids,
    ) -> None:
        self._source_policy = source_policy
        self._environment_probe = environment_probe
        self._ownership_checker = ownership_checker
        self._endpoint_probe = endpoint_probe
        self._page_shop_reader = page_shop_reader

    async def preflight(
        self, target: HubStudioSampleTarget
    ) -> HubStudioSamplePreflight:
        normalized_url = self._validate_target(target)
        await self._source_policy.require_hubstudio_fallback(
            tenant_id=target.tenant_id,
            shop_id=target.shop_id,
            platform_shop_id=target.platform_shop_id,
            official_access_state=target.official_access_state,
        )
        environment = await self._environment_probe(target.environment_id)
        if environment is None or environment.environment_id != target.environment_id:
            self._fail("environment_mismatch", "HubStudio environment was not found.")
        if not environment.running:
            self._fail("environment_offline", "HubStudio environment is not running.")
        environment_url = normalize_loopback_cdp_url(environment.cdp_url)
        if environment_url != normalized_url:
            self._fail(
                "environment_cdp_mismatch",
                "HubStudio environment and CDP URL do not match.",
            )
        try:
            owned_url = await asyncio.to_thread(self._ownership_checker, normalized_url)
        except PermissionError as error:
            raise HubStudioSamplePreflightError(
                "process_ownership_mismatch", "HubStudio process ownership is invalid."
            ) from error
        if owned_url != normalized_url or not await self._endpoint_probe(
            normalized_url
        ):
            self._fail("cdp_unavailable", "HubStudio CDP endpoint is unavailable.")
        page_shop_ids = await self._page_shop_reader(normalized_url)
        if page_shop_ids != frozenset({target.platform_shop_id}):
            self._fail(
                "page_shop_mismatch",
                "HubStudio page shop does not match the configured platform shop.",
            )
        return HubStudioSamplePreflight(target, normalized_url)

    async def revalidate(self, preflight: HubStudioSamplePreflight) -> None:
        target = preflight.target
        await self._source_policy.require_hubstudio_fallback(
            tenant_id=target.tenant_id,
            shop_id=target.shop_id,
            platform_shop_id=target.platform_shop_id,
            official_access_state=target.official_access_state,
        )

    @staticmethod
    def _validate_target(target: HubStudioSampleTarget) -> str:
        if not isinstance(target.tenant_id, UUID) or not isinstance(
            target.shop_id, UUID
        ):
            HubStudioSampleApplicationSource._fail(
                "invalid_binding", "tenant_id and shop_id are required."
            )
        if not _ENVIRONMENT_ID.fullmatch(target.environment_id or ""):
            HubStudioSampleApplicationSource._fail(
                "invalid_binding", "environment_id is required and invalid."
            )
        if not (target.platform_shop_id or "").strip():
            HubStudioSampleApplicationSource._fail(
                "invalid_binding", "platform_shop_id is required."
            )
        normalized_url = normalize_loopback_cdp_url(target.cdp_url)
        if normalized_url is None:
            HubStudioSampleApplicationSource._fail(
                "invalid_binding", "An explicit loopback cdp_url is required."
            )
        port = int(normalized_url.rsplit(":", 1)[1])
        if port in _DENIED_CDP_PORTS:
            HubStudioSampleApplicationSource._fail(
                "invalid_binding",
                "The configured port is not a HubStudio shop CDP port.",
            )
        return normalized_url

    @staticmethod
    def _fail(code: str, message: str):
        raise HubStudioSamplePreflightError(code, message)
