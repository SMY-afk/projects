from erp_api.models.affiliate_creator_detail import (
    AffiliateCreatorDetailItem,
    AffiliateCreatorDetailReport,
)
from erp_api.models.analytics_sync import AnalyticsSyncRun


def _constraint_sql(model, name):
    constraint = next(item for item in model.__table__.constraints if item.name == name)
    return str(constraint.sqltext)


def test_creator_detail_resource_and_status_constraints_are_strict():
    assert "product_card" in _constraint_sql(
        AffiliateCreatorDetailReport, "ck_affiliate_creator_detail_resource"
    )
    assert "partial" in _constraint_sql(
        AffiliateCreatorDetailReport, "ck_affiliate_creator_detail_status"
    )


def test_detail_items_are_tenant_shop_report_scoped():
    names = {
        constraint.name
        for constraint in AffiliateCreatorDetailItem.__table__.constraints
    }
    assert "uq_affiliate_creator_detail_item" in names


def test_analytics_run_accepts_creator_detail_without_reusing_global_video_type():
    sql = _constraint_sql(AnalyticsSyncRun, "ck_analytics_sync_runs_resource_type")
    assert "affiliate_creator_detail" in sql
