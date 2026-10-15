import httpx
import pytest

from erp_api.services.feishu_creator_export_service import (
    FEISHU_CREATOR_FIELDS,
    FEISHU_MERGED_SOURCE,
    FEISHU_TABLES,
    FeishuCreatorExportError,
    _creator_row,
    build_feishu_creator_export,
    configured_feishu_tables,
)


def test_configured_cooperation_tables_require_a_complete_pair() -> None:
    from types import SimpleNamespace

    assert [
        (table.product_line, table.app_token, table.table_id, table.view_id)
        for table in FEISHU_TABLES
    ] == [
        ("童车", "examplefc071571cfacf2fb2208", "tblexamplef60c4307", "vewHmXeS09"),
        ("遥控车", "example14571c6e716163d45e6b", "tblexample1012acf0", "vewHmXeS09"),
    ]
    assert configured_feishu_tables(SimpleNamespace()) == FEISHU_TABLES
    with pytest.raises(ValueError, match="complete IDs"):
        configured_feishu_tables(
            SimpleNamespace(feishu_coop_stroller_base_token="base")
        )
    tables = configured_feishu_tables(
        SimpleNamespace(
            feishu_coop_stroller_base_token="stroller-base",
            feishu_coop_stroller_table_id="stroller-table",
            feishu_coop_stroller_view_id="stroller-view",
            feishu_coop_rc_base_token="rc-base",
            feishu_coop_rc_table_id="rc-table",
            feishu_coop_rc_view_id="rc-view",
        )
    )
    assert [
        (table.product_line, table.app_token, table.table_id) for table in tables
    ] == [
        ("童车", "stroller-base", "stroller-table"),
        ("遥控车", "rc-base", "rc-table"),
    ]


def test_creator_row_keeps_only_the_last_non_empty_bd_in_one_source_record() -> None:
    row = _creator_row(
        {
            "fields": {
                "帐号名称": "creator-a",
                "BD负责人": [{"name": "Older BD"}, {"name": "Latest BD"}],
                "同意样品日期": "2026-09-20",
            }
        }
    )

    assert row["bdOwner"] == "Latest BD"


@pytest.mark.asyncio
async def test_errors_do_not_expose_app_secret_or_access_token() -> None:
    secret = "never-render-this-secret"
    token = "never-render-this-token"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(
                200, json={"code": 0, "tenant_access_token": token, "expire": 7200}
            )
        return httpx.Response(403, text=f"{secret} {token}")

    with pytest.raises(FeishuCreatorExportError) as exc_info:
        await build_feishu_creator_export(
            "app-id",
            secret,
            http_transport=httpx.MockTransport(handler),
        )

    rendered = str(exc_info.value)
    assert secret not in rendered
    assert token not in rendered


@pytest.mark.asyncio
async def test_rejects_incomplete_pagination() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(
                200, json={"code": 0, "tenant_access_token": "token", "expire": 7200}
            )
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "total": 2,
                    "has_more": False,
                    "items": [
                        {
                            "record_id": "row-1",
                            "fields": {
                                "帐号名称": "only-one",
                                "BD负责人": "BD",
                                "数据来源": "童车团队",
                            },
                        }
                    ],
                },
            },
        )

    with pytest.raises(FeishuCreatorExportError, match="incomplete"):
        await build_feishu_creator_export(
            "app-id",
            "app-secret",
            http_transport=httpx.MockTransport(handler),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "second_total,second_id,error",
    [(3, "row-2", "total changed"), (2, "row-1", "repeated a record")],
)
async def test_rejects_changing_total_or_repeated_record(
    second_total: int, second_id: str, error: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(
                200, json={"code": 0, "tenant_access_token": "token", "expire": 7200}
            )
        second = "page_token" in request.url.params
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "total": second_total if second else 2,
                    "has_more": not second,
                    "page_token": "next" if not second else None,
                    "items": [
                        {
                            "record_id": second_id if second else "row-1",
                            "fields": {
                                "帐号名称": "creator",
                                "BD负责人": "BD",
                                "数据来源": "童车团队",
                            },
                        }
                    ],
                },
            },
        )

    with pytest.raises(FeishuCreatorExportError, match=error):
        await build_feishu_creator_export(
            "app-id", "app-secret", http_transport=httpx.MockTransport(handler)
        )


@pytest.mark.asyncio
async def test_retries_a_transient_feishu_page_failure() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(
                200, json={"code": 0, "tenant_access_token": "token", "expire": 7200}
            )
        assert FEISHU_MERGED_SOURCE.table_id in request.url.path
        attempts += 1
        if attempts == 1:
            return httpx.Response(502, json={"code": 99991663})
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "total": 1,
                    "has_more": False,
                    "items": [
                        {
                            "record_id": "row-1",
                            "fields": {
                                FEISHU_CREATOR_FIELDS[0]: "creator-a",
                                FEISHU_CREATOR_FIELDS[1]: "BD",
                                "数据来源": "童车团队",
                            },
                        }
                    ],
                },
            },
        )

    payload = await build_feishu_creator_export(
        "app-id",
        "app-secret",
        http_transport=httpx.MockTransport(handler),
        retry_delays=(0,),
    )

    assert [table["total"] for table in payload["tables"]] == [1, 0]
    assert attempts == 2
