from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.affiliate_order import AffiliateOrderItem
from app.services.affiliate_parser import parse_affiliate_item


def ingest_affiliate_response(
    db: Session,
    payload: dict[str, Any],
    shop_id: str | None = None,
) -> dict[str, object]:
    data = payload.get("data") or {}
    items = data.get("sku_order_list", [])
    saved = 0

    for raw_item in items:
        parsed = parse_affiliate_item(raw_item)
        source_key = parsed["source_record_key"]
        existing = db.execute(
            select(AffiliateOrderItem).where(
                AffiliateOrderItem.source_record_key == source_key
            )
        ).scalar_one_or_none()

        if existing:
            for key, value in parsed.items():
                setattr(existing, key, value)
        else:
            db.add(AffiliateOrderItem(shop_id=shop_id, **parsed))

        saved += 1

    db.commit()
    return {
        "saved": saved,
        "has_more": data.get("has_more", False),
        "next_cursor": data.get("next_cursor"),
    }
