from uuid import UUID

import pytest

from erp_api.core.config import Settings, validate_runtime_settings
from erp_api.main import _split_endpoint


def test_production_rejects_hot_reload() -> None:
    settings = Settings(
        _env_file=None,
        app_env="production",
        api_reload=True,
        cors_origins="https://app.example.com",
        database_url="postgresql+asyncpg://erp:test@localhost:5432/erp",
        redis_url="redis://localhost:6379/0",
    )

    with pytest.raises(ValueError, match="API_RELOAD"):
        validate_runtime_settings(settings)


def test_production_requires_explicit_cors_origins() -> None:
    settings = Settings(
        _env_file=None,
        app_env="production",
        cors_origins="*",
        database_url="postgresql+asyncpg://erp:test@localhost:5432/erp",
        redis_url="redis://localhost:6379/0",
    )

    with pytest.raises(ValueError, match="CORS_ORIGINS"):
        validate_runtime_settings(settings)


def test_production_requires_a_captcha_hmac_secret() -> None:
    settings = Settings(
        _env_file=None,
        app_env="production",
        cors_origins="https://app.example.com",
        database_url="postgresql+asyncpg://erp:test@localhost:5432/erp",
        redis_url="redis://localhost:6379/0",
        auth_captcha_hmac_secret="",
    )

    with pytest.raises(ValueError, match="AUTH_CAPTCHA_HMAC_SECRET"):
        validate_runtime_settings(settings)


def test_default_development_port_matches_the_vite_proxy() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://erp:test@localhost:5432/erp",
        redis_url="redis://localhost:6379/0",
    )

    assert settings.api_port == 8080


def test_access_token_default_idle_ttl_is_two_hours() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://erp:test@localhost:5432/erp",
        redis_url="redis://localhost:6379/0",
    )

    assert settings.auth_access_token_ttl_seconds == 7200


def test_tiktok_oauth_state_default_ttl_is_short_lived() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://erp:test@localhost:5432/erp",
        redis_url="redis://localhost:6379/0",
    )

    assert settings.tiktok_oauth_state_ttl_seconds == 600


def test_tiktok_transport_defaults_are_bounded() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://erp:test@localhost:5432/erp",
        redis_url="redis://localhost:6379/0",
    )

    assert settings.tiktok_request_timeout_seconds == 10
    assert settings.tiktok_request_max_retries == 2
    assert settings.tiktok_retry_base_seconds == 0.5
    assert settings.tiktok_max_retry_delay_seconds == 30


def test_analytics_endpoint_configuration_is_optional_and_injectable() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://erp:test@localhost:5432/erp",
        redis_url="redis://localhost:6379/0",
        tiktok_video_analytics_url="https://open.example.test/analytics/202605/shop_videos/performance",
        tiktok_video_analytics_overview_url="https://open.example.test/analytics/202509/shop_videos/overview_performance",
        tiktok_video_analytics_field_map={"videoId": "id"},
        tiktok_live_analytics_url="https://open.example.test/analytics/202509/shop_lives/performance",
        tiktok_live_analytics_overview_url="https://open.example.test/analytics/202509/shop_lives/overview_performance",
        tiktok_live_analytics_field_map={"liveId": "id"},
    )

    assert settings.tiktok_video_analytics_items_path == "videos"
    assert settings.tiktok_live_analytics_items_path == "live_stream_sessions"
    assert settings.tiktok_video_analytics_field_map == {"videoId": "id"}
    assert settings.tiktok_video_analytics_overview_url.endswith(
        "/shop_videos/overview_performance"
    )


def test_analytics_raw_payload_ttl_has_a_safe_positive_default() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://erp:test@localhost:5432/erp",
        redis_url="redis://localhost:6379/0",
    )

    assert settings.tiktok_analytics_raw_payload_ttl_days == 30

    with pytest.raises(ValueError, match="greater than or equal to 1"):
        Settings(
            _env_file=None,
            database_url="postgresql+asyncpg://erp:test@localhost:5432/erp",
            redis_url="redis://localhost:6379/0",
            tiktok_analytics_raw_payload_ttl_days=0,
        )


def test_affiliate_center_capture_raw_payload_ttl_is_seven_days() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://erp:test@localhost:5432/erp",
        redis_url="redis://localhost:6379/0",
    )

    assert settings.affiliate_center_raw_payload_ttl_days == 7

    with pytest.raises(ValueError, match="Input should be 7"):
        Settings(
            _env_file=None,
            database_url="postgresql+asyncpg://erp:test@localhost:5432/erp",
            redis_url="redis://localhost:6379/0",
            affiliate_center_raw_payload_ttl_days=8,
        )


