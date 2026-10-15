from erp_api.core.config import Settings
from erp_api.infrastructure.database import Database
from erp_api.main import build_sample_application_services
from erp_api.services.feishu_sheet_ai_invitation_client import (
    FeishuSheetAiInvitationClient,
)


def test_ai_invitation_sheet_replaces_precheck_lookup_but_not_mirror() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://erp:test@localhost:5432/erp",
        redis_url="redis://localhost:6379/0",
        feishu_app_id="app-id",
        feishu_app_secret="app-secret",
        feishu_sample_base_token="sample-base",
        feishu_sample_table_id="sample-table",
        feishu_bd_roster_table_id="roster-table",
        feishu_bd_assignment_record_table_id="assignment-table",
        feishu_bd_invitation_protection_table_id="protection-table",
        feishu_ai_invitation_base_token="old-base",
        feishu_ai_invitation_table_id="old-table",
        feishu_ai_invitation_sheet_token="new-spreadsheet",
        feishu_ai_invitation_sheet_id="new-worksheet",
        feishu_ai_invitation_mirror_table_id="mirror-table",
        feishu_sample_auto_assignment_enabled=True,
        feishu_sample_auto_assignment_activation_at="2026-09-14T08:00:00+08:00",
        feishu_sample_auto_assignment_shop_ids=(
            "b94f051e-2cf1-5606-aa40-d083a74329ad"
        ),
        feishu_sample_auto_assignment_bd_names="BD A,BD B,BD C",
        feishu_sample_auto_assignment_category="test",
    )

    snapshot_store = object()
    services = build_sample_application_services(
        settings, Database(settings.database_url), ai_snapshot_store=snapshot_store
    )
    reader = services["sample_cooperation_precheck_service"]._reader
    protection = services["sample_bd_invitation_protection_service"]
    mirror = services["sample_ai_invitation_mirror_service"]

    assert isinstance(reader._ai_invitations, FeishuSheetAiInvitationClient)
    assert protection._lookup_sources[1].client is reader._ai_invitations
    assert protection._ai_snapshot_store is snapshot_store
    assert reader._ai_invitations._spreadsheet_token == "new-spreadsheet"
    assert mirror._source._table_id == "old-table"
