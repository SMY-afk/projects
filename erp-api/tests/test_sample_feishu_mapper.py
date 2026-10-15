from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from erp_api.services.feishu_sample_fields import BUSINESS_FIELDS, SYSTEM_FIELDS
from erp_api.services.sample_feishu_mapper import build_feishu_system_fields
from erp_api.services.sample_feishu_source_repository import (
    SampleFeishuSourceRecord,
)


def test_mapper_accepts_only_postgres_source_projection() -> None:
    observed_at = datetime(2026, 9, 10, tzinfo=UTC)
    synced_at = datetime(2026, 9, 10, 0, 5, tzinfo=UTC)
    first_seen_at = datetime(2026, 9, 9, 23, 55, tzinfo=UTC)
    record = SampleFeishuSourceRecord(
        application_id=uuid4(),
        tenant_id=uuid4(),
        shop_id=uuid4(),
        shop_name="Akeleo Toys",
        platform_application_id="sample-1",
        source_type="official_api",
        source_capture_id=uuid4(),
        source_observed_at=observed_at,
        first_seen_at=first_seen_at,
        creator_open_id="creator-open-id",
        creator_username="creator_name",
        creator_nickname="Creator",
        follower_count=1200,
        creator_gmv_minor=5_000_00,
        creator_gmv_currency="USD",
        creator_level="L2",
        platform_status="PENDING",
        product_id="product-1",
        product_title="Product",
        sku_id="sku-1",
        sku_name="Blue",
        commission_rate=Decimal("0.12"),
        available_quantity=1,
        feishu_record_id=None,
        assignment_version=0,
        creator_content_count=18,
        creator_ec_video_view=2600,
        creator_fulfillment_percentage=Decimal("73.50"),
        creator_units_sold=811,
        creator_pps=Decimal("4.2"),
        creator_rating=Decimal("4.8"),
        creator_profile_snapshot={"sample_score": {"overall": "86"}},
        tiktok_applied_at=datetime(2026, 9, 8, 12, 30, tzinfo=UTC),
        approve_expiration_at=datetime(2026, 9, 16, 0, 5, tzinfo=UTC),
    )

    fields = build_feishu_system_fields(record, synced_at=synced_at)

    assert fields["样品申请"] == "Akeleo Toys｜sample-1"
    assert fields["同步键（系统）"] == f"{record.shop_id}:sample-1"
    assert fields["申请编号"] == "sample-1"
    assert fields["店铺标识"] == "Akeleo Toys（本土店）"
    assert fields["数据来源"] == "official_api"
    assert fields["商品ID"] == ["product-1"]
    assert fields["首次发现时间"] == int(first_seen_at.timestamp() * 1000)
    assert fields["首次同步时间"] == int(synced_at.timestamp() * 1000)
    assert fields["TikTok申请时间"] == int(record.tiktok_applied_at.timestamp() * 1000)
    assert fields["30日内容数"] == 18
    assert fields["平均视频播放量"] == 2600
    assert fields["样品履约率"] == 0.735
    assert fields["30日销量"] == 811
    assert fields["PPS"] == "4.2/5.0"
    assert fields["达人评分"] == "4.8/5.0"
    assert fields["样品评分"] == 86
    assert fields["样品申请剩余时间"] == "剩余 6 天"
    assert set(fields) <= SYSTEM_FIELDS
    assert set(fields).isdisjoint(BUSINESS_FIELDS)
    assert "raw_payload" not in repr(fields)


def test_mapper_formats_subday_sample_time_left_with_hours_and_minutes() -> None:
    observed_at = datetime(2026, 9, 10, 0, 0, tzinfo=UTC)
    synced_at = observed_at + timedelta(hours=2)
    record = SampleFeishuSourceRecord(
        application_id=uuid4(),
        tenant_id=uuid4(),
        shop_id=uuid4(),
        shop_name="Akeleo Toys",
        platform_application_id="sample-time-left",
        source_type="hubstudio_cdp",
        source_capture_id=uuid4(),
        source_observed_at=observed_at,
        first_seen_at=observed_at,
        creator_open_id="creator-open-id",
        creator_username="creator_name",
        creator_nickname="Creator",
        follower_count=1200,
        creator_gmv_minor=None,
        creator_gmv_currency=None,
        creator_level=None,
        platform_status="PENDING",
        product_id="product-1",
        product_title="Product",
        sku_id="sku-1",
        sku_name="Blue",
        commission_rate=None,
        available_quantity=1,
        feishu_record_id=None,
        assignment_version=0,
        approve_expiration_at=observed_at + timedelta(hours=22, minutes=36),
    )

    fields = build_feishu_system_fields(record, synced_at=synced_at)

    assert fields["样品申请剩余时间"] == "剩余 20 小时 36 分"


