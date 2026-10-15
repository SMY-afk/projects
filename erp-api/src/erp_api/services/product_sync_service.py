from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from erp_api.services.product_repository import ProductRepository, ProductSyncResult
from erp_api.services.tiktok_client import TikTokClient
from erp_api.services.tiktok_transport import TikTokApiError, tiktok_request_context

logger = logging.getLogger("erp_api.product_sync")

_RETRYABLE_PRODUCT_CODES = frozenset(
    {
        "36009003",
        "http_500",
        "http_502",
        "http_503",
        "http_504",
        "invalid_response",
        "invalid_product_response",
    }
)
_RETRYABLE_UPSTREAM_STATUSES = frozenset({500, 502, 503, 504})

_CREDENTIAL_PATTERN = re.compile(
    r"(?i)\b(access[_ -]?token|refresh[_ -]?token|auth(?:orization)?[_ -]?code|shop[_ -]?cipher)"
    r"\b\s*(?:[:=]|\bis\b)?\s*['\"]?[^\s,'\";]+['\"]?|\bbearer\s+[^\s,;]+"
)


class ProductSyncService:
    def __init__(
        self,
        repository: ProductRepository,
        client: TikTokClient,
        *,
        max_resume_retries: int = 3,
        retry_base_seconds: float = 5,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if max_resume_retries < 0:
            raise ValueError("max_resume_retries must not be negative.")
        if retry_base_seconds <= 0:
            raise ValueError("retry_base_seconds must be positive.")
        self._repository = repository
        self._client = client
        self._max_resume_retries = max_resume_retries
        self._retry_base_seconds = retry_base_seconds
        self._sleep = sleep

    async def sync_products(
        self,
        tenant_id: UUID,
        *,
        shop_id: UUID,
        page_size: int = 100,
    ) -> ProductSyncResult:
        shop = await self._repository.get_authorized_tiktok_shop(tenant_id, shop_id)
        if shop is None:
            raise RuntimeError(
                "No authorized TikTok shop is available for this tenant."
            )

        access_token = shop.access_token
        if _needs_refresh(shop.expires_at):
            if not shop.refresh_token:
                raise RuntimeError(
                    "TikTok access token is expired and no refresh token is available."
                )
            with tiktok_request_context(tenant_id=str(tenant_id), shop_id=str(shop.id)):
                tokens = await self._client.refresh_access_token(shop.refresh_token)
            if not await self._repository.update_connection_tokens(
                tenant_id, shop.id, tokens
            ):
                raise RuntimeError(
                    "TikTok connection could not be updated after token refresh."
                )
            access_token = tokens.access_token

        run_id = await self._repository.create_sync_run(tenant_id, shop.id)
        cursor: str | None = None
        resume_attempt = 0
        try:
            with tiktok_request_context(tenant_id=str(tenant_id), shop_id=str(shop.id)):
                while True:
                    try:
                        async for page in self._client.iter_product_pages(
                            access_token,
                            shop_id=shop.platform_shop_id,
                            shop_cipher=shop.shop_cipher,
                            page_token=cursor,
                            page_size=page_size,
                        ):
                            products = await self._enrich_products(
                                page.products,
                                access_token=access_token,
                                shop_id=shop.platform_shop_id,
                                shop_cipher=shop.shop_cipher,
                            )
                            await self._repository.upsert_product_page(
                                tenant_id,
                                run_id,
                                shop.id,
                                products,
                                page.next_page_token,
                            )
                            cursor = page.next_page_token or None
                        break
                    except TikTokApiError as error:
                        if (
                            not _is_retryable_product_error(error)
                            or resume_attempt >= self._max_resume_retries
                        ):
                            raise
                        resume_attempt += 1
                        delay = self._retry_delay(resume_attempt)
                        logger.warning(
                            "product_sync_resume_scheduled",
                            extra={
                                "event": "product_sync_resume_scheduled",
                                "tenant_id": str(tenant_id),
                                "shop_id": str(shop.id),
                                "run_id": str(run_id),
                                "attempt": resume_attempt,
                                "delay_seconds": delay,
                                "has_committed_cursor": cursor is not None,
                                "error_code": error.code,
                            },
                        )
                        await self._sleep(delay)
        except Exception as error:
            reason = _sanitize_failure(error, shop.access_token, shop.shop_cipher)
            logger.exception(
                "product_sync_failed",
                extra={
                    "event": "product_sync_failed",
                    "tenant_id": str(tenant_id),
                    "shop_id": str(shop.id),
                    "run_id": str(run_id),
                    "failure_reason": reason,
                },
            )
            return await self._repository.fail_sync_run(tenant_id, run_id, reason)
        return await self._repository.complete_sync_run(tenant_id, run_id)

    def _retry_delay(self, attempt: int) -> float:
        return float(min(60, self._retry_base_seconds * (2 ** (attempt - 1))))

    async def _enrich_products(
        self,
        products,
        *,
        access_token: str,
        shop_id: str,
        shop_cipher: str | None,
    ):
        if not shop_cipher:
            raise RuntimeError("Authorized TikTok shop has no shop cipher.")
        semaphore = asyncio.Semaphore(4)

        async def enrich(product):
            try:
                async with semaphore:
                    return await self._client.get_product_detail(
                        access_token,
                        shop_id=shop_id,
                        shop_cipher=shop_cipher,
                        product_id=product.platform_product_id,
                    )
            except TikTokApiError as error:
                logger.warning(
                    "product_detail_enrichment_failed",
                    extra={
                        "event": "product_detail_enrichment_failed",
                        "platform_product_id": product.platform_product_id,
                        "error_code": error.code,
                    },
                )
                return product

        return list(await asyncio.gather(*(enrich(product) for product in products)))


def _needs_refresh(expires_at: datetime | None) -> bool:
    if expires_at is None:
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= datetime.now(UTC) + timedelta(seconds=60)


def _is_retryable_product_error(error: TikTokApiError) -> bool:
    return (
        error.code in _RETRYABLE_PRODUCT_CODES
        or error.upstream_status_code in _RETRYABLE_UPSTREAM_STATUSES
    )


def _sanitize_failure(
    error: Exception, access_token: str, shop_cipher: str | None
) -> str:
    message = str(error).splitlines()[0]
    for secret in (access_token, shop_cipher):
        if secret:
            message = message.replace(secret, "[REDACTED]")
    message = _CREDENTIAL_PATTERN.sub("credential=[REDACTED]", message)
    if isinstance(error, TikTokApiError):
        prefix = f"{type(error).__name__} code={error.code} status={error.status_code}"
    else:
        prefix = type(error).__name__
    return f"{prefix}: {message}"[:1000]
