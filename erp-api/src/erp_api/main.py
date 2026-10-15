import logging
import time
import uuid
from datetime import timedelta
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from erp_api.core.config import Settings, get_settings
from erp_api.core.errors import register_exception_handlers
from erp_api.core.lifespan import create_lifespan
from erp_api.core.logging import configure_logging, request_id_context
from erp_api.infrastructure.database import Database
from erp_api.routers import (
    affiliate,
    affiliate_center,
    affiliate_center_stable,
    affiliate_creator_detail,
    affiliate_live_accounts,
    affiliate_local_export,
    affiliate_service_export,
    auth,
    bestsellers,
    dashboard,
    data,
    feishu_sample_events,
    finance,
    health,
    logistics,
    logistics_tracking,
    orders,
    products,
    remote_affiliate_export,
    remote_sample_capture,
    returns,
    sample_applications,
    shops,
    sync_health,
    tiktok,
    tiktok_callback,
    tiktok_creators,
    tiktok_reauthorization,
)
from erp_api.services.affiliate_capture_intent_repository import (
    AffiliateCaptureIntentRepository,
)
from erp_api.services.affiliate_center_read_repository import (
    AffiliateCenterReadRepository,
)
from erp_api.services.affiliate_creator_detail_read_repository import (
    AffiliateCreatorDetailReadRepository,
)
from erp_api.services.affiliate_creator_persistence import AffiliateCreatorPersistence
from erp_api.services.affiliate_creator_repository import AffiliateCreatorRepository
from erp_api.services.affiliate_live_account_repository import (
    AffiliateLiveAccountRepository,
)
from erp_api.services.affiliate_official_availability import (
    AffiliateOfficialAvailabilityRepository,
)
from erp_api.services.affiliate_official_sync_service import (
    OfficialAffiliateSyncService,
)
from erp_api.services.affiliate_repository import AffiliateRepository
from erp_api.services.affiliate_source_resolver import AffiliateSourceResolver
from erp_api.services.affiliate_video_cover_storage import (
    configured_video_cover_writer,
)
from erp_api.services.affiliate_video_persistence import AffiliateVideoPersistence
from erp_api.services.analytics_quality_repository import AnalyticsQualityRepository
from erp_api.services.analytics_read_repository import AnalyticsReadRepository
from erp_api.services.analytics_repository import AnalyticsRepository
from erp_api.services.analytics_sync_repository import AnalyticsSyncRepository
from erp_api.services.analytics_sync_service import AnalyticsSyncService
from erp_api.services.auth import AuthService
from erp_api.services.auth_repository import AuthRepository
from erp_api.services.bestseller_read_repository import BestsellerReadRepository
from erp_api.services.bestseller_repository import BestsellerRepository
from erp_api.services.bestseller_sync_service import BestsellerSyncService
from erp_api.services.carrier_tracking_registry import CarrierTrackingAdapterRegistry
from erp_api.services.compass_export_rate_gate import CompassExportRateGate
from erp_api.services.creator_connection_repository import (
    CreatorConnectionRepository,
)
from erp_api.services.dashboard_repository import DashboardRepository
from erp_api.services.feishu_assignment_record_client import (
    FeishuAssignmentRecordClient,
)
from erp_api.services.feishu_assignment_workload_provider import (
    FeishuAssignmentWorkloadProvider,
)
from erp_api.services.feishu_bd_invitation_collection_client import (
    FeishuBdInvitationCollectionClient,
)
from erp_api.services.feishu_bd_roster_provider import FeishuBdRosterProvider
from erp_api.services.feishu_creator_export_service import configured_feishu_tables
from erp_api.services.feishu_creator_lookup_client import FeishuCreatorLookupClient
from erp_api.services.feishu_notification_client import FeishuNotificationClient
from erp_api.services.feishu_sample_batch_client import FeishuSampleBatchClient
from erp_api.services.feishu_sample_event_processor import (
    FeishuBusinessEventProcessor,
    FeishuSampleEventProcessor,
)
from erp_api.services.feishu_sample_event_receiver import FeishuSampleEventReceiver
from erp_api.services.feishu_sheet_ai_invitation_client import (
    FeishuSheetAiInvitationClient,
)
from erp_api.services.feishu_table_mirror_client import FeishuTableMirrorClient
from erp_api.services.finance_repository import FinanceRepository
from erp_api.services.finance_sync_repository import FinanceSyncRepository
from erp_api.services.finance_sync_service import FinanceSyncService
from erp_api.services.logistics_carrier_repository import LogisticsCarrierRepository
from erp_api.services.logistics_dispatch_repository import LogisticsDispatchRepository
from erp_api.services.logistics_document_factory import (
    build_logistics_document_service,
)
from erp_api.services.logistics_exception_repository import LogisticsExceptionRepository
from erp_api.services.logistics_exception_service import LogisticsExceptionService
from erp_api.services.logistics_order_status_repository import (
    LogisticsOrderStatusRepository,
)
from erp_api.services.logistics_order_status_service import LogisticsOrderStatusService
from erp_api.services.logistics_package_repository import LogisticsPackageRepository
from erp_api.services.logistics_repository import LogisticsRepository
from erp_api.services.logistics_shipping_repository import LogisticsShippingRepository
from erp_api.services.logistics_shipping_service import LogisticsShippingService
from erp_api.services.logistics_task_generation_repository import (
    LogisticsTaskGenerationRepository,
)
from erp_api.services.logistics_tracking_repository import LogisticsTrackingRepository
from erp_api.services.logistics_tracking_service import LogisticsTrackingService
from erp_api.services.order_logistics_projection import project_order_to_logistics
from erp_api.services.order_repository import OrderRepository
from erp_api.services.order_sync_repository import OrderSyncRepository
from erp_api.services.order_sync_service import OrderSyncService
from erp_api.services.platform_fulfillment_adapter import (
    PlatformFulfillmentAdapterRegistry,
)
from erp_api.services.platform_fulfillment_outbox_repository import (
    PlatformFulfillmentOutboxRepository,
)
from erp_api.services.platform_fulfillment_service import PlatformFulfillmentService
from erp_api.services.product_repository import ProductRepository
from erp_api.services.product_sync_service import ProductSyncService
from erp_api.services.returns_repository import ReturnsRepository
from erp_api.services.returns_sync_repository import ReturnsSyncRepository
from erp_api.services.returns_sync_service import ReturnsSyncService
from erp_api.services.sample_ai_invitation_mirror import (
    AI_INVITATION_CREATOR_FIELD,
    AI_INVITATION_SOURCE_RECORD_FIELD,
    AI_INVITATION_TIME_FIELD,
    SampleAiInvitationMirrorService,
)
from erp_api.services.sample_application_repository import SampleApplicationRepository
from erp_api.services.sample_application_sync_service import (
    SampleApplicationSyncService,
)
from erp_api.services.sample_assignment_image_gate import SampleAssignmentImageGate
from erp_api.services.sample_assignment_record_service import (
    SampleAssignmentRecordService,
)
from erp_api.services.sample_assignment_summary_repository import (
    SampleAssignmentSummaryRepository,
)
from erp_api.services.sample_assignment_summary_service import (
    ASSIGNMENT_SUMMARY_REVISION_KEY,
)
from erp_api.services.sample_auto_assignment_feishu_service import (
    SampleAutoAssignmentFeishuService,
)
from erp_api.services.sample_auto_assignment_repository import (
    SampleAutoAssignmentRepository,
)
from erp_api.services.sample_auto_assignment_service import SampleAutoAssignmentService
from erp_api.services.sample_bd_invitation_protection import (
    BD_INVITATION_CREATOR_FIELD,
    BdInvitationLookupSource,
    SampleBdInvitationProtectionService,
)
from erp_api.services.sample_business_readiness import SampleBusinessReadiness
from erp_api.services.sample_cooperation_reader import (
    DAILY_VALID_CREATOR_ACCOUNT_FIELD,
    DAILY_VALID_CREATORS_TABLE_ID,
    CooperationTableClient,
    SampleCooperationReader,
)
from erp_api.services.sample_cooperation_repository import (
    SampleCooperationRepository,
)
from erp_api.services.sample_cooperation_service import (
    SampleCooperationPrecheckService,
)
from erp_api.services.sample_creator_assignment_ownership import (
    SampleCreatorAssignmentOwnershipReader,
)
from erp_api.services.sample_creator_avatar_storage import (
    build_sample_creator_avatar_storage,
)
from erp_api.services.sample_feishu_client_router import SampleFeishuClientRouter
from erp_api.services.sample_feishu_group_cleanup import (
    delete_grouped_duplicate_records,
)
from erp_api.services.sample_feishu_mapping_repository import (
    SampleFeishuMappingRepository,
)
from erp_api.services.sample_feishu_reverse_poll_service import (
    SampleFeishuReversePollService,
)
from erp_api.services.sample_feishu_source_repository import (
    SampleFeishuSourceRepository,
)
from erp_api.services.sample_feishu_sync_service import SampleFeishuSyncService
from erp_api.services.sample_group_assignment_migration import (
    SampleGroupAssignmentMigrationService,
)
from erp_api.services.sample_notification_avatar import (
    SampleNotificationAvatarService,
)
from erp_api.services.sample_notification_delivery import (
    build_shop_record_url_templates,
)
from erp_api.services.sample_notification_product_image import (
    SampleNotificationProductImageService,
)
from erp_api.services.sample_notification_profile_enrichment import (
    SampleNotificationProfileEnrichmentService,
)
from erp_api.services.sample_notification_repository import (
    SampleNotificationRepository,
)
from erp_api.services.sample_notification_service import SampleNotificationService
from erp_api.services.sample_post_source_work_gate import SamplePostSourceWorkGate
from erp_api.services.sample_shop_pipeline_service import SampleShopPipelineService
from erp_api.services.sample_source_policy import (
    SampleSourcePolicy,
    SampleSourcePolicyRepository,
)
from erp_api.services.sample_source_recovery_service import (
    SampleSourceRecoveryService,
)
from erp_api.services.sample_sync_audit_repository import SampleSyncAuditRepository
from erp_api.services.scraped_data_repository import ScrapedDataRepository
from erp_api.services.shop_repository import ShopRepository
from erp_api.services.sync_health_repository import SyncHealthRepository
from erp_api.services.tiktok_ads_order_client import HttpTikTokAdsOrderClient
from erp_api.services.tiktok_affiliate_order_client import (
    HttpTikTokAffiliateOrderClient,
)
from erp_api.services.tiktok_apps import (
    LEGACY_TIKTOK_APP_PROFILE,
    TikTokAppProfile,
    TikTokAppRegistry,
    TikTokMultiAppAuthorizationService,
)
from erp_api.services.tiktok_authorization import TikTokAuthorizationService
from erp_api.services.tiktok_bestseller_client import HttpTikTokBestsellerClient
from erp_api.services.tiktok_client import HttpTikTokClient
from erp_api.services.tiktok_compass_client import HttpTikTokCompassClient
from erp_api.services.tiktok_data_client import (
    HttpTikTokAnalyticsClient,
    TikTokAnalyticsEndpoint,
)
from erp_api.services.tiktok_finance_client import HttpTikTokFinanceClient
from erp_api.services.tiktok_fulfillment_adapter import TikTokFulfillmentAdapter
from erp_api.services.tiktok_fulfillment_client import HttpTikTokFulfillmentClient
from erp_api.services.tiktok_logistics_client import HttpTikTokLogisticsClient
from erp_api.services.tiktok_order_client import HttpTikTokOrderClient
from erp_api.services.tiktok_overview_client import HttpTikTokOverviewClient
from erp_api.services.tiktok_platform_logistics_sync_repository import (
    PlatformLogisticsSyncRepository,
)
from erp_api.services.tiktok_platform_logistics_sync_service import (
    PlatformLogisticsSyncService,
)
from erp_api.services.tiktok_reauthorization_repository import (
    TikTokReauthorizationRepository,
)
from erp_api.services.tiktok_return_client import HttpTikTokReturnClient
from erp_api.services.tiktok_sample_application_client import (
    HttpTikTokSampleApplicationClient,
)
from erp_api.services.tiktok_transport import TikTokTransport
from erp_api.services.token_cipher import TokenCipher
from erp_api.services.video_performance_repository import (
    VideoPerformanceRepository,
)
from erp_api.services.webhook_service import WebhookService

