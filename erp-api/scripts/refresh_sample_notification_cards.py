from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.models.sample_application import SampleApplication
from erp_api.models.sample_application_workflow import SampleApplicationWorkflow
from erp_api.models.sample_notification_outbox import SampleNotificationOutbox
from erp_api.models.shop import Shop
from erp_api.services.feishu_notification_client import FeishuNotificationClient
from erp_api.services.feishu_sample_batch_client import FeishuSampleBatchClient
from erp_api.services.feishu_sample_errors import FeishuSampleError
from erp_api.services.sample_creator_avatar_storage import (
    build_sample_creator_avatar_storage,
)
from erp_api.services.sample_creator_profile_freshness import creator_profile_status
from erp_api.services.sample_notification_avatar import SampleNotificationAvatarService
from erp_api.services.sample_notification_card import build_sample_notification_card
from erp_api.services.sample_notification_image_keys import (
    resolve_notification_image_keys,
)
from erp_api.services.sample_notification_product_image import (
    SampleNotificationProductImageService,
)
from erp_api.services.sample_notification_refresh import (
    build_refresh_card_task,
    load_refresh_product_images,
)

BD_NAMES = frozenset({"李鸿程", "吴洵涛", "刘诚"})
RULE_VERSION = "bd-v1-smoke"
SHOP_NAME = "Akeleo Toys"


async def main() -> None:
    args = _arguments()
    settings = get_settings()
    _validate_settings(settings)
    record_url_template = _record_url_template(settings, args.tenant_domain)
    database = Database(settings.database_url)
    try:
        rows = await _smoke_rows(database, args.tenant_id, args.shop_id)
        targets = _targets(rows, record_url_template)
        if args.bd_name:
            targets = tuple(
                target for target in targets if target.bd_name == args.bd_name
            )
            if len(targets) != 1:
                raise RuntimeError("Expected exactly one BD card target.")
        await load_refresh_product_images(database, targets)
        profile_statuses = {
            target.bd_name: creator_profile_status(
                target.application.creator_profile_snapshot,
                target.application.creator_profile_observed_at,
                now=datetime.now(UTC),
            )
            for target in targets
        }
        if args.send_new and any(
            status != "current" for status in profile_statuses.values()
        ):
            raise RuntimeError("Creator details are incomplete or stale; not sent.")
        print(
            json.dumps(
                {
                    "status": "ready",
                    "shop": SHOP_NAME,
                    "target_count": len(targets),
                    "bd_names": sorted(target.bd_name for target in targets),
                    "product_image_counts": {
                        target.bd_name: len(target.product_image_urls)
                        for target in targets
                    },
                    "profile_freshness": profile_statuses,
                    "all_notifications_sent": all(
                        target.outbox.status == "sent" for target in targets
                    ),
                    "all_profiles_enriched": all(
                        target.application.creator_profile_snapshot.get(
                            "schema_version"
                        )
                        == 2
                        for target in targets
                    ),
                    "all_profiles_complete": all(
                        target.application.creator_profile_snapshot.get(
                            "creator_details_complete"
                        )
                        is True
                        for target in targets
                    ),
                    "apply": args.apply,
                },
                ensure_ascii=False,
            )
        )
        if not args.apply:
            return
        sample_client = FeishuSampleBatchClient(
            app_id=settings.feishu_app_id,
            app_secret=settings.feishu_app_secret.get_secret_value(),
            base_token=settings.feishu_sample_base_token.get_secret_value(),
            table_id=settings.feishu_sample_table_id,
        )
        client = FeishuNotificationClient(sample_client)
        avatar_storage = build_sample_creator_avatar_storage(settings)
        avatar_service = (
            SampleNotificationAvatarService(avatar_storage.object_storage, client)
            if avatar_storage is not None
            else None
        )
        product_service = SampleNotificationProductImageService(client)
        updated = []
        for target in targets:
            avatar_img_key, product_img_keys = await resolve_notification_image_keys(
                avatar_service,
                product_service,
                avatar_object_key=target.application.creator_avatar_object_key,
                product_image_urls=target.product_image_urls,
            )
            if args.send_new and not product_img_keys:
                raise RuntimeError(
                    "Product image is unavailable; notification not sent."
                )
            card = build_sample_notification_card(
                build_refresh_card_task(target),
                record_url_template,
                is_test=False,
                avatar_img_key=avatar_img_key,
                product_img_keys=product_img_keys,
            )
            if args.send_new:
                try:
                    message_id = await client.send_card(
                        recipient_open_id=target.outbox.recipient_open_id,
                        card=card,
                        idempotency_key=str(
                            uuid5(
                                NAMESPACE_URL,
                                f"sample-card-product-images-v10:{target.outbox.id}",
                            )
                        ),
                    )
                except FeishuSampleError as error:
                    print(json.dumps({"status": "failed", "code": error.error_code}))
                    raise
                await client.update_card(message_id=message_id, card=card)
            else:
                await client.update_card(message_id=target.message_id, card=card)
            updated.append(target.bd_name)
        verified = await _smoke_rows(database, args.tenant_id, args.shop_id)
        if any(outbox.status != "sent" for outbox, *_rest in verified):
            raise RuntimeError("Card refresh changed notification state.")
        print(
            json.dumps(
                {
                    "status": "succeeded",
                    "shop": SHOP_NAME,
                    "updated_bd_names": sorted(updated),
                    "updated_count": len(updated),
                    "delivery_mode": "new_message" if args.send_new else "update",
                    "new_message_requests": len(updated) if args.send_new else 0,
                    "notification_statuses_unchanged": True,
                },
                ensure_ascii=False,
            )
        )
    finally:
        await database.dispose()


