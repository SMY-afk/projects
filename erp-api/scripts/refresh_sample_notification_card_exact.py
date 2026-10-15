from __future__ import annotations

import argparse
import asyncio
import json
from types import SimpleNamespace
from uuid import UUID

from sqlalchemy import and_, select

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.models.sample_application import SampleApplication
from erp_api.models.sample_application_workflow import SampleApplicationWorkflow
from erp_api.models.sample_notification_outbox import SampleNotificationOutbox
from erp_api.models.shop import Shop
from erp_api.services.feishu_notification_client import FeishuNotificationClient
from erp_api.services.feishu_sample_batch_client import FeishuSampleBatchClient
from erp_api.services.sample_bd_assignment import CREATOR_LEVELS
from erp_api.services.sample_creator_avatar_storage import (
    build_sample_creator_avatar_storage,
)
from erp_api.services.sample_notification_avatar import SampleNotificationAvatarService
from erp_api.services.sample_notification_card import build_sample_notification_card
from erp_api.services.sample_notification_delivery import (
    build_shop_record_url_templates,
)
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


async def _load_target(database, arguments):
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
            and_(
                SampleApplicationWorkflow.tenant_id == SampleApplication.tenant_id,
                SampleApplicationWorkflow.shop_id == SampleApplication.shop_id,
                SampleApplicationWorkflow.sample_application_id
                == SampleApplication.id,
            ),
        )
        .join(
            Shop,
            and_(
                Shop.tenant_id == SampleApplication.tenant_id,
                Shop.id == SampleApplication.shop_id,
            ),
        )
        .where(
            SampleNotificationOutbox.tenant_id == arguments.tenant_id,
            SampleNotificationOutbox.shop_id == arguments.shop_id,
            SampleApplication.platform_application_id
            == arguments.platform_application_id,
            SampleApplication.is_current_projection.is_(True),
        )
    )
    async with database.system_session_factory() as session:
        rows = (await session.execute(statement)).all()
    if len(rows) != 1:
        raise RuntimeError("Exact current notification target is missing or ambiguous.")
    outbox, application, workflow, shop = rows[0]
    payload = outbox.payload if isinstance(outbox.payload, dict) else {}
    message_ids = tuple(
        value
        for value in (
            payload.get("message_id"),
            payload.get("group_message_id"),
        )
        if isinstance(value, str) and value
    )
    if (
        outbox.status != "sent"
        or len(message_ids) != 2
        or application.creator_level not in CREATOR_LEVELS
        or not isinstance(application.creator_gmv_minor, int)
        or not workflow.feishu_record_id
    ):
        raise RuntimeError("Notification target is not safe to refresh.")
    return SimpleNamespace(
        outbox=outbox,
        application=application,
        workflow=workflow,
        shop=shop,
        product_image_urls=(),
        message_ids=message_ids,
    )


async def run(arguments) -> None:
    settings = get_settings()
    database = Database(settings.database_url)
    try:
        target = await _load_target(database, arguments)
        await load_refresh_product_images(database, (target,))
        token_provider = FeishuSampleBatchClient(
            app_id=settings.feishu_app_id,
            app_secret=settings.feishu_app_secret.get_secret_value(),
            base_token=settings.feishu_sample_base_token.get_secret_value(),
            table_id=settings.feishu_sample_table_id,
        )
        client = FeishuNotificationClient(token_provider)
        avatar_storage = build_sample_creator_avatar_storage(settings)
        avatar_service = (
            SampleNotificationAvatarService(avatar_storage.object_storage, client)
            if avatar_storage is not None
            else None
        )
        product_image_service = SampleNotificationProductImageService(client)
        avatar_img_key, product_img_keys = await resolve_notification_image_keys(
            avatar_service,
            product_image_service,
            avatar_object_key=target.application.creator_avatar_object_key,
            product_image_urls=target.product_image_urls,
        )
        record_url_template = build_shop_record_url_templates(
            settings.feishu_sample_record_url_template,
            settings.feishu_sample_shop_table_ids,
        ).get(target.shop.id, settings.feishu_sample_record_url_template)
        card = build_sample_notification_card(
            build_refresh_card_task(target),
            record_url_template,
            is_test=False,
            avatar_img_key=avatar_img_key,
            product_img_keys=product_img_keys,
        )
        result = {
            "status": "ready",
            "creator_username": target.application.creator_username,
            "creator_level": target.application.creator_level,
            "creator_gmv_minor": target.application.creator_gmv_minor,
            "message_ids": target.message_ids,
            "apply": arguments.apply,
        }
        if arguments.apply:
            for message_id in target.message_ids:
                await client.update_card(
                    message_id=message_id,
                    card=card,
                )
            result["status"] = "updated"
            result["updated_count"] = len(target.message_ids)
        print(json.dumps(result, ensure_ascii=False))
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument("--shop-id", type=UUID, required=True)
    parser.add_argument("--platform-application-id", required=True)
    parser.add_argument("--apply", action="store_true")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