logger = logging.getLogger("erp_api.request")
REQUEST_ID_HEADER = "X-Request-ID"


def _create_tiktok_authorization_service(
    settings: Settings,
    redis: Redis,
    app_registry: TikTokAppRegistry | None = None,
) -> TikTokAuthorizationService | TikTokMultiAppAuthorizationService | None:
    if not settings.tiktok_service_id or not settings.tiktok_authorization_url:
        return None
    creator_url = (
        settings.tiktok_creator_authorization_url
        or "https://shop.tiktok.com/alliance/creator/auth"
    )
    if app_registry is None:
        return TikTokAuthorizationService(
            redis,
            service_id=settings.tiktok_service_id,
            authorization_url=settings.tiktok_authorization_url,
            app_key=settings.tiktok_app_key,
            creator_authorization_url=creator_url,
            state_ttl_seconds=settings.tiktok_oauth_state_ttl_seconds,
        )
    services = {
        name: TikTokAuthorizationService(
            redis,
            service_id=profile.service_id,
            authorization_url=(
                settings.tiktok_301_authorization_url
                if name == "301"
                else settings.tiktok_authorization_url
            ),
            app_key=profile.app_key,
            creator_authorization_url=(
                creator_url if name == LEGACY_TIKTOK_APP_PROFILE else None
            ),
            state_ttl_seconds=settings.tiktok_oauth_state_ttl_seconds,
            app_profile=name,
        )
        for name, profile in app_registry.profiles.items()
    }
    return TikTokMultiAppAuthorizationService(services, app_registry)


def _create_tiktok_client(
    settings: Settings,
    app_registry: TikTokAppRegistry | None = None,
) -> HttpTikTokClient | None:
    required = (
        settings.tiktok_app_key,
        settings.tiktok_app_secret,
        settings.tiktok_token_url,
        settings.tiktok_shop_identity_url,
    )
    if not all(required):
        return None
    token_base_url, token_path = _split_endpoint(settings.tiktok_token_url)
    api_base_url, identity_path = _split_endpoint(settings.tiktok_shop_identity_url)
    if app_registry is not None:
        auth_transport = app_registry.create_transport(token_base_url)
        api_transport = app_registry.create_transport(api_base_url)
    else:
        transport_options = {
            "app_key": settings.tiktok_app_key,
            "app_secret": settings.tiktok_app_secret.get_secret_value(),
            "timeout_seconds": settings.tiktok_request_timeout_seconds,
            "max_retries": settings.tiktok_request_max_retries,
            "retry_base_seconds": settings.tiktok_retry_base_seconds,
            "max_retry_delay_seconds": settings.tiktok_max_retry_delay_seconds,
        }
        auth_transport = TikTokTransport(base_url=token_base_url, **transport_options)
        api_transport = TikTokTransport(base_url=api_base_url, **transport_options)
    return HttpTikTokClient(
        auth_transport=auth_transport,
        api_transport=api_transport,
        token_path=token_path,
        identity_path=identity_path,
    )


def _create_tiktok_affiliate_order_client(
    settings: Settings,
    client: HttpTikTokClient | None,
) -> HttpTikTokAffiliateOrderClient | None:
    if client is None or not settings.tiktok_affiliate_order_url:
        return None
    _, path = _split_endpoint(settings.tiktok_affiliate_order_url)
    return HttpTikTokAffiliateOrderClient(client.api_transport, path=path)


