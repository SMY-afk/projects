import os
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ERP API"
    app_env: Literal["development", "test", "production"] = "development"
    api_prefix: str = "/api/v1"
    api_host: str = "127.0.0.1"
    api_port: int = 8080
    api_reload: bool = False
    cors_origins: str = "http://localhost:5173"
    cors_allow_credentials: bool = True
    log_level: str = "INFO"
    database_url: str
    redis_url: str
    auth_captcha_hmac_secret: str | None = None
    auth_captcha_ttl_seconds: int = 120
    auth_access_token_ttl_seconds: int = 7200
    auth_login_max_attempts: int = 5
    auth_login_rate_limit_seconds: int = 60
    tiktok_app_key: str | None = None
    tiktok_service_id: str | None = None
    tiktok_app_secret: SecretStr | None = None
    tiktok_301_app_key: str | None = None
    tiktok_301_service_id: str | None = None
    tiktok_301_app_secret: SecretStr | None = None
    tiktok_301_authorization_url: str = (
        "https://services.us.tiktokshop.com/open/authorize"
    )
    tiktok_authorization_url: str | None = None
    tiktok_creator_authorization_url: str | None = None
    tiktok_token_url: str | None = None
    tiktok_shop_identity_url: str | None = None
    tiktok_finance_statements_path: str = "/finance/202309/statements"
    tiktok_finance_payments_path: str = "/finance/202605/payments"
    tiktok_finance_statement_transactions_path: str = (
        "/finance/202501/statements/{statement_id}/statement_transactions"
    )
    tiktok_finance_order_transactions_path: str = (
        "/finance/202501/orders/{order_id}/statement_transactions"
    )
    tiktok_finance_unsettled_transactions_path: str = "/finance/202507/orders/unsettled"
    tiktok_finance_max_window_days: int = Field(default=30, ge=1, le=30)
    tiktok_finance_raw_payload_ttl_days: int = Field(default=30, ge=1)
    tiktok_finance_initial_sync_days: int = Field(default=30, ge=1, le=30)
    tiktok_finance_incremental_overlap_hours: int = Field(default=24, ge=0, le=168)
    tiktok_finance_order_detail_concurrency: int = Field(default=4, ge=1, le=10)
    tiktok_finance_sync_interval_minutes: Literal[10, 15, 20, 30] = 15
    tiktok_finance_job_max_tries: int = Field(default=5, ge=1, le=10)
    tiktok_fulfillment_ship_path_template: str = (
        "/fulfillment/202309/packages/{package_id}/ship"
    )
    platform_fulfillment_job_max_tries: int = Field(default=5, ge=1, le=10)
    platform_fulfillment_retry_base_seconds: int = Field(default=30, ge=1, le=600)
    platform_fulfillment_processing_timeout_minutes: int = Field(
        default=10, ge=1, le=120
    )
    logistics_webhook_signing_secrets: dict[str, SecretStr] = Field(
        default_factory=dict
    )
    logistics_tracking_poll_interval_minutes: int = Field(default=30, ge=5, le=1440)
    logistics_tracking_poll_retry_minutes: int = Field(default=10, ge=1, le=120)
    tiktok_logistics_sync_job_timeout_seconds: int = Field(default=900, ge=301, le=3600)
    logistics_exception_pickup_timeout_hours: int = Field(default=24, ge=1, le=168)
    logistics_exception_stalled_timeout_hours: int = Field(default=72, ge=1, le=720)
    logistics_exception_platform_grace_hours: int = Field(default=2, ge=1, le=72)
    finance_export_max_rows: int = Field(default=100_000, ge=1, le=1_000_000)
    tiktok_affiliate_order_url: str | None = None
    tiktok_ads_order_url: str | None = None
    tiktok_video_analytics_url: str | None = None
    tiktok_video_analytics_overview_url: str | None = None
    tiktok_video_analytics_items_path: str = "videos"
    tiktok_video_analytics_next_page_token_path: str | None = "next_page_token"
    tiktok_video_analytics_field_map: dict[str, str] = Field(default_factory=dict)
    tiktok_video_analytics_external_id_field: str = "videoId"
    tiktok_video_analytics_amount_currency_pairs: dict[str, str] = Field(
        default_factory=dict
    )
    tiktok_video_analytics_required_fields: list[str] = Field(default_factory=list)
    tiktok_video_analytics_source_updated_at_path: str | None = None
    tiktok_video_analytics_item_source_updated_at_path: str | None = None
    tiktok_video_analytics_status_path: str | None = None
    tiktok_video_analytics_status_map: dict[str, str] = Field(default_factory=dict)
    tiktok_video_analytics_max_window_days: int = 30
    tiktok_live_analytics_url: str | None = None
    tiktok_live_analytics_overview_url: str | None = None
    tiktok_live_analytics_items_path: str = "live_stream_sessions"
    tiktok_live_analytics_next_page_token_path: str | None = "next_page_token"
    tiktok_live_analytics_field_map: dict[str, str] = Field(default_factory=dict)
    tiktok_live_analytics_external_id_field: str = "liveId"
    tiktok_live_analytics_amount_currency_pairs: dict[str, str] = Field(
        default_factory=dict
    )
    tiktok_live_analytics_required_fields: list[str] = Field(default_factory=list)
    tiktok_live_analytics_source_updated_at_path: str | None = None
    tiktok_live_analytics_item_source_updated_at_path: str | None = None
    tiktok_live_analytics_status_path: str | None = None
    tiktok_live_analytics_status_map: dict[str, str] = Field(default_factory=dict)
    tiktok_live_analytics_max_window_days: int = 30
    tiktok_analytics_raw_payload_ttl_days: int = Field(default=30, ge=1)
    affiliate_center_raw_payload_ttl_days: Literal[7] = 7
    tiktok_affiliate_creator_schedule_max_attempts: int = Field(default=3, ge=1, le=10)
    tiktok_affiliate_creator_retry_minutes: Literal[5, 10, 15, 20, 30] = 10
    tiktok_affiliate_video_schedule_max_attempts: int = Field(default=3, ge=1, le=10)
    tiktok_affiliate_video_retry_minutes: Literal[5, 10, 15, 20, 30] = 10
    tiktok_analytics_initial_sync_days: int = Field(default=30, ge=1, le=30)
    tiktok_analytics_sync_hour_utc: int = Field(default=4, ge=0, le=23)
    tiktok_analytics_schedule: Literal["hourly", "daily"] = "daily"
    tiktok_analytics_sync_minute_utc: int = Field(default=0, ge=0, le=59)
    tiktok_bestseller_sync_hour_utc: int = Field(default=5, ge=0, le=23)
    tiktok_bestseller_sync_minute_utc: int = Field(default=0, ge=0, le=59)
    tiktok_analytics_job_max_tries: int = Field(default=5, ge=1, le=10)
    sync_health_window_hours: int = Field(default=168, ge=1, le=2160)
    sync_health_expected_interval_minutes: int = Field(default=1440, ge=1)
    tiktok_product_sync_minute_utc: int = Field(default=15, ge=0, le=59)
    tiktok_sample_reconciliation_hour_utc: int = Field(default=19, ge=0, le=23)
    tiktok_sample_reconciliation_minute_utc: int = Field(default=10, ge=0, le=59)
    tiktok_sample_sync_job_max_tries: int = Field(default=5, ge=2, le=20)
    tiktok_sample_shop_lock_retry_seconds: int = Field(default=30, ge=5, le=300)
    tiktok_sample_fast_job_timeout_seconds: int = Field(default=900, ge=60, le=3600)
    tiktok_sample_full_job_timeout_seconds: int = Field(default=3600, ge=300, le=7200)
    tiktok_sample_shutdown_grace_seconds: int = Field(default=120, ge=10, le=600)
    tiktok_ads_access_token: SecretStr | None = None
    feishu_app_id: str | None = None
    feishu_app_secret: SecretStr | None = None
    feishu_new_app_id: str | None = None
    feishu_new_app_secret: SecretStr | None = None
    feishu_sample_base_token: SecretStr | None = None
    feishu_sample_table_id: str | None = None
    feishu_sample_shop_table_ids: dict[UUID, str] = Field(default_factory=dict)
    feishu_event_verification_token: SecretStr | None = None
    feishu_event_encrypt_key: SecretStr | None = None
    feishu_sample_reverse_poll_enabled: bool = False
    feishu_sample_reverse_poll_interval_minutes: int = Field(default=60, ge=5, le=60)
    feishu_sample_notification_enabled: bool = False
    feishu_sample_record_url_template: str | None = None
    feishu_sample_notification_test_recipient_open_id: SecretStr | None = None
    feishu_sample_notification_live_recipients_enabled: bool = False
    feishu_sample_notification_group_chat_id: str | None = None
    feishu_sample_notification_max_attempts: int = Field(default=2, ge=1, le=2)
    feishu_sample_notification_retry_base_seconds: int = Field(default=30, ge=1)
    feishu_sample_notification_processing_timeout_minutes: int = Field(default=10, ge=1)
    feishu_sample_auto_assignment_enabled: bool = False
    feishu_sample_auto_assignment_activation_at: datetime | None = None
    feishu_bd_roster_table_id: str | None = None
    feishu_bd_assignment_record_table_id: str | None = None
    feishu_refundable_assignment_record_table_id: str | None = None
    feishu_refundable_sample_enabled: bool = False
    feishu_refundable_assignment_summary_table_id: str | None = None
    feishu_bd_invitation_protection_table_id: str | None = None
    feishu_ai_invitation_base_token: SecretStr | None = None
    feishu_ai_invitation_table_id: str | None = None
    feishu_ai_invitation_sheet_token: str | None = None
    feishu_ai_invitation_sheet_id: str | None = None
    feishu_ai_invitation_mirror_table_id: str | None = None
    feishu_coop_stroller_base_token: str | None = None
    feishu_coop_stroller_table_id: str | None = None
    feishu_coop_stroller_view_id: str | None = None
    feishu_coop_rc_base_token: str | None = None
    feishu_coop_rc_table_id: str | None = None
    feishu_coop_rc_view_id: str | None = None
    feishu_daily_valid_creator_table_id: str | None = None
    feishu_assignment_summary_sync_enabled: bool = False
    feishu_assignment_summary_table_id: str | None = None
    feishu_assignment_summary_shop_ids: str = ""
    feishu_assignment_summary_bd_names: str = ""
    feishu_assignment_summary_bd_aliases: dict[str, str] = Field(default_factory=dict)
    feishu_assignment_summary_sync_interval_seconds: int = Field(
        default=60, ge=60, le=3600
    )
    feishu_sample_auto_assignment_shop_ids: str = ""
    feishu_sample_auto_assignment_bd_names: str = ""
    feishu_sample_auto_assignment_category: str = ""
    feishu_sample_auto_assignment_batch_limit: int = Field(default=1, ge=1, le=100)
    feishu_sample_auto_assignment_bd_capacity: int = Field(default=10, ge=1, le=1000)
    affiliate_export_service_token: SecretStr | None = Field(
        default=None, min_length=32
    )
    affiliate_export_tenant_id: UUID | None = None
    sample_capture_service_token: SecretStr | None = Field(
        default=None, min_length=32
    )
    affiliate_capture_service_token: SecretStr | None = Field(
        default=None, min_length=32
    )
    tiktok_token_encryption_key: SecretStr | None = None
    order_pii_encryption_key: SecretStr | None = None
    object_storage_endpoint_url: str | None = None
    object_storage_region: str = "us-east-1"
    object_storage_access_key: SecretStr | None = None
    object_storage_secret_key: SecretStr | None = None
    object_storage_bucket: str | None = None
    object_storage_force_path_style: bool = False
    object_storage_key_prefix: str = ""
    object_storage_presigned_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    logistics_document_max_bytes: int = Field(
        default=10 * 1024 * 1024, ge=1, le=50 * 1024 * 1024
    )
    order_initial_backfill_days: int = 30
    order_sync_interval_minutes: int = 10
    order_pii_retention_days: int = 90
    tiktok_request_timeout_seconds: float = 10.0
    tiktok_request_max_retries: int = 2
    tiktok_retry_base_seconds: float = 0.5
    tiktok_max_retry_delay_seconds: float = 30.0
    tiktok_webhook_signing_secret: str | None = None
    tiktok_callback_base_url: str | None = None
    tiktok_oauth_state_ttl_seconds: int = 600
    ziniao_webdriver_url: str = "http://127.0.0.1:16888"
    ziniao_company: str | None = None
    ziniao_username: str | None = None
    ziniao_password: SecretStr | None = None
    ziniao_akeleo_browser_name: str | None = None
    ziniao_chromedriver_path: Path | None = None

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            origin.strip() for origin in self.cors_origins.split(",") if origin.strip()
        ]

    @property
    def sample_auto_assignment_shop_id_set(self) -> frozenset[UUID]:
        return frozenset(
            UUID(value.strip())
            for value in self.feishu_sample_auto_assignment_shop_ids.split(",")
            if value.strip()
        )

    @property
    def sample_auto_assignment_bd_name_set(self) -> frozenset[str]:
        return frozenset(
            value.strip()
            for value in self.feishu_sample_auto_assignment_bd_names.split(",")
            if value.strip()
        )

    @property
    def sample_auto_assignment_bd_names(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                value.strip()
                for value in self.feishu_sample_auto_assignment_bd_names.split(",")
                if value.strip()
            )
        )

    @property
    def assignment_summary_bd_names(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                value.strip()
                for value in self.feishu_assignment_summary_bd_names.split(",")
                if value.strip()
            )
        )

    @property
    def assignment_summary_shop_id_set(self) -> frozenset[UUID]:
        return frozenset(
            UUID(value.strip())
            for value in self.feishu_assignment_summary_shop_ids.split(",")
            if value.strip()
        )


