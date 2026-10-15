from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import re
import sys
from types import SimpleNamespace
from uuid import NAMESPACE_URL, UUID, uuid5

if os.name == "nt" and sys.version_info >= (3, 13):
    platform._wmi = None  # type: ignore[attr-defined]

from sqlalchemy import select

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.models.sample_application import SampleApplication
from erp_api.models.sample_application_workflow import SampleApplicationWorkflow
from erp_api.models.shop import Shop
from erp_api.services.feishu_bd_roster_provider import FeishuBdRosterProvider
from erp_api.services.feishu_notification_client import FeishuNotificationClient
from erp_api.services.feishu_sample_batch_client import FeishuSampleBatchClient
from erp_api.services.sample_creator_avatar_storage import (
    build_sample_creator_avatar_storage,
)
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


async def main() -> None:
    _progress("started")
    args = _arguments()
    settings = get_settings()
    _progress("settings_loaded")
    table_id = _table_id(settings, args.shop_id)
    if not all(
        (
            settings.feishu_app_id,
            settings.feishu_app_secret,
            settings.feishu_sample_base_token,
            table_id,
        )
    ):
        raise RuntimeError("Feishu sample test card is not configured.")
    database = Database(settings.database_url)
    try:
        application, workflow, shop = await _load_target(database, args)
        _progress("target_loaded")
        snapshot = application.creator_profile_snapshot
        if not isinstance(snapshot, dict) or not snapshot.get(
            "creator_details_complete"
        ):
            raise RuntimeError("Creator details are not complete; card not updated.")
        target = SimpleNamespace(
            application=application,
            workflow=workflow,
            shop=shop,
            outbox=SimpleNamespace(payload={"assigned_bd_name": args.bd_name}),
        )
        await load_refresh_product_images(database, (target,))
        _progress("product_sources_loaded")
        sample_client = FeishuSampleBatchClient(
            app_id=settings.feishu_app_id,
            app_secret=settings.feishu_app_secret.get_secret_value(),
            base_token=settings.feishu_sample_base_token.get_secret_value(),
            table_id=table_id,
        )
        roster_client = FeishuSampleBatchClient(
            app_id=settings.feishu_app_id,
            app_secret=settings.feishu_app_secret.get_secret_value(),
            base_token=settings.feishu_sample_base_token.get_secret_value(),
            table_id=args.roster_table_id,
        )
        member = (
            await FeishuBdRosterProvider(
                roster_client,
                allowed_bd_names={args.bd_name},
                default_capacity=1,
            ).list_members(args.tenant_id, args.shop_id)
        )[0]
        _progress("recipient_verified")
        if not member.recipient_open_id:
            raise RuntimeError("Verified BD recipient is unavailable.")
        notification_client = FeishuNotificationClient(sample_client)
        avatar_storage = build_sample_creator_avatar_storage(settings)
        avatar_service = (
            SampleNotificationAvatarService(
                avatar_storage.object_storage, notification_client
            )
            if avatar_storage is not None
            else None
        )
        avatar_key, product_keys = await resolve_notification_image_keys(
            avatar_service,
            SampleNotificationProductImageService(notification_client),
            avatar_object_key=application.creator_avatar_object_key,
            product_image_urls=target.product_image_urls,
        )
        _progress("images_resolved")
        if not product_keys:
            raise RuntimeError("Product images are unavailable; card not updated.")
        base_token = settings.feishu_sample_base_token.get_secret_value()
        record_url_template = (
            f"https://{args.tenant_domain}/base/{base_token}"
            f"?table={table_id}&view={args.view_id}&record={{record_id}}"
        )
        card = build_sample_notification_card(
            build_refresh_card_task(target),
            record_url_template,
            is_test=True,
            avatar_img_key=avatar_key,
            product_img_keys=product_keys,
        )
        message_id = await notification_client.send_card(
            recipient_open_id=member.recipient_open_id,
            card=card,
            idempotency_key=str(
                uuid5(
                    NAMESPACE_URL,
                    f"cross7-test:{application.id}:{member.recipient_open_id}",
                )
            ),
        )
        _progress("message_resolved")
        await notification_client.update_card(message_id=message_id, card=card)
        print(
            json.dumps(
                {
                    "status": "succeeded",
                    "message_id_present": bool(message_id),
                    "card_updated": True,
                    "product_image_count": len(product_keys),
                    "creator_details_complete": True,
                    "creator_profile_source_type": (
                        application.creator_profile_source_type
                    ),
                    "creator_profile_observed_at": (
                        application.creator_profile_observed_at.isoformat()
                        if application.creator_profile_observed_at
                        else None
                    ),
                },
                ensure_ascii=False,
            )
        )
    finally:
        await database.dispose()


async def _load_target(database, args):
    statement = (
        select(SampleApplication, SampleApplicationWorkflow, Shop)
        .join(
            SampleApplicationWorkflow,
            SampleApplicationWorkflow.sample_application_id == SampleApplication.id,
        )
        .join(Shop, Shop.id == SampleApplication.shop_id)
        .where(
            SampleApplication.id == args.application_id,
            SampleApplication.tenant_id == args.tenant_id,
            SampleApplication.shop_id == args.shop_id,
            SampleApplicationWorkflow.tenant_id == args.tenant_id,
            SampleApplicationWorkflow.shop_id == args.shop_id,
            Shop.tenant_id == args.tenant_id,
        )
    )
    async with database.system_session_factory() as session:
        row = (await session.execute(statement)).one_or_none()
    if row is None or not row[1].feishu_record_id:
        raise RuntimeError("Sample application or Feishu record is unavailable.")
    return row


def _arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument("--shop-id", type=UUID, required=True)
    parser.add_argument("--application-id", type=UUID, required=True)
    parser.add_argument("--bd-name", required=True)
    parser.add_argument("--tenant-domain", required=True)
    parser.add_argument("--view-id", required=True)
    parser.add_argument("--roster-table-id", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9-]+\.feishu\.cn", args.tenant_domain):
        raise ValueError("Feishu tenant domain is invalid.")
    if not re.fullmatch(r"vew[A-Za-z0-9]+", args.view_id):
        raise ValueError("Feishu view ID is invalid.")
    if not re.fullmatch(r"tbl[A-Za-z0-9]+", args.roster_table_id):
        raise ValueError("Feishu roster table ID is invalid.")
    return args


def _table_id(settings, shop_id: UUID) -> str | None:
    return (
        settings.feishu_sample_shop_table_ids.get(shop_id)
        or settings.feishu_sample_table_id
    )


def _progress(stage: str) -> None:
    print(json.dumps({"stage": stage}), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