def test_mapper_marks_expired_sample_application() -> None:
    synced_at = datetime(2026, 9, 10, 0, 0, tzinfo=UTC)
    record = SampleFeishuSourceRecord(
        application_id=uuid4(),
        tenant_id=uuid4(),
        shop_id=uuid4(),
        shop_name="Akeleo Toys",
        platform_application_id="sample-expired",
        source_type="hubstudio_cdp",
        source_capture_id=uuid4(),
        source_observed_at=synced_at,
        first_seen_at=synced_at,
        creator_open_id=None,
        creator_username="creator_name",
        creator_nickname="Creator",
        follower_count=None,
        creator_gmv_minor=None,
        creator_gmv_currency=None,
        creator_level=None,
        platform_status="PENDING",
        product_id=None,
        product_title=None,
        sku_id=None,
        sku_name=None,
        commission_rate=None,
        available_quantity=None,
        feishu_record_id=None,
        assignment_version=0,
        approve_expiration_at=synced_at - timedelta(seconds=1),
    )

    fields = build_feishu_system_fields(record, synced_at=synced_at)

    assert fields["样品申请剩余时间"] == "已过期"


def test_mapper_writes_multiple_product_ids_as_options_in_one_application() -> None:
    observed_at = datetime(2026, 9, 15, tzinfo=UTC)
    record = SampleFeishuSourceRecord(
        application_id=uuid4(),
        tenant_id=uuid4(),
        shop_id=uuid4(),
        shop_name="fanfu toy tool",
        platform_application_id="9425993608515544251",
        source_type="hubstudio_cdp",
        source_capture_id=uuid4(),
        source_observed_at=observed_at,
        first_seen_at=observed_at,
        creator_open_id="creator-open-id",
        creator_username="themuthaof3",
        creator_nickname="Themuthaof3",
        follower_count=1200,
        creator_gmv_minor=500_000,
        creator_gmv_currency="USD",
        creator_level="L2",
        platform_status="PENDING",
        product_id="product-1、product-2",
        product_title="First、Second",
        sku_id="sku-1、sku-2",
        sku_name="Red、Blue",
        commission_rate=None,
        available_quantity=1,
        feishu_record_id=None,
        assignment_version=0,
    )

    fields = build_feishu_system_fields(record, synced_at=observed_at)

    assert fields["商品ID"] == ["product-1", "product-2"]
    assert fields["申请编号"] == "9425993608515544251"


def test_mapper_keeps_unknown_shop_display_name_unchanged() -> None:
    observed_at = datetime(2026, 9, 10, tzinfo=UTC)
    record = SampleFeishuSourceRecord(
        application_id=uuid4(),
        tenant_id=uuid4(),
        shop_id=uuid4(),
        shop_name="Unclassified Shop",
        platform_application_id="sample-unknown-shop",
        source_type="official_api",
        source_capture_id=uuid4(),
        source_observed_at=observed_at,
        first_seen_at=observed_at,
        creator_open_id=None,
        creator_username=None,
        creator_nickname=None,
        follower_count=None,
        creator_gmv_minor=None,
        creator_gmv_currency=None,
        creator_level=None,
        platform_status="PENDING",
        product_id=None,
        product_title=None,
        sku_id=None,
        sku_name=None,
        commission_rate=None,
        available_quantity=None,
        feishu_record_id=None,
        assignment_version=0,
    )

    fields = build_feishu_system_fields(record, synced_at=observed_at)

    assert fields["店铺标识"] == "Unclassified Shop"