def _get_environment_file(app_env: str) -> Path | None:
    environment_file = Path(f".env.{app_env}")
    if environment_file.is_file():
        return environment_file
    legacy_development_file = Path(".env")
    if app_env == "development" and legacy_development_file.is_file():
        return legacy_development_file
    return None


def validate_runtime_settings(settings: Settings) -> Settings:
    sample_tables = settings.feishu_sample_shop_table_ids
    sample_target = (
        settings.feishu_sample_base_token,
        settings.feishu_sample_table_id,
        bool(sample_tables),
    )
    sample_connection_ready = bool(
        settings.feishu_app_id
        and settings.feishu_app_secret
        and settings.feishu_sample_base_token
        and (settings.feishu_sample_table_id or sample_tables)
    )
    if any(sample_target) and not sample_connection_ready:
        raise ValueError(
            "Feishu sample app credentials, Base token, and table ID must be "
            "configured together."
        )
    table_ids = [value.strip() for value in sample_tables.values()]
    if any(not value for value in table_ids):
        raise ValueError("Feishu sample shop table IDs cannot be blank.")
    if len(table_ids) != len(set(table_ids)):
        raise ValueError("Feishu sample shops require unique table IDs.")
    default_sample_connection_ready = bool(
        sample_connection_ready and settings.feishu_sample_table_id
    )
    if (
        settings.feishu_sample_reverse_poll_enabled
        and not default_sample_connection_ready
    ):
        raise ValueError(
            "Feishu sample reverse poll requires complete sample app settings."
        )
    if (
        settings.feishu_sample_notification_enabled
        and not default_sample_connection_ready
    ):
        raise ValueError(
            "Feishu sample notification requires complete sample app settings."
        )
    if settings.feishu_sample_notification_enabled and (
        not settings.feishu_sample_record_url_template
        or "{record_id}" not in settings.feishu_sample_record_url_template
        or not settings.feishu_sample_record_url_template.startswith("https://")
    ):
        raise ValueError(
            "Feishu sample notification requires a record URL template containing "
            "{record_id}."
        )
    if (
        settings.feishu_sample_notification_enabled
        and not settings.feishu_sample_notification_live_recipients_enabled
        and not settings.feishu_sample_notification_test_recipient_open_id
    ):
        raise ValueError(
            "Feishu sample notification test mode requires a test recipient OpenID."
        )
    if (
        settings.feishu_sample_notification_enabled
        and settings.feishu_sample_notification_live_recipients_enabled
        and not settings.feishu_sample_notification_group_chat_id
    ):
        raise ValueError(
            "Feishu sample notification live mode requires a group chat ID."
        )
    if settings.feishu_sample_auto_assignment_enabled:
        try:
            allowed_shop_ids = settings.sample_auto_assignment_shop_id_set
        except ValueError as error:
            raise ValueError(
                "Feishu sample auto-assignment shop allowlist contains an invalid UUID."
            ) from error
        if (
            not default_sample_connection_ready
            or not settings.feishu_bd_roster_table_id
            or not settings.feishu_bd_assignment_record_table_id
        ):
            raise ValueError(
                "Feishu sample auto-assignment requires the sample connection and "
                "BD roster and assignment record table IDs."
            )
        if not allowed_shop_ids:
            raise ValueError(
                "Feishu sample auto-assignment requires an explicit shop allowlist."
            )
        if not settings.sample_auto_assignment_bd_name_set:
            raise ValueError(
                "Feishu sample auto-assignment requires explicit BD names."
            )
        if not settings.feishu_sample_auto_assignment_category.strip():
            raise ValueError(
                "Feishu sample auto-assignment requires an explicit category."
            )
        activation_at = settings.feishu_sample_auto_assignment_activation_at
        if activation_at is None or activation_at.utcoffset() is None:
            raise ValueError(
                "Feishu sample auto-assignment requires a timezone-aware "
                "activation time."
            )
    try:
        assignment_summary_shop_ids = settings.assignment_summary_shop_id_set
    except ValueError as error:
        raise ValueError(
            "Feishu assignment summary shop scope contains an invalid UUID."
        ) from error
    if settings.feishu_assignment_summary_sync_enabled and (
        not settings.feishu_app_id
        or not settings.feishu_app_secret
        or not settings.feishu_sample_base_token
        or not settings.feishu_bd_assignment_record_table_id
        or not settings.feishu_assignment_summary_table_id
        or not assignment_summary_shop_ids
        or not settings.assignment_summary_bd_names
    ):
        raise ValueError(
            "Feishu assignment summary sync requires app credentials, Base token, "
            "assignment and summary table IDs, shop IDs, and BD names."
        )
    summary_bds = set(settings.assignment_summary_bd_names)
    if settings.feishu_assignment_summary_sync_enabled and any(
        not source.strip() or not target.strip() or target.strip() not in summary_bds
        for source, target in settings.feishu_assignment_summary_bd_aliases.items()
    ):
        raise ValueError(
            "Feishu assignment summary BD aliases must target configured BD names."
        )
    event_connection = (
        settings.feishu_event_verification_token,
        settings.feishu_event_encrypt_key,
    )
    if any(event_connection) and (
        not settings.feishu_app_id or not all(event_connection)
    ):
        raise ValueError(
            "Feishu event callback requires App ID, Verification Token, and Encrypt Key."
        )
    if settings.app_env != "production":
        return settings
    if settings.api_reload:
        raise ValueError("API_RELOAD must be false in production.")
    if not settings.cors_origin_list or "*" in settings.cors_origin_list:
        raise ValueError("Production CORS_ORIGINS must contain explicit origins.")
    if not settings.auth_captcha_hmac_secret:
        raise ValueError("AUTH_CAPTCHA_HMAC_SECRET must be set in production.")
    tiktok_settings = (
        settings.tiktok_app_key,
        settings.tiktok_service_id,
        settings.tiktok_app_secret,
        settings.tiktok_authorization_url,
        settings.tiktok_token_url,
        settings.tiktok_shop_identity_url,
        settings.tiktok_callback_base_url,
        settings.tiktok_token_encryption_key,
        settings.tiktok_webhook_signing_secret,
        settings.order_pii_encryption_key,
    )
    if any(tiktok_settings) and not all(tiktok_settings):
        raise ValueError(
            "TikTok OAuth settings must be configured as a complete set in production."
        )
    tiktok_301_settings = (
        settings.tiktok_301_app_key,
        settings.tiktok_301_service_id,
        settings.tiktok_301_app_secret,
    )
    if any(tiktok_301_settings) and not all(tiktok_301_settings):
        raise ValueError(
            "TikTok 301 App settings must be configured as a complete set in production."
        )
    ziniao_credentials = (
        settings.ziniao_company,
        settings.ziniao_username,
        settings.ziniao_password,
    )
    if any(ziniao_credentials) and not all(ziniao_credentials):
        raise ValueError(
            "Ziniao WebDriver credentials must be configured as a complete set."
        )
    object_storage_settings = (
        settings.object_storage_access_key,
        settings.object_storage_secret_key,
        settings.object_storage_bucket,
    )
    if any(object_storage_settings) and not all(object_storage_settings):
        raise ValueError(
            "Object storage access key, secret key, and bucket must be configured together."
        )
    return settings


@lru_cache
def get_settings() -> Settings:
    app_env = os.getenv("APP_ENV", "development").lower()
    settings = Settings(_env_file=_get_environment_file(app_env))
    return validate_runtime_settings(settings)
