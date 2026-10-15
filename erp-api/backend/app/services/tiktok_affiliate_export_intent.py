from __future__ import annotations

from urllib.parse import urlsplit
from uuid import UUID

from backend.app.services import tiktok_affiliate_intent_deferral as intent_deferral
from backend.app.services.capture_logging import capture_log
from backend.app.services.tiktok_affiliate_creator_capture import (
    TikTokAffiliateCreatorCaptureSession,
)
from backend.app.services.tiktok_affiliate_creator_export_sync import (
    AffiliateCreatorExportSyncError,
    sync_creator_export,
)
from backend.app.services.tiktok_affiliate_intent_page import PreparedIntentPage
from backend.app.services.tiktok_affiliate_video_capture import (
    TikTokAffiliateVideoCaptureSession,
)
from backend.app.services.tiktok_affiliate_video_export_sync import (
    AffiliateVideoExportSyncError,
    sync_video_export,
)
from erp_api.services.affiliate_capture_health import AffiliateCaptureHealthRepository
from erp_api.services.affiliate_capture_intent_repository import (
    AffiliateCaptureIntent,
    AffiliateCaptureIntentRepository,
)


async def run_export_intent(
    prepared: PreparedIntentPage,
    creator_capture: TikTokAffiliateCreatorCaptureSession,
    video_capture: TikTokAffiliateVideoCaptureSession,
    repository: AffiliateCaptureIntentRepository,
    tenant_id: UUID,
    intent: AffiliateCaptureIntent,
    health_repository: AffiliateCaptureHealthRepository | None,
    stopped,
) -> bool:
    if intent.resource not in {"creators", "videos"}:
        return False
    if (
        intent.resource == "videos"
        and urlsplit(getattr(getattr(prepared, "page", None), "url", "")).hostname
        == "affiliate-us.tiktok.com"
    ):
        return False
    try:
        if intent.resource == "creators":
            await sync_creator_export(prepared, creator_capture)
        else:
            await sync_video_export(prepared, video_capture)
    except (AffiliateCreatorExportSyncError, AffiliateVideoExportSyncError) as error:
        blocker = await intent_deferral.persist_failure_or_deferral(
            repository, tenant_id, intent.run_id, error.category
        )
        if blocker:
            await intent_deferral.defer_session_blocked_intent(
                blocker,
                tenant_id,
                intent,
                health_repository,
                page=prepared.page,
                stopped=stopped,
            )
        capture_log(
            "affiliate_intent_failed",
            tenant_id=tenant_id,
            shop_id=intent.shop_id,
            run_id=intent.run_id,
            failure_category=error.category,
            error_type=_root_error_type(error),
            error_code=_root_error_code(error),
        )
    except Exception as error:  # noqa: BLE001 -- always settle the claimed intent
        category = (
            "creator_export_persistence_failed"
            if intent.resource == "creators"
            else "video_export_persistence_failed"
        )
        await repository.fail_intent(tenant_id, intent.run_id, category)
        capture_log(
            "affiliate_intent_failed",
            tenant_id=tenant_id,
            shop_id=intent.shop_id,
            run_id=intent.run_id,
            failure_category=category,
            error_type=type(error).__name__,
            error_code=_root_error_code(error),
        )
    finally:
        await prepared.cleanup()
    return True


def _root_error_type(error: BaseException) -> str:
    return type(_root_error(error)).__name__


def _root_error_code(error: BaseException) -> str:
    message = " | ".join(_error_chain_messages(error)).casefold()
    fields = {
        "finishrate": "finish_rate",
        "productclickthroughrate": "product_click_through_rate",
        "engagementrate": "engagement_rate",
        "gmvminor": "gmv_minor",
        "estimatedcommissionminor": "estimated_commission_minor",
        "averageordervalueminor": "average_order_value_minor",
        "averagegmvperbuyerminor": "average_gmv_per_buyer_minor",
        "refundedgmvminor": "refunded_gmv_minor",
        "distinctgpmminor": "distinct_gpm_minor",
        "videoposttime": "video_post_time",
        "videoid": "video_id",
        "promotedproductids": "promoted_product_ids",
        "hashtags": "hashtags",
    }
    reasons = {
        "ratio must be between 0 and 1": "ratio_above_one",
        "minor amount must be an integer": "fractional_minor_amount",
        "currency must be a three-letter code": "invalid_currency",
        "does not match": "value_mismatch",
        "required text is missing": "required_value_missing",
        "duplicate values": "duplicate_values",
        "timezone is required": "timezone_missing",
        "invalid timestamp": "invalid_timestamp",
        "missing string": "identifier_missing",
    }
    field = next(
        (code for token, code in fields.items() if token in message), "unknown"
    )
    reason = next(
        (code for token, code in reasons.items() if token in message),
        "validation_failed",
    )
    return f"{field}_{reason}"


def _root_error(error: BaseException) -> BaseException:
    current = error
    seen: set[int] = set()
    while current.__cause__ is not None and id(current) not in seen:
        seen.add(id(current))
        current = current.__cause__
    return current


def _error_chain_messages(error: BaseException) -> list[str]:
    messages: list[str] = []
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        messages.append(str(current))
        current = current.__cause__
    return messages
