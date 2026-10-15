from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256

from app.parsers.affiliate_video_export_parser import (
    AffiliateVideoExportParseError,
    parse_affiliate_video_export,
)
from backend.app.services.tiktok_affiliate_analytics_page_control import capture_log
from backend.app.services.tiktok_affiliate_intent_page import PreparedIntentPage
from backend.app.services.tiktok_affiliate_video_capture import (
    TikTokAffiliateVideoCaptureSession,
)
from backend.app.services.tiktok_affiliate_video_export_download import (
    VideoExportDownloadError,
    delete_download,
    download_video_export,
)
from erp_api.services.affiliate_center_source import AffiliateSourcePageContext
from erp_api.services.affiliate_center_source_adapters import (
    map_browser_export_video_page,
)


class AffiliateVideoExportSyncError(RuntimeError):
    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category


async def sync_video_export(
    prepared: PreparedIntentPage,
    capture: TikTokAffiliateVideoCaptureSession,
) -> None:
    download = None
    try:
        content, task_id, download, request_id = await download_video_export(
            prepared.page, prepared.query
        )
        rows = parse_affiliate_video_export(
            content,
            prepared.query.currency,
            prepared.query.shop_timezone,
        )
        page = map_browser_export_video_page(
            prepared.query,
            rows,
            context=AffiliateSourcePageContext(
                request_id=request_id or _task_request_id(task_id),
                pagination_mode="unknown",
                page_number=1,
                page_size=max(1, len(rows)),
                has_more=False,
                total_count=len(rows),
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
        await capture.persist_mapped_page(page)
        await capture.finalize_resource(
            "videos",
            {
                "status": "complete",
                "failure_category": None,
                "expected_total": len(rows),
                "pages_fetched": 1,
                "records_received": len(rows),
                "records_unique": len({row["videoId"] for row in rows}),
                "duplicates": len(rows) - len({row["videoId"] for row in rows}),
            },
        )
        capture_log(
            "affiliate_video_export_synced",
            pages_fetched=1,
            records_received=len(rows),
            records_unique=len({row["videoId"] for row in rows}),
            duplicates=len(rows) - len({row["videoId"] for row in rows}),
            expected_total=len(rows),
        )
    except VideoExportDownloadError as error:
        raise AffiliateVideoExportSyncError(error.category, str(error)) from error
    except AffiliateVideoExportParseError as error:
        capture_log(_parse_failure_event(error))
        raise AffiliateVideoExportSyncError(
            "video_export_parse_changed", "Video export parse failed"
        ) from error
    except Exception as error:
        raise AffiliateVideoExportSyncError(
            "video_export_persistence_failed", "Video export persistence failed"
        ) from error
    finally:
        if download is not None:
            await delete_download(download)


def _task_request_id(task_id: str) -> str:
    return "export:" + sha256(task_id.encode("utf-8")).hexdigest()[:32]


def _parse_failure_event(error: AffiliateVideoExportParseError) -> str:
    message = str(error)
    fields = {
        "视频 ID": "video_id",
        "发布日期": "post_time",
        "联盟视频归因 GMV": "gmv",
        "归因于视频的订单数": "orders",
        "视频归因成交件数": "items",
        "视频商品曝光次数": "impressions",
        "视频商品点击量": "clicks",
        "视频播放量": "views",
        "完播率": "finish_rate",
        "商品点击率": "click_through_rate",
        "互动率": "engagement_rate",
    }
    field = next((value for key, value in fields.items() if key in message), "workbook")
    reasons = {
        "missing headers": "missing_headers",
        "invalid post time": "invalid_post_time",
        "is fractional": "fractional",
        "exceeds 100%": "over_100_percent",
        "is not numeric": "invalid_number",
        "must be non-negative": "negative_number",
    }
    reason = next(
        (value for key, value in reasons.items() if key in message),
        "invalid_format",
    )
    return f"affiliate_video_export_parse_failed_{field}_{reason}"
