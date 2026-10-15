from __future__ import annotations

import io
import zipfile
from xml.sax.saxutils import escape

import pytest

from app.parsers.affiliate_creator_export_parser import (
    AffiliateCreatorExportParseError,
    parse_affiliate_creator_export,
)
from scripts.affiliate_creator_export_audit import audit_creator_export

HEADERS = (
    "达人用户名",
    "联盟 GMV",
    "联盟直播 GMV",
    "联盟带货视频 GMV",
    "联盟商品橱窗 GMV",
    "联盟商品成交件数",
    "成交件数",
    "预计佣金",
    "预计固定费用",
    "平均订单金额",
    "联盟橱窗商品数",
    "联盟订单量",
    "点击率",
    "商品曝光次数",
    "平均联盟客户数",
    "联盟直播数",
    "联盟带货视频数",
    "定向合作 GMV",
    "定向合作预计佣金",
    "公开合作 GMV",
    "公开合作预计佣金",
    "联盟已退款的 GMV",
    "已退款的联盟商品数",
    "联盟粉丝数",
)


def test_creator_export_excludes_only_original_rows_without_account_name() -> None:
    identified = tuple("creator_one" if name == "达人用户名" else "1" for name in HEADERS)
    anonymous = tuple("--" if name == "达人用户名" else "1" for name in HEADERS)
    content = _xlsx_bytes(HEADERS, (identified, anonymous))

    with pytest.raises(ValueError, match="missing account names"):
        audit_creator_export(content, "USD", 2, allow_missing=False)

    rows, audit = audit_creator_export(content, "USD", 2, allow_missing=True)
    assert len(rows) == 1
    assert audit.source_total == 2
    assert audit.eligible_total == 1
    assert audit.excluded_missing_accounts == 1


def test_creator_export_does_not_hide_a_source_count_mismatch() -> None:
    identified = tuple("creator_one" if name == "达人用户名" else "1" for name in HEADERS)
    content = _xlsx_bytes(HEADERS, (identified,))
    with pytest.raises(ValueError, match="raw row count"):
        audit_creator_export(content, "USD", 2, allow_missing=True)


def test_export_parser_normalizes_strings_without_float_rounding() -> None:
    values = (
        "creator_one",
        "$1,234.56",
        "--",
        "1.2K",
        "0",
        "2",
        "9",
        "123.60",
        "--",
        "88.43",
        "0",
        "9",
        "5.67%",
        "13,988",
        "1.29",
        "0",
        "3",
        "1,000.00",
        "100.01",
        "234.56",
        "23.59",
        "0",
        "0",
        "329.22K",
    )

    rows = parse_affiliate_creator_export(_xlsx_bytes(HEADERS, (values,)), "USD")

    assert rows == [
        {
            "username": "@creator_one",
            "currency": "USD",
            "affiliateGmvMinor": 123456,
            "affiliateLiveGmvMinor": None,
            "affiliateVideoGmvMinor": 120000,
            "affiliateShowcaseGmvMinor": 0,
            "affiliateProductItemsSold": 2,
            "itemsSold": 9,
            "estimatedCommissionMinor": 12360,
            "estimatedFlatFeeMinor": None,
            "averageOrderAmountMinor": 8843,
            "showcaseProductCount": 0,
            "affiliateOrderCount": 9,
            "clickThroughRate": "0.0567",
            "productImpressions": 13988,
            "averageAffiliateCustomers": "1.29",
            "affiliateLiveCount": 0,
            "affiliateVideoCount": 3,
            "targetCollaborationGmvMinor": 100000,
            "targetCollaborationEstimatedCommissionMinor": 10001,
            "openCollaborationGmvMinor": 23456,
            "openCollaborationEstimatedCommissionMinor": 2359,
            "refundedAffiliateGmvMinor": 0,
            "refundedAffiliateProductCount": 0,
            "affiliateFollowerCount": 329220,
        }
    ]


def test_export_parser_reads_rows_when_dimension_is_incorrect() -> None:
    first = tuple(
        "creator_one"
        if header == "达人用户名"
        else "0.1"
        if header == "点击率"
        else "1"
        for header in HEADERS
    )
    second = tuple(
        "@creator_two"
        if header == "达人用户名"
        else "0.2"
        if header == "点击率"
        else "2"
        for header in HEADERS
    )

    rows = parse_affiliate_creator_export(
        _xlsx_bytes(HEADERS, (first, second), dimension="A1"),
        "USD",
    )

    assert [row["username"] for row in rows] == ["@creator_one", "@creator_two"]