def _arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument("--shop-id", type=UUID, required=True)
    parser.add_argument("--tenant-domain")
    parser.add_argument("--bd-name", choices=sorted(BD_NAMES))
    parser.add_argument("--send-new", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.tenant_domain and not re.fullmatch(
        r"[a-z0-9-]+\.feishu\.cn", args.tenant_domain
    ):
        raise ValueError("Feishu tenant domain is invalid.")
    if args.send_new and not args.bd_name:
        raise ValueError("A single BD name is required when sending a new card.")
    return args


def _validate_settings(settings) -> None:
    if not (
        settings.feishu_app_id
        and settings.feishu_app_secret
        and settings.feishu_sample_base_token
        and settings.feishu_sample_table_id
    ):
        raise RuntimeError("Feishu sample card refresh is not configured.")


def _record_url_template(settings, tenant_domain: str | None) -> str:
    if settings.feishu_sample_record_url_template:
        return settings.feishu_sample_record_url_template
    if not tenant_domain:
        raise RuntimeError("Feishu tenant domain is required for record links.")
    base_token = settings.feishu_sample_base_token.get_secret_value()
    return (
        f"https://{tenant_domain}/base/{base_token}"
        f"?table={settings.feishu_sample_table_id}&record={{record_id}}"
    )


async def _smoke_rows(database, tenant_id, shop_id):
    statement = (
        select(
            SampleNotificationOutbox,
            SampleApplication,
            SampleApplicationWorkflow,
            Shop,
        )
        .join(
            SampleApplication,
            SampleApplication.id == SampleNotificationOutbox.sample_application_id,
        )
        .join(
            SampleApplicationWorkflow,
            SampleApplicationWorkflow.sample_application_id == SampleApplication.id,
        )
        .join(Shop, Shop.id == SampleApplication.shop_id)
        .where(
            SampleNotificationOutbox.tenant_id == tenant_id,
            SampleNotificationOutbox.shop_id == shop_id,
            SampleApplication.tenant_id == tenant_id,
            SampleApplication.shop_id == shop_id,
            SampleApplicationWorkflow.tenant_id == tenant_id,
            SampleApplicationWorkflow.shop_id == shop_id,
            Shop.tenant_id == tenant_id,
            Shop.shop_name == SHOP_NAME,
            SampleNotificationOutbox.payload["source_event_id"].astext.like(
                f"bd-auto:{RULE_VERSION}:%"
            ),
        )
        .order_by(SampleNotificationOutbox.created_at)
    )
    async with database.system_session_factory() as session:
        return tuple((await session.execute(statement)).all())


def _targets(rows, record_url_template):
    if len(rows) != 3 or "{record_id}" not in record_url_template:
        raise RuntimeError("Expected exactly three refreshable smoke cards.")
    targets = []
    for outbox, application, workflow, shop in rows:
        payload = outbox.payload if isinstance(outbox.payload, dict) else {}
        bd_name = payload.get("assigned_bd_name")
        message_id = payload.get("message_id")
        snapshot = application.creator_profile_snapshot
        if (
            bd_name not in BD_NAMES
            or not isinstance(message_id, str)
            or not message_id
            or outbox.status != "sent"
            or not workflow.feishu_record_id
            or not isinstance(snapshot, dict)
            or snapshot.get("schema_version") != 2
        ):
            raise RuntimeError("A smoke card is not safe to refresh.")
        targets.append(
            SimpleNamespace(
                outbox=outbox,
                application=application,
                workflow=workflow,
                shop=shop,
                bd_name=bd_name,
                message_id=message_id,
            )
        )
    if {target.bd_name for target in targets} != BD_NAMES:
        raise RuntimeError("Smoke card BD coverage is incomplete.")
    if len({target.message_id for target in targets}) != 3:
        raise RuntimeError("Smoke card message IDs are not unique.")
    return tuple(targets)


if __name__ == "__main__":
    asyncio.run(main())