def test_mapper_keeps_unavailable_creator_metrics_blank() -> None:
    observed_at = datetime(2026, 9, 10, tzinfo=UTC)
    record = SampleFeishuSourceRecord(
        application_id=uuid4(),
        tenant_id=uuid4(),
        shop_id=uuid4(),
        shop_name="Akeleo Toys",
        platform_application_id="sample-missing-metrics",
        source_type="official_api",
        source_capture_id=uuid4(),
        source_observed_at=observed_at,
        first_seen_at=observed_at,
        creator_open_id="creator-open-id",
        creator_username="creator_name",
        creator_nickname="Creator",
        follower_count=1200,
        creator_gmv_minor=None,
        creator_gmv_currency=None,
        creator_level=None,
        platform_status="PENDING",
        product_id="product-1",
        product_title="Product",
        sku_id="sku-1",
        sku_name="Blue",
        commission_rate=None,
        available_quantity=1,
        feishu_record_id=None,
        assignment_version=0,
    )

    fields = build_feishu_system_fields(record, synced_at=observed_at)

    assert fields["30日内容数"] is None
    assert fields["平均视频播放量"] is None
    assert fields["样品履约率"] is None
    assert fields["30日销量"] is None
    assert fields["PPS"] == ""
    assert fields["达人评分"] == ""
    assert fields["样品评分"] is None
    assert fields["TikTok申请时间"] is None


def test_mapper_formats_whole_scores_with_one_decimal_place() -> None:
    observed_at = datetime(2026, 9, 10, tzinfo=UTC)
    record = SampleFeishuSourceRecord(
        application_id=uuid4(),
        tenant_id=uuid4(),
        shop_id=uuid4(),
        shop_name="Akeleo Toys",
        platform_application_id="sample-whole-scores",
        source_type="official_api",
        source_capture_id=uuid4(),
        source_observed_at=observed_at,
        first_seen_at=observed_at,
        creator_open_id="creator-open-id",
        creator_username="creator_name",
        creator_nickname="Creator",
        follower_count=1200,
        creator_gmv_minor=500_000,
        creator_gmv_currency="USD",
        creator_level="L2",
        platform_status="PENDING",
        product_id="product-1",
        product_title="Product",
        sku_id="sku-1",
        sku_name="Blue",
        commission_rate=None,
        available_quantity=1,
        feishu_record_id=None,
        assignment_version=0,
        creator_pps=Decimal(4),
        creator_rating=Decimal(5),
    )

    fields = build_feishu_system_fields(record, synced_at=observed_at)

    assert fields["PPS"] == "4.0/5.0"
    assert fields["达人评分"] == "5.0/5.0"


def test_mapper_matches_tiktok_creator_row_display_contract() -> None:
    observed_at = datetime(2026, 9, 11, tzinfo=UTC)
    record = SampleFeishuSourceRecord(
        application_id=uuid4(),
        tenant_id=uuid4(),
        shop_id=uuid4(),
        shop_name="Akeleo Toys",
        platform_application_id="9040959663885036442",
        source_type="official_api",
        source_capture_id=uuid4(),
        source_observed_at=observed_at,
        first_seen_at=observed_at,
        creator_open_id="creator-open-id",
        creator_username="bargainbashersrc",
        creator_nickname="BargainBashersRc",
        follower_count=1000,
        creator_gmv_minor=467_257,
        creator_gmv_currency="USD",
        creator_level="L2",
        platform_status="AWAITING_SHIPMENT",
        product_id="product-1",
        product_title="Product",
        sku_id="sku-1",
        sku_name="Blue",
        commission_rate=None,
        available_quantity=1,
        feishu_record_id=None,
        assignment_version=0,
        creator_content_count=480,
        creator_ec_video_view=101,
        creator_fulfillment_percentage=Decimal("97.73"),
        creator_units_sold=94,
        creator_pps=Decimal("4.4"),
        creator_rating=Decimal("3.5"),
        creator_profile_snapshot=None,
    )

    fields = build_feishu_system_fields(record, synced_at=observed_at)

    assert fields["30日GMV"] == 4672.57
    assert fields["30日内容数"] == 480
    assert fields["平均视频播放量"] == 101
    assert fields["样品履约率"] == 0.9773
    assert fields["30日销量"] == 94
    assert fields["PPS"] == "4.4/5.0"
    assert fields["达人评分"] == "3.5/5.0"
    assert fields["样品评分"] is None