def test_export_parser_preserves_rates_above_100_percent_as_decimal() -> None:
    values = tuple(
        "creator_one"
        if header == "达人用户名"
        else "125.5%"
        if header == "点击率"
        else "1"
        for header in HEADERS
    )

    rows = parse_affiliate_creator_export(_xlsx_bytes(HEADERS, (values,)), "USD")

    assert rows[0]["clickThroughRate"] == "1.255"


def test_export_parser_rejects_missing_identity_header() -> None:
    headers = tuple(
        "未知达人字段" if value == "达人用户名" else value for value in HEADERS
    )

    with pytest.raises(AffiliateCreatorExportParseError, match="达人用户名"):
        parse_affiliate_creator_export(_xlsx_bytes(headers, (HEADERS,)), "USD")


def test_export_parser_skips_a_metric_row_without_creator_identity() -> None:
    creator = tuple(
        "creator_one"
        if header == "达人用户名"
        else "0.1"
        if header == "点击率"
        else "1"
        for header in HEADERS
    )
    identityless = tuple("" if header == "达人用户名" else "0" for header in HEADERS)

    rows = parse_affiliate_creator_export(
        _xlsx_bytes(HEADERS, (creator, identityless)), "USD"
    )

    assert [row["username"] for row in rows] == ["@creator_one"]


def test_export_parser_reads_compass_creator_analytics_format() -> None:
    headers = (
        "Creator name",
        "Creator-attributed GMV",
        "Refunds",
        "Est. commission",
        "Attributed orders",
        "Creator-attributed items sold",
        "Items refunded",
        "Videos",
        "LIVE streams",
        "AOV",
        "Samples shipped",
    )
    descriptions = (
        "Creator",
        "GMV generated by customers who tapped on creator product links.",
        "Refund description",
        "Commission description",
        "Order description",
        "Items description",
        "Refunded items description",
        "Video description",
        "LIVE description",
        "AOV description",
        "Samples description",
    )
    values = (
        "creator_one",
        "$222.62",
        "$1.20",
        "$26.90",
        "3",
        "4",
        "1",
        "2",
        "1",
        "$74.21",
        "5",
    )

    rows = parse_affiliate_creator_export(
        _xlsx_bytes(headers, (descriptions, values)), "USD"
    )

    assert rows == [
        {
            "username": "@creator_one",
            "currency": "USD",
            "affiliateGmvMinor": 22262,
            "refundedAffiliateGmvMinor": 120,
            "estimatedCommissionMinor": 2690,
            "affiliateOrderCount": 3,
            "affiliateProductItemsSold": 4,
            "itemsSold": 4,
            "refundedAffiliateProductCount": 1,
            "affiliateVideoCount": 2,
            "affiliateLiveCount": 1,
            "averageOrderAmountMinor": 7421,
            "sourceExtensions": {"samplesShipped": 5},
        }
    ]


def test_export_parser_reads_us_seller_center_creator_format() -> None:
    headers = (
        "Creator username",
        "Affiliate GMV",
        "Est. commission",
        "Items sold",
        "Affiliate orders",
        "CTR",
    )
    values = ("creator_one", "1752.31", "244.31", "19", "19", "1.63%")

    rows = parse_affiliate_creator_export(
        _xlsx_bytes(headers, (values,)), "USD"
    )

    assert rows == [
        {
            "username": "@creator_one",
            "currency": "USD",
            "affiliateGmvMinor": 175231,
            "estimatedCommissionMinor": 24431,
            "itemsSold": 19,
            "affiliateOrderCount": 19,
            "clickThroughRate": "0.0163",
        }
    ]


def _xlsx_bytes(
    headers: tuple[str, ...],
    rows: tuple[tuple[str, ...], ...],
    *,
    dimension: str = "A1:X999",
) -> bytes:
    values = (headers, *rows)
    shared: list[str] = []
    indexes: dict[str, int] = {}
    sheet_rows = []
    for row_number, row in enumerate(values, start=1):
        cells = []
        for column_number, value in enumerate(row, start=1):
            if value not in indexes:
                indexes[value] = len(shared)
                shared.append(value)
            reference = f"{_column_name(column_number)}{row_number}"
            cells.append(f'<c r="{reference}" t="s"><v>{indexes[value]}</v></c>')
        sheet_rows.append(f'<row r="{row_number}">{"".join(cells)}</row>')
    worksheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<dimension ref="{dimension}"/><sheetData>{"".join(sheet_rows)}</sheetData>'
        "</worksheet>"
    )
    strings = "".join(f"<si><t>{escape(value)}</t></si>" for value in shared)
    shared_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        f'count="{sum(len(row) for row in values)}" uniqueCount="{len(shared)}">'
        f"{strings}</sst>"
    )
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/sharedStrings.xml", shared_xml)
        archive.writestr("xl/worksheets/sheet1.xml", worksheet)
    return target.getvalue()


def _column_name(number: int) -> str:
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result
