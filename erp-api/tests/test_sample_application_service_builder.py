from datetime import UTC, datetime
from uuid import UUID

import erp_api.main as main_module
from erp_api.core.config import Settings
from erp_api.infrastructure.database import Database
from erp_api.main import build_sample_application_services
from erp_api.services.feishu_sample_batch_client import FeishuSampleBatchClient
from erp_api.services.feishu_sample_event_processor import FeishuSampleEventProcessor
from erp_api.services.sample_ai_invitation_mirror import (
    SampleAiInvitationMirrorService,
)
from erp_api.services.sample_assignment_record_service import (
    SampleAssignmentRecordService,
)
from erp_api.services.sample_auto_assignment_feishu_service import (
    SampleAutoAssignmentFeishuService,
)
from erp_api.services.sample_auto_assignment_service import SampleAutoAssignmentService
from erp_api.services.sample_cooperation_reader import (
    DAILY_VALID_CREATORS_TABLE_ID,
)
from erp_api.services.sample_cooperation_service import (
    SampleCooperationPrecheckService,
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
from erp_api.services.sample_notification_profile_enrichment import (
    SampleNotificationProfileEnrichmentService,
)
from erp_api.services.sample_notification_service import SampleNotificationService
from erp_api.services.sample_shop_pipeline_service import SampleShopPipelineService


def _settings(**values) -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://erp:test@localhost:5432/erp",
        redis_url="redis://localhost:6379/0",
        **values,
    )


def test_sample_services_build_configured_feishu_client() -> None:
    settings = _settings(
        feishu_app_id="app-id",
        feishu_app_secret="app-secret",
        feishu_sample_base_token="base-token",
        feishu_sample_table_id="table-id",
    )

    services = build_sample_application_services(
        settings,
        Database(settings.database_url),
    )

    assert isinstance(services["feishu_sample_client"], FeishuSampleBatchClient)
    assert isinstance(
        services["sample_feishu_source_repository"],
        SampleFeishuSourceRepository,
    )
    assert isinstance(
        services["sample_feishu_mapping_repository"],
        SampleFeishuMappingRepository,
    )
    assert services["sample_feishu_sync_service"] is not None
    assert services["feishu_sample_event_processor"] is None
    assert services["feishu_sample_reverse_poll_service"] is None
    assert services["sample_notification_service"] is None
    assert services["sample_shop_pipeline_service"] is None


def test_sample_services_route_each_shop_to_its_own_feishu_table() -> None:
    first_shop_id = "b94f051e-2cf1-5606-aa40-d083a74329ad"
    second_shop_id = "7f68584d-867a-524d-aef4-6d6652ff77fa"
    settings = _settings(
        feishu_app_id="app-id",
        feishu_app_secret="app-secret",
        feishu_sample_base_token="base-token",
        feishu_sample_table_id="default-table-id",
        feishu_sample_shop_table_ids={
            first_shop_id: "first-table-id",
            second_shop_id: "second-table-id",
        },
    )

    services = build_sample_application_services(
        settings,
        Database(settings.database_url),
    )

    router = services["feishu_sample_client_router"]
    first = router.for_shop(UUID(first_shop_id))
    second = router.for_shop(UUID(second_shop_id))
    default = router.for_shop(UUID(int=333))
    assert first._table_id == "first-table-id"
    assert second._table_id == "second-table-id"
    assert default._table_id == "default-table-id"


def test_sample_services_build_event_processor_with_complete_callback_config() -> None:
    settings = _settings(
        feishu_app_id="app-id",
        feishu_app_secret="app-secret",
        feishu_sample_base_token="base-token",
        feishu_sample_table_id="table-id",
        feishu_event_verification_token="verification-token",
        feishu_event_encrypt_key="encrypt-key",
    )

    services = build_sample_application_services(
        settings,
        Database(settings.database_url),
    )

    assert isinstance(
        services["feishu_sample_event_processor"], FeishuSampleEventProcessor
    )


def test_sample_services_leave_feishu_disabled_without_target() -> None:
    settings = _settings(feishu_app_id="app-id", feishu_app_secret="app-secret")

    services = build_sample_application_services(
        settings,
        Database(settings.database_url),
    )

    assert services["feishu_sample_client"] is None
    assert services["sample_feishu_sync_service"] is None
    assert services["feishu_sample_event_processor"] is None
    assert services["feishu_sample_reverse_poll_service"] is None
    assert services["sample_notification_service"] is None
    assert services["sample_shop_pipeline_service"] is None


def test_sample_services_build_explicit_reverse_poll_fallback() -> None:
    settings = _settings(
        feishu_app_id="app-id",
        feishu_app_secret="app-secret",
        feishu_sample_base_token="base-token",
        feishu_sample_table_id="table-id",
        feishu_sample_reverse_poll_enabled=True,
    )

    services = build_sample_application_services(
        settings,
        Database(settings.database_url),
    )

    assert isinstance(
        services["feishu_sample_reverse_poll_service"],
        SampleFeishuReversePollService,
    )


def test_reverse_poll_includes_default_and_shop_specific_tables() -> None:
    shop_id = "b94f051e-2cf1-5606-aa40-d083a74329ad"
    settings = _settings(
        feishu_app_id="app-id",
        feishu_app_secret="app-secret",
        feishu_sample_base_token="base-token",
        feishu_sample_table_id="default-table-id",
        feishu_sample_shop_table_ids={shop_id: "shop-table-id"},
        feishu_sample_reverse_poll_enabled=True,
    )

    services = build_sample_application_services(
        settings,
        Database(settings.database_url),
    )

    reverse_poll = services["feishu_sample_reverse_poll_service"]
    assert len(reverse_poll._feishu_clients) == 2