def _create_tiktok_ads_order_client(
    settings: Settings,
    client: HttpTikTokClient | None,
) -> HttpTikTokAdsOrderClient | None:
    if client is None or not settings.tiktok_ads_order_url:
        return None
    _, path = _split_endpoint(settings.tiktok_ads_order_url)
    return HttpTikTokAdsOrderClient(client.api_transport, path=path)


def _create_tiktok_bestseller_client(
    client: HttpTikTokClient | None,
) -> HttpTikTokBestsellerClient | None:
    return HttpTikTokBestsellerClient(client.api_transport) if client else None


def _create_tiktok_finance_client(
    settings: Settings, client: HttpTikTokClient | None
) -> HttpTikTokFinanceClient | None:
    if client is None:
        return None
    return HttpTikTokFinanceClient(
        client.api_transport,
        statements_path=settings.tiktok_finance_statements_path,
        payments_path=settings.tiktok_finance_payments_path,
        statement_transactions_path=settings.tiktok_finance_statement_transactions_path,
        order_transactions_path=settings.tiktok_finance_order_transactions_path,
        unsettled_transactions_path=settings.tiktok_finance_unsettled_transactions_path,
    )


def _create_tiktok_analytics_client(
    settings: Settings,
    app_registry: TikTokAppRegistry | None = None,
) -> HttpTikTokAnalyticsClient | None:
    required = (
        settings.tiktok_app_key,
        settings.tiktok_app_secret,
        settings.tiktok_video_analytics_url,
        settings.tiktok_live_analytics_url,
        settings.tiktok_video_analytics_field_map,
        settings.tiktok_live_analytics_field_map,
    )
    if not all(required):
        return None
    video_base_url, video_path = _split_endpoint(settings.tiktok_video_analytics_url)
    live_base_url, live_path = _split_endpoint(settings.tiktok_live_analytics_url)
    return HttpTikTokAnalyticsClient(
        video_transport=_create_profile_aware_transport(
            settings, video_base_url, app_registry
        ),
        live_transport=_create_profile_aware_transport(
            settings, live_base_url, app_registry
        ),
        video_endpoint=TikTokAnalyticsEndpoint(
            path=video_path,
            items_path=settings.tiktok_video_analytics_items_path,
            next_page_token_path=settings.tiktok_video_analytics_next_page_token_path,
            field_map=settings.tiktok_video_analytics_field_map,
            required_fields=tuple(settings.tiktok_video_analytics_required_fields),
            source_updated_at_path=settings.tiktok_video_analytics_source_updated_at_path,
            item_source_updated_at_path=settings.tiktok_video_analytics_item_source_updated_at_path,
            status_path=settings.tiktok_video_analytics_status_path,
            status_map=settings.tiktok_video_analytics_status_map,
            max_window_days=settings.tiktok_video_analytics_max_window_days,
        ),
        live_endpoint=TikTokAnalyticsEndpoint(
            path=live_path,
            items_path=settings.tiktok_live_analytics_items_path,
            next_page_token_path=settings.tiktok_live_analytics_next_page_token_path,
            field_map=settings.tiktok_live_analytics_field_map,
            required_fields=tuple(settings.tiktok_live_analytics_required_fields),
            source_updated_at_path=settings.tiktok_live_analytics_source_updated_at_path,
            item_source_updated_at_path=settings.tiktok_live_analytics_item_source_updated_at_path,
            status_path=settings.tiktok_live_analytics_status_path,
            status_map=settings.tiktok_live_analytics_status_map,
            max_window_days=settings.tiktok_live_analytics_max_window_days,
            empty_data_as_empty_page=True,
        ),
    )


def _create_tiktok_overview_client(
    settings: Settings,
    app_registry: TikTokAppRegistry | None = None,
) -> HttpTikTokOverviewClient | None:
    required = (
        settings.tiktok_app_key,
        settings.tiktok_app_secret,
        settings.tiktok_video_analytics_overview_url,
        settings.tiktok_live_analytics_overview_url,
    )
    if not all(required):
        return None
    video_base_url, video_path = _split_endpoint(
        settings.tiktok_video_analytics_overview_url
    )
    live_base_url, live_path = _split_endpoint(
        settings.tiktok_live_analytics_overview_url
    )
    return HttpTikTokOverviewClient(
        video_transport=_create_profile_aware_transport(
            settings, video_base_url, app_registry
        ),
        live_transport=_create_profile_aware_transport(
            settings, live_base_url, app_registry
        ),
        video_path=video_path,
        live_path=live_path,
        max_window_days=min(
            settings.tiktok_video_analytics_max_window_days,
            settings.tiktok_live_analytics_max_window_days,
        ),
    )


def _split_endpoint(endpoint: str) -> tuple[str, str]:
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("TikTok endpoint must be an absolute HTTP(S) URL.")
    if parsed.query or parsed.fragment:
        raise ValueError("TikTok endpoint must not contain a query string or fragment.")
    return f"{parsed.scheme}://{parsed.netloc}", parsed.path or "/"


def _create_profile_aware_transport(
    settings: Settings,
    base_url: str,
    app_registry: TikTokAppRegistry | None,
):
    if app_registry is not None:
        return app_registry.create_transport(base_url)
    return TikTokTransport(
        base_url=base_url,
        app_key=settings.tiktok_app_key,
        app_secret=settings.tiktok_app_secret.get_secret_value(),
        timeout_seconds=settings.tiktok_request_timeout_seconds,
        max_retries=settings.tiktok_request_max_retries,
        retry_base_seconds=settings.tiktok_retry_base_seconds,
        max_retry_delay_seconds=settings.tiktok_max_retry_delay_seconds,
    )


def _create_shop_repository(
    settings: Settings, database: Database
) -> ShopRepository | None:
    if not settings.tiktok_token_encryption_key:
        return None
    return ShopRepository(
        database, TokenCipher(settings.tiktok_token_encryption_key.get_secret_value())
    )


def _create_tiktok_app_registry(
    settings: Settings,
    shop_repository: ShopRepository | None,
) -> TikTokAppRegistry | None:
    legacy_values = (
        settings.tiktok_app_key,
        settings.tiktok_app_secret,
        settings.tiktok_service_id,
    )
    if shop_repository is None or not all(legacy_values):
        return None
    profiles = {
        LEGACY_TIKTOK_APP_PROFILE: TikTokAppProfile(
            name=LEGACY_TIKTOK_APP_PROFILE,
            app_key=settings.tiktok_app_key,
            app_secret=settings.tiktok_app_secret.get_secret_value(),
            service_id=settings.tiktok_service_id,
        )
    }
    app_301_values = (
        settings.tiktok_301_app_key,
        settings.tiktok_301_app_secret,
        settings.tiktok_301_service_id,
    )
    if any(app_301_values) and not all(app_301_values):
        raise ValueError(
            "TikTok 301 App settings must be configured as a complete set."
        )
    if all(app_301_values):
        profiles["301"] = TikTokAppProfile(
            name="301",
            app_key=settings.tiktok_301_app_key,
            app_secret=settings.tiktok_301_app_secret.get_secret_value(),
            service_id=settings.tiktok_301_service_id,
        )
    return TikTokAppRegistry(
        profiles,
        shop_repository,
        timeout_seconds=settings.tiktok_request_timeout_seconds,
        max_retries=settings.tiktok_request_max_retries,
        retry_base_seconds=settings.tiktok_retry_base_seconds,
        max_retry_delay_seconds=settings.tiktok_max_retry_delay_seconds,
    )


def _create_tiktok_reauthorization_repository(
    settings: Settings, database: Database
) -> TikTokReauthorizationRepository | None:
    if not settings.tiktok_token_encryption_key:
        return None
    return TikTokReauthorizationRepository(
        database, TokenCipher(settings.tiktok_token_encryption_key.get_secret_value())
    )


