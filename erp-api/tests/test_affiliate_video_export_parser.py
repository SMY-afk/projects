from __future__ import annotations

import io
import zipfile
from xml.sax.saxutils import escape

from app.parsers.affiliate_video_export_parser import (
    _rate,
    parse_affiliate_video_export,
)

HEADERS = (
    "视频标题",
    "视频 ID",
    "发布日期",
    "视频链接",
    "达人名称",
    "商品 ID",
    "联盟视频归因 GMV",
    "归因于视频的订单数",
    "平均订单金额",
    "视频归因成交件数",
    "退款金额",
    "已退款的商品件数",
    "点赞数",
    "评论数",
    "分享次数",
    "视频商品曝光次数",
    "视频商品点击量",
    "完播率",
    "视频播放量",
    "商品点击率",
    "视频千次曝光成交金额",
    "互动率",
    "每位客户的平均 GMV",
    "预计佣金",
)

ENGLISH_HEADERS = (
    "Video title", "Video ID", "Post date", "Video link", "Creator name",
    "Product ID", "Creator video-attributed GMV", "Video-attributed orders",
    "AOV", "Video-attributed items sold", "Refunds", "Items refunded",
    "Likes", "Comments", "Shares", "Video product impressions",
    "Video product clicks", "Completion rate", "Video views", "CTR",
    "Video GPM", "Engagement", "Avg. GMV per customer", "Est. commission",
    "Est. flat fee",
)


def test_video_export_parser_maps_the_live_report_contract() -> None:
    values = (
        "#ad remote control car",
        "9371233970479993847",
        "02/15/2026 18:43",
        "https://www.tiktok.com/@retired_welder_/video/9371233970479993847",
        "retired_welder_",
        "9886166395461732977",
        "$294.40",
        "3",
        "$98.13",
        "3",
        "$0.00",
        "0",
        "35",
        "0",
        "4",
        "10.138K",
        "192",
        "1.5%",
        "9.712K",
        "1.89",
        "$29.04",
        "0.4%",
        "$98.13",
        "$34.78",
    )

    rows = parse_affiliate_video_export(
        _xlsx_bytes((HEADERS, tuple("" for _ in HEADERS), values)),
        "USD",
        "America/Los_Angeles",
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["videoId"] == "9371233970479993847"
    assert row["creatorUsername"] == "retired_welder_"
    assert row["videoPostTime"] == "2026-02-15T18:43:00-08:00"
    assert row["promotedProductIds"] == ["9886166395461732977"]
    assert row["gmvMinor"] == 29440
    assert row["estimatedCommissionMinor"] == 3478
    assert row["orderCount"] == 3
    assert row["productImpressions"] == 10138
    assert row["productClickThroughRate"] == "0.0189"


def test_video_export_parser_reads_creator_unique_id_from_video_url() -> None:
    values = (
        "Ride-on car",
        "9715917908745201297",
        "01/20/2026 17:07",
        "https://www.tiktok.com/@jennaclary4/video/9715917908745201297",
        "Jenna Clary",
        "9581838289276857046",
        "$0.00",
        "0",
        "$0.00",
        "0",
        "$0.00",
        "0",
        "0",
        "0",
        "0",
        "0",
        "0",
        "0%",
        "0",
        "0%",
        "$0.00",
        "0%",
        "$0.00",
        "$0.00",
    )

    rows = parse_affiliate_video_export(
        _xlsx_bytes((HEADERS, values)),
        "USD",
        "America/Los_Angeles",
    )

    assert rows[0]["creatorUsername"] == "jennaclary4"
    assert rows[0]["creatorNickname"] == "Jenna Clary"


def test_video_export_parser_accepts_platform_rates_over_one_hundred_percent() -> None:
    assert _rate("125", "商品点击率", 3) == "1.25"
    assert _rate("125%", "商品点击率", 3) == "1.25"


def test_video_export_parser_maps_us_report_headers() -> None:
    values = (
        "Ride-on car", "9715917908745201297", "10/06/2026 17:07",
        "https://www.tiktok.com/@jennaclary4/video/9715917908745201297",
        "Jenna Clary", "9581838289276857046", "$294.40", "3", "$98.13",
        "3", "$0.00", "0", "35", "0", "4", "10.138K", "192", "1.5%",
        "9.712K", "1.89", "$29.04", "0.4%", "$98.13", "$34.78", "$0.00",
    )

    rows = parse_affiliate_video_export(
        _xlsx_bytes((ENGLISH_HEADERS, values)), "USD", "America/Los_Angeles"
    )

    assert len(rows) == 1
    assert rows[0]["videoId"] == "9715917908745201297"
    assert rows[0]["videoPostTime"] == "2026-10-06T17:07:00-07:00"
    assert rows[0]["gmvMinor"] == 29440
    assert rows[0]["orderCount"] == 3
    assert rows[0]["productImpressions"] == 10138
    assert rows[0]["productClickThroughRate"] == "0.0189"


def _xlsx_bytes(rows: tuple[tuple[str, ...], ...]) -> bytes:
    sheet_rows = []
    for row_number, row in enumerate(rows, start=1):
        cells = []
        for column, value in enumerate(row, start=1):
            ref = f"{_column_name(column)}{row_number}"
            cells.append(
                f'<c r="{ref}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'
            )
        sheet_rows.append(f'<row r="{row_number}">{"".join(cells)}</row>')
    worksheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(sheet_rows)}</sheetData></worksheet>"
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("xl/worksheets/sheet1.xml", worksheet)
    return output.getvalue()


def _column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name
