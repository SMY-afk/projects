from datetime import UTC, datetime

import pytest

from erp_api.core.config import Settings, validate_runtime_settings


def _settings(**values) -> Settings:
    defaults = {
        "feishu_app_id": None,
        "feishu_app_secret": None,
        "feishu_sample_base_token": None,
        "feishu_sample_table_id": None,
        "feishu_sample_shop_table_ids": {},
        "feishu_event_verification_token": None,
        "feishu_event_encrypt_key": None,
        "feishu_sample_reverse_poll_enabled": False,
        "feishu_sample_notification_enabled": False,
        "feishu_sample_notification_live_recipients_enabled": False,
        "feishu_sample_notification_group_chat_id": None,
        "feishu_bd_roster_table_id": None,
        "feishu_bd_assignment_record_table_id": None,
        "feishu_sample_auto_assignment_enabled": False,
        "feishu_sample_auto_assignment_activation_at": None,
        "feishu_sample_auto_assignment_shop_ids": "",
        "feishu_sample_auto_assignment_bd_names": "",
        "feishu_sample_auto_assignment_category": "",
        "feishu_assignment_summary_sync_enabled": False,
        "feishu_assignment_summary_table_id": None,
        "feishu_assignment_summary_shop_ids": "",
        "feishu_assignment_summary_bd_names": "",
        "feishu_assignment_summary_bd_aliases": {},
    }
    defaults.update(values)
    return Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://erp:test@localhost:5432/erp",
        redis_url="redis://localhost:6379/0",
        **defaults,
    )


def test_auto_assignment_is_disabled_by_default() -> None:
    settings = validate_runtime_settings(_settings())

    assert settings.feishu_sample_auto_assignment_enabled is False
    assert settings.sample_auto_assignment_shop_id_set == frozenset()
    assert settings.feishu_assignment_summary_sync_enabled is False
    assert settings.feishu_assignment_summary_sync_interval_seconds == 60


def test_enabled_auto_assignment_requires_explicit_complete_scope() -> None:
    with pytest.raises(ValueError, match="sample connection"):
        validate_runtime_settings(_settings(feishu_sample_auto_assignment_enabled=True))


def test_enabled_auto_assignment_requires_activation_time() -> None:
    with pytest.raises(ValueError, match="activation time"):
        validate_runtime_settings(
            _settings(
                feishu_app_id="app-id",
                feishu_app_secret="app-secret",
                feishu_sample_base_token="base-token",
                feishu_sample_table_id="sample-table-id",
                feishu_bd_roster_table_id="roster-table-id",
                feishu_bd_assignment_record_table_id="assignment-table-id",
                feishu_sample_auto_assignment_enabled=True,
                feishu_sample_auto_assignment_shop_ids=(
                    "b94f051e-2cf1-5606-aa40-d083a74329ad"
                ),
                feishu_sample_auto_assignment_bd_names="BD A",
                feishu_sample_auto_assignment_category="test",
            )
        )


def test_enabled_auto_assignment_parses_allowlist_and_bd_names() -> None:
    first = "b94f051e-2cf1-5606-aa40-d083a74329ad"
    second = "7f68584d-867a-524d-aef4-6d6652ff77fa"
    settings = validate_runtime_settings(
        _settings(
            feishu_app_id="app-id",
            feishu_app_secret="app-secret",
            feishu_sample_base_token="base-token",
            feishu_sample_table_id="sample-table-id",
            feishu_bd_roster_table_id="roster-table-id",
            feishu_bd_assignment_record_table_id="assignment-table-id",
            feishu_sample_auto_assignment_enabled=True,
            feishu_sample_auto_assignment_activation_at=datetime(
                2026, 9, 14, tzinfo=UTC
            ),
            feishu_sample_auto_assignment_shop_ids=f"{first}, {second}",
            feishu_sample_auto_assignment_bd_names="李鸿程, 吴洵涛, 刘诚",
            feishu_sample_auto_assignment_category="测试",
        )
    )

    assert {str(value) for value in settings.sample_auto_assignment_shop_id_set} == {
        first,
        second,
    }
    assert settings.sample_auto_assignment_bd_name_set == {
        "李鸿程",
        "吴洵涛",
        "刘诚",
    }


def test_enabled_auto_assignment_rejects_invalid_shop_uuid() -> None:
    with pytest.raises(ValueError, match="invalid UUID"):
        validate_runtime_settings(
            _settings(
                feishu_app_id="app-id",
                feishu_app_secret="app-secret",
                feishu_sample_base_token="base-token",
                feishu_sample_table_id="sample-table-id",
                feishu_bd_roster_table_id="roster-table-id",
                feishu_bd_assignment_record_table_id="assignment-table-id",
                feishu_sample_auto_assignment_enabled=True,
                feishu_sample_auto_assignment_activation_at=datetime(
                    2026, 9, 14, tzinfo=UTC
                ),
                feishu_sample_auto_assignment_shop_ids="not-a-uuid",
                feishu_sample_auto_assignment_bd_names="BD A",
                feishu_sample_auto_assignment_category="test",
            )
        )


def test_enabled_assignment_summary_requires_complete_scope() -> None:
    with pytest.raises(ValueError, match="assignment summary sync requires"):
        validate_runtime_settings(
            _settings(feishu_assignment_summary_sync_enabled=True)
        )


def test_enabled_assignment_summary_accepts_explicit_scope() -> None:
    settings = validate_runtime_settings(
        _settings(
            feishu_app_id="app-id",
            feishu_app_secret="app-secret",
            feishu_sample_base_token="base-token",
            feishu_sample_table_id="sample-table-id",
            feishu_bd_assignment_record_table_id="assignment-table-id",
            feishu_assignment_summary_table_id="summary-table-id",
            feishu_assignment_summary_sync_enabled=True,
            feishu_assignment_summary_shop_ids=(
                "b94f051e-2cf1-5606-aa40-d083a74329ad"
            ),
            feishu_assignment_summary_bd_names="BD A, BD B, BD A",
            feishu_assignment_summary_bd_aliases={"BD Alpha": "BD A"},
        )
    )

    assert settings.assignment_summary_bd_names == ("BD A", "BD B")
    assert settings.feishu_assignment_summary_bd_aliases == {"BD Alpha": "BD A"}
