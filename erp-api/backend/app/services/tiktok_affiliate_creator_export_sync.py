from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from urllib.parse import parse_qs, urlsplit

from app.parsers.affiliate_creator_export_parser import (
    AffiliateCreatorExportParseError,
    parse_affiliate_creator_export,
)
from backend.app.services.tiktok_affiliate_analytics_page_control import (
    capture_log,
)
from backend.app.services.tiktok_affiliate_contract import platform_shop_id
from backend.app.services.tiktok_affiliate_creator_capture import (
    TikTokAffiliateCreatorCaptureSession,
)
from backend.app.services.tiktok_affiliate_creator_export_download import (
    CreatorExportDownloadError,
    delete_download,
    download_creator_export,
)
from backend.app.services.tiktok_affiliate_creator_identity_sample import (
    CreatorIdentitySample,
    CreatorIdentitySource,
    collect_creator_identity_sample,
    creator_identity_page_limit,
    prepare_creator_identity_source,
)
from backend.app.services.tiktok_affiliate_intent_page import PreparedIntentPage
from erp_api.services.affiliate_center_capture_policy import (
    evaluate_capture_completeness,
)
from erp_api.services.affiliate_center_source import AffiliateSourcePageContext
from erp_api.services.affiliate_center_source_adapters import (
    map_browser_export_creator_page,
)
from erp_api.services.affiliate_metric_parse_support import creator_username_key


class AffiliateCreatorExportSyncError(RuntimeError):
    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category


def _avatar_refresh_enabled() -> bool:
    value = os.getenv("AFFILIATE_CREATOR_AVATAR_REFRESH", "1")
    return value.strip().casefold() not in {"0", "false", "no", "off"}


async def sync_creator_export(
    prepared: PreparedIntentPage,
    capture: TikTokAffiliateCreatorCaptureSession,
) -> None:
    try:
        resolved_platform_shop_id = _creator_page_shop_id(prepared.page.url)
    except Exception as error:
        raise AffiliateCreatorExportSyncError(
            "creator_probe_metadata_failed", "Creator page shop metadata unavailable"
        ) from error
    identity_source = await _read_creator_identity_source(prepared)
    expected_total = (
        identity_source.expected_total if identity_source is not None else None
    )
    try:
        content, file_id, download, export_request_id = await download_creator_export(
            prepared.page
        )
    except CreatorExportDownloadError as error:
        raise AffiliateCreatorExportSyncError(error.category, str(error)) from error
    try:
        rows = parse_affiliate_creator_export(content, prepared.query.currency)
        export_unique_count = len({str(row["username"]).casefold() for row in rows})
        unique_count = export_unique_count
        page = map_browser_export_creator_page(
            prepared.query,
            rows,
            context=AffiliateSourcePageContext(
                request_id=(export_request_id or _file_request_id(file_id)),
                pagination_mode="unknown",
                page_number=1,
                page_size=max(1, len(rows)),
                has_more=False,
                total_count=expected_total,
                source_updated_at=datetime.now(UTC),
            ),
            raw_payload={
                "export": {
                    "format": "xlsx",
                    "recordCount": len(rows),
                    "remoteRetentionDays": 7,
                    "localFilePersisted": False,
                }
            },
        )
        identity_sample = await _reconciliation_sample(
            prepared,
            capture,
            export_total=unique_count,
            expected_total=expected_total,
            source=identity_source,
        )
        reconciled, added_count = _reconcile_export_records(
            page.records,
            identity_sample,
            expected_total,
        )
        if reconciled != page.records:
            page = replace(
                page,
                records=reconciled,
                raw_payload={
                    **page.raw_payload,
                    "reconciliation": {
                        "source": "creator_list",
                        "recordsAdded": added_count,
                    },
                },
            )
            unique_count = len(reconciled)
        await capture.persist_mapped_page(
            page,
            platform_shop_id=resolved_platform_shop_id,
        )
        completeness = evaluate_capture_completeness(
            has_more=False,
            next_cursor=None,
            unique_record_count=unique_count,
            total_count=expected_total,
        )
        source_total_available = expected_total is not None
        complete = source_total_available and completeness.complete
        snapshot = {
            "status": "complete" if complete else "partial",
            "failure_category": (
                None
                if complete
                else completeness.reason
                if source_total_available
                else "page_failed"
            ),
            "expected_total": expected_total,
            "pages_fetched": 1,
            "records_received": len(rows) + added_count,
            "records_unique": unique_count,
            "duplicates": len(rows) - export_unique_count,
        }
        await capture.finalize_resource("creators", snapshot)
        if _avatar_refresh_enabled():
            await _refresh_creator_avatars(
                prepared,
                capture,
                rows,
                sample=identity_sample,
                source=identity_source,
            )
        capture_log(
            "affiliate_creator_export_synced",
            pages_fetched=1,
            records_received=len(rows) + added_count,
            records_unique=unique_count,
            duplicates=len(rows) - export_unique_count,
            expected_total=expected_total,
        )
    except AffiliateCreatorExportParseError as error:
        raise AffiliateCreatorExportSyncError(
            "creator_export_parse_changed", "Creator export parse failed"
        ) from error
    except Exception as error:
        raise AffiliateCreatorExportSyncError(
            "creator_export_persistence_failed", "Creator export persistence failed"
        ) from error
    finally:
        await delete_download(download)