def test_bestseller_daily_schedule_has_bounded_defaults() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://erp:test@localhost:5432/erp",
        redis_url="redis://localhost:6379/0",
    )

    assert settings.tiktok_bestseller_sync_hour_utc == 5
    assert settings.tiktok_bestseller_sync_minute_utc == 0

    with pytest.raises(ValueError):
        Settings(
            _env_file=None,
            database_url="postgresql+asyncpg://erp:test@localhost:5432/erp",
            redis_url="redis://localhost:6379/0",
            tiktok_bestseller_sync_hour_utc=24,
        )


@pytest.mark.parametrize(
    "endpoint",
    [
        "not-an-absolute-url",
        "https://open.example.test/path?unexpected=true",
        "https://open.example.test/path#fragment",
    ],
)
def test_tiktok_endpoint_rejects_invalid_or_lossy_urls(endpoint: str) -> None:
    with pytest.raises(ValueError, match="TikTok endpoint"):
        _split_endpoint(endpoint)


def test_production_rejects_partial_tiktok_oauth_settings() -> None:
    settings = Settings(
        _env_file=None,
        app_env="production",
        cors_origins="https://app.example.com",
        database_url="postgresql+asyncpg://erp:test@localhost:5432/erp",
        redis_url="redis://localhost:6379/0",
        auth_captcha_hmac_secret="test-only-secret-not-for-production",
        tiktok_app_key="configured-without-the-rest",
    )

    with pytest.raises(ValueError, match="TikTok OAuth settings"):
        validate_runtime_settings(settings)


def test_tiktok_secrets_are_masked_in_settings_output() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://erp:test@localhost:5432/erp",
        redis_url="redis://localhost:6379/0",
        tiktok_app_secret="platform-secret-value",
        tiktok_token_encryption_key="token-encryption-secret-value-32-chars",
    )

    rendered = f"{settings!r} {settings.model_dump_json()}"
    assert "platform-secret-value" not in rendered
    assert "token-encryption-secret-value-32-chars" not in rendered
    assert settings.tiktok_app_secret.get_secret_value() == "platform-secret-value"


def test_tiktok_301_secret_is_masked_in_settings_output() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://erp:test@localhost:5432/erp",
        redis_url="redis://localhost:6379/0",
        tiktok_301_app_secret="301-secret-value",
    )

    rendered = f"{settings!r} {settings.model_dump_json()}"
    assert "301-secret-value" not in rendered


def test_feishu_secret_is_masked_in_settings_output() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://erp:test@localhost:5432/erp",
        redis_url="redis://localhost:6379/0",
        feishu_app_id="cli_test_app",
        feishu_app_secret="feishu-secret-value",
        feishu_sample_base_token="base-secret-value",
        feishu_sample_table_id="table-id",
        feishu_event_verification_token="event-secret-value",
        feishu_event_encrypt_key="event-encrypt-key-value",
    )

    rendered = f"{settings!r} {settings.model_dump_json()}"
    assert "feishu-secret-value" not in rendered
    assert "base-secret-value" not in rendered
    assert settings.feishu_app_secret.get_secret_value() == "feishu-secret-value"
    assert "event-secret-value" not in rendered
    assert "event-encrypt-key-value" not in rendered


def test_feishu_event_token_requires_app_id() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://erp:test@localhost:5432/erp",
        redis_url="redis://localhost:6379/0",
        feishu_event_verification_token="event-secret-value",
        feishu_event_encrypt_key="event-encrypt-key-value",
    )

    with pytest.raises(ValueError, match="App ID"):
        validate_runtime_settings(settings)


def test_feishu_event_token_requires_encrypt_key() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://erp:test@localhost:5432/erp",
        redis_url="redis://localhost:6379/0",
        feishu_app_id="cli_test_app",
        feishu_event_verification_token="event-secret-value",
    )

    with pytest.raises(ValueError, match="Encrypt Key"):
        validate_runtime_settings(settings)


def test_feishu_sample_target_requires_complete_connection_settings() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://erp:test@localhost:5432/erp",
        redis_url="redis://localhost:6379/0",
        feishu_sample_table_id="table-id",
    )

    with pytest.raises(ValueError, match="Feishu sample app credentials"):
        validate_runtime_settings(settings)


