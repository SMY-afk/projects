"""Backfill only the derived time-left field on existing Feishu sample rows."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import and_, select

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.models.sample_application import SampleApplication
from erp_api.models.sample_application_workflow import SampleApplicationWorkflow
from erp_api.models.shop import Shop
from erp_api.services.feishu_sample_batch_client import FeishuSampleBatchClient
from erp_api.services.sample_feishu_mapper import format_sample_time_left

SHOP_NAMES = frozenset(
    {"Akeleo Toys", "fanfu toy tool", "Akeleo Fun Toys", "Akeleo-Drive", "NEOPUP"}
)
FIELD_NAME = "样品申请剩余时间"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


async def _targets(database: Database):
    now = datetime.now(UTC)
    statement = (
        select(
            SampleApplication.shop_id,
            Shop.shop_name,
            SampleApplicationWorkflow.feishu_record_id,
            SampleApplication.approve_expiration_at,
            SampleApplication.source_observed_at,
        )
        .join(
            SampleApplicationWorkflow,
            and_(
                SampleApplicationWorkflow.sample_application_id == SampleApplication.id,
                SampleApplicationWorkflow.tenant_id == SampleApplication.tenant_id,
                SampleApplicationWorkflow.shop_id == SampleApplication.shop_id,
            ),
        )
        .join(
            Shop,
            and_(
                Shop.id == SampleApplication.shop_id,
                Shop.tenant_id == SampleApplication.tenant_id,
            ),
        )
        .where(
            Shop.shop_name.in_(SHOP_NAMES),
            SampleApplication.is_current_projection.is_(True),
            SampleApplicationWorkflow.feishu_record_id.is_not(None),
            SampleApplication.approve_expiration_at > now,
        )
    )
    async with database.system_session_factory() as session:
        return (await session.execute(statement)).all()


def _client(settings, shop_id):
    table_id = settings.feishu_sample_shop_table_ids.get(shop_id)
    if table_id is None:
        table_id = settings.feishu_sample_table_id
    if not table_id:
        raise RuntimeError("Feishu sample table is unavailable for a target shop.")
    return FeishuSampleBatchClient(
        app_id=settings.feishu_app_id,
        app_secret=settings.feishu_app_secret.get_secret_value(),
        base_token=settings.feishu_sample_base_token.get_secret_value(),
        table_id=table_id,
    )


async def _read_records(client, record_ids):
    normalized = tuple(record_ids)
    records = {}
    for offset in range(0, len(normalized), 100):
        batch = await client.batch_get_record_snapshots(
            normalized[offset : offset + 100]
        )
        records.update((item.record_id, item.snapshot.fields) for item in batch)
    return records


def _field_matches(actual, desired: str) -> bool:
    if actual == desired:
        return True
    if isinstance(actual, list) and all(isinstance(item, dict) for item in actual):
        parts = [item.get("text") for item in actual]
        return (
            all(isinstance(part, str) for part in parts) and "".join(parts) == desired
        )
    return False


async def main(*, apply: bool) -> None:
    settings = get_settings()
    database = Database(settings.database_url)
    try:
        rows = await _targets(database)
        grouped = defaultdict(dict)
        shop_names = {}
        now = datetime.now(UTC)
        for shop_id, shop_name, record_id, expires_at, observed_at in rows:
            grouped[shop_id][record_id] = {
                FIELD_NAME: format_sample_time_left(expires_at, now=now)
            }
            shop_names[shop_id] = shop_name
        if set(shop_names.values()) != SHOP_NAMES:
            missing = sorted(SHOP_NAMES - set(shop_names.values()))
            raise RuntimeError(
                f"Sample time-left backfill shop scope is incomplete: {missing}"
            )

        results = []
        for shop_id, update_map in grouped.items():
            client = _client(settings, shop_id)
            snapshots = await _read_records(client, update_map)
            missing = set(update_map) - set(snapshots)
            updates = [
                (record_id, fields)
                for record_id, fields in update_map.items()
                if record_id in snapshots
                and not _field_matches(
                    snapshots[record_id].get(FIELD_NAME), fields[FIELD_NAME]
                )
            ]
            if apply:
                for offset in range(0, len(updates), 500):
                    await client.batch_update_records(updates[offset : offset + 500])
                readback = await _read_records(
                    client, (record_id for record_id, _fields in updates)
                )
                mismatches = sum(
                    not _field_matches(
                        readback.get(record_id, {}).get(FIELD_NAME), fields[FIELD_NAME]
                    )
                    for record_id, fields in updates
                )
                if mismatches:
                    raise RuntimeError("Feishu sample time-left readback mismatch.")
            results.append(
                {
                    "shop": shop_names[shop_id],
                    "records": len(update_map),
                    "to_update": len(updates),
                    "missing_remote": len(missing),
                    "verified": len(updates) if apply else 0,
                }
            )
        print(
            json.dumps(
                {
                    "apply": apply,
                    "shops": sorted(results, key=lambda item: item["shop"]),
                },
                ensure_ascii=False,
            )
        )
    finally:
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(main(apply=_arguments().apply))