def _create_creator_connection_repository(
    settings: Settings, database: Database
) -> CreatorConnectionRepository | None:
    if not settings.tiktok_token_encryption_key:
        return None
    return CreatorConnectionRepository(
        database, TokenCipher(settings.tiktok_token_encryption_key.get_secret_value())
    )


def _create_product_repository(
    settings: Settings, database: Database
) -> ProductRepository | None:
    if not settings.tiktok_token_encryption_key:
        return None
    return ProductRepository(
        database, TokenCipher(settings.tiktok_token_encryption_key.get_secret_value())
    )


def build_product_services(
    settings: Settings,
    database: Database,
    client: HttpTikTokClient | None = None,
) -> dict[str, object | None]:
    repository = _create_product_repository(settings, database)
    if client is None:
        routing_repository = _create_shop_repository(settings, database)
        app_registry = _create_tiktok_app_registry(settings, routing_repository)
        client = _create_tiktok_client(settings, app_registry)
    service = (
        ProductSyncService(repository, client)
        if repository is not None and client is not None
        else None
    )
    return {"product_repository": repository, "product_sync_service": service}


def build_order_services(
    settings: Settings,
    database: Database,
    *,
    tiktok_client: HttpTikTokClient | None = None,
) -> dict[str, object | None]:
    if not settings.order_pii_encryption_key:
        return {
            "order_repository": None,
            "order_sync_repository": None,
            "order_sync_service": None,
        }
    pii_cipher = TokenCipher(settings.order_pii_encryption_key.get_secret_value())
    order_repository = OrderRepository(database, pii_cipher)
    sync_repository = OrderSyncRepository(
        database,
        pii_cipher,
        settings.order_pii_retention_days,
        logistics_projector=project_order_to_logistics,
    )
    shop_repository = _create_shop_repository(settings, database)
    app_registry = _create_tiktok_app_registry(settings, shop_repository)
    client = tiktok_client or _create_tiktok_client(settings, app_registry)
    affiliate_order_client = _create_tiktok_affiliate_order_client(settings, client)
    ads_order_client = _create_tiktok_ads_order_client(settings, client)
    order_sync_service = None
    if client is not None and shop_repository is not None:
        order_sync_service = OrderSyncService(
            sync_repository,
            order_repository,
            shop_repository,
            client,
            HttpTikTokOrderClient(client.api_transport),
            settings.order_initial_backfill_days,
            affiliate_order_client=affiliate_order_client,
            ads_order_client=ads_order_client,
            ads_access_token=(
                settings.tiktok_ads_access_token.get_secret_value()
                if settings.tiktok_ads_access_token
                else None
            ),
        )
    return {
        "order_repository": order_repository,
        "order_sync_repository": sync_repository,
        "order_sync_service": order_sync_service,
    }


