from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select

from erp_api.infrastructure.database import Database
from erp_api.models.analytics_quality_alert import AnalyticsQualityAlert
from erp_api.models.analytics_snapshot import TikTokLiveSession, TikTokVideoContent
from erp_api.services.tiktok_data_schemas import TikTokAnalyticsItem


@dataclass(frozen=True)
class QualityAlertInput:
    category: str
    platform_external_id: str | None
    details: dict[str, object]


class AnalyticsQualityRepository:
    """Persists append-only quality evidence without changing operator-traceable alerts."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def record_page_alerts(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        sync_run_id: UUID,
        *,
        resource_type: str,
        items: list[TikTokAnalyticsItem],
        external_id_field: str,
        amount_currency_pairs: Mapping[str, str],
    ) -> int:
        existing = await self._existing_source_times(
            tenant_id, shop_id, resource_type, items, external_id_field
        )
        alerts = evaluate_page_quality(
            items,
            external_id_field=external_id_field,
            amount_currency_pairs=amount_currency_pairs,
            existing_source_updated_at=existing,
        )
        if not alerts:
            return 0
        async for session in self._database.session(tenant_id):
            session.add_all(
                [
                    AnalyticsQualityAlert(
                        tenant_id=tenant_id,
                        shop_id=shop_id,
                        sync_run_id=sync_run_id,
                        resource_type=resource_type,
                        category=alert.category,
                        platform_external_id=alert.platform_external_id,
                        details=alert.details,
                    )
                    for alert in alerts
                ]
            )
            await session.commit()
            return len(alerts)
        raise RuntimeError("Tenant database session was not created.")

    async def _existing_source_times(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        resource_type: str,
        items: list[TikTokAnalyticsItem],
        external_id_field: str,
    ) -> dict[str, datetime | None]:
        external_ids = sorted(
            {
                external_id
                for item in items
                if isinstance((external_id := item.fields.get(external_id_field)), str)
                and external_id
            }
        )
        if not external_ids:
            return {}
        model, external_id_column = (
            (TikTokVideoContent, TikTokVideoContent.platform_video_id)
            if resource_type == "video"
            else (TikTokLiveSession, TikTokLiveSession.platform_live_id)
        )
        async for session in self._database.session(tenant_id):
            rows = (
                await session.execute(
                    select(external_id_column, model.source_updated_at).where(
                        model.shop_id == shop_id,
                        external_id_column.in_(external_ids),
                    )
                )
            ).all()
            return {external_id: updated_at for external_id, updated_at in rows}
        raise RuntimeError("Tenant database session was not created.")


def evaluate_page_quality(
    items: list[TikTokAnalyticsItem],
    *,
    external_id_field: str,
    amount_currency_pairs: Mapping[str, str],
    existing_source_updated_at: Mapping[str, datetime | None],
) -> list[QualityAlertInput]:
    alerts: list[QualityAlertInput] = []
    seen_external_ids: set[str] = set()
    currencies_by_amount_field: dict[str, set[str]] = {}
    for item in items:
        external_id = item.fields.get(external_id_field)
        external_id = (
            external_id if isinstance(external_id, str) and external_id else None
        )
        if external_id and external_id in seen_external_ids:
            alerts.append(
                QualityAlertInput(
                    "duplicate_external_id", external_id, {"field": external_id_field}
                )
            )
        elif external_id:
            seen_external_ids.add(external_id)
        if item.source_updated_at is None:
            alerts.append(
                QualityAlertInput(
                    "missing_date", external_id, {"field": "source_updated_at"}
                )
            )
        elif (
            external_id
            and (stored := existing_source_updated_at.get(external_id))
            and stored > item.source_updated_at
        ):
            alerts.append(
                QualityAlertInput(
                    "platform_time_regression",
                    external_id,
                    {
                        "storedAt": stored.isoformat(),
                        "incomingAt": item.source_updated_at.isoformat(),
                    },
                )
            )
        for amount_field, currency_field in amount_currency_pairs.items():
            amount = item.fields.get(amount_field)
            currency = item.fields.get(currency_field)
            if amount is None and currency is None:
                continue
            if amount is None or not _currency(currency):
                alerts.append(
                    QualityAlertInput(
                        "amount_currency_mismatch",
                        external_id,
                        {"amountField": amount_field, "currencyField": currency_field},
                    )
                )
                continue
            currencies_by_amount_field.setdefault(amount_field, set()).add(
                currency.upper()
            )
    for amount_field, currencies in currencies_by_amount_field.items():
        if len(currencies) > 1:
            alerts.append(
                QualityAlertInput(
                    "amount_currency_mismatch",
                    None,
                    {"amountField": amount_field, "currencies": sorted(currencies)},
                )
            )
    return alerts


def _currency(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.upper()
    return normalized if len(normalized) == 3 and normalized.isalpha() else None
