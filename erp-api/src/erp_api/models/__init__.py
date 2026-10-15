"""Core persistence models registered for Alembic metadata discovery."""

from erp_api.models.affiliate_creator import (
    AffiliateCreator,
    AffiliateCreatorMetric,
    AffiliateCreatorReport,
)
from erp_api.models.affiliate_creator_detail import (
    AffiliateCreatorDetailItem,
    AffiliateCreatorDetailReport,
)
from erp_api.models.affiliate_order_item import AffiliateOrderItem
from erp_api.models.affiliate_sync_state import AffiliateSyncState
from erp_api.models.analytics_quality_alert import AnalyticsQualityAlert
from erp_api.models.analytics_snapshot import (
    AnalyticsSnapshot,
    TikTokLiveSession,
    TikTokVideoContent,
)
from erp_api.models.analytics_sync import (
    AnalyticsRawPayload,
    AnalyticsSyncCursor,
    AnalyticsSyncRun,
)
from erp_api.models.bestseller_snapshot import BestsellerEntry, BestsellerSnapshot
from erp_api.models.creator_connection import CreatorConnection
from erp_api.models.creator_sync_state import CreatorSyncState
from erp_api.models.finance_payment import FinancePayment, FinancePaymentStatement
from erp_api.models.finance_statement import FinanceStatement
from erp_api.models.finance_sync import FinanceSyncCursor, FinanceSyncRun
from erp_api.models.finance_transaction import FinanceTransaction
from erp_api.models.finance_transaction_component import (
    FinanceTransactionComponent,
)
from erp_api.models.logistics_carrier import (
    LogisticsCarrier,
    LogisticsCarrierAccount,
    LogisticsCarrierService,
)
from erp_api.models.logistics_document import LogisticsDocument
from erp_api.models.logistics_exception import (
    LogisticsException,
    LogisticsExceptionAction,
)
from erp_api.models.logistics_package import LogisticsPackage, LogisticsPackageItem
from erp_api.models.logistics_platform_carrier_mapping import (
    LogisticsPlatformCarrierMapping,
)
from erp_api.models.logistics_task import LogisticsTask
from erp_api.models.logistics_task_item import LogisticsTaskItem
from erp_api.models.logistics_task_operation import LogisticsTaskOperation
from erp_api.models.logistics_task_review import LogisticsTaskReview
from erp_api.models.logistics_tracking_event import LogisticsTrackingEvent
from erp_api.models.logistics_waybill import LogisticsWaybill
from erp_api.models.order import Order
from erp_api.models.order_attribution import OrderAttribution
from erp_api.models.order_conversion_link import OrderConversionLink
from erp_api.models.order_fulfillment import OrderFulfillment
from erp_api.models.order_line import OrderLine
from erp_api.models.order_recipient import OrderRecipient
from erp_api.models.order_sync import OrderSyncCursor, OrderSyncRun
from erp_api.models.permission import Permission
from erp_api.models.pii_access_audit import PiiAccessAudit
from erp_api.models.platform_fulfillment_outbox import PlatformFulfillmentOutbox
from erp_api.models.product import Product
from erp_api.models.product_sku import ProductSku
from erp_api.models.product_sync_run import ProductSyncRun
from erp_api.models.return_request import ReturnRequest, ReturnRequestItem
from erp_api.models.return_rma import ReturnRma
from erp_api.models.role import Role
from erp_api.models.sample_application import SampleApplication
from erp_api.models.sample_application_event import SampleApplicationEvent
from erp_api.models.sample_application_workflow import SampleApplicationWorkflow
from erp_api.models.sample_ingest_batch import SampleIngestBatch
from erp_api.models.sample_notification_outbox import SampleNotificationOutbox
from erp_api.models.sample_sync_run import SampleSyncRun
from erp_api.models.scraped_data import ScrapedData
from erp_api.models.shop import Shop
from erp_api.models.shop_connection import ShopConnection
from erp_api.models.tenant import Tenant
from erp_api.models.tiktok_webhook_event import TikTokWebhookEvent
from erp_api.models.user import User
from erp_api.models.video_performance_snapshot import (
    TikTokVideoPerformanceSnapshot,
)

__all__ = [
    "AffiliateCreator",
    "AffiliateCreatorDetailItem",
    "AffiliateCreatorDetailReport",
    "AffiliateCreatorMetric",
    "AffiliateCreatorReport",
    "AffiliateOrderItem",
    "AffiliateSyncState",
    "AnalyticsQualityAlert",
    "AnalyticsRawPayload",
    "AnalyticsSnapshot",
    "AnalyticsSyncCursor",
    "AnalyticsSyncRun",
    "BestsellerEntry",
    "BestsellerSnapshot",
    "CreatorConnection",
    "CreatorSyncState",
    "FinancePayment",
    "FinancePaymentStatement",
    "FinanceStatement",
    "FinanceSyncCursor",
    "FinanceSyncRun",
    "FinanceTransaction",
    "FinanceTransactionComponent",
    "LogisticsCarrier",
    "LogisticsCarrierAccount",
    "LogisticsCarrierService",
    "LogisticsDocument",
    "LogisticsException",
    "LogisticsExceptionAction",
    "LogisticsPackage",
    "LogisticsPackageItem",
    "LogisticsPlatformCarrierMapping",
    "LogisticsTask",
    "LogisticsTaskItem",
    "LogisticsTaskOperation",
    "LogisticsTaskReview",
    "LogisticsTrackingEvent",
    "LogisticsWaybill",
    "Order",
    "OrderAttribution",
    "OrderConversionLink",
    "OrderFulfillment",
    "OrderLine",
    "OrderRecipient",
    "OrderSyncCursor",
    "OrderSyncRun",
    "Permission",
    "PiiAccessAudit",
    "PlatformFulfillmentOutbox",
    "Product",
    "ProductSku",
    "ProductSyncRun",
    "ReturnRequest",
    "ReturnRequestItem",
    "ReturnRma",
    "Role",
    "SampleApplication",
    "SampleApplicationEvent",
    "SampleApplicationWorkflow",
    "SampleIngestBatch",
    "SampleNotificationOutbox",
    "SampleSyncRun",
    "ScrapedData",
    "Shop",
    "ShopConnection",
    "Tenant",
    "TikTokLiveSession",
    "TikTokVideoContent",
    "TikTokVideoPerformanceSnapshot",
    "TikTokWebhookEvent",
    "User",
]