def build_sample_application_services(
    settings: Settings,
    database: Database,
    *,
    ai_snapshot_store=None,
    assignment_change_notifier=None,
) -> dict[str, object | None]:
    application_repository = SampleApplicationRepository(database)
    notification_repository = SampleNotificationRepository(database)
    feishu_mapping_repository = SampleFeishuMappingRepository(database)
    feishu_source_repository = SampleFeishuSourceRepository(
        database,
        activation_at=settings.feishu_sample_auto_assignment_activation_at,
    )
    audit_repository = SampleSyncAuditRepository(database)
    shop_repository = _create_shop_repository(settings, database)
    app_registry = _create_tiktok_app_registry(settings, shop_repository)
    tiktok_client = _create_tiktok_client(settings, app_registry)
    avatar_storage = build_sample_creator_avatar_storage(settings)
    service = None
    source_policy_repository = SampleSourcePolicyRepository(database)
    source_policy = SampleSourcePolicy(source_policy_repository)
    recovery_service = None
    feishu_client = None
    feishu_client_router = None
    feishu_sync_service = None
    feishu_event_processor = None
    feishu_reverse_poll_service = None
    notification_service = None
    auto_assignment_service = None
    product_image_service = None
    roster_provider = None
    auto_assignment_projection = None
    assignment_record_service = None
    profile_enrichment_service = None
    cooperation_precheck_service = None
    bd_invitation_protection_service = None
    ai_invitation_mirror_service = None
    shop_pipeline_service = None
    group_cleanup = None
    if shop_repository is not None and tiktok_client is not None:
        service = SampleApplicationSyncService(
            audit_repository,
            application_repository,
            shop_repository,
            HttpTikTokSampleApplicationClient(tiktok_client.api_transport),
            avatar_storage=avatar_storage,
        )
        recovery_service = SampleSourceRecoveryService(
            source_policy_repository,
            service,
        )
    if (
        settings.feishu_app_id
        and settings.feishu_app_secret
        and settings.feishu_sample_base_token
        and (settings.feishu_sample_table_id or settings.feishu_sample_shop_table_ids)
    ):
        client_options = {
            "app_id": settings.feishu_app_id,
            "app_secret": settings.feishu_app_secret.get_secret_value(),
            "base_token": settings.feishu_sample_base_token.get_secret_value(),
        }
        if settings.feishu_sample_table_id:
            feishu_client = FeishuSampleBatchClient(
                **client_options,
                table_id=settings.feishu_sample_table_id,
            )
        clients_by_shop = {}
        for shop_id, table_id in settings.feishu_sample_shop_table_ids.items():
            if (
                feishu_client is not None
                and table_id == settings.feishu_sample_table_id
            ):
                clients_by_shop[shop_id] = feishu_client
            else:
                clients_by_shop[shop_id] = FeishuSampleBatchClient(
                    **client_options,
                    table_id=table_id,
                )
        feishu_client_router = SampleFeishuClientRouter(
            feishu_client,
            clients_by_shop,
        )
        feishu_sync_service = SampleFeishuSyncService(
            feishu_source_repository,
            feishu_mapping_repository,
            audit_repository,
            feishu_client_router,
            deduplication_started_at=(
                settings.feishu_sample_auto_assignment_activation_at
            ),
        )
        ai_invitation_sheet_client = None
        if (
            settings.feishu_ai_invitation_sheet_token
            or settings.feishu_ai_invitation_sheet_id
        ):
            if not (
                settings.feishu_ai_invitation_sheet_token
                and settings.feishu_ai_invitation_sheet_id
            ):
                raise ValueError("AI invitation sheet configuration is incomplete.")
            ai_invitation_sheet_client = FeishuSheetAiInvitationClient(
                app_id=settings.feishu_app_id,
                app_secret=settings.feishu_app_secret.get_secret_value(),
                spreadsheet_token=settings.feishu_ai_invitation_sheet_token,
                sheet_id=settings.feishu_ai_invitation_sheet_id,
            )
        if (
            settings.feishu_ai_invitation_table_id
            and settings.feishu_ai_invitation_mirror_table_id
        ):
            source_base_token = (
                settings.feishu_ai_invitation_base_token.get_secret_value()
                if settings.feishu_ai_invitation_base_token
                else settings.feishu_sample_base_token.get_secret_value()
            )
            ai_invitation_mirror_service = SampleAiInvitationMirrorService(
                FeishuTableMirrorClient(
                    app_id=settings.feishu_app_id,
                    app_secret=settings.feishu_app_secret.get_secret_value(),
                    base_token=source_base_token,
                    table_id=settings.feishu_ai_invitation_table_id,
                ),
                FeishuTableMirrorClient(
                    app_id=settings.feishu_app_id,
                    app_secret=settings.feishu_app_secret.get_secret_value(),
                    base_token=settings.feishu_sample_base_token.get_secret_value(),
                    table_id=settings.feishu_ai_invitation_mirror_table_id,
                    writable_fields=(
                        AI_INVITATION_CREATOR_FIELD,
                        AI_INVITATION_TIME_FIELD,
                        AI_INVITATION_SOURCE_RECORD_FIELD,
                    ),
                ),
            )

        async def group_cleanup(
            *,
            tenant_id: uuid.UUID,
            shop_id: uuid.UUID,
            obsolete_platform_application_ids: frozenset[str],
        ):
            return await delete_grouped_duplicate_records(
                feishu=feishu_client_router.for_shop(shop_id),
                mappings=feishu_mapping_repository,
                tenant_id=tenant_id,
                shop_id=shop_id,
                obsolete_platform_application_ids=(obsolete_platform_application_ids),
                allow_delete=True,
            )

        if settings.feishu_sample_auto_assignment_enabled and feishu_client is not None:
            assignment_record_client = FeishuAssignmentRecordClient(
                app_id=settings.feishu_app_id,
                app_secret=settings.feishu_app_secret.get_secret_value(),
                base_token=settings.feishu_sample_base_token.get_secret_value(),
                table_id=settings.feishu_bd_assignment_record_table_id,
            )
            assignment_workloads = FeishuAssignmentWorkloadProvider(
                assignment_record_client,
                SampleAssignmentSummaryRepository(database),
                bd_aliases=settings.feishu_assignment_summary_bd_aliases,
            )
            refundable_assignment_client = None
            if settings.feishu_refundable_assignment_record_table_id:
                from erp_api.services.sample_assignment_type_router import CombinedAssignmentReader

                refundable_assignment_client = FeishuAssignmentRecordClient(
                    app_id=settings.feishu_app_id,
                    app_secret=settings.feishu_app_secret.get_secret_value(),
                    base_token=settings.feishu_sample_base_token.get_secret_value(),
                    table_id=settings.feishu_refundable_assignment_record_table_id,
                )
                assignment_workloads = FeishuAssignmentWorkloadProvider(
                    CombinedAssignmentReader(assignment_record_client, refundable_assignment_client),
                    SampleAssignmentSummaryRepository(database),
                    bd_aliases=settings.feishu_assignment_summary_bd_aliases,
                )
            roster_client = FeishuSampleBatchClient(
                app_id=settings.feishu_app_id,
                app_secret=settings.feishu_app_secret.get_secret_value(),
                base_token=settings.feishu_sample_base_token.get_secret_value(),
                table_id=settings.feishu_bd_roster_table_id,
            )
            roster_provider = FeishuBdRosterProvider(
                roster_client,
                allowed_bd_names=settings.sample_auto_assignment_bd_name_set,
                default_capacity=settings.feishu_sample_auto_assignment_bd_capacity,
                assignment_workloads=assignment_workloads,
            )
            valid_creator_client = FeishuSampleBatchClient(
                app_id=settings.feishu_app_id,
                app_secret=settings.feishu_app_secret.get_secret_value(),
                base_token=settings.feishu_sample_base_token.get_secret_value(),
                table_id=(settings.feishu_daily_valid_creator_table_id or DAILY_VALID_CREATORS_TABLE_ID),
            )
            ai_invitation_lookup_client = None
            if ai_invitation_sheet_client is not None:
                ai_invitation_lookup_client = ai_invitation_sheet_client
            elif settings.feishu_ai_invitation_table_id:
                ai_invitation_lookup_client = FeishuCreatorLookupClient(
                    app_id=settings.feishu_app_id,
                    app_secret=settings.feishu_app_secret.get_secret_value(),
                    base_token=(
                        settings.feishu_ai_invitation_base_token.get_secret_value()
                        if settings.feishu_ai_invitation_base_token
                        else settings.feishu_sample_base_token.get_secret_value()
                    ),
                    table_id=settings.feishu_ai_invitation_table_id,
                )
            if settings.feishu_bd_invitation_protection_table_id:
                valid_creator_lookup_client = FeishuCreatorLookupClient(
                    app_id=settings.feishu_app_id,
                    app_secret=settings.feishu_app_secret.get_secret_value(),
                    base_token=settings.feishu_sample_base_token.get_secret_value(),
                    table_id=(settings.feishu_daily_valid_creator_table_id or DAILY_VALID_CREATORS_TABLE_ID),
                )
                invitation_lookup_sources = [
                    BdInvitationLookupSource(
                        "（每日更新）有效达人",
                        valid_creator_lookup_client,
                        DAILY_VALID_CREATOR_ACCOUNT_FIELD,
                    )
                ]
                unavailable_invitation_sources: tuple[str, ...] = ("AI邀约表",)
                if ai_invitation_lookup_client is not None:
                    invitation_lookup_sources.append(
                        BdInvitationLookupSource(
                            "AI邀约表",
                            ai_invitation_lookup_client,
                            BD_INVITATION_CREATOR_FIELD,
                        )
                    )
                    unavailable_invitation_sources = ()
                bd_invitation_protection_service = SampleBdInvitationProtectionService(
                    FeishuBdInvitationCollectionClient(
                        app_id=settings.feishu_app_id,
                        app_secret=settings.feishu_app_secret.get_secret_value(),
                        base_token=(
                            settings.feishu_sample_base_token.get_secret_value()
                        ),
                        table_id=(settings.feishu_bd_invitation_protection_table_id),
                    ),
                    lookup_sources=tuple(invitation_lookup_sources),
                    unavailable_sources=unavailable_invitation_sources,
                    ai_snapshot_store=ai_snapshot_store,
                )
            cooperation_tables = tuple(
                CooperationTableClient(
                    label=table.product_line,
                    client=FeishuSampleBatchClient(
                        app_id=settings.feishu_app_id,
                        app_secret=settings.feishu_app_secret.get_secret_value(),
                        base_token=table.app_token,
                        table_id=table.table_id,
                    ),
                    view_id=table.view_id,
                )
                for table in configured_feishu_tables(settings)
            )
            cooperation_precheck_service = SampleCooperationPrecheckService(
                SampleCooperationRepository(
                    database,
                    activation_at=(
                        settings.feishu_sample_auto_assignment_activation_at
                    ),
                    batch_limit=settings.feishu_sample_auto_assignment_batch_limit,
                ),
                SampleCooperationReader(
                    cooperation_tables,
                    roster_client,
                    valid_creator_client,
                    bd_invitation_protection_service,
                    ai_invitation_client=ai_invitation_lookup_client,
                ),
                FeishuNotificationClient(feishu_client),
                feishu_client_router,
                exception_chat_id=(settings.feishu_sample_notification_group_chat_id),
                delivery_enabled=(
                    settings.feishu_sample_notification_live_recipients_enabled
                ),
                assignment_ownership=SampleCreatorAssignmentOwnershipReader(database),
            )
            auto_assignment_repository = SampleAutoAssignmentRepository(
                database,
                category=settings.feishu_sample_auto_assignment_category,
                batch_limit=settings.feishu_sample_auto_assignment_batch_limit,
                activation_at=settings.feishu_sample_auto_assignment_activation_at,
            )
            product_image_service = SampleNotificationProductImageService(
                FeishuNotificationClient(feishu_client)
            )
            auto_assignment_service = SampleAutoAssignmentService(
                auto_assignment_repository,
                roster_provider,
                SampleAssignmentImageGate(database, product_image_service),
                allowed_shop_ids=settings.sample_auto_assignment_shop_id_set,
            )
            auto_assignment_projection = SampleAutoAssignmentFeishuService(
                database,
                feishu_client_router,
                limit=settings.feishu_sample_auto_assignment_batch_limit,
            )
            assignment_record_service = SampleAssignmentRecordService(
                database,
                assignment_record_client,
                activation_at=settings.feishu_sample_auto_assignment_activation_at,
                limit=settings.feishu_sample_auto_assignment_batch_limit,
                change_notifier=assignment_change_notifier,
            )
            profile_enrichment_service = SampleNotificationProfileEnrichmentService(
                database,
                limit=settings.feishu_sample_auto_assignment_batch_limit,
            )
            if refundable_assignment_client is not None:
                from erp_api.services.sample_assignment_type_router import SampleAssignmentTypeRouter

                assignment_record_service = SampleAssignmentTypeRouter(
                    assignment_record_service,
                    SampleAssignmentRecordService(
                        database, refundable_assignment_client, sample_type="refundable",
                        activation_at=settings.feishu_sample_auto_assignment_activation_at,
                        limit=settings.feishu_sample_auto_assignment_batch_limit,
                        change_notifier=assignment_change_notifier,
                    ),
                )
        if (
            feishu_client is not None
            and settings.feishu_event_verification_token
            and settings.feishu_event_encrypt_key
        ):
            feishu_event_processor = FeishuSampleEventProcessor(
                application_repository,
                feishu_client,
                base_token=settings.feishu_sample_base_token.get_secret_value(),
                table_id=settings.feishu_sample_table_id,
            )
        if (
            settings.feishu_sample_reverse_poll_enabled
            and feishu_client_router is not None
        ):
            feishu_reverse_poll_service = SampleFeishuReversePollService(
                application_repository,
                feishu_mapping_repository,
                feishu_client_router.all_clients(),
                recipient_provider=roster_provider,
            )
        if settings.feishu_sample_notification_enabled and feishu_client is not None:
            notification_client = FeishuNotificationClient(feishu_client)
            notification_avatar_service = (
                SampleNotificationAvatarService(
                    avatar_storage.object_storage,
                    notification_client,
                )
                if avatar_storage is not None
                else None
            )
            notification_product_image_service = product_image_service or (
                SampleNotificationProductImageService(notification_client)
            )
            notification_service = SampleNotificationService(
                notification_repository,
                notification_client,
                feishu_client_router,
                record_url_template=settings.feishu_sample_record_url_template,
                record_url_templates_by_shop=build_shop_record_url_templates(
                    settings.feishu_sample_record_url_template,
                    settings.feishu_sample_shop_table_ids,
                ),
                test_recipient_open_id=(
                    settings.feishu_sample_notification_test_recipient_open_id.get_secret_value()
                    if settings.feishu_sample_notification_test_recipient_open_id
                    else None
                ),
                live_recipients_enabled=(
                    settings.feishu_sample_notification_live_recipients_enabled
                ),
                group_chat_id=settings.feishu_sample_notification_group_chat_id,
                max_attempts=settings.feishu_sample_notification_max_attempts,
                retry_base_seconds=(
                    settings.feishu_sample_notification_retry_base_seconds
                ),
                processing_timeout=timedelta(
                    minutes=(
                        settings.feishu_sample_notification_processing_timeout_minutes
                    )
                ),
                avatar_service=notification_avatar_service,
                product_image_service=notification_product_image_service,
            )
    if service is not None and feishu_sync_service is not None:
        shop_pipeline_service = SampleShopPipelineService(
            service,
            feishu_sync_service,
            notification_service,
            auto_assignment_service,
            auto_assignment_projection,
            assignment_record_service,
            profile_enrichment_service,
            cooperation_precheck=cooperation_precheck_service,
            group_cleanup=group_cleanup,
            group_assignment_migration=SampleGroupAssignmentMigrationService(database),
            work_gate=SamplePostSourceWorkGate(
                database,
                activation_at=settings.feishu_sample_auto_assignment_activation_at,
                cooperation_precheck=cooperation_precheck_service,
                auto_assignments=auto_assignment_service,
                notifications=notification_service,
            ),
            business_readiness=SampleBusinessReadiness(),
        )
    return {
        "sample_application_repository": application_repository,
        "sample_feishu_mapping_repository": feishu_mapping_repository,
        "sample_feishu_source_repository": feishu_source_repository,
        "sample_sync_audit_repository": audit_repository,
        "sample_application_sync_service": service,
        "sample_source_policy": source_policy,
        "sample_source_recovery_service": recovery_service,
        "feishu_sample_client": feishu_client,
        "feishu_sample_client_router": feishu_client_router,
        "sample_feishu_sync_service": feishu_sync_service,
        "feishu_sample_event_processor": feishu_event_processor,
        "feishu_sample_reverse_poll_service": feishu_reverse_poll_service,
        "sample_notification_repository": notification_repository,
        "sample_notification_service": notification_service,
        "sample_auto_assignment_service": auto_assignment_service,
        "sample_auto_assignment_projection": auto_assignment_projection,
        "sample_assignment_record_service": assignment_record_service,
        "sample_notification_profile_enrichment_service": (profile_enrichment_service),
        "sample_cooperation_precheck_service": cooperation_precheck_service,
        "sample_bd_invitation_protection_service": (bd_invitation_protection_service),
        "sample_ai_invitation_mirror_service": ai_invitation_mirror_service,
        "sample_shop_pipeline_service": shop_pipeline_service,
    }


