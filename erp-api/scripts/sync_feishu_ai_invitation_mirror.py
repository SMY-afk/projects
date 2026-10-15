from __future__ import annotations

import argparse
import asyncio
import json

from erp_api.core.config import get_settings
from erp_api.services.feishu_table_mirror_client import FeishuTableMirrorClient
from erp_api.services.sample_ai_invitation_mirror import (
    AI_INVITATION_CREATOR_FIELD,
    AI_INVITATION_SOURCE_RECORD_FIELD,
    AI_INVITATION_TIME_FIELD,
    SampleAiInvitationMirrorService,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


async def main(arguments: argparse.Namespace) -> None:
    settings = get_settings()
    required = (
        settings.feishu_app_id,
        settings.feishu_app_secret,
        settings.feishu_sample_base_token,
        settings.feishu_ai_invitation_table_id,
        settings.feishu_ai_invitation_mirror_table_id,
    )
    if not all(required):
        raise RuntimeError("AI invitation mirror is not fully configured.")
    app_secret = settings.feishu_app_secret.get_secret_value()
    source_base = (
        settings.feishu_ai_invitation_base_token.get_secret_value()
        if settings.feishu_ai_invitation_base_token
        else settings.feishu_sample_base_token.get_secret_value()
    )
    source = FeishuTableMirrorClient(
        app_id=settings.feishu_app_id,
        app_secret=app_secret,
        base_token=source_base,
        table_id=settings.feishu_ai_invitation_table_id,
    )
    target = FeishuTableMirrorClient(
        app_id=settings.feishu_app_id,
        app_secret=app_secret,
        base_token=settings.feishu_sample_base_token.get_secret_value(),
        table_id=settings.feishu_ai_invitation_mirror_table_id,
        writable_fields=(
            AI_INVITATION_CREATOR_FIELD,
            AI_INVITATION_TIME_FIELD,
            AI_INVITATION_SOURCE_RECORD_FIELD,
        ),
    )
    service = SampleAiInvitationMirrorService(source, target)
    await service.validate()
    with (
        source.capture_evidence() as source_trace,
        target.capture_evidence() as target_trace,
    ):
        try:
            result = await service.sync(dry_run=not arguments.apply)
        except Exception:
            print(
                json.dumps(
                    {
                        "source_responses": [
                            item.__dict__ for item in source_trace.responses
                        ],
                        "target_responses": [
                            item.__dict__ for item in target_trace.responses
                        ],
                    },
                    ensure_ascii=True,
                )
            )
            raise
    print(
        json.dumps(
            {"apply": arguments.apply, **result.__dict__},
            ensure_ascii=True,
        )
    )


if __name__ == "__main__":
    asyncio.run(main(_arguments()))
