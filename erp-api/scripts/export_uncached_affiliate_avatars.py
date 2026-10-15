"""Read-only exact-tenant export of fresh official avatars not yet cached by ERP."""
import asyncio
import json
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from sqlalchemy import select, text

from erp_api.main import app
from erp_api.models.affiliate_creator import AffiliateCreator
from erp_api.services.affiliate_avatar_cache_policy import CACHED_AVATAR_PREFIX

TENANT = UUID("6d0032eb-6a58-5a93-a819-d55c2a1c2e26")
LABELS = {
    "50770999-40ce-5b84-bb01-13701932bdf1": "cross-border-4",
    "6fdc5cdc-90da-5524-82f7-9b11746c5e10": "local",
    "fe629cb8-fa7b-56a5-970c-2f6e9ebc5703": "cross-border-7",
    "5e1fed24-8268-5b5a-9ead-5efb862e7a51": "cross-border-12",
    "eb7678c2-67d6-5446-85f0-dc8fba9b75d6": "cross-border-3",
}


async def main():
    records = []
    try:
        async with app.state.database.system_session_factory() as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            rows = await session.scalars(select(AffiliateCreator).where(
                AffiliateCreator.tenant_id == TENANT,
                AffiliateCreator.shop_id.in_([UUID(key) for key in LABELS]),
                AffiliateCreator.avatar_url.is_not(None),
                ~AffiliateCreator.avatar_url.like(CACHED_AVATAR_PREFIX + "%")))
            now = datetime.now(UTC).timestamp()
            for row in rows:
                parsed = urlsplit(row.avatar_url)
                try:
                    expiry = int(parse_qs(parsed.query).get("x-expires", ["0"])[0])
                except ValueError:
                    continue
                identifier = row.source_identifiers.get("tiktok_page_creator_id")
                if expiry <= now + 120 or not identifier:
                    continue
                records.append({"id": str(row.id), "username": row.username_normalized,
                                "avatarUrlBefore": row.avatar_url, "url": row.avatar_url,
                                "tenantId": str(TENANT), "shopId": str(row.shop_id),
                                "shopLabel": LABELS[str(row.shop_id)],
                                "sourceIdentity": {"tiktok_page_creator_id": identifier}})
                if len(records) == 2000:
                    break
        print(json.dumps(records))
    finally:
        await app.state.database.dispose()
        await app.state.redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