def build_platform_fulfillment_services(
    settings: Settings,
    database: Database,
    *,
    tiktok_client: HttpTikTokClient | None = None,
) -> dict[str, object]:
    tracking_cipher = (
        TokenCipher(settings.order_pii_encryption_key.get_secret_value())
        if settings.order_pii_encryption_key
        else None
    )
    repository = PlatformFulfillmentOutboxRepository(database, tracking_cipher)
    shop_repository = _create_shop_repository(settings, database)
    if tiktok_client is None:
        app_registry = _create_tiktok_app_registry(settings, shop_repository)
        tiktok_client = _create_tiktok_client(settings, app_registry)
    adapters = []
    if tiktok_client is not None and shop_repository is not None:
        adapters.append(
            TikTokFulfillmentAdapter(
                shop_repository,
                tiktok_client,
                HttpTikTokFulfillmentClient(
                    tiktok_client.api_transport,
                    ship_path_template=settings.tiktok_fulfillment_ship_path_template,
                ),
            )
        )
    service = PlatformFulfillmentService(
        repository,
        PlatformFulfillmentAdapterRegistry(adapters),
        max_tries=settings.platform_fulfillment_job_max_tries,
        retry_base_seconds=settings.platform_fulfillment_retry_base_seconds,
        processing_timeout=timedelta(
            minutes=settings.platform_fulfillment_processing_timeout_minutes
        ),
    )
    return {
        "platform_fulfillment_outbox_repository": repository,
        "platform_fulfillment_service": service,
    }


def build_logistics_tracking_services(
    settings: Settings,
    database: Database,
    *,
    tiktok_client: HttpTikTokClient | None = None,
) -> dict[str, object]:
    tracking_cipher = (
        TokenCipher(settings.order_pii_encryption_key.get_secret_value())
        if settings.order_pii_encryption_key
        else None
    )
    repository = LogisticsTrackingRepository(database, tracking_cipher)
    exception_repository = LogisticsExceptionRepository(database)
    exception_service = LogisticsExceptionService(
        exception_repository,
        pickup_timeout=timedelta(
            hours=settings.logistics_exception_pickup_timeout_hours
        ),
        stalled_timeout=timedelta(
            hours=settings.logistics_exception_stalled_timeout_hours
        ),
        platform_grace=timedelta(
            hours=settings.logistics_exception_platform_grace_hours
        ),
    )
    service = LogisticsTrackingService(
        repository,
        CarrierTrackingAdapterRegistry(),
        webhook_secrets={
            key: value.get_secret_value()
            for key, value in settings.logistics_webhook_signing_secrets.items()
        },
        poll_interval=timedelta(
            minutes=settings.logistics_tracking_poll_interval_minutes
        ),
        poll_retry_interval=timedelta(
            minutes=settings.logistics_tracking_poll_retry_minutes
        ),
        exception_service=exception_service,
    )
    shop_repository = _create_shop_repository(settings, database)
    if tiktok_client is None:
        app_registry = _create_tiktok_app_registry(settings, shop_repository)
        tiktok_client = _create_tiktok_client(settings, app_registry)
    platform_sync_service = (
        PlatformLogisticsSyncService(
            PlatformLogisticsSyncRepository(database, tracking_cipher),
            shop_repository,
            HttpTikTokLogisticsClient(tiktok_client.api_transport),
            repository,
            exception_service,
        )
        if tracking_cipher is not None
        and shop_repository is not None
        and tiktok_client is not None
        else None
    )
    return {
        "logistics_tracking_repository": repository,
        "logistics_tracking_service": service,
        "logistics_exception_repository": exception_repository,
        "logistics_exception_service": exception_service,
        "platform_logistics_sync_service": platform_sync_service,
        "logistics_order_status_service": (
            LogisticsOrderStatusService(
                LogisticsOrderStatusRepository(database),
                shop_repository,
                HttpTikTokLogisticsClient(tiktok_client.api_transport),
                HttpTikTokOrderClient(tiktok_client.api_transport),
            )
            if shop_repository is not None and tiktok_client is not None
            else None
        ),
    }