async def _refresh_creator_avatars(
    prepared: PreparedIntentPage,
    capture: TikTokAffiliateCreatorCaptureSession,
    rows: list[dict[str, object]],
    *,
    sample: CreatorIdentitySample | None = None,
    source: CreatorIdentitySource | None = None,
) -> None:
    try:
        if sample is None:
            sample = await collect_creator_identity_sample(
                prepared.page,
                prepared.query,
                capture.tenant_id,
                max_pages=30,
                request_interval=0.2,
                target_usernames=_top_creator_usernames(rows),
                trigger=prepared.trigger if source is None else None,
                source=source,
            )
        refreshed = await capture.refresh_identities(prepared.query, sample.records)
        capture_log(
            "affiliate_creator_avatars_refreshed",
            shop_id=str(prepared.query.shop_id),
            records_unique=refreshed,
        )
    except Exception:  # noqa: BLE001 -- avatar refresh must not invalidate metrics
        capture_log(
            "affiliate_creator_avatar_refresh_failed",
            shop_id=str(prepared.query.shop_id),
        )


async def _reconciliation_sample(
    prepared: PreparedIntentPage,
    capture: TikTokAffiliateCreatorCaptureSession,
    *,
    export_total: int,
    expected_total: int | None,
    source: CreatorIdentitySource | None,
) -> CreatorIdentitySample | None:
    if source is None or expected_total is None or export_total == expected_total:
        return None
    try:
        return await collect_creator_identity_sample(
            prepared.page,
            prepared.query,
            capture.tenant_id,
            max_pages=creator_identity_page_limit(expected_total),
            request_interval=0.2,
            collect_all=True,
            source=source,
        )
    except Exception:  # noqa: BLE001 -- incomplete reconciliation stays partial
        capture_log(
            "affiliate_creator_export_reconciliation_failed",
            shop_id=str(prepared.query.shop_id),
        )
        return None


def _reconcile_export_records(
    records: tuple,
    sample: CreatorIdentitySample | None,
    expected_total: int | None,
) -> tuple[tuple, int]:
    if sample is None or sample.expected_total != expected_total:
        return records, 0
    sample_pairs = ((record.username_normalized, record) for record in sample.records)
    sample_by_username = dict(sample_pairs)
    if len(sample_by_username) != expected_total:
        return records, 0
    export_by_username = {record.username_normalized: record for record in records}
    reconciled = tuple(
        export_by_username.get(*item) for item in sample_by_username.items()
    )
    return reconciled, len(reconciled) - len(export_by_username)


async def _read_creator_identity_source(
    prepared: PreparedIntentPage,
) -> CreatorIdentitySource | None:
    try:
        return await prepare_creator_identity_source(prepared.page, prepared.trigger)
    except Exception:  # noqa: BLE001 -- missing source total makes the run partial
        capture_log(
            "affiliate_creator_source_total_failed",
            shop_id=str(prepared.query.shop_id),
        )
    return None


def _top_creator_usernames(
    rows: list[dict[str, object]], *, limit: int = 50
) -> frozenset[str]:
    ordered = sorted(
        rows,
        key=lambda row: (
            row.get("affiliateGmvMinor")
            if isinstance(row.get("affiliateGmvMinor"), int)
            else -1
        ),
        reverse=True,
    )
    return frozenset(
        creator_username_key(str(row["username"])) for row in ordered[:limit]
    )


def _file_request_id(file_id: str) -> str:
    return "export:" + sha256(file_id.encode("utf-8")).hexdigest()[:32]


def _creator_page_shop_id(url: str) -> str:
    value = platform_shop_id(url)
    if value:
        return value
    values = parse_qs(urlsplit(url).query).get("shop_id")
    if values and values[0].strip():
        return values[0].strip()
    raise ValueError("Creator page shop ID is missing")