def test_feishu_sample_shop_tables_require_unique_table_ids() -> None:
    first_shop_id = UUID("e4408786-af60-545e-8f8c-5ef22a71e675")
    second_shop_id = UUID("6dcc40dd-28d8-5dff-b7ec-383e429642f9")
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://erp:test@localhost:5432/erp",
        redis_url="redis://localhost:6379/0",
        feishu_app_id="app-id",
        feishu_app_secret="app-secret",
        feishu_sample_base_token="base-token",
        feishu_sample_shop_table_ids={
            first_shop_id: "table-id",
            second_shop_id: "table-id",
        },
    )

    with pytest.raises(ValueError, match="unique table IDs"):
        validate_runtime_settings(settings)


def test_feishu_reverse_poll_requires_complete_sample_target() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://erp:test@localhost:5432/erp",
        redis_url="redis://localhost:6379/0",
        feishu_sample_reverse_poll_enabled=True,
    )

    with pytest.raises(ValueError, match="reverse poll"):
        validate_runtime_settings(settings)


def test_feishu_notification_sender_requires_complete_sample_target() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://erp:test@localhost:5432/erp",
        redis_url="redis://localhost:6379/0",
        feishu_sample_notification_enabled=True,
    )

    with pytest.raises(ValueError, match="notification"):
        validate_runtime_settings(settings)


def test_feishu_notification_sender_requires_record_url_template() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://erp:test@localhost:5432/erp",
        redis_url="redis://localhost:6379/0",
        feishu_app_id="app-id",
        feishu_app_secret="app-secret",
        feishu_sample_base_token="base-token",
        feishu_sample_table_id="table-id",
        feishu_sample_notification_enabled=True,
    )

    with pytest.raises(ValueError, match="record URL template"):
        validate_runtime_settings(settings)


def test_feishu_notification_test_mode_requires_test_recipient() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://erp:test@localhost:5432/erp",
        redis_url="redis://localhost:6379/0",
        feishu_app_id="app-id",
        feishu_app_secret="app-secret",
        feishu_sample_base_token="base-token",
        feishu_sample_table_id="table-id",
        feishu_sample_notification_enabled=True,
        feishu_sample_record_url_template=(
            "https://example.invalid/configure-resource"
            "&record={record_id}"
        ),
    )

    with pytest.raises(ValueError, match="test recipient OpenID"):
        validate_runtime_settings(settings)


def test_feishu_notification_live_mode_is_an_explicit_opt_in() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://erp:test@localhost:5432/erp",
        redis_url="redis://localhost:6379/0",
        feishu_app_id="app-id",
        feishu_app_secret="app-secret",
        feishu_sample_base_token="base-token",
        feishu_sample_table_id="table-id",
        feishu_sample_notification_enabled=True,
        feishu_sample_record_url_template=(
            "https://example.invalid/configure-resource"
            "&record={record_id}"
        ),
        feishu_sample_notification_live_recipients_enabled=True,
        feishu_sample_notification_group_chat_id="oc-business",
    )

    assert validate_runtime_settings(settings) is settings


def test_feishu_notification_live_mode_requires_group_chat() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://erp:test@localhost:5432/erp",
        redis_url="redis://localhost:6379/0",
        feishu_app_id="app-id",
        feishu_app_secret="app-secret",
        feishu_sample_base_token="base-token",
        feishu_sample_table_id="table-id",
        feishu_sample_notification_enabled=True,
        feishu_sample_record_url_template=(
            "https://example.invalid/configure-resource"
            "&record={record_id}"
        ),
        feishu_sample_notification_live_recipients_enabled=True,
        feishu_sample_notification_group_chat_id="",
    )

    with pytest.raises(ValueError, match="group chat ID"):
        validate_runtime_settings(settings)


def test_ziniao_password_is_masked_in_settings_output() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://erp:test@localhost:5432/erp",
        redis_url="redis://localhost:6379/0",
        ziniao_password="ziniao-secret-value",
    )

    rendered = f"{settings!r} {settings.model_dump_json()}"
    assert "ziniao-secret-value" not in rendered


def test_production_rejects_partial_ziniao_credentials() -> None:
    settings = Settings(
        _env_file=None,
        app_env="production",
        cors_origins="https://app.example.com",
        database_url="postgresql+asyncpg://erp:test@localhost:5432/erp",
        redis_url="redis://localhost:6379/0",
        auth_captcha_hmac_secret="test-only-secret-not-for-production",
        ziniao_company="configured-without-the-rest",
    )

    with pytest.raises(ValueError, match="Ziniao WebDriver credentials"):
        validate_runtime_settings(settings)