def build_finance_services(
    settings: Settings,
    database: Database,
    *,
    tiktok_client: HttpTikTokClient | None = None,
) -> dict[str, object | None]:
    repository = FinanceSyncRepository(database)
    read_repository = FinanceRepository(
        database, export_max_rows=settings.finance_export_max_rows
    )
    shop_repository = _create_shop_repository(settings, database)
    if tiktok_client is None:
        app_registry = _create_tiktok_app_registry(settings, shop_repository)
        tiktok_client = _create_tiktok_client(settings, app_registry)
    finance_client = _create_tiktok_finance_client(settings, tiktok_client)
    service = (
        FinanceSyncService(
            repository,
            shop_repository,
            finance_client,
            initial_sync_days=settings.tiktok_finance_initial_sync_days,
            incremental_overlap_hours=(
                settings.tiktok_finance_incremental_overlap_hours
            ),
            order_detail_concurrency=settings.tiktok_finance_order_detail_concurrency,
        )
        if shop_repository is not None and finance_client is not None
        else None
    )
    return {
        "finance_repository": read_repository,
        "finance_sync_repository": repository,
        "finance_sync_service": service,
    }


def build_analytics_services(
    settings: Settings,
    database: Database,
    *,
    tiktok_client: HttpTikTokClient | None = None,
    tiktok_app_registry: TikTokAppRegistry | None = None,
    redis_client=None,
) -> dict[str, object | None]:
    analytics_repository = AnalyticsRepository(database)
    read_repository = AnalyticsReadRepository(database)
    affiliate_live_account_repository = AffiliateLiveAccountRepository(database)
    video_performance_repository = VideoPerformanceRepository(database)
    quality_repository = AnalyticsQualityRepository(database)
    sync_repository = AnalyticsSyncRepository(
        database,
        raw_payload_ttl_days=settings.tiktok_analytics_raw_payload_ttl_days,
    )
    bestseller_repository = BestsellerRepository(
        database,
        raw_payload_ttl_days=settings.tiktok_analytics_raw_payload_ttl_days,
    )
    bestseller_read_repository = BestsellerReadRepository(database)
    shop_repository = _create_shop_repository(settings, database)
    tiktok_app_registry = tiktok_app_registry or _create_tiktok_app_registry(
        settings, shop_repository
    )
    tiktok_client = tiktok_client or _create_tiktok_client(
        settings, tiktok_app_registry
    )
    bestseller_client = _create_tiktok_bestseller_client(tiktok_client)
    client = _create_tiktok_analytics_client(settings, tiktok_app_registry)
    overview_client = _create_tiktok_overview_client(settings, tiktok_app_registry)
    service = None
    affiliate_source_resolver = (
        AffiliateSourceResolver(shop_repository)
        if shop_repository is not None
        else None
    )
    official_affiliate_sync_service = None
    bestseller_sync_service = (
        BestsellerSyncService(
            bestseller_repository,
            shop_repository,
            bestseller_client,
        )
        if shop_repository is not None and bestseller_client is not None
        else None
    )
    if (
        client is not None
        and overview_client is not None
        and tiktok_client is not None
        and shop_repository is not None
    ):
        if (
            settings.tiktok_video_analytics_external_id_field
            not in settings.tiktok_video_analytics_field_map
            or settings.tiktok_live_analytics_external_id_field
            not in settings.tiktok_live_analytics_field_map
        ):
            raise ValueError(
                "Analytics external ID fields must be present in their configured field maps."
            )
        service = AnalyticsSyncService(
            sync_repository,
            analytics_repository,
            video_performance_repository,
            quality_repository,
            shop_repository,
            client,
            overview_client,
            video_external_id_field=settings.tiktok_video_analytics_external_id_field,
            live_external_id_field=settings.tiktok_live_analytics_external_id_field,
            video_amount_currency_pairs=settings.tiktok_video_analytics_amount_currency_pairs,
            live_amount_currency_pairs=settings.tiktok_live_analytics_amount_currency_pairs,
            initial_sync_days=settings.tiktok_analytics_initial_sync_days,
            schedule_mode=settings.tiktok_analytics_schedule,
        )
        official_affiliate_sync_service = OfficialAffiliateSyncService(
            sync_repository,
            shop_repository,
            affiliate_source_resolver,
            client,
            HttpTikTokCompassClient(
                tiktok_client.api_transport,
                reuse_existing=True,
            ),
            AffiliateCreatorPersistence(database),
            AffiliateVideoPersistence(
                analytics_repository,
                video_performance_repository,
                cover_storage=configured_video_cover_writer(),
            ),
            AffiliateOfficialAvailabilityRepository(redis_client)
            if redis_client is not None
            else None,
            CompassExportRateGate(redis_client) if redis_client is not None else None,
        )
    return {
        "analytics_repository": analytics_repository,
        "analytics_read_repository": read_repository,
        "affiliate_live_account_repository": affiliate_live_account_repository,
        "video_performance_repository": video_performance_repository,
        "analytics_quality_repository": quality_repository,
        "analytics_sync_repository": sync_repository,
        "bestseller_repository": bestseller_repository,
        "bestseller_read_repository": bestseller_read_repository,
        "bestseller_sync_service": bestseller_sync_service,
        "analytics_sync_service": service,
        "affiliate_source_resolver": affiliate_source_resolver,
        "official_affiliate_sync_service": official_affiliate_sync_service,
    }


def _get_request_id(request: Request) -> str:
    candidate = request.headers.get(REQUEST_ID_HEADER, "")
    if (
        1 <= len(candidate) <= 128
        and candidate.replace("-", "").replace("_", "").isalnum()
    ):
        return candidate
    return str(uuid.uuid4())