def test_sample_services_build_explicit_notification_sender() -> None:
    settings = _settings(
        feishu_app_id="app-id",
        feishu_app_secret="app-secret",
        feishu_sample_base_token="base-token",
        feishu_sample_table_id="table-id",
        feishu_sample_notification_enabled=True,
        feishu_sample_notification_test_recipient_open_id="ou-test",
        feishu_sample_record_url_template=(
            "https://example.invalid/configure-resource"
        ),
    )

    services = build_sample_application_services(
        settings,
        Database(settings.database_url),
    )

    assert isinstance(
        services["sample_notification_service"], SampleNotificationService
    )


def test_sample_notification_sender_copies_assignment_card_to_configured_group() -> None:
    settings = _settings(
        feishu_app_id="app-id",
        feishu_app_secret="app-secret",
        feishu_sample_base_token="base-token",
        feishu_sample_table_id="table-id",
        feishu_sample_notification_enabled=True,
        feishu_sample_notification_test_recipient_open_id="ou-test",
        feishu_sample_notification_group_chat_id="oc-business",
        feishu_sample_record_url_template=(
            "https://example.invalid/configure-resource"
        ),
    )

    services = build_sample_application_services(
        settings,
        Database(settings.database_url),
    )

    notification_service = services["sample_notification_service"]
    assert isinstance(notification_service, SampleNotificationService)
    assert notification_service._group_chat_id == "oc-business"


def test_sample_services_build_allowlisted_auto_assignment() -> None:
    shop_id = "b94f051e-2cf1-5606-aa40-d083a74329ad"
    settings = _settings(
        feishu_app_id="app-id",
        feishu_app_secret="app-secret",
        feishu_sample_base_token="base-token",
        feishu_sample_table_id="sample-table-id",
        feishu_bd_roster_table_id="roster-table-id",
        feishu_bd_assignment_record_table_id="assignment-table-id",
        feishu_bd_invitation_protection_table_id="protection-table-id",
        feishu_ai_invitation_base_token="ai-base-token",
        feishu_ai_invitation_table_id="ai-table-id",
        feishu_ai_invitation_mirror_table_id="ai-mirror-table-id",
        feishu_sample_auto_assignment_enabled=True,
        feishu_sample_auto_assignment_activation_at="2026-09-14T08:00:00+08:00",
        feishu_sample_auto_assignment_shop_ids=shop_id,
        feishu_sample_auto_assignment_bd_names="BD A,BD B,BD C",
        feishu_sample_auto_assignment_category="test",
    )

    services = build_sample_application_services(
        settings,
        Database(settings.database_url),
    )

    assert isinstance(
        services["sample_auto_assignment_service"], SampleAutoAssignmentService
    )
    assert services["sample_feishu_source_repository"]._activation_at == datetime(
        2026, 9, 14, 0, 0, tzinfo=UTC
    )
    assert isinstance(
        services["sample_auto_assignment_projection"],
        SampleAutoAssignmentFeishuService,
    )
    assert isinstance(
        services["sample_assignment_record_service"],
        SampleAssignmentRecordService,
    )
    assert services["sample_assignment_record_service"]._activation_at == datetime(
        2026, 9, 14, 0, 0, tzinfo=UTC
    )
    assert isinstance(
        services["sample_notification_profile_enrichment_service"],
        SampleNotificationProfileEnrichmentService,
    )
    assert isinstance(
        services["sample_cooperation_precheck_service"],
        SampleCooperationPrecheckService,
    )
    reader = services["sample_cooperation_precheck_service"]._reader
    assert reader._valid_creators._table_id == DAILY_VALID_CREATORS_TABLE_ID
    protection = services["sample_bd_invitation_protection_service"]
    assert protection._client._table_id == "protection-table-id"
    assert [source.label for source in protection._lookup_sources] == [
        "（每日更新）有效达人",
        "AI邀约表",
    ]
    assert protection._lookup_sources[1].client._base_token == "ai-base-token"
    assert protection._lookup_sources[1].client._table_id == "ai-table-id"
    assert protection._unavailable_sources == ()
    assert reader._invitation_protection is protection
    mirror = services["sample_ai_invitation_mirror_service"]
    assert isinstance(mirror, SampleAiInvitationMirrorService)
    assert mirror._source._base_token == "ai-base-token"
    assert mirror._source._table_id == "ai-table-id"
    assert mirror._target._base_token == "base-token"
    assert mirror._target._table_id == "ai-mirror-table-id"


def test_sample_services_build_complete_shop_pipeline(monkeypatch) -> None:
    settings = _settings(
        feishu_app_id="app-id",
        feishu_app_secret="app-secret",
        feishu_sample_base_token="base-token",
        feishu_sample_table_id="table-id",
    )
    monkeypatch.setattr(main_module, "_create_shop_repository", lambda *_args: object())
    monkeypatch.setattr(
        main_module, "_create_tiktok_app_registry", lambda *_args: object()
    )
    monkeypatch.setattr(
        main_module,
        "_create_tiktok_client",
        lambda *_args: type("Client", (), {"api_transport": object()})(),
    )

    services = build_sample_application_services(
        settings,
        Database(settings.database_url),
    )

    assert isinstance(
        services["sample_shop_pipeline_service"], SampleShopPipelineService
    )
