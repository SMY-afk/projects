from __future__ import annotations

from typing import Protocol
from uuid import UUID

from sqlalchemy import select

from erp_api.infrastructure.database import Database
from erp_api.models.sample_application import SampleApplication


class SampleImageVerifier(Protocol):
    async def is_available(self, source_url: str) -> bool: ...


class SampleAssignmentImageGate:
    """Require every product in an application to have a reachable sample image."""

    def __init__(self, database: Database, verifier: SampleImageVerifier) -> None:
        self._database = database
        self._verifier = verifier

    async def blocked_reason(
        self, tenant_id: UUID, shop_id: UUID, application_id: UUID
    ) -> str | None:
        async with self._database.system_session_factory() as session:
            application = await session.scalar(
                select(SampleApplication).where(
                    SampleApplication.tenant_id == tenant_id,
                    SampleApplication.shop_id == shop_id,
                    SampleApplication.id == application_id,
                )
            )
        if application is None:
            raise LookupError("Sample image gate application was not found.")
        urls = _source_image_urls(application)
        if not urls:
            return "sample_image_missing"
        for url in urls:
            if not await self._verifier.is_available(url):
                return "sample_image_unavailable"
        return None


def _source_image_urls(application: SampleApplication) -> tuple[str, ...]:
    payload = application.raw_payload or {}
    raw_products = payload.get("products")
    if isinstance(raw_products, list):
        products = [
            item.get("product") if isinstance(item, dict) else None
            for item in raw_products
        ]
    elif isinstance(payload.get("product"), dict):
        products = [payload["product"]]
    else:
        products = []
    if products:
        urls = [
            product.get("sku_image_url") if isinstance(product, dict) else None
            for product in products
        ]
        if any(not isinstance(url, str) or not url.strip() for url in urls):
            return ()
        return tuple(dict.fromkeys(url.strip() for url in urls))
    stored = application.product_image_urls or []
    urls = stored if stored else [application.sku_image_url]
    return tuple(
        dict.fromkeys(url.strip() for url in urls if isinstance(url, str) and url.strip())
    )