def create_app() -> FastAPI:
    settings = get_settings()
    if "*" in settings.cors_origin_list and settings.cors_allow_credentials:
        raise ValueError(
            "CORS_ORIGINS cannot contain '*' when credentials are enabled."
        )

    configure_logging(settings.log_level)
    database = Database(settings.database_url)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=create_lifespan(settings, database, redis),
    )
    app.state.database = database
    app.state.settings = settings
    app.state.redis = redis
    app.state.auth_service = AuthService(
        redis,
        captcha_hmac_secret=settings.auth_captcha_hmac_secret or str(uuid.uuid4()),
        captcha_ttl_seconds=settings.auth_captcha_ttl_seconds,
        access_token_ttl_seconds=settings.auth_access_token_ttl_seconds,
        login_max_attempts=settings.auth_login_max_attempts,
        login_rate_limit_seconds=settings.auth_login_rate_limit_seconds,
    )
    app.state.auth_repository = AuthRepository(database)
    app.state.shop_repository = _create_shop_repository(settings, database)
    app.state.tiktok_app_registry = _create_tiktok_app_registry(
        settings, app.state.shop_repository
    )
    app.state.tiktok_authorization_service = _create_tiktok_authorization_service(
        settings, redis, app.state.tiktok_app_registry
    )
    app.state.tiktok_client = _create_tiktok_client(
        settings, app.state.tiktok_app_registry
    )
    app.state.tiktok_bestseller_client = _create_tiktok_bestseller_client(
        app.state.tiktok_client
    )
    app.state.tiktok_analytics_client = _create_tiktok_analytics_client(
        settings, app.state.tiktok_app_registry
    )
    app.state.tiktok_reauthorization_repository = (
        _create_tiktok_reauthorization_repository(settings, database)
    )
    app.state.creator_connection_repository = _create_creator_connection_repository(
        settings, database
    )
    product_services = build_product_services(
        settings, database, client=app.state.tiktok_client
    )
    app.state.product_repository = product_services["product_repository"]
    app.state.dashboard_repository = DashboardRepository(database)
    app.state.affiliate_repository = AffiliateRepository(database)
    app.state.affiliate_creator_repository = AffiliateCreatorRepository(database)
    app.state.affiliate_center_read_repository = AffiliateCenterReadRepository(database)
    app.state.affiliate_creator_detail_read_repository = (
        AffiliateCreatorDetailReadRepository(database)
    )
    app.state.affiliate_capture_intent_repository = AffiliateCaptureIntentRepository(
        database
    )
    app.state.logistics_repository = LogisticsRepository(database)
    app.state.logistics_task_generation_repository = LogisticsTaskGenerationRepository(
        database
    )
    app.state.returns_repository = ReturnsRepository(database)
    app.state.returns_sync_service = (
        ReturnsSyncService(
            app.state.shop_repository,
            HttpTikTokReturnClient(app.state.tiktok_client.api_transport),
            ReturnsSyncRepository(database),
        )
        if app.state.tiktok_client is not None
        else None
    )
    app.state.logistics_carrier_repository = LogisticsCarrierRepository(database)
    app.state.logistics_package_repository = LogisticsPackageRepository(database)
    app.state.logistics_document_service = build_logistics_document_service(
        settings, database
    )
    app.state.logistics_dispatch_repository = LogisticsDispatchRepository(database)
    tracking_cipher = (
        TokenCipher(settings.order_pii_encryption_key.get_secret_value())
        if settings.order_pii_encryption_key
        else None
    )
    app.state.logistics_shipping_service = LogisticsShippingService(
        LogisticsShippingRepository(database, tracking_cipher)
    )
    app.state.scraped_data_repository = ScrapedDataRepository(database)
    app.state.sync_health_repository = SyncHealthRepository(
        database,
        window_hours=settings.sync_health_window_hours,
        expected_interval_minutes=settings.sync_health_expected_interval_minutes,
    )
    app.state.product_sync_service = product_services["product_sync_service"]
    for name, service in build_order_services(
        settings, database, tiktok_client=app.state.tiktok_client
    ).items():
        setattr(app.state, name, service)
    for name, service in build_platform_fulfillment_services(
        settings,
        database,
        tiktok_client=app.state.tiktok_client,
    ).items():
        setattr(app.state, name, service)
    for name, service in build_logistics_tracking_services(
        settings, database, tiktok_client=app.state.tiktok_client
    ).items():
        setattr(app.state, name, service)
    for name, service in build_finance_services(
        settings,
        database,
        tiktok_client=app.state.tiktok_client,
    ).items():
        setattr(app.state, name, service)
    for name, service in build_analytics_services(
        settings,
        database,
        tiktok_client=app.state.tiktok_client,
        tiktok_app_registry=app.state.tiktok_app_registry,
        redis_client=redis,
    ).items():
        setattr(app.state, name, service)
    app.state.webhook_service = (
        WebhookService(
            database,
            settings.tiktok_webhook_signing_secret,
            TokenCipher(settings.order_pii_encryption_key.get_secret_value()),
        )
        if settings.tiktok_webhook_signing_secret and settings.order_pii_encryption_key
        else None
    )
    app.state.feishu_sample_event_receiver = (
        FeishuSampleEventReceiver(
            verification_token=settings.feishu_event_verification_token.get_secret_value(),
            encrypt_key=settings.feishu_event_encrypt_key.get_secret_value(),
            app_id=settings.feishu_app_id,
        )
        if (
            settings.feishu_event_verification_token
            and settings.feishu_event_encrypt_key
            and settings.feishu_app_id
        )
        else None
    )
    app.state.feishu_sample_event_processor = None
    if (
        app.state.feishu_sample_event_receiver is not None
        and settings.feishu_app_secret
        and settings.feishu_sample_base_token
    ):
        base_token = settings.feishu_sample_base_token.get_secret_value()
        table_ids = set(settings.feishu_sample_shop_table_ids.values())
        if settings.feishu_sample_table_id:
            table_ids.add(settings.feishu_sample_table_id)
        processors = {
            table_id: FeishuSampleEventProcessor(
                SampleApplicationRepository(database),
                FeishuSampleBatchClient(
                    app_id=settings.feishu_app_id,
                    app_secret=settings.feishu_app_secret.get_secret_value(),
                    base_token=base_token,
                    table_id=table_id,
                ),
                base_token=base_token,
                table_id=table_id,
            )
            for table_id in table_ids
        }

        async def notify_assignment_change():
            await redis.incr(ASSIGNMENT_SUMMARY_REVISION_KEY)

        app.state.feishu_sample_event_processor = FeishuBusinessEventProcessor(
            base_token=base_token,
            sample_processors=processors,
            assignment_table_id=settings.feishu_bd_assignment_record_table_id,
            assignment_notifier=notify_assignment_change,
        )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-API-Contract-Version",
            REQUEST_ID_HEADER,
        ],
        expose_headers=[REQUEST_ID_HEADER, "Content-Disposition"],
    )

    @app.middleware("http")
    async def add_request_id_and_log(request: Request, call_next):
        request_id = _get_request_id(request)
        request.state.request_id = request_id
        context_token = request_id_context.set(request_id)
        started_at = time.perf_counter()
        try:
            response = await call_next(request)
            response.headers[REQUEST_ID_HEADER] = request_id
            logger.info(
                "request_completed",
                extra={
                    "event": "request_completed",
                    "method": request.method,
                    "path": request.url.path,
                    "request_id": request_id,
                    "status_code": response.status_code,
                    "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
                },
            )
            return response
        finally:
            request_id_context.reset(context_token)

    register_exception_handlers(app)
    app.include_router(auth.router, prefix="/api")
    app.include_router(dashboard.router, prefix="/api")
    app.include_router(products.router, prefix="/api")
    app.include_router(orders.router, prefix="/api")
    app.include_router(shops.router, prefix="/api")
    app.include_router(data.router, prefix="/api")
    app.include_router(bestsellers.router, prefix="/api")
    app.include_router(sync_health.router, prefix="/api")
    app.include_router(affiliate.router, prefix="/api")
    app.include_router(affiliate_center.router, prefix="/api")
    app.include_router(affiliate_local_export.router, prefix="/api")
    app.include_router(affiliate_service_export.router, prefix="/api")
    app.include_router(remote_affiliate_export.router, prefix="/api")
    app.include_router(remote_sample_capture.router, prefix="/api")
    app.include_router(affiliate_center_stable.router, prefix="/api")
    app.include_router(affiliate_creator_detail.router, prefix="/api")
    app.include_router(affiliate_live_accounts.router, prefix="/api")
    app.include_router(finance.router, prefix="/api")
    app.include_router(feishu_sample_events.router, prefix=settings.api_prefix)
    app.include_router(logistics.router, prefix="/api")
    app.include_router(returns.router, prefix="/api")
    app.include_router(sample_applications.router, prefix="/api")
    app.include_router(health.api_router)
    app.include_router(health.router)
    app.include_router(tiktok.router, prefix=settings.api_prefix)
    app.include_router(tiktok_callback.router, prefix=settings.api_prefix)
    app.include_router(tiktok_creators.router, prefix=settings.api_prefix)
    app.include_router(tiktok_reauthorization.router, prefix=settings.api_prefix)
    app.include_router(tiktok.webhook_router, prefix=settings.api_prefix)
    app.include_router(logistics_tracking.webhook_router, prefix=settings.api_prefix)
    return app


app = create_app()
